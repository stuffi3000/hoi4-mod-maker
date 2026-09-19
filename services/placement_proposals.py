"""Headless placement proposal orchestration service, M5.2 Slice 1.

Thin deterministic layer over domain.generators.placement that composes
generation with manager ingestion without touching the filesystem, Qt,
views, controllers, or exports. Generation helpers never mutate their
inputs and ingestion helpers only mutate the explicitly supplied
placement manager. Acceptance is never triggered implicitly and sea
selection for ports is never guessed.
"""
from __future__ import annotations

from collections.abc import Iterable as CollectionsIterable
from collections.abc import Mapping as CollectionsMapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from domain.generators.placement import PlacementAcceptanceReport
from domain.generators.placement import PlacementProposalResult
from domain.generators.placement import PlacementStoreReport
from domain.generators.placement import PortProposalResult
from domain.generators.placement import PortStoreReport
from domain.generators.placement import accept_stored_placements
from domain.generators.placement import generate_placement_proposals
from domain.generators.placement import generate_port_proposals
from domain.generators.placement import store_placement_proposals
from domain.generators.placement import store_port_proposals
from domain.managers.map_placement import POSITION_SLOT_COUNT

__all__ = [
    "PortProposalWorkflowResult",
    "SlotProposalWorkflowResult",
    "accept_selected_placements",
    "propose_port_placements",
    "propose_slot_placements",
]


@dataclass(frozen=True)
class SlotProposalWorkflowResult:
    """Immutable outcome of slot proposal generation plus ingestion.

    Attributes:
        proposal: PlacementProposalResult from generate_placement_proposals.
        store_report: PlacementStoreReport from store_placement_proposals.
    """

    proposal: PlacementProposalResult
    store_report: PlacementStoreReport

    @property
    def diagnostics(self):
        """Explicit absence signals surfaced from generation."""
        return self.proposal.diagnostics

    @property
    def slots(self):
        """Generated slot records in province then slot order."""
        return self.proposal.slots


@dataclass(frozen=True)
class PortProposalWorkflowResult:
    """Immutable outcome of port proposal generation plus ingestion.

    Attributes:
        proposal: PortProposalResult from generate_port_proposals.
        store_report: PortStoreReport from store_port_proposals.
    """

    proposal: PortProposalResult
    store_report: PortStoreReport

    @property
    def diagnostics(self):
        """Explicit absence signals surfaced from generation."""
        return self.proposal.diagnostics

    @property
    def ports(self):
        """Generated port records in province order."""
        return self.proposal.ports


def propose_slot_placements(
    province_map: np.ndarray,
    tile_map: np.ndarray,
    manager: Any,
    *,
    height_map: np.ndarray | None = None,
    province_ids: CollectionsIterable[int] | None = None,
    seed: int = 0,
    slot_count: int = int(POSITION_SLOT_COUNT),
    min_separation: float = 2.0,
    border_weight: float = 1.0,
    coast_weight: float = 1.0,
    height_weight: float = 0.5,
    slope_weight: float = 1.0,
    replace_generated: bool = False,
) -> SlotProposalWorkflowResult:
    """Generate land slot proposals and store them without acceptance.

    Calls generate_placement_proposals with the supplied rasters and
    deterministic options, then store_placement_proposals into the
    supplied manager. Stored records keep provenance generated with
    review status unreviewed. This function never marks anything
    reviewed or accepted.

    Args:
        province_map: Two dimensional integer array of province ids.
        tile_map: Two dimensional integer array of tile surface types.
        manager: MapPlacementManager-like object mutated in place.
        height_map: Optional height raster forwarded verbatim.
        province_ids: Optional iterable of province ids to propose for.
        seed: Deterministic tie-break seed.
        slot_count: Slots per province forwarded to the generator.
        min_separation: Minimum separation forwarded to the generator.
        border_weight: Border weight forwarded to the generator.
        coast_weight: Coast weight forwarded to the generator.
        height_weight: Height weight forwarded to the generator.
        slope_weight: Slope weight forwarded to the generator.
        replace_generated: Forwarded to ingestion. False keeps existing
            records and reports skips. True replaces only unreviewed
            generated records while authored or reviewed records stay
            protected.

    Returns:
        SlotProposalWorkflowResult with both the proposal result and
        the store report. Diagnostics are surfaced on the result.
    """
    if province_ids is None:
        wanted_provinces = None
    else:
        wanted_provinces = list(province_ids)
    proposal = generate_placement_proposals(
        province_map,
        tile_map,
        height_map=height_map,
        province_ids=wanted_provinces,
        seed=seed,
        slot_count=slot_count,
        min_separation=min_separation,
        border_weight=border_weight,
        coast_weight=coast_weight,
        height_weight=height_weight,
        slope_weight=slope_weight,
    )
    report = store_placement_proposals(
        manager,
        proposal,
        replace_generated=replace_generated,
    )
    return SlotProposalWorkflowResult(proposal=proposal, store_report=report)


