"""Shared stage context and helpers (M2.4)."""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field

import numpy as np


@dataclass
class StageContext:
    profile_name: str = "legacy_full"
    game_profile: object = None
    game_target: object = None
    mod_name: str = "WorldTest"
    tag: str = "AAA"
    scope: dict = field(default_factory=dict)
    output_dir: str = ""
    tile_map: object = None
    province_map: object = None
    terrain_map: object = None
    height_map: object = None
    river_map: object = None
    provincial_terrain: dict = field(default_factory=dict)
    state_mgr: object = None
    country_mgr: object = None
    continent_mgr: object = None
    adjacency_mgr: object = None
    railway_mgr: object = None
    supply_mgr: object = None
    adjacency_rule_mgr: object = None
    strategic_region_mgr: object = None
    logistics_exception_mgr: object = None
    map_placement_mgr: object = None
    colormap_settings: object = None
    default_map_settings: object = None
    assets: dict = field(default_factory=dict)
    dirty_assets: set = field(default_factory=set)
    acceptance_tags: tuple = ()
    scratch: dict = field(default_factory=dict)
    written: list = field(default_factory=list)
    provenance: list = field(default_factory=list)
    placeholders: list = field(default_factory=list)

    def enabled(self, key: str) -> bool:
        return bool(self.scope.get(key, True))

    def manager(self, name: str):
        return getattr(self, name, None)


def build_context_from_plan(plan, output_dir: str) -> StageContext:
    snapshot = plan.snapshot
    arrays = snapshot.mutable_arrays()
    managers = snapshot.fork_managers()
    profile_name = getattr(plan, "profile_name", None)
    placement_mgr = managers.get("map_placement_mgr")
    project_meta = getattr(snapshot, "project_meta", None)
    lifecycle = getattr(plan, "lifecycle", "draft") or "draft"
    foundation_legacy_compat = (
        profile_name == "foundation"
        and placement_mgr is None
        and project_meta is None
        and lifecycle not in ("frozen", "accepted")
    )
    return StageContext(
        profile_name=plan.profile_name,
        game_profile=plan.game_profile,
        game_target=plan.game_target,
        mod_name=plan.mod_name,
        tag=plan.tag,
        scope=dict(plan.scope or {}),
        output_dir=str(output_dir),
        tile_map=arrays["tile_map"],
        province_map=arrays["province_map"],
        terrain_map=arrays["terrain_map"],
        height_map=arrays["height_map"],
        river_map=arrays["river_map"],
        provincial_terrain=copy.deepcopy(snapshot.provincial_terrain or {}),
        state_mgr=managers["state_mgr"],
        country_mgr=managers["country_mgr"],
        continent_mgr=managers["continent_mgr"],
        adjacency_mgr=managers["adjacency_mgr"],
        railway_mgr=managers["railway_mgr"],
        supply_mgr=managers["supply_mgr"],
        adjacency_rule_mgr=managers["adjacency_rule_mgr"],
        strategic_region_mgr=managers["strategic_region_mgr"],
        logistics_exception_mgr=managers["logistics_exception_mgr"],
        map_placement_mgr=managers.get("map_placement_mgr"),
        colormap_settings=copy.deepcopy(snapshot.colormap_settings),
        default_map_settings=copy.deepcopy(snapshot.default_map_settings),
        assets=dict(snapshot.assets or {}),
        dirty_assets=set(snapshot.dirty_assets or ()),
        acceptance_tags=tuple(plan.acceptance_tags or ()),
        scratch={
            "province_type_overrides": dict(snapshot.province_type_overrides or {}),
            "foundation_legacy_compat": foundation_legacy_compat,
        },
    )


def snapshot_output_files(output_dir: str) -> set:
    found = set()
    if not os.path.isdir(output_dir):
        return found
    for root, _dirs, files in os.walk(output_dir):
        for name in files:
            found.add(os.path.relpath(os.path.join(root, name), output_dir).replace(os.sep, "/"))
    return found


