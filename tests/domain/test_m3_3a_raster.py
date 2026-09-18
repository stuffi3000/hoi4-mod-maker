"""M3.3a raster/definition validator tests (no game install)."""
from __future__ import annotations

import numpy as np
import pytest

from data.constants import TILE_LAND, TILE_SEA
from domain.validation import FINDING_SEVERITIES
from domain.validators.raster import (
    CODES,
    _normalize_definition_ids,
    validate_raster_definition,
)

pytestmark = pytest.mark.unit

_RATIO_RELAXED = 1.0


def _halves_4x4():
    tile = np.ones((4, 4), dtype=np.uint8) * TILE_LAND
    tile[:, 2:] = TILE_SEA
    prov = np.array(
        [[1, 1, 2, 2], [1, 1, 2, 2], [1, 1, 2, 2], [1, 1, 2, 2]],
        dtype=np.int32,
    )
    return tile, prov


def _codes(findings):
    return [f.code for f in findings]


def test_clean_input_has_no_findings():
    tile, prov = _halves_4x4()
    findings = validate_raster_definition(
        tile, prov, definitions={1: "land", 2: "sea"},
        wrap_horizontal=False, max_bbox_ratio=_RATIO_RELAXED,
    )
    assert findings == []


def test_shape_mismatch_is_blocker_and_stops():
    tile = np.ones((4, 4), dtype=np.uint8)
    prov = np.ones((4, 5), dtype=np.int32)
    findings = validate_raster_definition(tile, prov)
    assert len(findings) == 1
    assert findings[0].code == "raster.dimensions"
    assert findings[0].severity == "blocker"


def test_non_2d_input_is_blocker():
    tile = np.ones((4,), dtype=np.uint8)
    prov = np.ones((4,), dtype=np.int32)
    findings = validate_raster_definition(tile, prov)
    assert [f.code for f in findings] == ["raster.dimensions"]
    assert findings[0].severity == "blocker"


def test_expected_dimensions_mismatch_and_match():
    tile, prov = _halves_4x4()
    bad = validate_raster_definition(
        tile, prov, expected_dimensions=(8, 8),
        wrap_horizontal=False, max_bbox_ratio=_RATIO_RELAXED,
    )
    assert "raster.dimensions" in _codes(bad)
    dim = next(f for f in bad if f.code == "raster.dimensions")
    assert dim.severity == "error"
    assert "8x8" in dim.evidence
    good = validate_raster_definition(
        tile, prov, expected_dimensions=(4, 4),
        wrap_horizontal=False, max_bbox_ratio=_RATIO_RELAXED,
    )
    assert "raster.dimensions" not in _codes(good)


def test_profile_dimensions_are_reported():
    class _BadProfile:
        def validate_dimensions(self, width, height):
            return ["Map width %d is not a multiple of 256" % width]

    class _GoodProfile:
        def validate_dimensions(self, width, height):
            return []

    tile, prov = _halves_4x4()
    bad = validate_raster_definition(
        tile, prov, profile=_BadProfile(),
        wrap_horizontal=False, max_bbox_ratio=_RATIO_RELAXED,
    )
    assert "raster.dimensions" in _codes(bad)
    good = validate_raster_definition(
        tile, prov, profile=_GoodProfile(),
        wrap_horizontal=False, max_bbox_ratio=_RATIO_RELAXED,
    )
    assert "raster.dimensions" not in _codes(good)


def test_definition_missing_and_negative_ids():
    tile, prov = _halves_4x4()
    findings = validate_raster_definition(
        tile, prov, definitions={1: "land"},
        wrap_horizontal=False, max_bbox_ratio=_RATIO_RELAXED,
    )
    missing = [f for f in findings if f.code == "raster.definition_missing"]
    assert len(missing) == 1
    assert missing[0].severity == "error"
    assert missing[0].affected_ids == (2,)
    assert len(missing[0].coordinates) == 1

    neg = prov.copy()
    neg[0, 0] = -5
    neg_findings = validate_raster_definition(
        tile, neg, wrap_horizontal=False, max_bbox_ratio=_RATIO_RELAXED,
    )
    neg_missing = [f for f in neg_findings if f.code == "raster.definition_missing"]
    assert neg_missing and -5 in neg_missing[0].affected_ids


def test_definition_orphan_is_warning():
    tile, prov = _halves_4x4()
    findings = validate_raster_definition(
        tile, prov, definitions={1: "land", 2: "sea", 9: "land"},
        wrap_horizontal=False, max_bbox_ratio=_RATIO_RELAXED,
    )
    orphans = [f for f in findings if f.code == "raster.definition_orphan"]
    assert len(orphans) == 1
    assert orphans[0].severity == "warning"
    assert orphans[0].affected_ids == (9,)
    assert orphans[0].waivable is True


