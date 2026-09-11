"""DowngradeMountainCommand — Downgrade "too many mountains" with one click.

Do three things:
1. Visual layer (terrain.bmp): Snowy mountains → mountains, mountains → hills, hills → plains
   + Connected components clean small hilly patches <50px→plain
2. Height map (height_map): synchronized down one level (snow-45, mountain-35, hill-30)
   This ensures that the 3D effects in the game are consistent with the textures, and there will be no separation like "plain textures but still mountains"
3. Attribute layer (provincial_terrain dict): synchronous downgrade per-province type

Supports undo (save old terrain_map + old height_map + old provincial_terrain dict)."""
from __future__ import annotations

import numpy as np

from commands.base import Command
from data.constants import SEA_LEVEL
from data.terrain_types import PALETTE_TO_TYPE, TERRAIN_PALETTE_INDEX
from domain.map_data import MapData


# Palette downgrade mapping for visual layer (terrain.bmp)
# Maintain the large ecology (desert mountains → desert hills), other mountains → general hills
_PALETTE_DOWNGRADE: dict[int, int] = {
    # Snowy Mountain → Mountain
    16: 6,       # snow_16 → terrain_6 (mountain)
    31: 6,       # desert_mountain_tops → mountain
    19: 0,       # plains_snow → plains
    # Mountain → Hill (preserve desert ecology)
    6: 17,       # terrain_6 (mountain) → hills_blend
    10: 17,      # terrain_10 → hills_blend
    11: 8,       # desert_mountain_11 → desert_hills (Desert Hills)
    18: 17,      # sand mountain variation → hills_blend
    20: 17,      # grass mountain variation → hills_blend
    27: 1,       # jungle_mountain → forest (the jungle is downgraded to forest/hill dispute, use forest)
    # Hills → Plains (keep desert)
    17: 0,       # hills_blend → terrain_0 (plains)
    2: 3,        # desert_mountain(hills type) → desert
    8: 3,        # desert_hills → desert
}


# The type name of the attribute layer (provincial_terrain dict) is downgraded
_TYPE_DOWNGRADE: dict[str, str] = {
    "mountain": "hills",
    "hills": "plains",
}


# After downgrading, isolated "hilly" patches (originally scattered mountain points) smaller than this number of pixels
# was cleared into plains. Directly fix the problem of "orange dots scattered in plain areas".
_MIN_PATCH_PIXELS = 50

# Palette index of hill class (to be cleaned after downgrade)
_HILLS_PALETTES = (17, 2, 8)

# Height map degradation amount (according to the palette category of the original pixel)
# HOI4 height band center interval is about 40, decrease by one band ≈ minus 30-45
_SNOW_PALETTES = (16, 19, 31)
_MOUNTAIN_PALETTES = (6, 10, 11, 18, 20, 27)
_HEIGHT_DROP_SNOW = 45      # Snow Mountain -45 → Mountain Height
_HEIGHT_DROP_MOUNTAIN = 35  # Mountain -35 → Hill height
_HEIGHT_DROP_HILLS = 30     # Hills -30 → Plain height


