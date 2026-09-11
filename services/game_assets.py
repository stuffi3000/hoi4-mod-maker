"""Game Asset Reading - The preview function reads original assets from the user's HOI4 installation directory.

The preview needs to use the game's own "recipe" to synthesize a picture that is close to the in-game look and feel:
- terrain={} block in common/terrain/00_terrain.txt:
    terrain.bmp palette index → atlas tile number (texture = N)
- map/terrain/atlas0.dds: terrain material atlas, 4×4 grid × 512px tiles
- map/terrain/atlas_normal0.dds: normal map (bump light and shadow)

All files are read and cached on demand during runtime; when the game directory/file is missing, each getter returns None,
Downgraded by the caller to solid color rendering. This module does not depend on Qt.

Reference: Reference/Map modding.txt lines 344-362 (atlas tiles are arranged row-major:
texture = 11, which is the rightmost cell in row 3 of the 4×4 grid)."""

from __future__ import annotations

import json
import os
import re

import numpy as np

from data.constants import DEFAULT_HOI4_PATH
# The atlas atlas is fixed to a 4×4 tile grid
ATLAS_GRID = 4

TERRAIN_DEF_RELPATH = "common/terrain/00_terrain.txt"
ATLAS_RELPATH = "map/terrain/atlas0.dds"
ATLAS_NORMAL_RELPATH = "map/terrain/atlas_normal0.dds"
# Area tone map (RGB=Hue, A=City Lights Mask); half the resolution of the corresponding map
COLORMAP_RGB_RELPATH = "map/terrain/colormap_rgb_cityemissivemask_a.dds"


# User configuration file (shared with language settings), game directory persisted here
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".hoi4_map_maker.json")
_CONFIG_KEY_GAME_DIR = "hoi4_game_dir"