def record_written(ctx: StageContext, before: set) -> list:
    from domain.export_contract import WrittenFile
    from services.export_manifest import hash_file
    after = snapshot_output_files(ctx.output_dir)
    new_files = []
    for rel_path in sorted(after - before):
        full = os.path.join(ctx.output_dir, rel_path.replace("/", os.sep))
        try:
            size = os.path.getsize(full)
            digest = hash_file(full)
        except OSError:
            continue
        entry = WrittenFile(rel_path, size, digest)
        ctx.written.append(entry)
        new_files.append(entry)
    return new_files


def classify_current(ctx) -> tuple:
    from services.export_planner import classify_provinces
    province_count = int(np.asarray(ctx.province_map).max())
    return classify_provinces(np.asarray(ctx.province_map), np.asarray(ctx.tile_map),
                              province_count, overrides=ctx.scratch.get("province_type_overrides"))


def compute_centroids(province_map) -> tuple:
    flat_pm = np.asarray(province_map).ravel()
    count = int(np.asarray(province_map).max()) + 1
    pid_count = np.bincount(flat_pm, minlength=count)
    height, width = np.asarray(province_map).shape
    ys_grid, xs_grid = np.mgrid[0:height, 0:width]
    sum_y = np.bincount(flat_pm, weights=ys_grid.ravel().astype(np.float64), minlength=count)
    sum_x = np.bincount(flat_pm, weights=xs_grid.ravel().astype(np.float64), minlength=count)
    try:
        del ys_grid, xs_grid
    except NameError:
        pass
    return pid_count, sum_x, sum_y


def build_export_states(ctx) -> dict | None:
    if "states" in ctx.scratch:
        return ctx.scratch["states"]
    state_mgr = ctx.state_mgr
    land_ids, _sea_ids, _lake_ids = classify_current(ctx)
    land_id_set = set(land_ids)
    if state_mgr is None or not getattr(state_mgr, "states", None):
        ctx.scratch["states"] = None
        ctx.scratch["land_id_set"] = land_id_set
        return None
    states: dict = {}
    for sid, state in state_mgr.states.items():
        land_provs = [int(p) for p in getattr(state, "provinces", []) or [] if int(p) in land_id_set]
        if land_provs:
            states[int(sid)] = land_provs
    assigned: set = set()
    for provs in states.values():
        assigned.update(provs)
    orphans = [int(p) for p in land_ids if p not in assigned]
    if orphans:
        province_map = np.asarray(ctx.province_map)
        pid_count, sum_x, sum_y = compute_centroids(province_map)
        size = len(pid_count)
        centers: dict = {}
        for sid, provs in states.items():
            total = tx = ty = 0.0
            for pid in provs:
                if 0 < pid < size and pid_count[pid] > 0:
                    tx += sum_x[pid]
                    ty += sum_y[pid]
                    total += pid_count[pid]
            if total > 0:
                centers[sid] = (ty / total, tx / total)
        adopted = 0
        for orphan in orphans:
            if orphan >= size or pid_count[orphan] == 0 or not centers:
                continue
            ocy, ocx = sum_y[orphan] / pid_count[orphan], sum_x[orphan] / pid_count[orphan]
            best = min(centers, key=lambda sid: (centers[sid][0] - ocy) ** 2 + (centers[sid][1] - ocx) ** 2)
            states[best].append(orphan)
            target = state_mgr.get_state(best) if hasattr(state_mgr, "get_state") else state_mgr.states.get(best)
            if target is not None and orphan not in (getattr(target, "provinces", []) or []):
                target.provinces.append(orphan)
            adopted += 1
        if adopted:
            ctx.provenance.append("orphan adoption assigned %d land provinces during generation" % adopted)
    ctx.scratch["states"] = states or None
    ctx.scratch["land_id_set"] = land_id_set
    return ctx.scratch["states"]
