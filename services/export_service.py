"""MOD export service — verification before export + automatic repair + adjustment export_full_mod.

The UI layer (MainWindow) is only responsible for directory selection + error display, and the business rules are all here."""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field

from domain.managers.state import normalize_state_category
from ui.i18n import get_language


@dataclass(frozen=True)
class ExportReport:
    """Export results report"""
    warnings: list[str] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


def validate_before_export(canvas, state_mgr, country_mgr) -> list[str]:
    """Returns a list of warnings. Empty list = safe to export."""
    warnings: list[str] = []
    pm = canvas.province_map
    if int(pm.max()) == 0:
        warnings.append("No province data; generate provinces first")
        return warnings

    if not state_mgr.states:
        warnings.append("No states; group provinces automatically or create a state manually")

    if not country_mgr.countries:
        warnings.append("No countries; create at least one country")

    unowned = []
    for sid, state in state_mgr.states.items():
        owner = country_mgr.get_owner_of_state(sid)
        if not owner:
            unowned.append(str(sid))
    if unowned:
        warnings.append(
            f"{len(unowned)} states have no country: {', '.join(unowned[:5])}..."
        )

    for tag, country in country_mgr.countries.items():
        if country.capital <= 0:
            warnings.append(f"Country {tag} has no capital")

    # ── River legality (display-level issue: the game will not crash, but the flow will be cut off/not displayed)──
    from domain.managers.river import validate_rivers, VALID_RIVER_VALUES
    rm = getattr(canvas, "river_map", None)
    if rm is not None and bool(np.isin(rm, list(VALID_RIVER_VALUES)).any()):
        issues = [
            w for w in validate_rivers(rm, lang=get_language())
            if w not in ("No river data", "River validation passed ✓")
        ]
        for w in issues[:5]:
            warnings.append(f"River: {w}")
        if len(issues) > 5:
            n = len(issues) - 5
            warnings.append(f"River: {n} more issues; see Validate River on the River page")

    return warnings


# ────────────────── Export pre-check steps (scheduled by pre_export_check_and_fix)──────────────────
# One function per step: does one thing and writes the result to the passed warnings / fixed list.


def _precheck_sync_terrain_tile(terrain_map, tile_map, fixed) -> None:
    """Step 1: Consistency between terrain_map and tile_map — land cannot be ocean, ocean must be ocean, and lakes must be lakes."""
    from data.terrain_types import TERRAIN_PALETTE_INDEX
    from data.constants import TILE_LAND, TILE_SEA, TILE_LAKE
    ocean_idx = TERRAIN_PALETTE_INDEX["ocean"]
    plains_idx = TERRAIN_PALETTE_INDEX["plains"]
    lakes_idx = TERRAIN_PALETTE_INDEX["lakes"]

    land_bad = (tile_map == TILE_LAND) & (terrain_map == ocean_idx)
    sea_bad = (tile_map == TILE_SEA) & (terrain_map != ocean_idx)
    lake_bad = (tile_map == TILE_LAKE) & (terrain_map != lakes_idx)

    count_lb = int(np.sum(land_bad))
    count_sb = int(np.sum(sea_bad))
    count_lk = int(np.sum(lake_bad))

    if count_lb > 0:
        terrain_map[land_bad] = plains_idx
        fixed.append(f"Changed terrain on {count_lb:,} land pixels from ocean to plains")
    if count_sb > 0:
        terrain_map[sea_bad] = ocean_idx
        fixed.append(f"Changed terrain on {count_sb:,} sea pixels to ocean")
    if count_lk > 0:
        terrain_map[lake_bad] = lakes_idx
        fixed.append(f"Changed terrain on {count_lk:,} lake pixels to lakes")


def _precheck_clean_empty_states(state_mgr, country_mgr, fixed) -> None:
    """Step 2: Delete the empty State + compact the ID continuously.

    The empty state left by merging province must be deleted. After deletion, there will still be a gap in the ID → HOI4 statetemplate.cpp:651
    Report 'Missing State ID' → divide by zero in AI tick phase → crash (actual test case at 2026-04-25 16:30).
    Therefore, after deletion, the remaining state must be renumbered to 1..N, and the state owner reference in country_mgr must be updated simultaneously."""
    empty_sids = state_mgr.find_empty_state_ids()
    if empty_sids:
        for sid in empty_sids:
            state_mgr.delete_state(sid)
        preview = ", ".join(str(s) for s in empty_sids[:10])
        more = f"; {len(empty_sids)} total" if len(empty_sids) > 10 else ""
        fixed.append(f"Deleted {len(empty_sids)} empty states left by province merges: {preview}{more}")
    mapping = state_mgr.compact_ids()
    if mapping:
        if country_mgr is not None:
            country_mgr.remap_state_ids(mapping)
        fixed.append(f"Renumbered {len(mapping)} states with consecutive IDs (HOI4 does not allow ID gaps)")


