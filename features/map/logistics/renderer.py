"""Logistics Mode Canvas Rendering - Railroad Grade Shaded Illustration.

Each province with railways is colored by level (1=grey-blue → 5=red).
Much faster than drawing line segments and KR 1027 rails don’t get stuck."""

from __future__ import annotations

import hashlib

import numpy as np


_COMPONENT_PALETTE = np.asarray(
    (
        (54, 111, 180),
        (67, 145, 108),
        (177, 116, 53),
        (145, 82, 164),
        (51, 157, 165),
        (188, 91, 101),
        (129, 144, 57),
        (91, 111, 173),
    ),
    dtype=np.uint8,
)
_DISCONNECTED_COLOR = np.asarray((232, 72, 72), dtype=np.uint8)
_OFF_RAIL_SUPPLY_COLOR = np.asarray((245, 52, 194), dtype=np.uint8)


def _component_color(component_id: str, index: int) -> np.ndarray:
    """Return a deterministic RGB color for one stable component identity."""
    digest = hashlib.sha256(str(component_id).encode("ascii", "replace")).digest()
    palette_index = (int.from_bytes(digest[:4], "big") + int(index)) % len(_COMPONENT_PALETTE)
    return _COMPONENT_PALETTE[palette_index]


def highlight_logistics_findings(
    rgb: np.ndarray,
    province_map: np.ndarray,
    graph,
    *,
    component_keys=(),
    supply_keys=(),
) -> np.ndarray:
    """Highlight disconnected components and off-rail supply provinces."""
    from domain.logistics_exceptions import (
        component_identity_for,
        is_component_key,
        is_supply_key,
        supply_province_for,
    )

    result = np.asarray(rgb, dtype=np.uint8).copy()
    province_arr = np.asarray(province_map)
    component_ids = {
        component_identity_for(key)
        for key in component_keys
        if is_component_key(key)
    }
    supply_ids = {
        supply_province_for(key)
        for key in supply_keys
        if is_supply_key(key)
    }
    highlighted_provinces = []
    for component in tuple(getattr(graph, "components", ()) or ()):
        if getattr(component, "component_id", None) in component_ids:
            highlighted_provinces.extend(
                getattr(component, "provinces", ()) or ()
            )
    if highlighted_provinces:
        result[np.isin(province_arr, tuple(highlighted_provinces))] = (
            _DISCONNECTED_COLOR
        )
    if supply_ids:
        result[np.isin(province_arr, tuple(sorted(supply_ids)))] = (
            _OFF_RAIL_SUPPLY_COLOR
        )
    return result


def build_logistics_component_colors(
    province_map: np.ndarray,
    graph,
    *,
    base_rgb: np.ndarray | None = None,
    exception_manager=None,
) -> np.ndarray:
    """Build an RGB province/component map for logistics mode."""
    province_arr = np.asarray(province_map)
    if province_arr.ndim != 2:
        raise ValueError("province_map must be a 2-D array")
    if base_rgb is None:
        result = np.empty((*province_arr.shape, 3), dtype=np.uint8)
        result[...] = (48, 53, 62)
    else:
        base = np.asarray(base_rgb, dtype=np.uint8)
        if base.shape != (*province_arr.shape, 3):
            raise ValueError("base_rgb must match province_map with an RGB channel")
        result = base.copy()

    components = tuple(getattr(graph, "components", ()) or ())
    if components and province_arr.size:
        # Components are disjoint province-ID sets. Build one province-ID
        # lookup and index it once instead of scanning the full raster once
        # per component. Belgium has hundreds of components, so the latter
        # turns this refresh into billions of element comparisons.
        max_pid = int(province_arr.max())
        if max_pid >= 0 and max_pid <= 2_000_000:
            component_lookup = np.full(max_pid + 1, -1, dtype=np.int32)
            component_colors = []
            for index, component in enumerate(components):
                provinces = tuple(getattr(component, "provinces", ()) or ())
                valid_provinces = tuple(
                    int(pid)
                    for pid in provinces
                    if isinstance(pid, (int, np.integer))
                    and 0 <= int(pid) <= max_pid
                )
                if not valid_provinces:
                    continue
                color_index = len(component_colors)
                component_lookup[np.asarray(valid_provinces, dtype=np.int64)] = color_index
                component_colors.append(
                    _component_color(
                        getattr(component, "component_id", ""), index
                    )
                )
            if component_colors:
                if np.issubdtype(province_arr.dtype, np.integer) and not np.any(
                    province_arr < 0
                ):
                    component_indices = component_lookup[province_arr]
                    matched = component_indices >= 0
                else:
                    valid = (province_arr >= 0) & (province_arr <= max_pid)
                    component_indices = np.full(
                        province_arr.shape, -1, dtype=np.int32
                    )
                    component_indices[valid] = component_lookup[
                        province_arr[valid].astype(np.int64, copy=False)
                    ]
                    matched = component_indices >= 0
                colors = np.asarray(component_colors, dtype=np.uint8)
                result[matched] = colors[component_indices[matched]]
        else:
            # Keep the renderer correct for unusual projects with sparse,
            # very large province IDs without allocating a huge lookup table.
            for index, component in enumerate(components):
                provinces = tuple(getattr(component, "provinces", ()) or ())
                if provinces:
                    result[np.isin(province_arr, provinces)] = _component_color(
                        getattr(component, "component_id", ""), index
                    )

    from domain.logistics_exceptions import evaluate_exception_coverage, relevant_exception_keys

    if exception_manager is None:
        highlight_keys = relevant_exception_keys(graph)
    else:
        coverage = evaluate_exception_coverage(exception_manager, graph)
        highlight_keys = tuple(sorted(set(coverage.missing_keys) | set(coverage.stale_keys)))
    from domain.logistics_exceptions import is_component_key, is_supply_key

    component_keys = tuple(key for key in highlight_keys if is_component_key(key))
    supply_keys = tuple(key for key in highlight_keys if is_supply_key(key))
    return highlight_logistics_findings(
        result,
        province_arr,
        graph,
        component_keys=component_keys,
        supply_keys=supply_keys,
    )


def render(canvas) -> None:
    """Logistics Mode: Railroad grade coloring."""
    color_rgb = getattr(canvas, "_logistics_component_rgb", None)
    if color_rgb is None:
        color_rgb = getattr(canvas, "_railway_color_rgb", None)
    if color_rgb is not None:
        canvas._display_buffer[:, :, 0] = color_rgb[:, :, 2]
        canvas._display_buffer[:, :, 1] = color_rgb[:, :, 1]
        canvas._display_buffer[:, :, 2] = color_rgb[:, :, 0]
        canvas._display_buffer[:, :, 3] = 255
    else:
        # fallback: Map of land and sea floor
        from features.map.land import renderer as land_renderer
        land_renderer.render(canvas)


def partial_render(canvas, x0: int, y0: int, x1: int, y1: int) -> None:
    buf = canvas._display_buffer[y0:y1, x0:x1]
    color_rgb = getattr(canvas, "_logistics_component_rgb", None)
    if color_rgb is None:
        color_rgb = getattr(canvas, "_railway_color_rgb", None)
    if color_rgb is not None:
        region = color_rgb[y0:y1, x0:x1]
        buf[:, :, 0] = region[:, :, 2]
        buf[:, :, 1] = region[:, :, 1]
        buf[:, :, 2] = region[:, :, 0]
        buf[:, :, 3] = 255
    else:
        from features.map.land import renderer as land_renderer
        land_renderer.partial_render(canvas, x0, y0, x1, y1)
