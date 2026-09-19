"""PlacementController -- Headless placement proposal boundary (M5.2/M5.3).

Thin controller layer over the already-reviewed placement proposal
services plus undoable placement transform edits. It reads rasters from
``Project.map_data``, mutates only ``Project.map_placement_mgr``, and
records undoable state through the existing ``ManagerSnapshotCommand``
plus ``CommandHistory`` conventions. No PyQt, filesystem, dialog,
export, or view code lives here.
"""
from __future__ import annotations

from collections.abc import Iterable as CollectionsIterable
from collections.abc import Mapping as CollectionsMapping
from typing import TYPE_CHECKING
from typing import Any

from commands.map.manager_snapshot import ManagerSnapshotCommand
from controllers.base import BaseController
from domain.managers.map_placement import POSITION_SLOT_COUNT
from services import placement_proposals as placement_service
from services.placement_proposals import PlacementAcceptanceReport
from services.placement_proposals import PortProposalWorkflowResult
from services.placement_proposals import SlotProposalWorkflowResult
from services.placement_transforms import read_placement_transform
from services.placement_transforms import reset_placement_transform
from services.placement_transforms import update_placement_transform

if TYPE_CHECKING:
    from commands.history import CommandHistory
    from model.project import Project

__all__ = ["PlacementController"]

_TRANSFORM_SNAPSHOT_FIELDS: dict[str, str] = {
    "slot": "_slots",
    "port": "_ports",
    "building": "_buildings",
    "weather": "_weather",
}