def _precheck_warn_orphan_provinces(province_map, tile_map, province_count,
                                    state_mgr, warnings) -> None:
    """Step 3: The land province must belong to a certain State (the exporter will automatically adopt it, please prompt here first)."""
    from data.constants import TILE_LAND
    flat_pm = province_map.ravel()
    flat_tm = tile_map.ravel()
    n = province_count + 1
    land_counts = np.bincount(flat_pm, weights=(flat_tm == TILE_LAND), minlength=n)
    total_counts = np.bincount(flat_pm, minlength=n)

    land_pids = set()
    for pid in range(1, province_count + 1):
        if total_counts[pid] > 0 and land_counts[pid] > total_counts[pid] / 2:
            land_pids.add(pid)

    assigned_pids = set()
    for sid, state in state_mgr.states.items():
        assigned_pids.update(state.provinces)

    orphan_pids = land_pids - assigned_pids
    if orphan_pids:
        warnings.append(
            f"{len(orphan_pids)} land provinces are not assigned to a state (assigned automatically during export)"
        )


def _precheck_fix_unowned_states(state_mgr, country_mgr, warnings, fixed) -> None:
    """Step 4: Each State must have an owner (no AI tick will crash), and will be automatically assigned to the first State."""
    unowned = []
    for sid in state_mgr.states:
        owner = country_mgr.get_owner_of_state(sid)
        if not owner:
            unowned.append(sid)
    if not unowned:
        return
    if country_mgr.countries:
        first_tag = next(iter(country_mgr.countries))
        for sid in unowned:
            country_mgr.assign_state(sid, first_tag)
            state = state_mgr.get_state(sid)
            if state:
                state.owner_tag = first_tag
        fixed.append(f"Assigned {len(unowned)} unowned states automatically to {first_tag}")
    else:
        warnings.append(f"{len(unowned)} states have no owner and no country is available for assignment")


