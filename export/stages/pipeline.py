"""Ordered stage pipeline (M2.4).

`export/mod_exporter.py` remains the compatibility facade; the stages below
own the actual file generation for planner-driven exports. Execution order
is fixed so definition.csv always uses the final coastal set and acceptance
test ownership is visible in the exported state shells.
"""
from __future__ import annotations

from export.stages import acceptance_content, assets, core_rasters, descriptor, logistics
from export.stages import map_metadata, placements, regions, scaffold_content, state_geography


STAGE_MODULES = {
    core_rasters.NAME: core_rasters,
    regions.NAME: regions,
    logistics.NAME: logistics,
    placements.NAME: placements,
    map_metadata.NAME: map_metadata,
    state_geography.NAME: state_geography,
    acceptance_content.NAME: acceptance_content,
    scaffold_content.NAME: scaffold_content,
    assets.NAME: assets,
    descriptor.NAME: descriptor,
}

STAGE_ORDER = (
    "core_rasters",
    "regions",
    "logistics",
    "placements",
    "map_metadata",
    "acceptance_content",
    "state_geography",
    "scaffold_content",
    "assets",
    "descriptor",
)


def stages_for_profile(profile_name: str) -> tuple:
    from domain.export_contract import PROFILE_STAGES
    try:
        wanted = tuple(PROFILE_STAGES[profile_name])
    except KeyError:
        raise ValueError("unknown export profile %r" % profile_name)
    unknown = [name for name in wanted if name not in STAGE_MODULES]
    if unknown:
        raise ValueError("export stages not implemented: %s" % ", ".join(unknown))
    return tuple(name for name in STAGE_ORDER if name in wanted)


def _legacy_complete_working_copy(ctx) -> list:
    notes = []
    from services import export_service as _es
    import numpy as _np
    fixed: list = []
    if ctx.state_mgr is not None:
        _es._precheck_clean_empty_states(ctx.state_mgr, ctx.country_mgr, fixed)
    if ctx.state_mgr is not None and ctx.country_mgr is not None:
        _es._precheck_fix_unowned_states(ctx.state_mgr, ctx.country_mgr, [], fixed)
    if ctx.country_mgr is not None and getattr(ctx.country_mgr, "countries", None):
        _es._precheck_fix_missing_capitals(ctx.state_mgr, ctx.country_mgr, [], fixed)
    region_mgr = ctx.strategic_region_mgr
    if region_mgr is not None and getattr(region_mgr, "regions", None) \
            and ctx.state_mgr is not None and getattr(ctx.state_mgr, "states", None):
        province_map = _np.asarray(ctx.province_map)
        _es._precheck_align_states_to_regions(province_map, int(province_map.max()),
                                              ctx.state_mgr, region_mgr, fixed)
        _es._precheck_split_disconnected_regions(province_map, int(province_map.max()),
                                                 region_mgr, fixed)
    if ctx.state_mgr is not None and getattr(ctx.state_mgr, "states", None):
        filled = _es.fill_default_state_data(
            ctx.state_mgr,
            _np.asarray(ctx.terrain_map) if ctx.terrain_map is not None else None,
            _np.asarray(ctx.province_map),
            _np.asarray(ctx.tile_map),
        )
        if filled:
            fixed.append("Filled default resources/buildings for %d states" % filled)
    notes.extend(fixed)
    return notes


def run_pipeline(ctx, layers=None) -> list:
    from domain.export_contract import StageResult
    wanted = list(layers) if layers else list(stages_for_profile(ctx.profile_name))
    for name in wanted:
        if name not in STAGE_MODULES:
            raise ValueError("unknown export stage %r" % name)
        module = STAGE_MODULES[name]
        if ctx.profile_name not in tuple(getattr(module, "PROFILES", ())):
            raise ValueError("stage %r does not apply to profile %r" % (name, ctx.profile_name))
    import numpy as _np
    import data.constants as _constants
    _map_h, _map_w = _np.asarray(ctx.province_map).shape[:2]
    old_size = (int(_constants.MAP_WIDTH), int(_constants.MAP_HEIGHT))
    _constants.set_map_size(int(_map_w), int(_map_h))
    try:
        results = []
        if ctx.profile_name == "legacy_full":
            legacy_notes = _legacy_complete_working_copy(ctx)
            if legacy_notes:
                ctx.provenance.append("legacy export-copy completion: %s" % "; ".join(legacy_notes))
        for name in wanted:
            module = STAGE_MODULES[name]
            result = module.run(ctx)
            if not isinstance(result, StageResult):
                raise TypeError("stage %r must return a StageResult" % name)
            results.append(result)
        return results
    finally:
        # Writers need the active map size, but an export must not change the
        # editor's process-wide defaults for the next project/export.
        _constants.set_map_size(*old_size)
