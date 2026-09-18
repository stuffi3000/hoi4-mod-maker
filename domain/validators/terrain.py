"""Terrain, river, and mask validation slice (M3.3b).

Pure, non-mutating validators over in-memory raster layers. The public
entry point is :func:`validate_terrain_layers`, which returns a
deterministic list of :class:`domain.validation.ValidationFinding`.

Stable finding codes emitted here:

- ``terrain.shape``: terrain layer shape does not match the tile map.
- ``river.shape``: river layer shape does not match the tile map.
- ``height.shape``: height layer shape does not match the tile map.
- ``mask.shape``: city/tree mask shape does not match the tile map
  (or the profile-expected mask size when a profile is supplied).
- ``terrain.index``: terrain palette index is not legal.
- ``terrain.surface_mismatch``: land/sea/lake tile disagrees with
  terrain semantics (ocean/lakes placement).
- ``river.value``: river raster holds an illegal palette value.
- ``river.width``: solid 2x2 river block (wider than one pixel).
- ``river.connectivity``: diagonal-only river contact without an
  orthogonal bridge.
- ``height.value``: height sample outside the 0-255 BMP range.
- ``city.value``: city mask sample outside the 0-255 BMP range.
- ``tree.value``: tree index outside the profile/vanilla legal set.

Layers used: ``terrain``, ``rivers``, ``heightmap``, ``cities``,
``trees``. Shape/index/surface/value findings use ``error``;
river width/connectivity findings use ``warning``.

The validator never mutates its inputs, never touches Qt, and keeps no
global mutable state. Findings are emitted in a fixed pipeline order
with sorted coordinates so repeated calls are byte-identical.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from domain.validation import ValidationFinding

__all__ = ["validate_terrain_layers"]

_COORD_LIMIT = 8

_TERRAIN_LAYER = "terrain"
_RIVERS_LAYER = "rivers"
_HEIGHT_LAYER = "heightmap"
_CITIES_LAYER = "cities"
_TREES_LAYER = "trees"

_FALLBACK_TILE_UNDEFINED = 0
_FALLBACK_TILE_LAND = 1
_FALLBACK_TILE_SEA = 2
_FALLBACK_TILE_LAKE = 3

_FALLBACK_OCEAN_INDEX = 15
_FALLBACK_LAKES_INDEX = 14

_FALLBACK_TREE_LEGAL = frozenset({0, 2, 3, 5, 6, 11, 28, 29})
_FALLBACK_RIVER_VALID = frozenset(range(12))
_FALLBACK_RIVER_BG = frozenset({254, 255})

_ASSET_FOR_KIND = {
    "terrain": "map/terrain.bmp",
    "river": "map/rivers.bmp",
    "height": "map/heightmap.bmp",
    "city": "map/cities.bmp",
    "tree": "map/trees.bmp",
}


def _tile_constants() -> tuple[int, int, int, int]:
    try:
        from data.constants import TILE_LAND, TILE_LAKE, TILE_SEA, TILE_UNDEFINED
        return (
            int(TILE_UNDEFINED),
            int(TILE_LAND),
            int(TILE_SEA),
            int(TILE_LAKE),
        )
    except Exception:
        return (
            _FALLBACK_TILE_UNDEFINED,
            _FALLBACK_TILE_LAND,
            _FALLBACK_TILE_SEA,
            _FALLBACK_TILE_LAKE,
        )


def _ocean_lake_indices() -> tuple[int, int]:
    try:
        from data.terrain_types import TERRAIN_PALETTE_INDEX
        ocean = int(TERRAIN_PALETTE_INDEX.get("ocean", _FALLBACK_OCEAN_INDEX))
        lakes = int(TERRAIN_PALETTE_INDEX.get("lakes", _FALLBACK_LAKES_INDEX))
        return (ocean, lakes)
    except Exception:
        return (_FALLBACK_OCEAN_INDEX, _FALLBACK_LAKES_INDEX)


def _graphical_legal_indices() -> set[int]:
    try:
        from data.terrain_types import GRAPHICAL_TERRAIN_BY_INDEX
        return {int(v) for v in GRAPHICAL_TERRAIN_BY_INDEX.keys()}
    except Exception:
        pass
    try:
        from data.terrain_types import TERRAIN_PALETTE_INDEX
        return {int(v) for v in TERRAIN_PALETTE_INDEX.values()}
    except Exception:
        return {
            0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
            14, 15, 16, 17, 18, 19, 20, 21, 22, 27, 31,
        }


def _extract_int_set(values: Any) -> set[int]:
    out: set[int] = set()
    if values is None:
        return out
    if isinstance(values, Mapping):
        items: list[Any] = []
        items.extend(list(values.keys()))
        items.extend(list(values.values()))
    elif isinstance(values, (str, bytes)):
        return out
    else:
        try:
            items = list(values)  # type: ignore[arg-type]
        except TypeError:
            items = [values]
    for item in items:
        try:
            if isinstance(item, bool):
                continue
            number = int(item)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if 0 <= number <= 255:
            out.add(number)
    return out


def _resolve_legal_terrain_indices(
    terrain_indices: Any, profile: Any
) -> tuple[set[int], str]:
    base = _graphical_legal_indices()
    if terrain_indices is not None:
        if isinstance(terrain_indices, Mapping):
            explicit = _extract_int_set(terrain_indices)
        else:
            explicit = _extract_int_set(terrain_indices)
        if explicit:
            return (explicit, "explicit")
        return (base, "registry-fallback")
    if profile is not None:
        candidate: Any = None
        if hasattr(profile, "terrain_indices"):
            try:
                candidate = getattr(profile, "terrain_indices")
            except Exception:
                candidate = None
        elif isinstance(profile, Mapping) and "terrain_indices" in profile:
            candidate = profile["terrain_indices"]
        profile_set = _extract_int_set(candidate) if candidate is not None else set()
        if profile_set:
            return (base | profile_set, "profile+registry")
        return (base, "registry")
    return (base, "registry")


def _resolve_legal_tree_indices(profile: Any) -> tuple[set[int], str]:
    if profile is not None:
        candidate: Any = None
        if hasattr(profile, "tree_indices"):
            try:
                candidate = getattr(profile, "tree_indices")
            except Exception:
                candidate = None
        elif isinstance(profile, Mapping) and "tree_indices" in profile:
            candidate = profile["tree_indices"]
        extracted = _extract_int_set(candidate) if candidate is not None else set()
        if extracted:
            return (extracted, "profile")
    return (set(_FALLBACK_TREE_LEGAL), "registry-fallback")


def _resolve_legal_river_values() -> tuple[set[int], set[int], set[int]]:
    try:
        from domain.managers.river import VALID_RIVER_VALUES
        valid = {int(v) for v in set(VALID_RIVER_VALUES)}
    except Exception:
        valid = set(_FALLBACK_RIVER_VALID)
    try:
        from domain.managers.river import RIVER_BG_LAND, RIVER_BG_SEA
        background = {int(RIVER_BG_LAND), int(RIVER_BG_SEA)}
    except Exception:
        background = set(_FALLBACK_RIVER_BG)
    return (valid, background, valid | background)


def _profile_expected_shape(
    profile: Any, asset_key: str, tile_shape: tuple[int, int]
) -> tuple[int, int] | None:
    if profile is None:
        return None
    try:
        height, width = int(tile_shape[0]), int(tile_shape[1])
    except (TypeError, ValueError):
        return None
    map_w, map_h = width, height
    try:
        func = getattr(profile, "expected_bmp_size", None)
        if callable(func):
            expected = func(asset_key, map_w, map_h)
            if expected is not None:
                exp_w, exp_h = int(expected[0]), int(expected[1])
                return (exp_h, exp_w)
    except Exception:
        pass
    try:
        if isinstance(profile, Mapping):
            bmp = profile.get("bmp", None)
            if isinstance(bmp, Mapping) and asset_key in bmp:
                contract = bmp[asset_key]
                if isinstance(contract, Mapping):
                    wdiv = int(contract.get("width_divisor", 1) or 1)
                    hdiv = int(contract.get("height_divisor", 1) or 1)
                    return (map_h // hdiv, map_w // wdiv)
    except Exception:
        return None
    return None


def _acceptable_shapes(
    kind: str, tile_shape: tuple[int, int], profile: Any
) -> set[tuple[int, int]]:
    asset_key = _ASSET_FOR_KIND.get(kind, "")
    expected = _profile_expected_shape(profile, asset_key, tile_shape) if asset_key else None
    if expected is None or expected == tile_shape:
        return {tile_shape}
    return {tile_shape, expected}


def _sample_coords(mask: np.ndarray, limit: int = _COORD_LIMIT) -> tuple[tuple[tuple[int, int], ...], int]:
    if mask.size == 0 or not bool(np.any(mask)):
        return ((), 0)
    ys, xs = np.where(mask)
    total = int(ys.shape[0])
    order = np.lexsort((xs, ys))
    chosen = order[:limit]
    coords = tuple((int(xs[i]), int(ys[i])) for i in chosen)
    return (coords, total)


def _shape_finding(
    *,
    code: str,
    layer: str,
    label: str,
    actual: tuple[int, ...],
    acceptable: set[tuple[int, int]],
    tile_shape: tuple[int, int],
) -> ValidationFinding:
    options = sorted(acceptable)
    if len(options) == 1:
        expected_text = "%dx%d" % (options[0][1], options[0][0])
    else:
        expected_text = " or ".join("%dx%d" % (w, h) for h, w in options)
    if len(actual) >= 2:
        actual_text = "%dx%d" % (int(actual[1]), int(actual[0]))
    elif len(actual) == 1:
        actual_text = "%d" % int(actual[0])
    else:
        actual_text = "empty"
    tile_text = "%dx%d" % (int(tile_shape[1]), int(tile_shape[0]))
    return ValidationFinding(
        code=code,
        severity="error",
        message="%s shape %s does not match tile map %s" % (label, actual_text, tile_text),
        layer=layer,
        evidence="expected=%s; actual=%s; tile=%s" % (expected_text, actual_text, tile_text),
    )


def _river_width_finding(
    river_mask: np.ndarray,
) -> ValidationFinding | None:
    height, width = int(river_mask.shape[0]), int(river_mask.shape[1])
    if height < 2 or width < 2:
        return None
    pixels = river_mask.astype(np.uint8)
    block = (
        pixels[:-1, :-1]
        + pixels[:-1, 1:]
        + pixels[1:, :-1]
        + pixels[1:, 1:]
    )
    wide = block >= 4
    count = int(np.sum(wide))
    if count <= 0:
        return None
    coords, total = _sample_coords(wide)
    return ValidationFinding(
        code="river.width",
        severity="warning",
        message="%d river blocks are wider than one pixel" % count,
        layer=_RIVERS_LAYER,
        coordinates=coords,
        evidence="wide_2x2_blocks=%d; sampled_blocks=%d" % (count, len(coords)),
    )


def _river_connectivity_finding(
    river_mask: np.ndarray,
) -> ValidationFinding | None:
    height, width = int(river_mask.shape[0]), int(river_mask.shape[1])
    if height == 0 or width == 0 or not bool(np.any(river_mask)):
        return None
    ys, xs = np.where(river_mask)
    if ys.shape[0] == 0:
        return None
    total_diagonal = 0
    sample_coords: list[tuple[int, int]] = []
    for dy, dx in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
        ny = ys + dy
        nx = xs + dx
        valid = (ny >= 0) & (ny < height) & (nx >= 0) & (nx < width)
        safe_y = np.clip(ny, 0, height - 1)
        safe_x = np.clip(nx, 0, width - 1)
        has_diag = valid & river_mask[safe_y, safe_x]
        first_y = ys + dy
        first_x = xs
        second_y = ys
        second_x = xs + dx
        valid_first = (first_y >= 0) & (first_y < height) & (first_x >= 0) & (first_x < width)
        valid_second = (second_y >= 0) & (second_y < height) & (second_x >= 0) & (second_x < width)
        has_first = valid_first & river_mask[
            np.clip(first_y, 0, height - 1), np.clip(first_x, 0, width - 1)
        ]
        has_second = valid_second & river_mask[
            np.clip(second_y, 0, height - 1), np.clip(second_x, 0, width - 1)
        ]
        isolated = has_diag & (~has_first) & (~has_second)
        count = int(np.sum(isolated))
        total_diagonal += count
        if count > 0 and len(sample_coords) < _COORD_LIMIT:
            hit = np.where(isolated)[0][: (_COORD_LIMIT - len(sample_coords))]
            for idx in hit:
                sample_coords.append((int(xs[int(idx)]), int(ys[int(idx)])))
    pairs = total_diagonal // 2
    if pairs <= 0:
        return None
    sample_coords = sorted(set(sample_coords))[:_COORD_LIMIT]
    return ValidationFinding(
        code="river.connectivity",
        severity="warning",
        message="%d diagonal-only river contacts need orthogonal bridges" % pairs,
        layer=_RIVERS_LAYER,
        coordinates=tuple(sample_coords),
        evidence="diagonal_pairs=%d" % pairs,
    )


def _out_of_range_mask(values: np.ndarray) -> np.ndarray | None:
    if values.size == 0:
        return None
    if values.dtype == np.uint8:
        return None
    flat = np.asarray(values)
    try:
        if np.issubdtype(flat.dtype, np.floating):
            bad = ~np.isfinite(flat)
            bad = bad | (flat < 0) | (flat > 255)
        else:
            bad = (flat < 0) | (flat > 255)
    except TypeError:
        return None
    if not bool(np.any(bad)):
        return None
    return np.asarray(bad, dtype=bool)


def validate_terrain_layers(
    tile_map: Any,
    terrain_map: Any,
    *,
    river_map: Any | None = None,
    height_map: Any | None = None,
    city_map: Any | None = None,
    tree_map: Any | None = None,
    profile: Any | None = None,
    terrain_indices: Any | None = None,
) -> list[ValidationFinding]:
    """Validate terrain, river, and mask rasters against the tile map.

    All inputs are read-only; they are never mutated. Every supplied
    layer must share the tile-map shape (or, when ``profile`` names an
    explicit BMP size such as quarter-map trees, the profile-expected
    shape). Terrain indices are checked against ``terrain_indices`` when
    supplied, otherwise against the profile plus the repository
    graphical-terrain registry. River legality uses
    ``domain.managers.river.VALID_RIVER_VALUES`` plus the 254/255
    backgrounds. Tree legality uses ``profile.tree_indices`` when
    available, otherwise the vanilla legal set.
    """
    findings: list[ValidationFinding] = []
    if tile_map is None or terrain_map is None:
        missing = "tile_map" if tile_map is None else "terrain_map"
        return [
            ValidationFinding(
                code="terrain.shape",
                severity="error",
                message="%s is required for terrain validation" % missing,
                layer=_TERRAIN_LAYER,
                evidence="missing=%s" % missing,
            )
        ]
    try:
        tile_arr = np.asarray(tile_map)
        terrain_arr = np.asarray(terrain_map)
    except Exception:
        return [
            ValidationFinding(
                code="terrain.shape",
                severity="error",
                message="tile_map and terrain_map must be array-like",
                layer=_TERRAIN_LAYER,
                evidence="non-array input",
            )
        ]
    if tile_arr.ndim != 2 or terrain_arr.ndim != 2:
        return [
            ValidationFinding(
                code="terrain.shape",
                severity="error",
                message="tile and terrain layers must be 2D",
                layer=_TERRAIN_LAYER,
                evidence="tile_ndim=%s; terrain_ndim=%s"
                % (getattr(tile_arr, "ndim", "?"), getattr(terrain_arr, "ndim", "?")),
            )
        ]
    tile_shape = (int(tile_arr.shape[0]), int(tile_arr.shape[1]))
    if tile_arr.size == 0 or terrain_arr.size == 0:
        return [
            ValidationFinding(
                code="terrain.shape",
                severity="error",
                message="tile and terrain layers must be non-empty",
                layer=_TERRAIN_LAYER,
                evidence="tile_shape=%s; terrain_shape=%s"
                % (tuple(tile_arr.shape), tuple(terrain_arr.shape)),
            )
        ]

    try:
        river_arr = None if river_map is None else np.asarray(river_map)
    except Exception:
        river_arr = None
        findings.append(
            ValidationFinding(
                code="river.shape",
                severity="error",
                message="river_map must be array-like",
                layer=_RIVERS_LAYER,
                evidence="non-array river_map",
            )
        )
    try:
        height_arr = None if height_map is None else np.asarray(height_map)
    except Exception:
        height_arr = None
        findings.append(
            ValidationFinding(
                code="height.shape",
                severity="error",
                message="height_map must be array-like",
                layer=_HEIGHT_LAYER,
                evidence="non-array height_map",
            )
        )
    try:
        city_arr = None if city_map is None else np.asarray(city_map)
    except Exception:
        city_arr = None
        findings.append(
            ValidationFinding(
                code="mask.shape",
                severity="error",
                message="city_map must be array-like",
                layer=_CITIES_LAYER,
                evidence="non-array city_map",
            )
        )
    try:
        tree_arr = None if tree_map is None else np.asarray(tree_map)
    except Exception:
        tree_arr = None
        findings.append(
            ValidationFinding(
                code="mask.shape",
                severity="error",
                message="tree_map must be array-like",
                layer=_TREES_LAYER,
                evidence="non-array tree_map",
            )
        )

    terrain_ok = tuple(terrain_arr.shape[:2]) in _acceptable_shapes("terrain", tile_shape, profile)
    if not terrain_ok:
        findings.append(
            _shape_finding(
                code="terrain.shape",
                layer=_TERRAIN_LAYER,
                label="terrain_map",
                actual=tuple(terrain_arr.shape),
                acceptable=_acceptable_shapes("terrain", tile_shape, profile),
                tile_shape=tile_shape,
            )
        )
    river_ok = True
    if river_arr is not None:
        if river_arr.ndim != 2:
            river_ok = False
            findings.append(
                ValidationFinding(
                    code="river.shape",
                    severity="error",
                    message="river_map must be 2D",
                    layer=_RIVERS_LAYER,
                    evidence="river_ndim=%s; tile=%dx%d"
                    % (getattr(river_arr, "ndim", "?"), tile_shape[1], tile_shape[0]),
                )
            )
        elif tuple(river_arr.shape[:2]) not in _acceptable_shapes("river", tile_shape, profile):
            river_ok = False
            findings.append(
                _shape_finding(
                    code="river.shape",
                    layer=_RIVERS_LAYER,
                    label="river_map",
                    actual=tuple(river_arr.shape),
                    acceptable=_acceptable_shapes("river", tile_shape, profile),
                    tile_shape=tile_shape,
                )
            )
    height_ok = True
    if height_arr is not None:
        if height_arr.ndim != 2:
            height_ok = False
            findings.append(
                ValidationFinding(
                    code="height.shape",
                    severity="error",
                    message="height_map must be 2D",
                    layer=_HEIGHT_LAYER,
                    evidence="height_ndim=%s; tile=%dx%d"
                    % (getattr(height_arr, "ndim", "?"), tile_shape[1], tile_shape[0]),
                )
            )
        elif tuple(height_arr.shape[:2]) not in _acceptable_shapes("height", tile_shape, profile):
            height_ok = False
            findings.append(
                _shape_finding(
                    code="height.shape",
                    layer=_HEIGHT_LAYER,
                    label="height_map",
                    actual=tuple(height_arr.shape),
                    acceptable=_acceptable_shapes("height", tile_shape, profile),
                    tile_shape=tile_shape,
                )
            )
    city_ok = True
    if city_arr is not None:
        if city_arr.ndim != 2:
            city_ok = False
            findings.append(
                ValidationFinding(
                    code="mask.shape",
                    severity="error",
                    message="city_map must be 2D",
                    layer=_CITIES_LAYER,
                    evidence="city_ndim=%s; tile=%dx%d"
                    % (getattr(city_arr, "ndim", "?"), tile_shape[1], tile_shape[0]),
                )
            )
        elif tuple(city_arr.shape[:2]) not in _acceptable_shapes("city", tile_shape, profile):
            city_ok = False
            findings.append(
                _shape_finding(
                    code="mask.shape",
                    layer=_CITIES_LAYER,
                    label="city_map",
                    actual=tuple(city_arr.shape),
                    acceptable=_acceptable_shapes("city", tile_shape, profile),
                    tile_shape=tile_shape,
                )
            )
    tree_ok = True
    if tree_arr is not None:
        if tree_arr.ndim != 2:
            tree_ok = False
            findings.append(
                ValidationFinding(
                    code="mask.shape",
                    severity="error",
                    message="tree_map must be 2D",
                    layer=_TREES_LAYER,
                    evidence="tree_ndim=%s; tile=%dx%d"
                    % (getattr(tree_arr, "ndim", "?"), tile_shape[1], tile_shape[0]),
                )
            )
        elif tuple(tree_arr.shape[:2]) not in _acceptable_shapes("tree", tile_shape, profile):
            tree_ok = False
            findings.append(
                _shape_finding(
                    code="mask.shape",
                    layer=_TREES_LAYER,
                    label="tree_map",
                    actual=tuple(tree_arr.shape),
                    acceptable=_acceptable_shapes("tree", tile_shape, profile),
                    tile_shape=tile_shape,
                )
            )

    if terrain_ok:
        legal_terrain, legal_source = _resolve_legal_terrain_indices(terrain_indices, profile)
        try:
            unique_terrain = np.unique(terrain_arr)
        except Exception:
            unique_terrain = np.array([], dtype=np.int64)
        illegal_values = sorted(int(v) for v in unique_terrain.tolist() if int(v) not in legal_terrain)
        if illegal_values:
            illegal_set = set(illegal_values)
            try:
                bad_mask = np.isin(terrain_arr, list(illegal_set))
            except Exception:
                bad_mask = terrain_arr != terrain_arr
            coords, total = _sample_coords(np.asarray(bad_mask, dtype=bool))
            findings.append(
                ValidationFinding(
                    code="terrain.index",
                    severity="error",
                    message="%d terrain pixels use %d illegal indices" % (total, len(illegal_values)),
                    layer=_TERRAIN_LAYER,
                    affected_ids=tuple(illegal_values),
                    coordinates=coords,
                    evidence="illegal=%s; pixels=%d; source=%s"
                    % (",".join(str(v) for v in illegal_values), total, legal_source),
                )
            )
        _, tile_land, tile_sea, tile_lake = _tile_constants()
        ocean_idx, lakes_idx = _ocean_lake_indices()
        try:
            illegal_lookup = set(illegal_values)
        except Exception:
            illegal_lookup = set()
        for kind, tile_value, bad_desc, make_bad in (
            ("land", tile_land, "land pixels use water terrain", lambda t: (t == ocean_idx) | (t == lakes_idx)),
            ("sea", tile_sea, "sea pixels do not use ocean terrain", lambda t: t != ocean_idx),
            ("lake", tile_lake, "lake pixels do not use lakes terrain", lambda t: t != lakes_idx),
        ):
            try:
                surface = tile_arr == tile_value
            except Exception:
                continue
            if not bool(np.any(surface)):
                continue
            try:
                terrain_vals = terrain_arr[surface]
            except Exception:
                continue
            if illegal_lookup:
                try:
                    keep = ~np.isin(terrain_vals, list(illegal_lookup))
                except Exception:
                    keep = np.ones(terrain_vals.shape, dtype=bool)
                if not bool(np.any(keep)):
                    continue
                check_vals = terrain_vals[keep]
                full_bad = make_bad(terrain_arr)
                legal_only_bad = full_bad & surface
                try:
                    illegal_mask = np.isin(terrain_arr, list(illegal_lookup))
                    legal_only_bad = legal_only_bad & (~illegal_mask)
                except Exception:
                    pass
                bad_count = int(np.sum(legal_only_bad))
                if bad_count <= 0:
                    continue
                coords, total = _sample_coords(np.asarray(legal_only_bad, dtype=bool))
                distinct = sorted(int(v) for v in np.unique(check_vals[make_bad(check_vals)]).tolist())
            else:
                try:
                    bad = make_bad(terrain_arr) & surface
                except Exception:
                    continue
                bad_count = int(np.sum(bad))
                if bad_count <= 0:
                    continue
                coords, total = _sample_coords(np.asarray(bad, dtype=bool))
                try:
                    distinct = sorted(int(v) for v in np.unique(terrain_arr[bad]).tolist())
                except Exception:
                    distinct = []
            findings.append(
                ValidationFinding(
                    code="terrain.surface_mismatch",
                    severity="error",
                    message="%d %s" % (bad_count, bad_desc),
                    layer=_TERRAIN_LAYER,
                    affected_ids=tuple(distinct),
                    coordinates=coords,
                    evidence="surface=%s; pixels=%d; terrain=%s; tile=%d"
                    % (kind, bad_count, ",".join(str(v) for v in distinct), int(tile_value)),
                )
            )

    if river_arr is not None and river_ok:
        _, _, legal_river = _resolve_legal_river_values()
        try:
            unique_river = np.unique(river_arr)
        except Exception:
            unique_river = np.array([], dtype=np.int64)
        illegal_river = sorted(int(v) for v in unique_river.tolist() if int(v) not in legal_river)
        if illegal_river:
            illegal_set = set(illegal_river)
            try:
                bad_mask = np.isin(river_arr, list(illegal_set))
            except Exception:
                bad_mask = np.zeros(river_arr.shape, dtype=bool)
            coords, total = _sample_coords(np.asarray(bad_mask, dtype=bool))
            findings.append(
                ValidationFinding(
                    code="river.value",
                    severity="error",
                    message="%d river pixels use %d illegal values" % (total, len(illegal_river)),
                    layer=_RIVERS_LAYER,
                    affected_ids=tuple(illegal_river),
                    coordinates=coords,
                    evidence="illegal=%s; pixels=%d"
                    % (",".join(str(v) for v in illegal_river), total),
                )
            )
        try:
            valid_only, _, _ = _resolve_legal_river_values()
            river_mask = np.isin(river_arr, list(valid_only))
        except Exception:
            river_mask = np.zeros(river_arr.shape, dtype=bool)
        if bool(np.any(river_mask)):
            width_finding = _river_width_finding(np.asarray(river_mask, dtype=bool))
            if width_finding is not None:
                findings.append(width_finding)
            connectivity_finding = _river_connectivity_finding(np.asarray(river_mask, dtype=bool))
            if connectivity_finding is not None:
                findings.append(connectivity_finding)

    if height_arr is not None and height_ok:
        bad_height = _out_of_range_mask(height_arr)
        if bad_height is not None:
            coords, total = _sample_coords(bad_height)
            try:
                distinct = sorted(int(v) for v in np.unique(height_arr[bad_height]).tolist())
            except Exception:
                distinct = []
            findings.append(
                ValidationFinding(
                    code="height.value",
                    severity="error",
                    message="%d height pixels are outside 0-255" % total,
                    layer=_HEIGHT_LAYER,
                    affected_ids=tuple(distinct),
                    coordinates=coords,
                    evidence="pixels=%d; values=%s" % (total, ",".join(str(v) for v in distinct)),
                )
            )
    if city_arr is not None and city_ok:
        bad_city = _out_of_range_mask(city_arr)
        if bad_city is not None:
            coords, total = _sample_coords(bad_city)
            try:
                distinct = sorted(int(v) for v in np.unique(city_arr[bad_city]).tolist())
            except Exception:
                distinct = []
            findings.append(
                ValidationFinding(
                    code="city.value",
                    severity="error",
                    message="%d city pixels are outside 0-255" % total,
                    layer=_CITIES_LAYER,
                    affected_ids=tuple(distinct),
                    coordinates=coords,
                    evidence="pixels=%d; values=%s" % (total, ",".join(str(v) for v in distinct)),
                )
            )
    if tree_arr is not None and tree_ok:
        legal_tree, tree_source = _resolve_legal_tree_indices(profile)
        try:
            unique_tree = np.unique(tree_arr)
        except Exception:
            unique_tree = np.array([], dtype=np.int64)
        illegal_tree = sorted(int(v) for v in unique_tree.tolist() if int(v) not in legal_tree)
        if illegal_tree:
            illegal_set = set(illegal_tree)
            try:
                bad_mask = np.isin(tree_arr, list(illegal_set))
            except Exception:
                bad_mask = np.zeros(tree_arr.shape, dtype=bool)
            coords, total = _sample_coords(np.asarray(bad_mask, dtype=bool))
            findings.append(
                ValidationFinding(
                    code="tree.value",
                    severity="error",
                    message="%d tree pixels use %d illegal indices" % (total, len(illegal_tree)),
                    layer=_TREES_LAYER,
                    affected_ids=tuple(illegal_tree),
                    coordinates=coords,
                    evidence="illegal=%s; pixels=%d; source=%s"
                    % (",".join(str(v) for v in illegal_tree), total, tree_source),
                )
            )
    return findings