def propose_port_placements(
    province_map: np.ndarray,
    tile_map: np.ndarray,
    manager: Any,
    sea_mapping: CollectionsMapping,
    *,
    height_map: np.ndarray | None = None,
    province_ids: CollectionsIterable[int] | None = None,
    seed: int = 0,
    border_weight: float = 1.0,
    coast_weight: float = 1.0,
    height_weight: float = 0.5,
    slope_weight: float = 1.0,
    replace_generated: bool = False,
) -> PortProposalWorkflowResult:
    """Generate port proposals for an explicit sea mapping and store them.

    Calls generate_port_proposals with the exact supplied sea_mapping,
    then store_port_proposals into the supplied manager. The mapped sea
    is always used exactly as given. This function never substitutes a
    guessed adjacent sea and never marks anything reviewed or accepted.

    Args:
        province_map: Two dimensional integer array of province ids.
        tile_map: Two dimensional integer array of tile surface types.
        manager: MapPlacementManager-like object mutated in place.
        sea_mapping: Required explicit mapping of land province id to
            intended sea province id. Must be supplied by the caller.
        height_map: Optional height raster forwarded verbatim.
        province_ids: Optional iterable of land province ids to propose
            for. Defaults to the sorted keys of sea_mapping.
        seed: Deterministic tie-break seed.
        border_weight: Border weight forwarded to the generator.
        coast_weight: Coast weight forwarded to the generator.
        height_weight: Height weight forwarded to the generator.
        slope_weight: Slope weight forwarded to the generator.
        replace_generated: Forwarded to ingestion. False keeps existing
            records and reports skips. True replaces only unreviewed
            generated records while authored or reviewed records stay
            protected.

    Returns:
        PortProposalWorkflowResult with both the proposal result and
        the store report. Diagnostics are surfaced on the result.

    Raises:
        TypeError: If sea_mapping is None because the caller must pass
            an explicit mapping.
        ValueError: If sea_mapping is not a mapping.
    """
    if sea_mapping is None:
        raise TypeError(
            "sea_mapping is required, pass an explicit mapping of land "
            "province to sea province; guessing a sea is not allowed"
        )
    if not isinstance(sea_mapping, CollectionsMapping):
        raise ValueError(
            "sea_mapping must be a mapping of land province to sea province, "
            f"got {type(sea_mapping).__name__}"
        )
    sea_snapshot = dict(sea_mapping)
    if province_ids is None:
        wanted_provinces = None
    else:
        wanted_provinces = list(province_ids)
    proposal = generate_port_proposals(
        province_map,
        tile_map,
        sea_snapshot,
        height_map=height_map,
        province_ids=wanted_provinces,
        seed=seed,
        border_weight=border_weight,
        coast_weight=coast_weight,
        height_weight=height_weight,
        slope_weight=slope_weight,
    )
    report = store_port_proposals(
        manager,
        proposal,
        replace_generated=replace_generated,
    )
    return PortProposalWorkflowResult(proposal=proposal, store_report=report)


def accept_selected_placements(
    manager: Any,
    *,
    slot_keys: CollectionsIterable[tuple[int, int]] = (),
    port_ids: CollectionsIterable[int] = (),
    review_status: str = "reviewed",
) -> PlacementAcceptanceReport:
    """Accept only caller-selected stored slot and port proposals.

    Delegates to accept_stored_placements with the explicit key lists.
    Nothing is accepted implicitly. An empty selection accepts nothing.

    Args:
        manager: MapPlacementManager-like object mutated in place.
        slot_keys: Iterable of selected (province_id, slot) pairs.
        port_ids: Iterable of selected port province ids.
        review_status: Either reviewed or accepted.

    Returns:
        PlacementAcceptanceReport with accepted keys and missing entries
        for requested keys with no stored record.
    """
    wanted_slots = list(slot_keys)
    wanted_ports = list(port_ids)
    return accept_stored_placements(
        manager,
        wanted_slots,
        wanted_ports,
        review_status=review_status,
    )
