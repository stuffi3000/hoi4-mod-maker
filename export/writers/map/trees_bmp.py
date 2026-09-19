"""map/trees.bmp writer.

8-bit indexed BMP, bottom-up, vanilla palette (256 colors).
Size = map ÷ 4 (HOI4 scaled to actual map).

Reference: Map modding.txt §Trees (lines 419-470)."""

from __future__ import annotations

import os
import struct

import numpy as np

# Note: Use import as, not from import — from import is value binding, set_map_size is not updated.
import data.constants as _const
from data.trees_palette import TREES_PALETTE_BYTES

def _coerce_positive_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _resolve_explicit_target(target_width=None, target_height=None):
    width = _coerce_positive_int(target_width) if target_width is not None else None
    height = _coerce_positive_int(target_height) if target_height is not None else None
    if width is not None and height is not None:
        return (width, height)
    return None


def _resolve_profile_tree_size(profile, map_width, map_height):
    try:
        map_w = int(map_width)
        map_h = int(map_height)
    except (TypeError, ValueError):
        return None
    if map_w <= 0 or map_h <= 0:
        return None
    if profile is None:
        return None
    try:
        from domain.game_profile import resolve_tree_dimensions as _resolve
        sized = _resolve(profile, map_w, map_h)
    except Exception:
        return None
    try:
        out_w = int(sized[0])
        out_h = int(sized[1])
    except (TypeError, ValueError, IndexError):
        return None
    if out_w <= 0 or out_h <= 0:
        return None
    return (out_w, out_h)


