"""M5.3 pure placement transform contract coverage."""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from domain.managers.map_placement import BuildingPlacement
from domain.managers.map_placement import PortPlacement
from domain.managers.map_placement import ProvincePositionSlot
from services import placement_transforms
from services.placement_transforms import PlacementTransform
from services.placement_transforms import read_placement_transform
from services.placement_transforms import reset_placement_transform
from services.placement_transforms import update_placement_transform

pytestmark = pytest.mark.unit


def _mapping_record():
    """Mapping record with fractional coordinates."""
    return {"x": 12.5, "y": -3.75, "rotation": 45.25, "height": 1.5}


def _object_record():
    """Duck-typed object record with fractional coordinates."""
    return SimpleNamespace(x=12.5, y=-3.75, rotation=45.25, height=1.5)


def test_public_exports():
    """Public dataclass and helpers are exported through all."""
    assert set(placement_transforms.__all__) == {
        "PlacementTransform",
        "read_placement_transform",
        "reset_placement_transform",
        "update_placement_transform",
    }


def test_read_mapping_preserves_fractional_values():
    """Mapping records round-trip with fractional values as floats."""
    result = read_placement_transform(_mapping_record())
    assert result == PlacementTransform(x=12.5, y=-3.75, rotation=45.25, height=1.5)
    assert isinstance(result.x, float)
    assert isinstance(result.y, float)
    assert isinstance(result.rotation, float)
    assert isinstance(result.height, float)


def test_read_object_record_preserves_fractional_values():
    """Object records round-trip with fractional values as floats."""
    result = read_placement_transform(_object_record())
    assert result == PlacementTransform(x=12.5, y=-3.75, rotation=45.25, height=1.5)
    assert isinstance(result.x, float)
    assert isinstance(result.rotation, float)


def test_read_manager_records():
    """Real manager records expose a compatible transform shape."""
    slot_record = ProvincePositionSlot(
        province_id=1, slot=0, x=10.5, y=20.25, rotation=30.5, height=2.75
    )
    building_record = BuildingPlacement(
        id=7, province_id=1, building_type="arms_factory",
        x=1.25, y=2.5, rotation=90.5, height=0.5,
    )
    port_record = PortPlacement(
        province_id=3, x=-4.5, y=8.25, rotation=15.5, height=3.5
    )
    assert read_placement_transform(slot_record) == PlacementTransform(
        x=10.5, y=20.25, rotation=30.5, height=2.75
    )
    assert read_placement_transform(building_record) == PlacementTransform(
        x=1.25, y=2.5, rotation=90.5, height=0.5
    )
    assert read_placement_transform(port_record) == PlacementTransform(
        x=-4.5, y=8.25, rotation=15.5, height=3.5
    )
    assert read_placement_transform(slot_record.to_dict()) == PlacementTransform(
        x=10.5, y=20.25, rotation=30.5, height=2.75
    )


def test_read_accepts_integer_coordinates_as_floats():
    """Integer coordinates are accepted and stored as floats."""
    result = read_placement_transform({"x": 4, "y": 6, "rotation": 0, "height": 2})
    assert result == PlacementTransform(x=4.0, y=6.0, rotation=0.0, height=2.0)
    assert isinstance(result.x, float)


def test_update_partial_fields_keep_remainder():
    """Omitted update fields remain unchanged."""
    base = PlacementTransform(x=1.5, y=2.5, rotation=3.5, height=4.5)
    only_x = update_placement_transform(base, x=9.25)
    assert only_x == PlacementTransform(x=9.25, y=2.5, rotation=3.5, height=4.5)
    only_rotation = update_placement_transform(base, rotation=180.5)
    assert only_rotation == PlacementTransform(x=1.5, y=2.5, rotation=180.5, height=4.5)
    pair = update_placement_transform(base, y=-7.75, height=0.25)
    assert pair == PlacementTransform(x=1.5, y=-7.75, rotation=3.5, height=0.25)


def test_update_with_no_overrides_returns_equal_copy():
    """An empty update returns an equal but distinct transform."""
    base = PlacementTransform(x=1.5, y=2.5, rotation=3.5, height=4.5)
    result = update_placement_transform(base)
    assert result == base
    assert result is not base


def test_update_accepts_mapping_and_object_sources():
    """Update accepts duck-typed mapping and object transform sources."""
    from_mapping = update_placement_transform(_mapping_record(), x=0.5)
    assert from_mapping == PlacementTransform(x=0.5, y=-3.75, rotation=45.25, height=1.5)
    from_object = update_placement_transform(_object_record(), height=9.75)
    assert from_object == PlacementTransform(x=12.5, y=-3.75, rotation=45.25, height=9.75)


def test_update_preserves_fractional_values():
    """Updated fractional values are preserved exactly."""
    base = PlacementTransform(x=0.0, y=0.0, rotation=0.0, height=0.0)
    result = update_placement_transform(base, x=0.1, y=0.2, rotation=0.3, height=0.4)
    assert result.x == pytest.approx(0.1)
    assert result.y == pytest.approx(0.2)
    assert result.rotation == pytest.approx(0.3)
    assert result.height == pytest.approx(0.4)


