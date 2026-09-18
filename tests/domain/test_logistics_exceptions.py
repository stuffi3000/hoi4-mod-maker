"""Focused M4.5 logistics-exception tests (synthetic, no game install)."""
from __future__ import annotations

import pytest

from domain.logistics_exceptions import (
    REASONS,
    LogisticsException,
    LogisticsExceptionManager,
    component_identity_for,
    component_key,
    evaluate_exception,
    evaluate_exceptions,
    exception_kind,
    is_component_key,
    is_supply_key,
    supply_key,
    supply_province_for,
)
from domain.logistics_graph import build_logistics_graph
from domain.managers.railway import RailwayManager
from domain.managers.supply_node import SupplyNodeManager

pytestmark = pytest.mark.unit


def _alpha_graph():
    """Two railway components plus one supply-only province."""
    rail = RailwayManager()
    rail.add(2, [1, 2, 3])
    rail.add(1, [10, 11])
    supply = SupplyNodeManager()
    supply.add(2)
    supply.add(11)
    supply.add(99)
    return build_logistics_graph(rail, supply)


def _beta_graph():
    """Alpha topology extended with province 4, shifting component identity."""
    rail = RailwayManager()
    rail.add(2, [1, 2, 3, 4])
    rail.add(1, [10, 11])
    supply = SupplyNodeManager()
    supply.add(2)
    supply.add(11)
    supply.add(99)
    return build_logistics_graph(rail, supply)


def _gamma_graph():
    """Alpha rails without the supply-only province."""
    rail = RailwayManager()
    rail.add(2, [1, 2, 3])
    rail.add(1, [10, 11])
    supply = SupplyNodeManager()
    supply.add(2)
    supply.add(11)
    return build_logistics_graph(rail, supply)


def _containing_component(graph, province_id: int) -> str:
    for component in graph.components:
        if province_id in component.provinces:
            return component.component_id
    raise AssertionError("province %r missing from graph" % (province_id,))


def test_all_four_reason_categories_accepted() -> None:
    """Every documented reason category files both record shapes."""
    assert REASONS == ("island", "overseas_convoy", "intentional_isolation", "future_content")
    graph = _alpha_graph()
    host = _containing_component(graph, 2)
    lone = _containing_component(graph, 99)
    for reason in REASONS:
        component_record = LogisticsException(
            key=component_key(lone), reason=reason, note="note-%s" % (reason,)
        )
        assert component_record.reason == reason
        assert component_record.component_id == lone
        assert component_record.is_component is True
        supply_record = LogisticsException(
            key=supply_key(2), reason=reason, note="node", component_id=host
        )
        assert supply_record.reason == reason
        assert supply_record.supply_province == 2
        assert supply_record.component_id == host
        assert supply_record.is_supply is True


def test_component_and_supply_key_helpers() -> None:
    """Key builders, kind checks, and embedded-identity parsing agree."""
    graph = _alpha_graph()
    host = _containing_component(graph, 2)
    component_id = component_key(host)
    supply_id = supply_key(2)
    assert exception_kind(component_id) == "component"
    assert exception_kind(supply_id) == "supply"
    assert is_component_key(component_id) is True
    assert is_supply_key(component_id) is False
    assert is_supply_key(supply_id) is True
    assert is_component_key(supply_id) is False
    assert component_identity_for(component_id) == host
    assert supply_province_for(supply_id) == 2
    with pytest.raises(ValueError):
        component_identity_for(supply_id)
    with pytest.raises(ValueError):
        supply_province_for(component_id)


def test_manager_crud_is_deterministic() -> None:
    """Add, read, replace, and delete behave deterministically."""
    graph = _alpha_graph()
    host = _containing_component(graph, 2)
    lone = _containing_component(graph, 99)
    manager = LogisticsExceptionManager()
    assert len(manager) == 0
    assert manager.get_all() == []
    manager.add_supply(11, _containing_component(graph, 11), "island", note="second")
    manager.add_component(lone, "future_content", note="first")
    assert manager.keys() == tuple(sorted(manager.keys()))
    assert [record.key for record in manager.get_all()] == list(manager.keys())
    assert manager.get(component_key(lone)).note == "first"
    assert manager.get(supply_key(99)) is None
    assert component_key(lone) in manager
    assert supply_key(99) not in manager
    with pytest.raises(ValueError):
        manager.add_component(lone, "island")
    previous = manager.upsert(
        LogisticsException(key=component_key(lone), reason="island", note="revised")
    )
    assert previous.note == "first"
    assert manager.get(component_key(lone)).note == "revised"
    assert manager.get(component_key(lone)).reason == "island"
    assert manager.remove(supply_key(99)) is False
    assert manager.remove(supply_key(11)) is True
    assert len(manager) == 1
    assert host is not None
    manager.clear()
    assert manager.get_all() == []
    assert len(manager) == 0