def _precheck_align_states_to_regions(province_map, province_count,
                                      state_mgr, strategic_region_mgr, fixed) -> None:
    """Step 5.4: state ↔ strategic area alignment.

    HOI4 requires that all provinces in a state belong to the same strategic area, otherwise nudge will be reported
    "provinces are not belong to the same strategic region as other provinces".
    Hand-drawn strategic areas/automatically generated by land blocks may cut the state. Repair strategy:
    Taking the "pixel connected group within the state" as a unit, move the entire group of provinces into the strategic area where most of the provinces in the group are located.
    The group is connected and the target area already contains the provinces in the group → After moving, the target area is still connected and will not create the situation of being demolished in 5.5.
    The states themselves that are not connected (enclaves/offshore islands) can only be aligned to the group level, and the rest will be warned by the 5.6 final inspection."""
    from scipy.ndimage import label as _sci_label, find_objects as _sci_find_objects

    regions_now = strategic_region_mgr.regions
    pid_to_rid: dict[int, int] = {}
    for r in regions_now.values():
        for p in r.province_ids:
            pid_to_rid[p] = r.id

    # Cut state: provinces belong to multiple strategic areas, or some provinces are not assigned strategic areas
    split_states: list[tuple[int, list[int]]] = []
    for sid, st in state_mgr.states.items():
        provs = [p for p in st.provinces if 0 < p <= province_count]
        if len(provs) < 2:
            continue
        rids = {pid_to_rid.get(p, 0) for p in provs}
        if len(rids - {0}) > 1 or (len(rids) > 1 and 0 in rids):
            split_states.append((sid, provs))

    if not split_states:
        return

    # Each state only calculates connected components within its own bounding box to avoid scanning the entire image state by state.
    state_id_map = state_mgr.build_state_id_map(province_map)
    max_sid = max(state_mgr.states.keys())
    boxes = _sci_find_objects(state_id_map, max_label=max_sid)

    region_provs: dict[int, set[int]] = {
        rid: set(r.province_ids) for rid, r in regions_now.items()
    }
    moved = 0
    for sid, provs in split_states:
        box = boxes[sid - 1] if 0 < sid <= len(boxes) else None
        if box is None:
            continue
        sub_pm = province_map[box]
        labeled, n_comp = _sci_label(state_id_map[box] == sid)
        for comp in range(1, n_comp + 1):
            comp_pids = [int(p) for p in np.unique(sub_pm[labeled == comp]) if p > 0]
            counts: dict[int, int] = {}
            for p in comp_pids:
                rid = pid_to_rid.get(p, 0)
                if rid:
                    counts[rid] = counts.get(rid, 0) + 1
            if not counts:
                continue  # The entire group is not assigned strategic areas → leaving it to the completion of the export dialog
            # The strategic area where most provinces are located; when the numbers are tied, use the smaller ID to ensure the result is certain.
            target = min(counts, key=lambda k: (-counts[k], k))
            for p in comp_pids:
                old = pid_to_rid.get(p, 0)
                if old == target:
                    continue
                if old in region_provs:
                    region_provs[old].discard(p)
                region_provs.setdefault(target, set()).add(p)
                pid_to_rid[p] = target
                moved += 1

    if not moved:
        return

    # Write back to manager; the vacated strategic area will be deleted directly (the ID will be renumbered when exporting)
    emptied = []
    for rid, prov_set in region_provs.items():
        region = strategic_region_mgr.get(rid)
        if region is None:
            continue
        if not prov_set:
            emptied.append(rid)
        elif set(region.province_ids) != prov_set:
            region.province_ids = sorted(prov_set)
    for rid in emptied:
        strategic_region_mgr.remove_region(rid)
    msg = f"Corrected strategic-region assignment for {moved} provinces so states are not split across regions (affecting {len(split_states)} states"
    if emptied:
        msg += f", deleted {len(emptied)} regions emptied by the move"
    msg += ")"
    fixed.append(msg)


def _precheck_split_disconnected_regions(province_map, province_count,
                                         strategic_region_mgr, fixed) -> None:
    """Step 5.5: Split geographically disconnected strategic regions.

    The HOI4 engine requires provinces within each strategic region to be **geographically connected** (pixel-level 4-adjacency).
    Users manually animate regions in the UI or old version data may produce disconnected regions (a region
    Spanning two separate areas). HOI4 loads this region → engine infinite loop / divide-by-zero crash (actual test case).
    Here it is forced to be split according to connectivity, and the disconnected parts become independent regions."""
    from domain.managers.strategic_region import _split_connected
    split_count = 0
    new_regions_added = 0
    for old_region in list(strategic_region_mgr.regions.values()):
        provs = [p for p in old_region.province_ids if 0 < p <= province_count]
        if len(provs) < 2:
            continue
        groups = _split_connected(province_map, set(provs))
        if len(groups) <= 1:
            continue  # Already connected, not moving
        # Disconnected: the first group remains in the original region, and the remaining groups are split into new regions
        split_count += 1
        old_region.province_ids = list(groups[0])
        for extra_group in groups[1:]:
            new_r = strategic_region_mgr.create_region()
            new_r.province_ids = list(extra_group)
            new_r.naval_terrain = old_region.naval_terrain
            new_r.weather_preset = old_region.weather_preset
            new_regions_added += 1
    if split_count > 0:
        fixed.append(
            f"Split {split_count} geographically disconnected strategic regions → added {new_regions_added} connected regions (HOI4 requires provinces in a region to be pixel-connected or it may crash)"
        )