def test_reset_is_neutral_and_preserves_position():
    """Neutral reset keeps x and y while zeroing rotation and height."""
    base = PlacementTransform(x=12.5, y=-3.75, rotation=45.25, height=1.5)
    result = reset_placement_transform(base)
    assert result == PlacementTransform(x=12.5, y=-3.75, rotation=0.0, height=0.0)


def test_reset_accepts_mapping_and_object_sources():
    """Neutral reset works from mapping and object records."""
    from_mapping = reset_placement_transform(_mapping_record())
    assert from_mapping == PlacementTransform(x=12.5, y=-3.75, rotation=0.0, height=0.0)
    from_object = reset_placement_transform(_object_record())
    assert from_object == PlacementTransform(x=12.5, y=-3.75, rotation=0.0, height=0.0)


def test_reset_already_neutral_is_stable():
    """Resetting a neutral transform returns an equal value."""
    base = PlacementTransform(x=2.0, y=3.0, rotation=0.0, height=0.0)
    assert reset_placement_transform(base) == base


def test_read_does_not_mutate_mapping():
    """Reading leaves the source mapping unchanged."""
    source = _mapping_record()
    snapshot = dict(source)
    read_placement_transform(source)
    assert source == snapshot


def test_update_does_not_mutate_inputs():
    """Updates leave mapping, object, and transform inputs unchanged."""
    mapping_source = _mapping_record()
    mapping_snapshot = dict(mapping_source)
    object_source = _object_record()
    base = PlacementTransform(x=1.5, y=2.5, rotation=3.5, height=4.5)
    update_placement_transform(mapping_source, x=99.5)
    update_placement_transform(object_source, y=99.5)
    update_placement_transform(base, rotation=99.5)
    reset_placement_transform(base)
    assert mapping_source == mapping_snapshot
    assert object_source == SimpleNamespace(x=12.5, y=-3.75, rotation=45.25, height=1.5)
    assert base == PlacementTransform(x=1.5, y=2.5, rotation=3.5, height=4.5)


@pytest.mark.parametrize("field_name", ["x", "y", "rotation", "height"])
@pytest.mark.parametrize("bad_value", [True, False])
def test_bool_coordinates_rejected(field_name, bad_value):
    """Bool values are rejected for every coordinate."""
    source = _mapping_record()
    source[field_name] = bad_value
    with pytest.raises(ValueError):
        read_placement_transform(source)
    base = PlacementTransform(x=1.5, y=2.5, rotation=3.5, height=4.5)
    with pytest.raises(ValueError):
        update_placement_transform(base, **{field_name: bad_value})


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_coordinates_rejected(bad_value):
    """NaN and infinite values are rejected on read and update."""
    with pytest.raises(ValueError):
        read_placement_transform({"x": bad_value, "y": 0.0, "rotation": 0.0, "height": 0.0})
    with pytest.raises(ValueError):
        read_placement_transform(SimpleNamespace(x=0.0, y=bad_value, rotation=0.0, height=0.0))
    base = PlacementTransform(x=1.0, y=2.0, rotation=3.0, height=4.0)
    with pytest.raises(ValueError):
        update_placement_transform(base, rotation=bad_value)
    with pytest.raises(ValueError):
        PlacementTransform(x=bad_value, y=0.0, rotation=0.0, height=0.0)


@pytest.mark.parametrize("bad_value", ["12.5", None, [12.5], {"nested": 1.0}])
def test_non_numeric_coordinates_rejected(bad_value):
    """Strings, None, and containers are rejected for coordinates."""
    with pytest.raises(ValueError):
        read_placement_transform({"x": bad_value, "y": 0.0, "rotation": 0.0, "height": 0.0})
    base = PlacementTransform(x=1.0, y=2.0, rotation=3.0, height=4.0)
    with pytest.raises(ValueError):
        update_placement_transform(base, height=bad_value)


def test_missing_fields_rejected():
    """Records missing any coordinate raise ValueError."""
    with pytest.raises(ValueError):
        read_placement_transform({"x": 1.0, "y": 2.0, "rotation": 0.0})
    with pytest.raises(ValueError):
        read_placement_transform({"y": 2.0, "rotation": 0.0, "height": 0.0})
    with pytest.raises(ValueError):
        read_placement_transform(SimpleNamespace(x=1.0, y=2.0))
    with pytest.raises(ValueError):
        read_placement_transform(SimpleNamespace())
    with pytest.raises(ValueError):
        read_placement_transform(None)


def test_direct_construction_validates_coordinates():
    """Direct dataclass construction applies the same validation."""
    with pytest.raises(ValueError):
        PlacementTransform(x=True, y=0.0, rotation=0.0, height=0.0)
    with pytest.raises(ValueError):
        PlacementTransform(x=0.0, y=float("nan"), rotation=0.0, height=0.0)
    with pytest.raises(ValueError):
        PlacementTransform(x=0.0, y=0.0, rotation="bad", height=0.0)


def test_results_are_frozen():
    """Read, update, and reset results reject attribute assignment."""
    base = PlacementTransform(x=1.5, y=2.5, rotation=3.5, height=4.5)
    for result in (
        read_placement_transform(_mapping_record()),
        update_placement_transform(base, x=2.5),
        reset_placement_transform(base),
    ):
        assert isinstance(result, PlacementTransform)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.x = 999.0
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.rotation = 999.0