class DowngradeMountainCommand(Command):
    """Downgrade mountains with one click."""

    label = "Downgrade mountains"

    def __init__(
        self,
        map_data: MapData,
        mask: np.ndarray | None = None,
        strength: float = 0.5,
    ) -> None:
        """mask: None = downgrade the entire map
              (H,W) bool array = downgrade only pixels with mask==True
        strength: 0..1, downgrade strength
            1.0 = entire band is degraded (-45/-35/-30 height)
            0.5 = lower only the upper half of the band (-22/-17/-15 height, milder)
            0.0 = nothing drops (no-op)"""
        self._map_data = map_data
        self._mask = mask.copy() if mask is not None else None
        self._strength = float(max(0.0, min(1.0, strength)))
        self._old_terrain: np.ndarray | None = None
        self._old_height: np.ndarray | None = None
        self._old_prov_terrain: dict | None = None

    def execute(self) -> None:
        if self._strength <= 0:
            # no-op, still snapshot to facilitate unified undo
            self._old_terrain = self._map_data.terrain_map.copy()
            self._old_height = self._map_data.height_map.copy()
            self._old_prov_terrain = dict(self._map_data.provincial_terrain)
            return

        # Note: terrain_map is a ref, changing it back will cause pollution. The original value must be copied first
        tm_orig = self._map_data.terrain_map.copy()  # The original palette is for high-level downgrades
        hm = self._map_data.height_map
        self._old_terrain = tm_orig
        self._old_height = hm.copy()
        self._old_prov_terrain = dict(self._map_data.provincial_terrain)

        # —— Step 1: Calculate the "degradation threshold" of each band according to intensity
        # Strength 1.0: The entire band is degraded (threshold = band_low)
        # Strength 0.5: Only lower the upper half of the band (threshold = midpoint)
        # Strength 0.2: only reduces the top 20% of the band
        # Degrade after judging "current height > threshold" for land pixels one by one.
        # Band interval (corresponds to TerrainGenConfig default value):
        #   Hills: 130-165, Mountain: 165-210, Snow: 210+
        # Plains: <130 (no downgrade)
        s = self._strength
        hills_thr = 130 + (1 - s) * 35   # 130..165
        mountain_thr = 165 + (1 - s) * 45  # 165..210
        snow_thr = 210 + (1 - s) * 30    # 210..240 (snow upper limit counts as 240)

        # Find the pixels in each band that are "high enough to be downgraded"
        was_snow = np.isin(tm_orig, _SNOW_PALETTES) & (hm >= snow_thr)
        was_mountain = np.isin(tm_orig, _MOUNTAIN_PALETTES) & (hm >= mountain_thr)
        was_hills = np.isin(tm_orig, _HILLS_PALETTES) & (hm >= hills_thr)
        downgrade_mask = was_snow | was_mountain | was_hills

        # —— Step 2: Apply palette LUT only to pixels within downgrade_mask ——
        lut = np.arange(256, dtype=np.uint8)
        for old_idx, new_idx in _PALETTE_DOWNGRADE.items():
            lut[old_idx] = new_idx
        new_tm = tm_orig.copy()
        new_tm[downgrade_mask] = lut[tm_orig[downgrade_mask]]

        # —— Step 3: Clean up small hilly patches (only deal with the hills that have just fallen) ——
        hills_after = np.isin(new_tm, _HILLS_PALETTES) & downgrade_mask
        small_patch_mask = np.zeros_like(hills_after)
        if np.any(hills_after):
            from scipy.ndimage import label as _label
            labels, n = _label(hills_after, structure=np.ones((3, 3), dtype=bool))
            if n > 0:
                sizes = np.bincount(labels.ravel())
                small_labels = np.where(sizes < _MIN_PATCH_PIXELS)[0]
                small_labels = small_labels[small_labels > 0]
                if len(small_labels) > 0:
                    small_patch_mask = np.isin(labels, small_labels)
                    new_tm[small_patch_mask] = 0

        # —— If a selection mask is specified, restore the terrain outside the mask to its original value ——
        if self._mask is not None:
            new_tm[~self._mask] = tm_orig[~self._mask]

        self._map_data.terrain_map[:] = new_tm

        # —— Step 4: Height map downgrade (only downgrade the pixels marked as downgraded in Step 1, the amount is scaled by strength) ——
        new_hm = hm.astype(np.int16)  # Use int16 to avoid underflow
        # If there is a mask, height degradation is also limited to the selected area.
        if self._mask is not None:
            was_snow = was_snow & self._mask
            was_mountain = was_mountain & self._mask
            was_hills = was_hills & self._mask
            small_patch_mask_in = small_patch_mask & self._mask
        else:
            small_patch_mask_in = small_patch_mask
        # Scale the drop by strength (1.0=-45/-35/-30, 0.5=-22/-17/-15)
        new_hm[was_snow] -= int(_HEIGHT_DROP_SNOW * s)
        new_hm[was_mountain] -= int(_HEIGHT_DROP_MOUNTAIN * s)
        new_hm[was_hills] -= int(_HEIGHT_DROP_HILLS * s)
        # Small spots are extra reduced
        extra_drop = small_patch_mask_in & (~was_snow)
        new_hm[extra_drop] -= int(15 * s)
        # Keep the bottom line: land cannot be lower than SEA_LEVEL+1
        land_mask = self._map_data.tile_map == 1  # TILE_LAND
        np.clip(new_hm, 0, 255, out=new_hm)
        new_hm_u8 = new_hm.astype(np.uint8)
        # Land pixels are at least SEA_LEVEL+1
        np.maximum(
            new_hm_u8, SEA_LEVEL + 1, out=new_hm_u8, where=land_mask
        )
        self._map_data.height_map[:] = new_hm_u8

        # —— Step 5: Downgrade provincial_terrain dict (attribute layer) ——
        # Only downgrade provinces where "more than half of the pixels are actually changed", and avoid changing the attributes of the entire province to avoid sporadic pixel changes.
        changed_mask = downgrade_mask.copy()
        if self._mask is not None:
            changed_mask &= self._mask
        downgrade_pids = self._pids_majority_in_mask(changed_mask)

        new_prov: dict = {}
        for pid, typ in self._old_prov_terrain.items():
            if pid in downgrade_pids:
                new_prov[pid] = _TYPE_DOWNGRADE.get(typ, typ)
            else:
                new_prov[pid] = typ
        self._map_data.provincial_terrain.clear()
        self._map_data.provincial_terrain.update(new_prov)

    def _pids_majority_in_mask(self, mask: np.ndarray) -> set[int]:
        """Returns the set of province ids in province_map where >50% of the pixels fall within the mask."""
        if not np.any(mask):
            return set()
        pm = self._map_data.province_map
        all_pids = pm.ravel()
        max_pid = int(all_pids.max())
        total = np.bincount(all_pids, minlength=max_pid + 1)
        in_cnt = np.bincount(pm[mask], minlength=max_pid + 1)
        ratio = np.zeros_like(total, dtype=np.float32)
        nonzero = total > 0
        ratio[nonzero] = in_cnt[nonzero] / total[nonzero]
        pids = np.where(ratio > 0.5)[0]
        return set(int(p) for p in pids if p > 0)

    def undo(self) -> None:
        if self._old_terrain is not None:
            self._map_data.terrain_map[:] = self._old_terrain
        if self._old_height is not None:
            self._map_data.height_map[:] = self._old_height
        if self._old_prov_terrain is not None:
            self._map_data.provincial_terrain.clear()
            self._map_data.provincial_terrain.update(self._old_prov_terrain)