class PlacementController(BaseController):
    """Headless boundary that invokes placement proposal services."""

    PLACEMENT_CHANGED_EVENT = "placement_changed"

    def __init__(self, project: "Project", command_history: "CommandHistory") -> None:
        """Bind the controller to a project and its command history."""
        super().__init__(project, command_history)

    def propose_slots(
        self,
        province_ids: CollectionsIterable[int] | None = None,
        *,
        seed: int = 0,
        slot_count: int = int(POSITION_SLOT_COUNT),
        min_separation: float = 2.0,
        border_weight: float = 1.0,
        coast_weight: float = 1.0,
        height_weight: float = 0.5,
        slope_weight: float = 1.0,
        replace_generated: bool = False,
    ) -> SlotProposalWorkflowResult:
        """Generate slot proposals and store them as unreviewed records.

        Delegates to
        ``services.placement_proposals.propose_slot_placements`` with
        ``map_data.province_map``, ``tile_map``, and ``height_map`` plus
        the explicit options. Stored records stay generated and
        unreviewed; this method never accepts anything.

        Returns the service workflow result unchanged.
        """
        map_data = self.project.map_data
        manager = self.project.map_placement_mgr
        snap_fields = [name for name in ("_slots",) if hasattr(manager, name)]
        cmd = ManagerSnapshotCommand("Propose slot placements", manager, snap_fields)
        result = placement_service.propose_slot_placements(
            map_data.province_map,
            map_data.tile_map,
            manager,
            height_map=map_data.height_map,
            province_ids=province_ids,
            seed=seed,
            slot_count=slot_count,
            min_separation=min_separation,
            border_weight=border_weight,
            coast_weight=coast_weight,
            height_weight=height_weight,
            slope_weight=slope_weight,
            replace_generated=replace_generated,
        )
        store_report = result.store_report
        changed = bool(store_report.stored_keys or store_report.replaced_keys)
        if changed:
            cmd.capture_after()
            self.history.execute(cmd)
            self.project.mark_dirty()
            self.event_bus.emit(self.PLACEMENT_CHANGED_EVENT, action="proposed_slots")
        return result

    def propose_ports(
        self,
        sea_mapping: CollectionsMapping,
        province_ids: CollectionsIterable[int] | None = None,
        *,
        seed: int = 0,
        border_weight: float = 1.0,
        coast_weight: float = 1.0,
        height_weight: float = 0.5,
        slope_weight: float = 1.0,
        replace_generated: bool = False,
    ) -> PortProposalWorkflowResult:
        """Generate port proposals for an explicit land-to-sea mapping.

        The caller must supply ``sea_mapping``; it is forwarded verbatim
        to ``services.placement_proposals.propose_port_placements`` and
        never inferred or guessed. Stored records stay generated and
        unreviewed; this method never accepts anything.

        Returns the service workflow result unchanged.
        """
        if sea_mapping is None:
            raise TypeError(
                "sea_mapping is required, pass an explicit mapping of land "
                "province to sea province; guessing a sea is not allowed"
            )
        map_data = self.project.map_data
        manager = self.project.map_placement_mgr
        snap_fields = [name for name in ("_ports",) if hasattr(manager, name)]
        cmd = ManagerSnapshotCommand("Propose port placements", manager, snap_fields)
        result = placement_service.propose_port_placements(
            map_data.province_map,
            map_data.tile_map,
            manager,
            sea_mapping,
            height_map=map_data.height_map,
            province_ids=province_ids,
            seed=seed,
            border_weight=border_weight,
            coast_weight=coast_weight,
            height_weight=height_weight,
            slope_weight=slope_weight,
            replace_generated=replace_generated,
        )
        store_report = result.store_report
        changed = bool(store_report.stored_ids or store_report.replaced_ids)
        if changed:
            cmd.capture_after()
            self.history.execute(cmd)
            self.project.mark_dirty()
            self.event_bus.emit(self.PLACEMENT_CHANGED_EVENT, action="proposed_ports")
        return result

    def accept_selected(
        self,
        slot_keys: CollectionsIterable[tuple[int, int]] = (),
        port_ids: CollectionsIterable[int] = (),
        review_status: str = "reviewed",
    ) -> PlacementAcceptanceReport:
        """Accept only the explicitly selected slot and port proposals.

        Delegates to
        ``services.placement_proposals.accept_selected_placements``
        with exactly the given keys and ids. An empty selection accepts
        nothing; there is no implicit bulk acceptance.

        Returns the service acceptance report unchanged.
        """
        manager = self.project.map_placement_mgr
        snap_fields = [
            name for name in ("_slots", "_ports") if hasattr(manager, name)
        ]
        cmd = ManagerSnapshotCommand("Accept selected placements", manager, snap_fields)
        report = placement_service.accept_selected_placements(
            manager,
            slot_keys=slot_keys,
            port_ids=port_ids,
            review_status=review_status,
        )
        changed = bool(report.accepted_slot_keys or report.accepted_port_ids)
        if changed:
            cmd.capture_after()
            self.history.execute(cmd)
            self.project.mark_dirty()
            self.event_bus.emit(self.PLACEMENT_CHANGED_EVENT, action="accepted")
        return report

    def update_transform(
        self,
        kind: str,
        key: Any,
        *,
        x: Any = None,
        y: Any = None,
        rotation: Any = None,
        height: Any = None,
    ) -> bool:
        """Update one placement transform without touching other fields.

        Supported kinds are explicit and deterministic: ``slot`` uses a
        ``(province_id, slot)`` key, ``port`` uses a province id,
        ``building`` uses a building record id, and ``weather`` uses a
        weather record id. Unknown kinds raise ValueError and missing
        records raise KeyError without mutation.

        Only the supplied transform fields change; ``None`` means keep
        the current value. Fractional values survive as floats. Every
        non-transform field (meaning, provenance, review status, sea
        province, building type and state, weather size and kind) is
        preserved through the existing manager APIs. Slots and ports use
        ``set_province_slot`` and ``set_port``; buildings and weather
        use ``update_building`` and ``update_weather``.

        A real change snapshots only the affected manager collection,
        executes history, marks dirty, and emits ``placement_changed``
        with action ``updated_transform`` plus kind and key. A no-op
        returns False and leaves manager, dirty flag, history, and
        events unchanged.
        """
        field_name = _TRANSFORM_SNAPSHOT_FIELDS.get(kind)
        if field_name is None:
            raise ValueError(
                f"unknown placement kind {kind!r}; "
                f"expected one of {sorted(_TRANSFORM_SNAPSHOT_FIELDS)}"
            )
        record, normalized_key = self._lookup_transform_record(kind, key)
        overrides: dict[str, Any] = {}
        if x is not None:
            overrides["x"] = x
        if y is not None:
            overrides["y"] = y
        if rotation is not None:
            overrides["rotation"] = rotation
        if height is not None:
            overrides["height"] = height
        current = read_placement_transform(record)
        updated = update_placement_transform(record, **overrides)
        if updated == current:
            return False
        manager = self.project.map_placement_mgr
        cmd = ManagerSnapshotCommand(
            f"Update {kind} transform", manager, [field_name]
        )
        self._store_transform(kind, normalized_key, record, updated)
        cmd.capture_after()
        self.history.execute(cmd)
        self.project.mark_dirty()
        self.event_bus.emit(
            self.PLACEMENT_CHANGED_EVENT,
            action="updated_transform",
            kind=kind,
            key=normalized_key,
        )
        return True

    def reset_transform(self, kind: str, key: Any) -> bool:
        """Reset one placement transform to neutral orientation/height.

        Neutral reset preserves x/y and sets rotation/height to 0.0 as
        defined by the pure contract. Kinds, keys, preservation,
        snapshot scope, dirty, event, no-op, and error semantics match
        ``update_transform``; the emitted action is ``reset_transform``.
        """
        field_name = _TRANSFORM_SNAPSHOT_FIELDS.get(kind)
        if field_name is None:
            raise ValueError(
                f"unknown placement kind {kind!r}; "
                f"expected one of {sorted(_TRANSFORM_SNAPSHOT_FIELDS)}"
            )
        record, normalized_key = self._lookup_transform_record(kind, key)
        current = read_placement_transform(record)
        neutral = reset_placement_transform(record)
        if neutral == current:
            return False
        manager = self.project.map_placement_mgr
        cmd = ManagerSnapshotCommand(
            f"Reset {kind} transform", manager, [field_name]
        )
        self._store_transform(kind, normalized_key, record, neutral)
        cmd.capture_after()
        self.history.execute(cmd)
        self.project.mark_dirty()
        self.event_bus.emit(
            self.PLACEMENT_CHANGED_EVENT,
            action="reset_transform",
            kind=kind,
            key=normalized_key,
        )
        return True

    def _lookup_transform_record(self, kind: str, key: Any) -> tuple[Any, Any]:
        """Return the live record and normalized key for a transform kind."""
        manager = self.project.map_placement_mgr
        if kind == "slot":
            if not isinstance(key, (tuple, list)) or len(key) != 2:
                raise ValueError(
                    f"slot key must be (province_id, slot), got {key!r}"
                )
            province_id, slot = key[0], key[1]
            record = manager.get_province_slot(province_id, slot)
            if record is None:
                raise KeyError(f"unknown province slot: {(province_id, slot)!r}")
            return record, (province_id, slot)
        if kind == "port":
            record = manager.get_port(key)
            if record is None:
                raise KeyError(f"unknown port province: {key!r}")
            return record, key
        if kind == "building":
            record = manager.get_building(key)
            if record is None:
                raise KeyError(f"unknown building placement id: {key!r}")
            return record, key
        if kind == "weather":
            record = manager.get_weather(key)
            if record is None:
                raise KeyError(f"unknown weather position id: {key!r}")
            return record, key
        raise ValueError(f"unknown placement kind {kind!r}")

    def _store_transform(
        self, kind: str, key: Any, record: Any, transform: Any
    ) -> None:
        """Persist a computed transform through manager APIs only."""
        manager = self.project.map_placement_mgr
        if kind == "slot":
            province_id, slot = key
            manager.set_province_slot(
                province_id,
                slot,
                x=transform.x,
                y=transform.y,
                rotation=transform.rotation,
                height=transform.height,
                meaning=record.meaning,
                provenance=record.provenance,
                review_status=record.review_status,
            )
            return
        if kind == "port":
            manager.set_port(
                key,
                x=transform.x,
                y=transform.y,
                rotation=transform.rotation,
                height=transform.height,
                sea_province=record.sea_province,
                provenance=record.provenance,
                review_status=record.review_status,
            )
            return
        if kind == "building":
            manager.update_building(
                key,
                x=transform.x,
                y=transform.y,
                rotation=transform.rotation,
                height=transform.height,
            )
            return
        if kind == "weather":
            manager.update_weather(
                key,
                x=transform.x,
                y=transform.y,
                rotation=transform.rotation,
                height=transform.height,
            )
            return
        raise ValueError(f"unknown placement kind {kind!r}")
