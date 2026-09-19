"""PlacementController -- Headless placement proposal boundary (M5.2).

Thin controller layer over the already-reviewed placement proposal
services. It reads rasters from ``Project.map_data``, mutates only
``Project.map_placement_mgr``, and records undoable state through the
existing ``ManagerSnapshotCommand`` plus ``CommandHistory`` conventions.
No PyQt, filesystem, dialog, export, or view code lives here.
"""
from __future__ import annotations

from collections.abc import Iterable as CollectionsIterable
from collections.abc import Mapping as CollectionsMapping
from typing import TYPE_CHECKING

from commands.map.manager_snapshot import ManagerSnapshotCommand
from controllers.base import BaseController
from domain.managers.map_placement import POSITION_SLOT_COUNT
from services import placement_proposals as placement_service
from services.placement_proposals import PlacementAcceptanceReport
from services.placement_proposals import PortProposalWorkflowResult
from services.placement_proposals import SlotProposalWorkflowResult

if TYPE_CHECKING:
    from commands.history import CommandHistory
    from model.project import Project

__all__ = ["PlacementController"]


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