def test_deterministic_round_trip_preserves_notes_and_identity() -> None:
    """Serialization order, notes, and graph identity survive round trips."""
    graph = _alpha_graph()
    host_two = _containing_component(graph, 2)
    host_eleven = _containing_component(graph, 11)
    lone = _containing_component(graph, 99)
    entries = [
        LogisticsException(key=component_key(lone), reason="island", note="far away"),
        LogisticsException(
            key=supply_key(2), reason="overseas_convoy", note="convoy fed",
            component_id=host_two,
        ),
        LogisticsException(
            key=supply_key(11), reason="intentional_isolation", note="pocket",
            component_id=host_eleven,
        ),
        LogisticsException(
            key=component_key(host_two), reason="future_content", note="reconnect later"
        ),
    ]
    first = LogisticsExceptionManager(entries)
    second = LogisticsExceptionManager(list(reversed(entries)))
    assert first.to_dict() == second.to_dict()
    assert [record.key for record in first.get_all()] == sorted(
        record.key for record in entries
    )
    payload = first.to_dict()
    assert first.to_dict() == payload
    restored = LogisticsExceptionManager.from_dict(payload)
    assert restored.to_dict() == payload
    assert LogisticsExceptionManager.from_dict(restored.to_dict()).to_dict() == payload
    by_key = {record.key: record for record in restored.get_all()}
    assert by_key[component_key(lone)].note == "far away"
    assert by_key[component_key(lone)].component_id == lone
    assert by_key[supply_key(2)].note == "convoy fed"
    assert by_key[supply_key(2)].component_id == host_two
    assert by_key[supply_key(11)].component_id == host_eleven


def test_current_records_evaluate_valid() -> None:
    """Records filed against the current graph evaluate as valid."""
    graph = _alpha_graph()
    host = _containing_component(graph, 2)
    lone = _containing_component(graph, 99)
    manager = LogisticsExceptionManager()
    manager.add_component(host, "intentional_isolation", note="pocket")
    manager.add_component(lone, "island", note="offshore")
    manager.add_supply(11, _containing_component(graph, 11), "overseas_convoy")
    report = manager.evaluate(graph)
    assert report.is_clean is True
    assert report.stale == ()
    assert report.stale_keys == ()
    assert report.valid_keys == manager.keys()
    assert len(report) == 3
    assert all(status.detail for status in report.statuses)
    assert [status.exception.key for status in report.statuses] == list(manager.keys())


def test_stale_component_exception_reported_and_pruned() -> None:
    """A vanished component identity is reported and removable in order."""
    alpha = _alpha_graph()
    beta = _beta_graph()
    host = _containing_component(alpha, 2)
    assert host not in {component.component_id for component in beta.components}
    manager = LogisticsExceptionManager()
    manager.add_component(host, "intentional_isolation", note="pocket")
    assert manager.evaluate(alpha).is_clean is True
    report = manager.evaluate(beta)
    assert report.is_clean is False
    assert report.valid == ()
    assert report.stale_keys == (component_key(host),)
    assert report.statuses[0].detail == "unknown-component"
    removed = manager.prune_stale(beta)
    assert [record.key for record in removed] == [component_key(host)]
    assert removed[0].component_id == host
    assert removed[0].note == "pocket"
    assert manager.get_all() == []


def test_changed_component_supply_exception_invalidated() -> None:
    """A supply node absorbed into another component invalidates its waiver."""
    alpha = _alpha_graph()
    beta = _beta_graph()
    host = _containing_component(alpha, 2)
    assert _containing_component(beta, 2) != host
    manager = LogisticsExceptionManager()
    manager.add_supply(2, host, "overseas_convoy", note="convoy route")
    assert manager.evaluate(alpha).is_clean is True
    report = manager.evaluate(beta)
    assert report.is_clean is False
    assert report.stale_keys == (supply_key(2),)
    assert report.statuses[0].detail == "supply-moved-component"
    assert manager.remove_stale(beta)[0].component_id == host
    assert manager.get_all() == []


def test_removed_supply_exception_invalidated() -> None:
    """A deleted supply node invalidates its waiver while others survive."""
    alpha = _alpha_graph()
    gamma = _gamma_graph()
    lone = _containing_component(alpha, 99)
    assert 99 in alpha.supply_provinces
    assert 99 not in gamma.supply_provinces
    manager = LogisticsExceptionManager()
    manager.add_supply(99, lone, "island", note="offshore node")
    manager.add_supply(2, _containing_component(alpha, 2), "future_content")
    assert manager.evaluate(alpha).is_clean is True
    report = manager.evaluate(gamma)
    assert report.is_clean is False
    assert report.stale_keys == (supply_key(99),)
    assert report.valid_keys == (supply_key(2),)
    assert report.statuses[0].exception.key == supply_key(2)
    removed = manager.prune_stale(gamma)
    assert [record.key for record in removed] == [supply_key(99)]
    assert manager.keys() == (supply_key(2),)