def _precheck_warn_cross_region_states(state_mgr, strategic_region_mgr, warnings) -> None:
    """Step 5.6: Final inspection — state still cut by strategic zones.

    After 5.4 alignment + 5.5 connectivity splitting, only the "state itself's pixels are not connected" (enclaves/offshore islands) are left across regions:
    The strategic areas must be connected (otherwise they will collapse). Two separated areas cannot be in the same area. This is a contradiction in the data itself and cannot be fixed automatically.
    There is only a nudge warning in the game, which does not affect the gameplay; to eliminate it, you must split the enclave into an independent state."""
    pid_to_rid: dict[int, int] = {}
    for r in strategic_region_mgr.regions.values():
        for p in r.province_ids:
            pid_to_rid[p] = r.id
    cross_sids = []
    for sid, st in state_mgr.states.items():
        rids = {pid_to_rid[p] for p in st.provinces if p in pid_to_rid}
        if len(rids) > 1:
            cross_sids.append(sid)
    if cross_sids:
        preview = ", ".join(str(s) for s in cross_sids[:10])
        more = f"; {len(cross_sids)} total" if len(cross_sids) > 10 else ""
        warnings.append(
            f"{len(cross_sids)} states contain exclaves/offshore islands and cannot fit in one strategic region (State {preview}{more}). This only causes a harmless in-game warning; split the exclaves into separate states to eliminate it"
        )


def _precheck_fix_missing_capitals(state_mgr, country_mgr, warnings, fixed) -> None:
    """Step 6: Each country must have a capital (invalid capital selection will result in country collapse) — automatically uses the first province of the first state."""
    for tag, country in country_mgr.countries.items():
        if country.capital > 0:
            continue
        owned_states = country_mgr.get_states_of_country(tag)
        if owned_states and state_mgr:
            first_state = state_mgr.get_state(owned_states[0])
            if first_state and first_state.provinces:
                country.capital = first_state.provinces[0]
                fixed.append(f"Set the capital of {tag} automatically to province {country.capital}")
            else:
                warnings.append(f"Country {tag} has no capital and one could not be set automatically")
        else:
            warnings.append(f"Country {tag} has no capital and no territory")


def pre_export_check_and_fix(
    tile_map: np.ndarray,
    province_map: np.ndarray,
    terrain_map: np.ndarray | None,
    state_mgr,
    country_mgr,
    continent_mgr=None,
    strategic_region_mgr=None,
) -> ExportReport:
    """Automatically detect and fix known issues before exporting.

    Returns an ExportReport containing repair information and a warning that automatic repair cannot be performed."""
    warnings: list[str] = []
    fixed: list[str] = []

    province_count = int(province_map.max())
    if province_count == 0:
        return ExportReport(warnings=["No province data"], fixed=[], stats={})

    # ── 1. Synchronize terrain_map and tile_map ──
    if terrain_map is not None:
        _precheck_sync_terrain_tile(terrain_map, tile_map, fixed)

    # ── 2. Province colors — generate_province_colors uses the used collection to ensure uniqueness, no collision, no checking ──

    # ── 2.5 Delete empty State + compaction ID consecutive ──
    if state_mgr:
        _precheck_clean_empty_states(state_mgr, country_mgr, fixed)

    # ── 3. Verify that all land provinces belong to State ──
    if state_mgr and state_mgr.states:
        _precheck_warn_orphan_provinces(province_map, tile_map, province_count,
                                        state_mgr, warnings)

    # ── 4. Verify that all States have owners ──
    if state_mgr and country_mgr:
        _precheck_fix_unowned_states(state_mgr, country_mgr, warnings, fixed)

    # ── 5. Verify that the province belongs to the mainland ──
    if continent_mgr is not None:
        # continent_mgr defaults to index 0 for all land provinces, so generally no problem
        if continent_mgr.count() == 0:
            warnings.append("No continents are defined; the default continent will be used during export")

    # ── 5.4 state ↔ strategic area alignment (state groups cut by strategic areas are moved back to the same area) ──
    if (strategic_region_mgr is not None and strategic_region_mgr.regions
            and state_mgr and state_mgr.states):
        _precheck_align_states_to_regions(province_map, province_count,
                                          state_mgr, strategic_region_mgr, fixed)

    # ── 5.5 Split geographically disconnected strategic regions (if not split, it will collapse) ──
    if strategic_region_mgr is not None and strategic_region_mgr.regions:
        _precheck_split_disconnected_regions(province_map, province_count,
                                             strategic_region_mgr, fixed)

    # ── 5.6 Final inspection: state still cut by strategic areas (enclave state, cannot be repaired, only warning) ──
    if (strategic_region_mgr is not None and strategic_region_mgr.regions
            and state_mgr and state_mgr.states):
        _precheck_warn_cross_region_states(state_mgr, strategic_region_mgr, warnings)

    # ── 6. Verify country capital ──
    if country_mgr and country_mgr.countries:
        _precheck_fix_missing_capitals(state_mgr, country_mgr, warnings, fixed)

    # ── Statistics ──
    stats = {
        "provinces": province_count,
        "states": len(state_mgr.states) if state_mgr else 0,
        "countries": len(country_mgr.countries) if country_mgr else 0,
    }

    return ExportReport(warnings=warnings, fixed=fixed, stats=stats)


