"""Project Completion Checks — A set of standards shared by export preflight and production progress panels.

Migrated from views/export_dialog.py (2026-06 architecture cleanup):
Completion is a business rule not a dialog detail, export preflight and M2’s resident progress panel
The same set of calculations must be used, otherwise there will be a conflict between the two sets of standards "the panel says it is complete, and the export says something is missing".

map_source: any provided province_map / tile_map / terrain_map / height_map
Object of properties (either MapData or Canvas), does not depend on Qt."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ui.i18n import tr

from domain.validation import ValidationReport
from services.validation_service import report_from_check_items


@dataclass
class CheckItem:
    """single check item"""
    name: str           # display name
    status: str         # "ok" / "missing" / "warning"
    detail: str         # Detailed description
    can_auto: bool      # Whether it can be automatically completed
    count: int = 0      # Quantity (number of provinces/number of states, etc.)
    code: str = ""      # Stable locale-independent rule code (e.g. readiness.provinces)


def _project_lifecycle_name(project) -> str:
    try:
        meta = getattr(project, "project_meta", None)
        if meta is not None:
            value = getattr(meta, "lifecycle", "draft")
            if isinstance(value, str):
                text = value.strip()
                if text:
                    return text
            if value is not None:
                text = str(value).strip()
                if text:
                    return text
    except Exception:
        pass
    return "draft"


def _is_foundation_profile_name(profile_name) -> bool:
    try:
        if profile_name is None:
            return False
        return str(profile_name).strip() == "foundation"
    except Exception:
        return False


def _build_placement_check_item(project, map_source, profile_name=None):
    manager = getattr(project, "map_placement_mgr", None)
    if manager is not None:
        try:
            from domain.validators.placement import validate_manager_placement_completeness as _validate
        except ImportError:
            return None
        try:
            province_map = getattr(map_source, "province_map", None)
            tile_map = getattr(map_source, "tile_map", None)
            lifecycle = _project_lifecycle_name(project)
            findings = _validate(province_map, tile_map, manager, lifecycle=lifecycle)
        except Exception:
            return None
        name = tr("export_check_placements")
        if not findings:
            return CheckItem(name, "ok", tr("export_check_placements_ok"), False, 0, code="readiness.placements")
        severities = set()
        for _f in findings:
            try:
                severities.add(str(getattr(_f, "severity", "") or "").strip().lower())
            except Exception:
                continue
        status = "missing" if (severities & {"blocker", "error"}) else "warning"
        parts = []
        for _f in findings:
            try:
                _msg = str(getattr(_f, "message", "") or "").strip()
            except Exception:
                _msg = ""
            try:
                _ev = str(getattr(_f, "evidence", "") or "").strip()
            except Exception:
                _ev = ""
            if _msg and _ev:
                parts.append(_msg + ": " + _ev)
            elif _msg:
                parts.append(_msg)
            elif _ev:
                parts.append(_ev)
        joined = "; ".join(parts) if parts else "placement review required"
        try:
            detail = tr("export_check_placements_review").format(issues=joined)
        except Exception:
            detail = joined + " - review placements in the Placement editor"
        return CheckItem(name, status, detail, False, 0, code="readiness.placements")
    if _is_foundation_profile_name(profile_name):
        return CheckItem(tr("export_check_placements"), "missing", tr("export_check_no_placements"), False, 0, code="readiness.placements")
    return None


def _append_placement_readiness(items, project, map_source, profile_name=None):
    try:
        extra = _build_placement_check_item(project, map_source, profile_name)
    except Exception:
        extra = None
    if extra is not None:
        items.append(extra)
    return items


def _logistics_finding_detail(finding) -> str:
    """Render a logistics finding with the province IDs it affects."""
    detail = str(getattr(finding, "message", "Logistics data requires attention"))
    affected = tuple(getattr(finding, "affected_ids", ()) or ())
    if affected:
        shown = ", ".join(str(value) for value in affected[:40])
        if len(affected) > 40:
            shown += ", ... (+%d more)" % (len(affected) - 40)
        detail += " " + tr("export_check_affected_provinces").format(provinces=shown)
    evidence = str(getattr(finding, "evidence", "") or "").strip()
    if evidence:
        detail += "\n" + tr("export_check_logistics_details").format(evidence=evidence)
    return detail


def _append_logistics_readiness(items, project, map_source, profile=None):
    """Add the same logistics/reference checks used by the export planner."""
    manager_names = (
        "adjacency_mgr", "railway_mgr", "supply_mgr", "adjacency_rule_mgr",
        "logistics_exception_mgr",
    )
    if not any(getattr(project, name, None) is not None for name in manager_names):
        # Keep compatibility with lightweight legacy readiness fixtures that
        # do not model logistics managers at all.
        return items

    validation_failed = False
    try:
        from domain.validators.logistics import validate_logistics_references

        findings = validate_logistics_references(
            map_source.province_map,
            map_source.tile_map,
            adjacency_mgr=getattr(project, "adjacency_mgr", None),
            railway_mgr=getattr(project, "railway_mgr", None),
            supply_mgr=getattr(project, "supply_mgr", None),
            adjacency_rule_mgr=getattr(project, "adjacency_rule_mgr", None),
            logistics_exception_mgr=getattr(project, "logistics_exception_mgr", None),
            country_mgr=getattr(project, "country_mgr", None),
            profile=profile,
            lifecycle=_project_lifecycle_name(project),
        )
    except (ImportError, TypeError, ValueError):
        findings = []
        validation_failed = True

    name_by_code = {
        "logistics.railway_route": tr("export_check_railways"),
        "logistics.graph": tr("export_check_logistics"),
        "logistics.exception_coverage": tr("export_check_logistics"),
        "logistics.adjacency_endpoint": tr("export_check_adjacencies"),
        "logistics.adjacency_rule": tr("export_check_adjacencies"),
        "logistics.port": tr("export_check_logistics"),
        "logistics.supply_node": tr("export_check_logistics"),
        "logistics.duplicate_route": tr("export_check_railways"),
    }

    def append_finding(finding, *, code: str | None = None) -> None:
        raw_code = str(getattr(finding, "code", "logistics") or "logistics")
        severity = str(getattr(finding, "severity", "warning") or "warning").lower()
        status = "missing" if severity in ("error", "blocker") else "warning"
        affected = tuple(getattr(finding, "affected_ids", ()) or ())
        if raw_code.startswith("adjacency.review"):
            name = tr("export_check_adjacency_review")
        else:
            name = name_by_code.get(raw_code, tr("export_check_logistics"))
        items.append(CheckItem(
            name=name,
            status=status,
            detail=_logistics_finding_detail(finding),
            can_auto=False,
            count=len(affected) or 1,
            code=code or "readiness." + raw_code,
        ))

    for finding in findings:
        append_finding(finding)

    # Keep the adjacency review decision visible before export.  The planner
    # uses the same lifecycle-sensitive policy, so the two screens cannot
    # disagree about whether an empty layer was reviewed.
    meta = getattr(project, "project_meta", None)
    if meta is not None:
        try:
            from domain.adjacency_review import evaluate_adjacency_review

            lifecycle = _project_lifecycle_name(project)
            context = "freeze" if lifecycle in ("frozen", "accepted") else "foundation_candidate"
            decision = evaluate_adjacency_review(
                getattr(project, "adjacency_mgr", None),
                getattr(project, "adjacency_rule_mgr", None),
                state=getattr(meta, "adjacency_review", "unreviewed"),
                note=getattr(meta, "adjacency_review_note", ""),
                review_hash=getattr(meta, "adjacency_review_hash", None),
                context=context,
            )
            if decision.finding is not None:
                append_finding(decision.finding, code="readiness.adjacency_review")
        except (ImportError, TypeError, ValueError):
            pass

    if validation_failed:
        items.append(CheckItem(
            tr("export_check_logistics"),
            "warning",
            tr("export_check_logistics_unavailable"),
            False,
            0,
            code="readiness.logistics",
        ))
    elif not findings:
        items.append(CheckItem(
            tr("export_check_logistics"),
            "ok",
            tr("export_check_logistics_ok"),
            False,
            0,
            code="readiness.logistics",
        ))
    return items


def check_project_readiness(project, map_source, profile=None, dimensions: tuple[int, int] | None = None, profile_name: str | None = None) -> list[CheckItem]:
    """Check whether the item can be exported and return the list of checked items.

    ``profile``/``dimensions`` optionally validate explicit map sizes against
    the data-driven game profile instead of relying on global constants.
    Omitted values preserve the legacy UI/generator behaviour."""
    items: list[CheckItem] = []
    pm = map_source.province_map
    tm = map_source.tile_map
    province_count = int(pm.max())
    if profile is not None or dimensions is not None:
        try:
            _rw, _rh = (int(dimensions[0]), int(dimensions[1])) if dimensions is not None else (int(pm.shape[1]), int(pm.shape[0]))
        except Exception:
            _rw, _rh = int(pm.shape[1]), int(pm.shape[0])
        _prof = profile
        if _prof is None:
            try:
                from services.game_profile_service import get_default_profile as _get_prof
                _prof = _get_prof()
            except Exception:
                _prof = None
        if _prof is not None:
            _derr = _prof.validate_dimensions(_rw, _rh)
            if _derr:
                items.append(CheckItem("map_dimensions", "missing", "; ".join(_derr), False, code="readiness.map_dimensions"))
                _append_placement_readiness(items, project, map_source, profile_name)
                return items

    # 1. Land/Province
    if province_count == 0:
        items.append(CheckItem(
            tr("export_check_provinces"), "missing",
            tr("export_check_no_provinces"), False, code="readiness.provinces"))
        # Follow-up inspections are meaningless without provinces
        _append_placement_readiness(items, project, map_source, profile_name)
        return items

    from data.constants import TILE_LAND
    flat_tm = tm.ravel()
    flat_pm = pm.ravel()
    land_pixels = int(np.sum(flat_tm == TILE_LAND))
    if land_pixels == 0:
        items.append(CheckItem(
            tr("export_check_land"), "missing",
            tr("export_check_no_land"), False, code="readiness.land"))
        _append_placement_readiness(items, project, map_source, profile_name)
        return items

    # Check ID continuity (there may be holes after merging provinces)
    existing_ids = set(int(x) for x in np.unique(pm) if x > 0)
    expected_ids = set(range(1, province_count + 1))
    gap_ids = expected_ids - existing_ids
    if gap_ids:
        items.append(CheckItem(
            tr("export_check_provinces"), "warning",
            tr("export_check_province_gaps").format(
                total=len(existing_ids), gaps=len(gap_ids)),
            False, len(existing_ids), code="readiness.provinces"))
    else:
        items.append(CheckItem(
            tr("export_check_provinces"), "ok",
            tr("export_check_province_ok").format(count=province_count),
            False, province_count, code="readiness.provinces"))

    # A province must resolve to one surface class.  Lake/land splits are
    # safe to normalize, so the export auto-correct path can repair them.
    try:
        from domain.province_surface import find_land_lake_splits

        land_lake_splits = find_land_lake_splits(tm, pm)
    except (ImportError, TypeError, ValueError):
        land_lake_splits = ()
    if land_lake_splits:
        ids = ", ".join(str(item.province_id) for item in land_lake_splits[:12])
        if len(land_lake_splits) > 12:
            ids += ", ..."
        items.append(CheckItem(
            tr("export_check_surface"),
            "warning",
            tr("export_check_land_lake_split").format(
                count=len(land_lake_splits), provinces=ids
            ),
            True,
            len(land_lake_splits),
            code="readiness.province_surfaces",
        ))

    # 2. State
    state_mgr = project.state_mgr
    state_count = len(state_mgr.states) if state_mgr.states else 0
    if state_count == 0:
        items.append(CheckItem(
            tr("export_check_state"), "missing",
            tr("export_check_no_state"),
            True, code="readiness.states"))
    else:
        # Check orphan provinces
        n = province_count + 1
        land_counts = np.bincount(flat_pm, weights=(flat_tm == TILE_LAND), minlength=n)
        total_counts = np.bincount(flat_pm, minlength=n)
        land_pids = set()
        for pid in range(1, n):
            if total_counts[pid] > 0 and land_counts[pid] > total_counts[pid] / 2:
                land_pids.add(pid)
        assigned = set()
        for s in state_mgr.states.values():
            assigned.update(s.provinces)
        orphans = land_pids - assigned
        if orphans:
            items.append(CheckItem(
                tr("export_check_state"), "warning",
                tr("export_check_state_orphans").format(
                    count=state_count, orphans=len(orphans)),
                True, state_count, code="readiness.states"))
        else:
            items.append(CheckItem(
                tr("export_check_state"), "ok",
                tr("export_check_state_ok").format(count=state_count),
                False, state_count, code="readiness.states"))

    # 3. Country
    country_mgr = project.country_mgr
    country_count = len(country_mgr.countries) if country_mgr.countries else 0
    if country_count == 0:
        items.append(CheckItem(
            tr("export_check_country"), "missing",
            tr("export_check_no_country"),
            True, code="readiness.countries"))
    else:
        # Check for unowned State
        unowned = []
        for sid in state_mgr.states:
            if not country_mgr.get_owner_of_state(sid):
                unowned.append(sid)
        if unowned:
            items.append(CheckItem(
                tr("export_check_country"), "warning",
                tr("export_check_country_unowned").format(
                    count=country_count, unowned=len(unowned)),
                True, country_count, code="readiness.countries"))
        else:
            items.append(CheckItem(
                tr("export_check_country"), "ok",
                tr("export_check_country_ok").format(count=country_count),
                False, country_count, code="readiness.countries"))

    # 4. Strategic areas
    sr_mgr = project.strategic_region_mgr
    sr_count = sr_mgr.count() if sr_mgr else 0
    if sr_count == 0:
        items.append(CheckItem(
            tr("export_check_strategic_region"), "missing",
            tr("export_check_no_strategic_region"),
            True, code="readiness.strategic_regions"))
    else:
        items.append(CheckItem(
            tr("export_check_strategic_region"), "ok",
            tr("export_check_strategic_region_ok").format(count=sr_count),
            False, sr_count, code="readiness.strategic_regions"))

    # 5. Mainland
    cont_mgr = project.continent_mgr
    cont_count = cont_mgr.count() if cont_mgr else 0
    if cont_count == 0:
        items.append(CheckItem(
            tr("export_check_continent"), "missing",
            tr("export_check_no_continent"),
            True, code="readiness.continents"))
    else:
        items.append(CheckItem(
            tr("export_check_continent"), "ok",
            tr("export_check_continent_ok").format(count=cont_count),
            False, cont_count, code="readiness.continents"))

    # 6. Terrain
    ter = map_source.terrain_map
    if ter is None or int(ter.max()) == 0:
        items.append(CheckItem(
            tr("export_check_terrain"), "missing",
            tr("export_check_no_terrain"),
            True, code="readiness.terrain"))
    else:
        items.append(CheckItem(
            tr("export_check_terrain"), "ok",
            tr("export_check_terrain_ok"), False, code="readiness.terrain"))

    # 7. Height
    hm = map_source.height_map
    if hm is None or int(hm.max()) == int(hm.min()):
        items.append(CheckItem(
            tr("export_check_heightmap"), "missing",
            tr("export_check_no_heightmap"),
            True, code="readiness.heightmap"))
    else:
        items.append(CheckItem(
            tr("export_check_heightmap"), "ok",
            tr("export_check_heightmap_ok"), False, code="readiness.heightmap"))

    # 8. Art assets (only displayed when there are imported assets)
    asset_total = len(getattr(project, "assets", {}) or {})
    if asset_total > 0:
        clean_count = project.clean_asset_count()
        dirty_count = project.dirty_asset_count()
        if dirty_count == 0:
            items.append(CheckItem(
                tr("export_check_assets"), "ok",
                tr("export_check_assets_all_clean").format(total=asset_total),
                False, asset_total, code="readiness.assets"))
        else:
            items.append(CheckItem(
                tr("export_check_assets"), "warning",
                tr("export_check_assets_dirty").format(
                    total=asset_total, clean=clean_count, dirty=dirty_count),
                False, asset_total, code="readiness.assets"))

    _append_logistics_readiness(items, project, map_source, profile=profile)
    _append_placement_readiness(items, project, map_source, profile_name)
    return items


def check_project_readiness_report(project, map_source, profile=None, dimensions: tuple[int, int] | None = None, context="draft_preview", source="readiness", profile_name: str | None = None) -> ValidationReport:
    """Build a shared ValidationReport from the live readiness checks.

    Calls check_project_readiness exactly once and adapts its CheckItem
    list without running duplicate checks. Finding codes come from the
    locale-independent CheckItem codes, so reports stay stable across
    UI languages. The wrapper is Qt-free like the underlying checks.
    """
    items = check_project_readiness(project, map_source, profile=profile, dimensions=dimensions, profile_name=profile_name)
    return report_from_check_items(items, source=source, context=context)
