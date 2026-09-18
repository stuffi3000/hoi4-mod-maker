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
from domain.validators.raster import validate_raster_definition
from domain.validators.terrain import validate_terrain_layers

FOUNDATION_RASTER_VALIDATOR_NAME = "raster/definition"
FOUNDATION_TERRAIN_VALIDATOR_NAME = "terrain/layers"


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


def create_foundation_validator_registry():
    registry = ValidatorRegistry()
    registry.register(FOUNDATION_RASTER_VALIDATOR_NAME, _foundation_raster_check)
    registry.register(FOUNDATION_TERRAIN_VALIDATOR_NAME, _foundation_terrain_check)
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
    )
    return ValidationReport(findings=findings, source=source, context=context)


__all__ = [
    "FINDING_SEVERITIES",
    "GATE_CONTEXTS",
    "SEVERITY_RANK",
    "FOUNDATION_RASTER_VALIDATOR_NAME",
    "FOUNDATION_TERRAIN_VALIDATOR_NAME",
    "GateDecision",
    "ValidationFinding",
    "ValidationReport",
    "ValidatorRegistry",
    "coerce_finding",
    "create_foundation_validator_registry",
    "evaluate_gate",
    "run_foundation_validation",
]