def test_id_gap_lists_missing_ids():
    tile = np.ones((4, 4), dtype=np.uint8) * TILE_LAND
    prov = np.array(
        [[1, 1, 3, 3], [1, 1, 3, 3], [1, 1, 3, 3], [1, 1, 3, 3]],
        dtype=np.int32,
    )
    findings = validate_raster_definition(
        tile, prov, wrap_horizontal=False, max_bbox_ratio=_RATIO_RELAXED,
    )
    gaps = [f for f in findings if f.code == "raster.id_gap"]
    assert len(gaps) == 1
    assert gaps[0].severity == "error"
    assert gaps[0].affected_ids == (2,)
    assert gaps[0].repair_code == "province.compact_ids"


def test_surface_mixed_and_threshold():
    tile = np.ones((4, 4), dtype=np.uint8) * TILE_LAND
    tile[0:2, 0:2] = TILE_SEA
    prov = np.array(
        [[1, 1, 2, 2], [1, 1, 2, 2], [1, 1, 2, 2], [1, 1, 2, 2]],
        dtype=np.int32,
    )
    flagged = validate_raster_definition(
        tile, prov, wrap_horizontal=False, max_bbox_ratio=_RATIO_RELAXED,
        mixed_threshold=0.0,
    )
    mixed = [f for f in flagged if f.code == "raster.surface_mixed"]
    assert len(mixed) == 1
    assert mixed[0].severity == "warning"
    assert mixed[0].affected_ids == (1,)
    assert "minority" in mixed[0].evidence
    suppressed = validate_raster_definition(
        tile, prov, wrap_horizontal=False, max_bbox_ratio=_RATIO_RELAXED,
        mixed_threshold=0.6,
    )
    assert "raster.surface_mixed" not in _codes(suppressed)


def test_surface_unknown_when_undefined_dominates():
    tile = np.zeros((4, 4), dtype=np.uint8)
    tile[:, 2:] = TILE_LAND
    prov = np.array(
        [[1, 1, 2, 2], [1, 1, 2, 2], [1, 1, 2, 2], [1, 1, 2, 2]],
        dtype=np.int32,
    )
    findings = validate_raster_definition(
        tile, prov, wrap_horizontal=False, max_bbox_ratio=_RATIO_RELAXED,
    )
    unknown = [f for f in findings if f.code == "raster.surface_unknown"]
    assert len(unknown) == 1
    assert unknown[0].severity == "error"
    assert unknown[0].affected_ids == (1,)


def test_connectivity_flags_split_province():
    tile = np.ones((4, 4), dtype=np.uint8) * TILE_LAND
    prov = np.array(
        [[1, 2, 2, 2], [2, 2, 2, 2], [2, 2, 2, 2], [2, 2, 2, 1]],
        dtype=np.int32,
    )
    findings = validate_raster_definition(
        tile, prov, wrap_horizontal=False, max_bbox_ratio=_RATIO_RELAXED,
    )
    conn = [f for f in findings if f.code == "raster.connectivity"]
    assert len(conn) == 1
    assert conn[0].affected_ids == (1,)
    assert conn[0].severity == "error"


def test_x_crossing_and_wrap_seam():
    tile = np.ones((2, 2), dtype=np.uint8) * TILE_LAND
    prov = np.array([[1, 2], [3, 4]], dtype=np.int32)
    findings = validate_raster_definition(
        tile, prov, wrap_horizontal=False, max_bbox_ratio=_RATIO_RELAXED,
    )
    crosses = [f for f in findings if f.code == "raster.x_crossing"]
    assert len(crosses) == 1
    assert crosses[0].severity == "error"
    assert tuple(sorted(crosses[0].affected_ids)) == (1, 2, 3, 4)
    assert (0, 0) in crosses[0].coordinates

    seam_prov = np.array([[1, 1, 1, 2], [3, 1, 1, 4]], dtype=np.int32)
    seam_tile = np.ones((2, 4), dtype=np.uint8) * TILE_LAND
    with_wrap = validate_raster_definition(
        seam_tile, seam_prov, wrap_horizontal=True, max_bbox_ratio=_RATIO_RELAXED,
    )
    without_wrap = validate_raster_definition(
        seam_tile, seam_prov, wrap_horizontal=False, max_bbox_ratio=_RATIO_RELAXED,
    )
    assert "raster.x_crossing" in _codes(with_wrap)
    assert "raster.x_crossing" not in _codes(without_wrap)


