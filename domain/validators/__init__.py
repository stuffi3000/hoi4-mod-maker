"""Validator package with shared M3.1/M3.2a contracts."""
from domain.validation import (
    GATE_CONTEXTS,
    FINDING_SEVERITIES,
    SEVERITY_RANK,
    GateDecision,
    ValidationFinding,
    ValidationReport,
    ValidatorRegistry,
    coerce_finding,
    evaluate_gate,
)
from domain.validators.geography import validate_geography_references
from domain.validators.logistics import validate_logistics_references
from domain.validators.raster import validate_raster_definition
from domain.validators.terrain import validate_terrain_layers

FOUNDATION_RASTER_VALIDATOR_NAME = "raster/definition"
FOUNDATION_TERRAIN_VALIDATOR_NAME = "terrain/layers"
FOUNDATION_GEOGRAPHY_VALIDATOR_NAME = "geography/references"
FOUNDATION_LOGISTICS_VALIDATOR_NAME = "logistics/references"


def _foundation_raster_check(
    *,
    tile_map=None,
    province_map=None,
    definitions=None,
    terrain_map=None,
    river_map=None,
    height_map=None,
    city_map=None,
    tree_map=None,
    profile=None,
    expected_dimensions=None,
    wrap_horizontal=None,
    max_bbox_ratio=None,
    include_engine_boundary=False,
    mixed_threshold=0.0,
    terrain_indices=None,
    **_ignored,
):
    return validate_raster_definition(
        tile_map,
        province_map,
        definitions,
        profile=profile,
        expected_dimensions=expected_dimensions,
        wrap_horizontal=wrap_horizontal,
        max_bbox_ratio=max_bbox_ratio,
        include_engine_boundary=include_engine_boundary,
        mixed_threshold=mixed_threshold,
    )


def _foundation_terrain_check(
    *,
    tile_map=None,
    terrain_map=None,
    province_map=None,
    definitions=None,
    river_map=None,
    height_map=None,
    city_map=None,
    tree_map=None,
    profile=None,
    expected_dimensions=None,
    wrap_horizontal=None,
    max_bbox_ratio=None,
    include_engine_boundary=False,
    mixed_threshold=0.0,
    terrain_indices=None,
    **_ignored,
):
    return validate_terrain_layers(
        tile_map,
        terrain_map,
        river_map=river_map,
        height_map=height_map,
        city_map=city_map,
        tree_map=tree_map,
        profile=profile,
        terrain_indices=terrain_indices,
    )


def _foundation_geography_check(
    *,
    tile_map=None,
    province_map=None,
    definitions=None,
    terrain_map=None,
    river_map=None,
    height_map=None,
    city_map=None,
    tree_map=None,
    profile=None,
    expected_dimensions=None,
    wrap_horizontal=None,
    max_bbox_ratio=None,
    include_engine_boundary=False,
    mixed_threshold=0.0,
    terrain_indices=None,
    state_mgr=None,
    country_mgr=None,
    continent_mgr=None,
    strategic_region_mgr=None,
    adjacency_mgr=None,
    railway_mgr=None,
    supply_mgr=None,
    adjacency_rule_mgr=None,
    **_ignored,
):
    return validate_geography_references(
        province_map,
        tile_map,
        state_mgr=state_mgr,
        country_mgr=country_mgr,
        continent_mgr=continent_mgr,
        strategic_region_mgr=strategic_region_mgr,
        profile=profile,
        wrap_horizontal=wrap_horizontal,
    )


def _foundation_logistics_check(
    *,
    tile_map=None,
    province_map=None,
    definitions=None,
    terrain_map=None,
    river_map=None,
    height_map=None,
    city_map=None,
    tree_map=None,
    profile=None,
    expected_dimensions=None,
    wrap_horizontal=None,
    max_bbox_ratio=None,
    include_engine_boundary=False,
    mixed_threshold=0.0,
    terrain_indices=None,
    state_mgr=None,
    country_mgr=None,
    continent_mgr=None,
    strategic_region_mgr=None,
    adjacency_mgr=None,
    railway_mgr=None,
    supply_mgr=None,
    adjacency_rule_mgr=None,
    **_ignored,
):
    return validate_logistics_references(
        province_map,
        tile_map,
        adjacency_mgr=adjacency_mgr,
        railway_mgr=railway_mgr,
        supply_mgr=supply_mgr,
        adjacency_rule_mgr=adjacency_rule_mgr,
        country_mgr=country_mgr,
        profile=profile,
        wrap_horizontal=wrap_horizontal,
    )


def create_foundation_validator_registry():
    registry = ValidatorRegistry()
    registry.register(FOUNDATION_RASTER_VALIDATOR_NAME, _foundation_raster_check)
    registry.register(FOUNDATION_TERRAIN_VALIDATOR_NAME, _foundation_terrain_check)
    registry.register(FOUNDATION_GEOGRAPHY_VALIDATOR_NAME, _foundation_geography_check)
    registry.register(FOUNDATION_LOGISTICS_VALIDATOR_NAME, _foundation_logistics_check)
    return registry


def run_foundation_validation(
    tile_map=None,
    province_map=None,
    definitions=None,
    terrain_map=None,
    river_map=None,
    height_map=None,
    city_map=None,
    tree_map=None,
    profile=None,
    expected_dimensions=None,
    wrap_horizontal=None,
    max_bbox_ratio=None,
    include_engine_boundary=False,
    mixed_threshold=0.0,
    terrain_indices=None,
    state_mgr=None,
    country_mgr=None,
    continent_mgr=None,
    strategic_region_mgr=None,
    adjacency_mgr=None,
    railway_mgr=None,
    supply_mgr=None,
    adjacency_rule_mgr=None,
    context="draft_preview",
    source="foundation",
):
    registry = create_foundation_validator_registry()
    findings = registry.run(
        tile_map=tile_map,
        province_map=province_map,
        definitions=definitions,
        terrain_map=terrain_map,
        river_map=river_map,
        height_map=height_map,
        city_map=city_map,
        tree_map=tree_map,
        profile=profile,
        expected_dimensions=expected_dimensions,
        wrap_horizontal=wrap_horizontal,
        max_bbox_ratio=max_bbox_ratio,
        include_engine_boundary=include_engine_boundary,
        mixed_threshold=mixed_threshold,
        terrain_indices=terrain_indices,
        state_mgr=state_mgr,
        country_mgr=country_mgr,
        continent_mgr=continent_mgr,
        strategic_region_mgr=strategic_region_mgr,
        adjacency_mgr=adjacency_mgr,
        railway_mgr=railway_mgr,
        supply_mgr=supply_mgr,
        adjacency_rule_mgr=adjacency_rule_mgr,
    )
    return ValidationReport(findings=findings, source=source, context=context)


__all__ = [
    "FINDING_SEVERITIES",
    "GATE_CONTEXTS",
    "SEVERITY_RANK",
    "FOUNDATION_RASTER_VALIDATOR_NAME",
    "FOUNDATION_TERRAIN_VALIDATOR_NAME",
    "FOUNDATION_GEOGRAPHY_VALIDATOR_NAME",
    "FOUNDATION_LOGISTICS_VALIDATOR_NAME",
    "GateDecision",
    "ValidationFinding",
    "ValidationReport",
    "ValidatorRegistry",
    "coerce_finding",
    "create_foundation_validator_registry",
    "evaluate_gate",
    "run_foundation_validation",
]