def fill_default_state_data(
    state_mgr,
    terrain_map: np.ndarray | None,
    province_map: np.ndarray,
    tile_map: np.ndarray,
) -> int:
    """Populate default terrain-based data for States without resources/buildings.

    Only empty data is filled in and values ​​already set by the user are not overwritten.
    Returns the number of States populated with default data."""
    if not state_mgr or not state_mgr.states:
        return 0

    from data.constants import TILE_LAND
    from data.terrain_types import PALETTE_TO_TYPE

    filled_count = 0
    rng = np.random.RandomState(42)

    # Vectorized precomputation: number of land pixels in each province + terrain distribution (one full map scan instead of N times)
    max_pid = int(province_map.max())
    flat_pm = province_map.ravel()
    flat_tm = tile_map.ravel()
    flat_land = (flat_tm == TILE_LAND).astype(np.int32)
    pid_land_count = np.bincount(flat_pm, weights=flat_land, minlength=max_pid + 1)

    # Number of pixels for each (province_id, terrain_index)
    pid_terrain_count: dict[int, dict[int, int]] = {}
    if terrain_map is not None:
        flat_ter = terrain_map.ravel()
        land_mask_flat = flat_land.astype(bool)
        land_pids = flat_pm[land_mask_flat]
        land_ters = flat_ter[land_mask_flat]
        # Do a bincount for a single key encoded with (pid * 256 + terrain_idx)
        combined = land_pids.astype(np.int64) * 256 + land_ters.astype(np.int64)
        combined_counts = np.bincount(combined)
        for code in np.nonzero(combined_counts)[0]:
            pid_code = int(code // 256)
            ter_code = int(code % 256)
            if pid_code not in pid_terrain_count:
                pid_terrain_count[pid_code] = {}
            pid_terrain_count[pid_code][ter_code] = int(combined_counts[code])

    for sid, state in state_mgr.states.items():
        has_resources = bool(state.resources and any(v > 0 for v in state.resources.values()))
        has_buildings = bool(state.buildings and any(v > 0 for v in state.buildings.values()))

        if has_resources and has_buildings:
            continue

        # Summarize the terrain composition of the state using precomputed data
        terrain_counts: dict[str, int] = {}
        total_land_pixels = 0
        for pid in state.provinces:
            if pid > max_pid:
                continue
            land_px = int(pid_land_count[pid])
            total_land_pixels += land_px
            if land_px > 0 and pid in pid_terrain_count:
                for ter_idx, count in pid_terrain_count[pid].items():
                    ttype = PALETTE_TO_TYPE.get(ter_idx, "plains")
                    terrain_counts[ttype] = terrain_counts.get(ttype, 0) + count

        if total_land_pixels == 0:
            continue

        filled_count += 1

        # Determine the main terrain
        dominant = max(terrain_counts, key=terrain_counts.get) if terrain_counts else "plains"

        # Normalize legacy editor aliases before deriving export defaults.
        # HOI4 does not define ``tiny``/``small`` state categories; the
        # equivalent vanilla keys are ``pastoral``/``rural``.
        state.category = normalize_state_category(state.category)

        # Set up infrastructure based on state_category
        cat_infra = {
            "wasteland": 0, "pastoral": 1, "rural": 1,
            "town": 2, "large_town": 2, "city": 3,
            "large_city": 4, "metropolis": 5, "megalopolis": 5,
        }

        # ── Fill resources ──
        if not has_resources:
            resources: dict[str, int] = {}
            if dominant in ("mountain", "hills"):
                # Mountain/Hill: Steel/Chrome
                resources["steel"] = rng.randint(4, 20)
                if rng.random() > 0.5:
                    resources["chromium"] = rng.randint(2, 12)
            elif dominant == "desert":
                # Desert: Oil Probability
                if rng.random() > 0.4:
                    resources["oil"] = rng.randint(2, 16)
            elif dominant in ("jungle",):
                # Jungle: Rubber
                resources["rubber"] = rng.randint(2, 10)
            elif dominant in ("forest",):
                # Forest: Tungsten
                if rng.random() > 0.5:
                    resources["tungsten"] = rng.randint(2, 8)
            elif dominant == "urban":
                # City: Aluminum
                resources["aluminium"] = rng.randint(4, 16)

            if resources:
                state.resources = resources

        # ── Infill buildings ──
        if not has_buildings:
            infra = cat_infra.get(state.category, 1)
            buildings: dict[str, int] = {}
            if infra > 0:
                buildings["infrastructure"] = infra
            state.buildings = buildings

        # ── Fill manpower ──
        if state.manpower <= 0:
            # Estimated by number of provinces and categories
            province_count = len(state.provinces)
            base = province_count * 50000
            cat_multiplier = {
                "wasteland": 0, "pastoral": 0.5, "rural": 1.0,
                "town": 1.5, "large_town": 2.0, "city": 3.0,
                "large_city": 5.0, "metropolis": 7.0, "megalopolis": 10.0,
            }
            state.manpower = int(base * cat_multiplier.get(state.category, 1.0))

    return filled_count


def export_mod(
    output_dir: str,
    canvas,
    state_mgr,
    country_mgr,
    continent_mgr,
    adjacency_mgr=None,
    railway_mgr=None,
    supply_mgr=None,
    colormap_settings=None,
    default_map_settings=None,
    adjacency_rule_mgr=None,
    strategic_region_mgr=None,
    scope: dict[str, bool] | None = None,
    assets: dict[str, bytes] | None = None,
    dirty_assets: set[str] | None = None,
) -> ExportReport:
    """Call the complete export pipeline. Throw an exception on failure. Return ExportReport."""
    # ── Automatically detect and repair before export──
    report = pre_export_check_and_fix(
        tile_map=canvas.tile_map,
        province_map=canvas.province_map,
        terrain_map=canvas.terrain_map,
        state_mgr=state_mgr,
        country_mgr=country_mgr,
        continent_mgr=continent_mgr,
        strategic_region_mgr=strategic_region_mgr,
    )

    # ── Fill State default resource/building ──
    filled = fill_default_state_data(
        state_mgr=state_mgr,
        terrain_map=canvas.terrain_map,
        province_map=canvas.province_map,
        tile_map=canvas.tile_map,
    )
    if filled > 0:
        report = ExportReport(
            warnings=report.warnings,
            fixed=list(report.fixed) + [f"Filled default resources/buildings for {filled} states"],
            stats=report.stats,
        )

    # ──Province number empty prompt──
    # The ID holes left by merging provinces are automatically compacted by the exporter on the export copy, and the project data remains unchanged.
    if scope is None or scope.get("compact_ids", True):
        _ids = np.unique(canvas.province_map)
        _nonzero = _ids[_ids > 0]
        _gap_count = int(_nonzero[-1]) - len(_nonzero) if len(_nonzero) else 0
        if _gap_count > 0:
            report = ExportReport(
                warnings=report.warnings,
                fixed=list(report.fixed) + [
                    f"Detected {_gap_count} gaps in province numbering left by merges; exported files were compacted automatically to consecutive IDs while project data remains unchanged"
                ],
                stats=report.stats,
            )

    # ──Execute export──
    from export.mod_exporter import export_full_mod
    export_full_mod(
        canvas.tile_map,
        canvas.province_map,
        output_dir,
        state_mgr=state_mgr,
        country_mgr=country_mgr,
        river_map=canvas.river_map,
        terrain_map=canvas.terrain_map,
        height_map=canvas.height_map,
        continent_mgr=continent_mgr,
        adjacency_mgr=adjacency_mgr,
        railway_mgr=railway_mgr,
        supply_mgr=supply_mgr,
        colormap_settings=colormap_settings,
        default_map_settings=default_map_settings,
        adjacency_rule_mgr=adjacency_rule_mgr,
        strategic_region_mgr=strategic_region_mgr,
        provincial_terrain=canvas.map_data.provincial_terrain,
        scope=scope,
        assets=assets,
        dirty_assets=dirty_assets,
    )

    # ── Statistics export file ──
    import os
    file_count = sum(len(files) for _, _, files in os.walk(output_dir))
    stats = dict(report.stats)
    stats["files"] = file_count

    return ExportReport(
        warnings=report.warnings,
        fixed=report.fixed,
        stats=stats,
    )