def test_bbox_default_flags_but_ratio_relaxes():
    tile = np.ones((8, 8), dtype=np.uint8) * TILE_LAND
    prov = np.full((8, 8), 2, dtype=np.int32)
    prov[0, 0] = 1
    default = validate_raster_definition(tile, prov, wrap_horizontal=False)
    boxes = [f for f in default if f.code == "raster.bbox"]
    assert len(boxes) == 1
    assert boxes[0].affected_ids == (2,)
    relaxed = validate_raster_definition(
        tile, prov, wrap_horizontal=False, max_bbox_ratio=1.0,
    )
    assert "raster.bbox" not in _codes(relaxed)


def test_definition_normalization_variants():
    expected = {1, 2}
    assert _normalize_definition_ids(None) is None
    assert _normalize_definition_ids({1: "land", 2: "sea"}) == expected
    assert _normalize_definition_ids([1, 2]) == expected
    assert _normalize_definition_ids((2, 1)) == expected
    assert _normalize_definition_ids({1, 2}) == expected
    assert _normalize_definition_ids([{"id": 1}, {"province_id": 2}]) == expected
    assert _normalize_definition_ids(
        {(255, 0, 0): {"id": 1}, (0, 255, 0): {"id": 2}}
    ) == expected
    assert _normalize_definition_ids(np.array([1, 2])) == expected
    assert _normalize_definition_ids("1") == {1}

    tile, prov = _halves_4x4()
    variants = [
        {1: "land", 2: "sea"},
        [1, 2],
        [2, 1],
        [{"id": 1}, {"id": 2}],
        {(255, 0, 0): {"id": 1}, (0, 255, 0): {"id": 2}},
    ]
    results = [
        validate_raster_definition(
            tile, prov, definitions=v,
            wrap_horizontal=False, max_bbox_ratio=_RATIO_RELAXED,
        )
        for v in variants
    ]
    assert all(r == [] for r in results)


def test_definition_normalization_rejects_bad_input():
    with pytest.raises(ValueError):
        _normalize_definition_ids([{"foo": 1}])
    with pytest.raises(ValueError):
        _normalize_definition_ids(["not-an-id"])
    with pytest.raises(ValueError):
        _normalize_definition_ids({1: "x", (1, 2, 3): {"id": 2}})


def test_stable_codes_and_metadata():
    tile = np.ones((4, 4), dtype=np.uint8) * TILE_LAND
    prov = np.array(
        [[1, 1, 3, 3], [1, 1, 3, 3], [1, 1, 3, 3], [1, 1, 3, 3]],
        dtype=np.int32,
    )
    findings = validate_raster_definition(
        tile, prov, definitions={1: "land"},
        wrap_horizontal=False, max_bbox_ratio=_RATIO_RELAXED,
    )
    assert findings
    allowed = set(FINDING_SEVERITIES)
    seen = set()
    for finding in findings:
        assert finding.code in CODES
        assert finding.code.startswith("raster.")
        assert finding.severity in allowed
        assert finding.layer == "provinces"
        assert finding.message.strip()
        assert finding.evidence.strip()
        assert tuple(sorted(finding.affected_ids)) == tuple(finding.affected_ids)
        assert tuple(sorted(finding.coordinates)) == tuple(finding.coordinates)
        for x, y in finding.coordinates:
            assert 0 <= x < 4 and 0 <= y < 4
        seen.add(finding.code)
    assert "raster.definition_missing" in seen
    assert "raster.id_gap" in seen
    order = [CODES.index(code) for code in _codes(findings)]
    assert order == sorted(order)


def test_no_mutation_of_arrays_or_definitions():
    tile, prov = _halves_4x4()
    tile_snapshot = tile.copy()
    prov_snapshot = prov.copy()
    definitions = {1: "land", 2: "sea"}
    snapshot_defs = dict(definitions)
    validate_raster_definition(
        tile, prov, definitions=definitions,
        wrap_horizontal=False, max_bbox_ratio=_RATIO_RELAXED,
    )
    np.testing.assert_array_equal(tile, tile_snapshot)
    np.testing.assert_array_equal(prov, prov_snapshot)
    assert definitions == snapshot_defs


def test_deterministic_ordering():
    tile = np.ones((4, 4), dtype=np.uint8) * TILE_LAND
    prov = np.array(
        [[1, 1, 3, 3], [1, 1, 3, 3], [1, 1, 3, 3], [1, 1, 3, 3]],
        dtype=np.int32,
    )
    first = validate_raster_definition(
        tile, prov, definitions=[1, 9],
        wrap_horizontal=False, max_bbox_ratio=_RATIO_RELAXED,
    )
    second = validate_raster_definition(
        tile, prov, definitions=[9, 1],
        wrap_horizontal=False, max_bbox_ratio=_RATIO_RELAXED,
    )
    assert first == second
    again = validate_raster_definition(
        tile, prov, definitions=[1, 9],
        wrap_horizontal=False, max_bbox_ratio=_RATIO_RELAXED,
    )
    assert [f.to_dict() for f in first] == [f.to_dict() for f in again]