def _nearest_indices(src_len, dst_len):
    try:
        src = int(src_len)
        dst = int(dst_len)
    except (TypeError, ValueError):
        return None
    if src <= 0 or dst <= 0:
        return None
    rows = (np.arange(dst, dtype=np.int64) * np.int64(src) // np.int64(dst))
    rows = np.clip(rows, 0, src - 1).astype(np.int64)
    return rows


def _resize_nearest(data, target_h, target_w):
    src_h, src_w = int(data.shape[0]), int(data.shape[1])
    dst_h, dst_w = int(target_h), int(target_w)
    if src_h == dst_h and src_w == dst_w:
        return data.astype(np.uint8, copy=True)
    row_idx = _nearest_indices(src_h, dst_h)
    col_idx = _nearest_indices(src_w, dst_w)
    if row_idx is None or col_idx is None:
        return data.astype(np.uint8, copy=True)
    return np.asarray(data[row_idx[:, None], col_idx], dtype=np.uint8)


def _profile_legal_tree_indices(profile):
    if profile is None:
        return None
    try:
        from domain.managers.default_map_settings import resolve_profile_tree_indices
        return resolve_profile_tree_indices(profile)
    except (ImportError, AttributeError, TypeError, ValueError):
        return None


def write_trees_bmp(
    output_dir: str,
    tree_map: np.ndarray | None = None,
    map_width: int | None = None,
    map_height: int | None = None,
    *,
    profile=None,
    target_width: int | None = None,
    target_height: int | None = None,
) -> tuple[int, int]:
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "trees.bmp")
    explicit = _resolve_explicit_target(target_width, target_height)
    if tree_map is not None:
        data = np.asarray(tree_map).astype(np.uint8)
        if data.ndim != 2:
            data = np.asarray(data).reshape(data.shape[:2]).astype(np.uint8)
        base_h, base_w = int(data.shape[0]), int(data.shape[1])
        if explicit is not None:
            out_w, out_h = explicit
        elif profile is not None and map_width is not None and map_height is not None:
            resolved = _resolve_profile_tree_size(profile, map_width, map_height)
            if resolved is not None:
                out_w, out_h = resolved
            else:
                out_w, out_h = base_w, base_h
        else:
            out_w, out_h = base_w, base_h
        if (out_w, out_h) != (base_w, base_h):
            data = _resize_nearest(data, out_h, out_w)
        h, w = int(data.shape[0]), int(data.shape[1])
    else:
        try:
            mw = int(map_width) if map_width is not None else int(_const.MAP_WIDTH)
        except (TypeError, ValueError):
            mw = int(_const.MAP_WIDTH)
        try:
            mh = int(map_height) if map_height is not None else int(_const.MAP_HEIGHT)
        except (TypeError, ValueError):
            mh = int(_const.MAP_HEIGHT)
        if explicit is not None:
            w, h = explicit
        elif profile is not None:
            resolved = _resolve_profile_tree_size(profile, mw, mh)
            if resolved is not None:
                w, h = resolved
            else:
                w, h = mw // 4, mh // 4
        else:
            w, h = mw // 4, mh // 4
        w, h = int(w), int(h)
        if w <= 0:
            w = max(1, mw // 4)
        if h <= 0:
            h = max(1, mh // 4)
        data = np.zeros((h, w), dtype=np.uint8)
    legal = _profile_legal_tree_indices(profile)
    if legal:
        allowed = np.zeros(256, dtype=bool)
        allowed[list(legal)] = True
        data = np.where(allowed[data], data, 0).astype(np.uint8, copy=False)
    row_bytes = w
    row_pad = (4 - row_bytes % 4) % 4
    padded_row = row_bytes + row_pad
    data_flipped = data[::-1, :]
    palette_size = 256 * 4
    pixel_size = padded_row * h
    header_size = 14 + 40 + palette_size
    file_size = header_size + pixel_size
    with open(path, "wb") as handle:
        handle.write(b"BM")
        handle.write(struct.pack("<I", file_size))
        handle.write(struct.pack("<HH", 0, 0))
        handle.write(struct.pack("<I", header_size))
        handle.write(struct.pack("<I", 40))
        handle.write(struct.pack("<i", w))
        handle.write(struct.pack("<i", h))
        handle.write(struct.pack("<HH", 1, 8))
        handle.write(struct.pack("<I", 0))
        handle.write(struct.pack("<I", pixel_size))
        handle.write(struct.pack("<ii", 2835, 2835))
        handle.write(struct.pack("<II", 256, 0))
        handle.write(TREES_PALETTE_BYTES)
        pad = b"\x00" * row_pad
        for row in range(h):
            handle.write(data_flipped[row, :].tobytes())
            if row_pad:
                handle.write(pad)
    return (w, h)


def auto_generate_tree_map(
    terrain_map: np.ndarray,
    *,
    profile=None,
    target_width: int | None = None,
    target_height: int | None = None,
    map_width: int | None = None,
    map_height: int | None = None,
) -> np.ndarray:
    from data.terrain_types import TERRAIN_PALETTE_INDEX
    from data.trees_palette import TERRAIN_TO_TREE_INDEX
    full = np.asarray(terrain_map)
    full_h, full_w = int(full.shape[0]), int(full.shape[1])
    try:
        eff_map_w = int(map_width) if map_width is not None else full_w
    except (TypeError, ValueError):
        eff_map_w = full_w
    try:
        eff_map_h = int(map_height) if map_height is not None else full_h
    except (TypeError, ValueError):
        eff_map_h = full_h
    explicit = _resolve_explicit_target(target_width, target_height)
    if explicit is not None:
        w, h = explicit
    elif profile is not None:
        resolved = _resolve_profile_tree_size(profile, eff_map_w, eff_map_h)
        if resolved is not None:
            w, h = resolved
        else:
            w, h = full_w // 4, full_h // 4
    else:
        w, h = full_w // 4, full_h // 4
    w, h = int(w), int(h)
    if w <= 0:
        w = max(1, full_w // 4)
    if h <= 0:
        h = max(1, full_h // 4)
    row_idx = _nearest_indices(full_h, h)
    col_idx = _nearest_indices(full_w, w)
    if row_idx is None or col_idx is None:
        step_y = max(1, full_h // max(1, h))
        step_x = max(1, full_w // max(1, w))
        small_terrain = full[::step_y, ::step_x][:h, :w]
    else:
        small_terrain = np.asarray(full[row_idx[:, None], col_idx])
        if small_terrain.shape[:2] != (h, w):
            small_terrain = np.asarray(small_terrain).reshape(h, w)
    idx_to_name: dict[int, str] = {}
    for tname, tidx in TERRAIN_PALETTE_INDEX.items():
        try:
            idx_to_name[int(tidx)] = str(tname)
        except (TypeError, ValueError):
            continue
    tree_map = np.zeros((h, w), dtype=np.uint8)
    legal = _profile_legal_tree_indices(profile)
    for terrain_idx in sorted(idx_to_name.keys()):
        terrain_name = idx_to_name[terrain_idx]
        try:
            tree_idx = int(TERRAIN_TO_TREE_INDEX.get(terrain_name, 0))
        except (TypeError, ValueError):
            continue
        if tree_idx > 0 and (not legal or tree_idx in legal):
            try:
                tree_map[small_terrain == terrain_idx] = np.uint8(tree_idx)
            except Exception:
                continue
    return tree_map