def _read_config_game_dir() -> str | None:
    """Read the game directory saved in the user configuration; returns None if it does not exist or has expired."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            path = json.load(f).get(_CONFIG_KEY_GAME_DIR)
    except Exception:
        return None
    if path and os.path.isfile(os.path.join(path, TERRAIN_DEF_RELPATH)):
        return path
    return None


def _save_config_game_dir(path: str) -> None:
    """Write the game directory into the user configuration (retain other keys such as language); failure to write is not fatal."""
    config: dict = {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception:
        pass
    config[_CONFIG_KEY_GAME_DIR] = path
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except OSError:
        pass  # It will still take effect in this session, but you will have to reselect it next time you start it.


def find_hoi4_install() -> str | None:
    """Returns to the HOI4 installation directory, returns None if not found.

    Search order: Directory where user configuration is saved → Built-in default path (DEFAULT_HOI4_PATH).
    Automatic scanning of Steam library lists is part of M3 (preparing for public release)."""
    saved = _read_config_game_dir()
    if saved is not None:
        return saved
    if os.path.isfile(os.path.join(DEFAULT_HOI4_PATH, TERRAIN_DEF_RELPATH)):
        return DEFAULT_HOI4_PATH
    return None


# Match graphic terrain entries: { ... color = { index list } ... texture = N ... }
# The entry body does not contain other braces except the braces for color ([^{}] guarantees no cross-entry matching);
# Entries in the categories block do not have a texture field and will not be matched.
_GFX_ENTRY_RE = re.compile(
    r"\{[^{}]*?color\s*=\s*\{([\d\s]+)\}[^{}]*?texture\s*=\s*(\d+)[^{}]*?\}",
    re.S,
)
_TYPE_RE = re.compile(r"type\s*=\s*(\w+)")


def parse_graphical_terrain(text: str) -> list[dict]:
    """Parse the graphical terrain entry of 00_terrain.txt.

    Returns [{"type": "plains", "indices": [0], "texture": 1}, ...].
    Only items with color and texture fields are recognized (i.e. terrain={} block content)."""
    text = re.sub(r"#[^\n]*", "", text)  # Go to annotation
    entries: list[dict] = []
    for m in _GFX_ENTRY_RE.finditer(text):
        type_m = _TYPE_RE.search(m.group(0))
        entries.append({
            "type": type_m.group(1) if type_m else "",
            "indices": [int(x) for x in m.group(1).split()],
            "texture": int(m.group(2)),
        })
    return entries


def parse_terrain_to_texture(text: str) -> dict[int, int]:
    """Parse the 00_terrain.txt text and return {terrain.bmp palette index: atlas tile number}.

    The color of an entry can be listed in multiple indexes, all mapped to the same tile.
    texture = 255 (Lake) is left as is, it is up to the compositor to decide what to do with it."""
    mapping: dict[int, int] = {}
    for e in parse_graphical_terrain(text):
        for idx in e["indices"]:
            mapping[idx] = e["texture"]
    return mapping


def parse_water_palette_indices(text: str) -> set[int]:
    """Returns a collection of palette indices belonging to water bodies (ocean/lakes) in terrain.bmp."""
    water: set[int] = set()
    for e in parse_graphical_terrain(text):
        if e["type"] in ("ocean", "lakes"):
            water.update(e["indices"])
    return water


def slice_atlas(atlas: np.ndarray, grid: int = ATLAS_GRID) -> np.ndarray:
    """Cut the atlas into a tile array, return (grid*grid, height, width, channel), arranged in row priority."""
    h, w = atlas.shape[:2]
    th, tw = h // grid, w // grid
    c = atlas.shape[2]
    tiles = atlas[: grid * th, : grid * tw].reshape(grid, th, grid, tw, c)
    return tiles.swapaxes(1, 2).reshape(grid * grid, th, tw, c)


class GameAssets:
    """Lazy read + in-process cached game asset container.

    Usage:
        assets = GameAssets()
        if not assets.available():
            ... prompt the user to select a game directory, or downgrade solid color rendering ...
        tiles = assets.atlas_tiles() # None = Failed to read the file"""

    def __init__(self, install_dir: str | None = None) -> None:
        self.install_dir = install_dir if install_dir else find_hoi4_install()
        self._cache: dict[str, object] = {}
        # The reason for the latest reading failure, for UI prompts and troubleshooting
        self.last_error: str = ""

    def available(self) -> bool:
        return self.install_dir is not None

    # ─────────── Getters for each asset ────────────

    def terrain_to_texture(self) -> dict[int, int] | None:
        """palette-index → atlas-tile-number mapping."""
        return self._cached("terrain_to_texture", self._load_terrain_mapping)

    def atlas_tiles(self) -> np.ndarray | None:
        """Terrain Material Tiles (16, 512, 512, 4) uint8."""
        return self._cached(
            "atlas_tiles", lambda: self._load_dds_tiles(ATLAS_RELPATH))

    def atlas_normal_tiles(self) -> np.ndarray | None:
        """Normal map tiles (16, 512, 512, 4) uint8."""
        return self._cached(
            "atlas_normal_tiles", lambda: self._load_dds_tiles(ATLAS_NORMAL_RELPATH))

    def water_palette_indices(self) -> set[int] | None:
        """Palette index for water bodies (ocean/lakes) in terrain.bmp."""
        def _load():
            path = self._abs(TERRAIN_DEF_RELPATH)
            if path is None:
                return None
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    return parse_water_palette_indices(f.read())
            except OSError as e:
                self.last_error = f"Failed to read {path}: {e}"
                return None
        return self._cached("water_palette_indices", _load)

    def colormap_rgb(self) -> np.ndarray | None:
        """vanilla area tone map (H, W, 3) uint8 (alpha channel is city lights mask, discarded).

        The resolution is half of the vanilla map, and is only used with vanilla map data;
        The color tone of the self-made map uses this tool's own colormap function."""
        def _load():
            arr = self._read_dds(COLORMAP_RGB_RELPATH)
            return None if arr is None else arr[:, :, :3]
        return self._cached("colormap_rgb", _load)

    # ─────────── Internal implementation ───────────

    def _cached(self, key: str, loader):
        if key not in self._cache:
            self._cache[key] = loader()
        return self._cache[key]

    def _abs(self, relpath: str) -> str | None:
        if self.install_dir is None:
            self.last_error = "HOI4 installation directory was not found"
            return None
        path = os.path.join(self.install_dir, relpath)
        if not os.path.isfile(path):
            self.last_error = f"Game file does not exist: {path}"
            return None
        return path

    def _load_terrain_mapping(self) -> dict[int, int] | None:
        path = self._abs(TERRAIN_DEF_RELPATH)
        if path is None:
            return None
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                mapping = parse_terrain_to_texture(f.read())
        except OSError as e:
            self.last_error = f"Failed to read {path}: {e}"
            return None
        if not mapping:
            self.last_error = f"No graphical terrain definitions were found in {path}"
            return None
        return mapping

    def _read_dds(self, relpath: str) -> np.ndarray | None:
        """Read DDS as (H, W, 4) uint8, and return None on failure."""
        path = self._abs(relpath)
        if path is None:
            return None
        try:
            from PIL import Image
            with Image.open(path) as im:
                return np.asarray(im.convert("RGBA"))
        except Exception as e:  # There are many types of PIL decoding failures and they are all downgraded uniformly.
            self.last_error = f"Failed to decode {path}: {e}"
            return None

    def _load_dds_tiles(self, relpath: str) -> np.ndarray | None:
        arr = self._read_dds(relpath)
        if arr is None:
            return None
        if arr.shape[0] % ATLAS_GRID or arr.shape[1] % ATLAS_GRID:
            self.last_error = f"{relpath} size {arr.shape} is not a {ATLAS_GRID}×{ATLAS_GRID} grid"
            return None
        return slice_atlas(arr)


def detect_supported_version() -> str | None:
    """Install the detected version from the local game and return the 'major.minor.*' format used by the descriptor.

    Read the rawVersion of launcher-settings.json (such as "1.19.2.0" → "1.19.*").
    Mods exported after the game is updated will automatically declare the new version and will no longer be blocked by the launcher due to hard-coding of the old version number.
    Marked as "obsolete". Undetectable (no game installed/file format changed) Returns None,
    The caller falls back to data/constants.DEFAULT_SUPPORTED_VERSION."""
    install = find_hoi4_install()
    if install is None:
        return None
    path = os.path.join(install, "launcher-settings.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f).get("rawVersion", "")
    except Exception:
        return None
    parts = str(raw).split(".")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{parts[0]}.{parts[1]}.*"
    return None


def resolve_supported_version() -> str:
    """Export the game version declared by the MOD: give priority to local detection, and fall back to the default constants if it fails."""
    from data.constants import DEFAULT_SUPPORTED_VERSION
    return detect_supported_version() or DEFAULT_SUPPORTED_VERSION


# ─────────── Process-level default instance (preview renderer and preview page shared cache) ───────────

_default_assets: GameAssets | None = None


def get_default_assets() -> GameAssets:
    """Get the process-level default GameAssets, created when called for the first time."""
    global _default_assets
    if _default_assets is None:
        _default_assets = GameAssets()
    return _default_assets


def set_default_install_dir(path: str) -> GameAssets:
    """The user manually selects the game directory and rebuilds the default instance (all old caches are invalidated).

    At the same time, it is persisted to the user configuration, and the directory will be automatically used next time it is started."""
    global _default_assets
    _default_assets = GameAssets(install_dir=path)
    _save_config_game_dir(path)
    return _default_assets