def test_evaluation_leaves_manager_and_graph_unchanged() -> None:
    """Evaluation and clean pruning never mutate manager or graph inputs."""
    graph = _alpha_graph()
    manager = LogisticsExceptionManager()
    manager.add_component(_containing_component(graph, 2), "island", note="kept")
    manager.add_supply(99, _containing_component(graph, 99), "future_content")
    snapshot = manager.to_dict()
    report = manager.evaluate(graph)
    assert report.is_clean is True
    assert manager.prune_stale(graph) == ()
    assert manager.to_dict() == snapshot
    assert manager.keys() == tuple(sorted(snapshot["exceptions"][index]["key"] for index in range(2)))
    assert graph == _alpha_graph()
    assert graph.supply_provinces == _alpha_graph().supply_provinces
    status = evaluate_exception(manager.get(supply_key(99)), graph)
    assert status.valid is True
    assert manager.to_dict() == snapshot


def test_standalone_evaluate_helpers_cover_mixed_records() -> None:
    """Module-level evaluation matches manager evaluation ordering."""
    alpha = _alpha_graph()
    beta = _beta_graph()
    host = _containing_component(alpha, 2)
    lone = _containing_component(alpha, 99)
    records = [
        LogisticsException(key=supply_key(99), reason="island", note="n", component_id=lone),
        LogisticsException(key=component_key(host), reason="island", note="c"),
    ]
    direct = evaluate_exceptions(list(reversed(records)), beta)
    assert [status.exception.key for status in direct.statuses] == sorted(
        record.key for record in records
    )
    assert direct.stale_keys == (component_key(host),)
    assert direct.valid_keys == (supply_key(99),)
    single = evaluate_exception(records[0], beta)
    assert single.valid is True
    assert single.exception == records[0]
    as_mapping = evaluate_exception(records[0].to_dict(), beta)
    assert as_mapping.valid is True
    assert as_mapping.exception == records[0]


@pytest.mark.parametrize(
    "reason",
    ["archipelago", "Island", "island ", " overseas_convoy", "", "overseas", None, 42, "future-content"],
)
def test_invalid_reasons_rejected(reason) -> None:
    """Unknown reason categories are rejected at every entry point."""
    graph = _alpha_graph()
    host = _containing_component(graph, 2)
    with pytest.raises(ValueError):
        LogisticsException(key=component_key(host), reason=reason)
    with pytest.raises(ValueError):
        LogisticsException(key=supply_key(2), reason=reason, component_id=host)
    with pytest.raises(ValueError):
        LogisticsExceptionManager().add_component(host, reason)
    with pytest.raises(ValueError):
        LogisticsExceptionManager().add_supply(2, host, reason)
    with pytest.raises(ValueError):
        LogisticsException.from_dict(
            {"key": component_key(host), "reason": reason, "note": "", "component_id": host}
        )


@pytest.mark.parametrize(
    "key",
    [
        "component:xyz",
        "component:ABCDEF123456",
        "component:",
        "component:1234567890123",
        "supply:0",
        "supply:-4",
        "supply:01",
        "supply:abc",
        "supply:",
        "railway:123",
        "",
        None,
        123,
    ],
)
def test_invalid_keys_rejected(key) -> None:
    """Malformed component and supply keys are rejected, never normalized."""
    with pytest.raises(ValueError):
        LogisticsException(key=key, reason="island", component_id="0123456789ab")
    with pytest.raises(ValueError):
        exception_kind(key)
    assert is_component_key(key) is False
    assert is_supply_key(key) is False
    assert (key in LogisticsExceptionManager()) is False


def test_mismatched_identity_and_store_shape_rejected() -> None:
    """Identity mismatches, missing identities, and bad payloads fail loudly."""
    graph = _alpha_graph()
    host = _containing_component(graph, 2)
    lone = _containing_component(graph, 99)
    with pytest.raises(ValueError):
        LogisticsException(
            key=component_key(host), reason="island", component_id=lone
        )
    with pytest.raises(ValueError):
        LogisticsException(key=supply_key(2), reason="island")
    with pytest.raises(ValueError):
        LogisticsException(
            key=supply_key(2), reason="island", component_id="not-an-id"
        )
    with pytest.raises(ValueError):
        LogisticsException(
            key=component_key(host), reason="island", note=None
        )
    with pytest.raises(ValueError):
        LogisticsException.from_dict(
            {
                "key": component_key(host),
                "reason": "island",
                "note": "",
                "component_id": host,
                "extra": "nope",
            }
        )
    with pytest.raises(ValueError):
        LogisticsException.from_dict({"key": component_key(host)})
    with pytest.raises(ValueError):
        LogisticsExceptionManager.from_dict({"exceptions": "nope"})
    with pytest.raises(ValueError):
        LogisticsExceptionManager.from_dict({"other": []})
    first = LogisticsExceptionManager()
    first.add_component(host, "island")
    with pytest.raises(ValueError):
        first.add_component(host, "island")
    with pytest.raises(ValueError):
        LogisticsExceptionManager.from_dict(
            {
                "exceptions": [
                    LogisticsException(
                        key=component_key(host), reason="island"
                    ).to_dict(),
                    LogisticsException(
                        key=component_key(host), reason="island"
                    ).to_dict(),
                ]
            }
        )