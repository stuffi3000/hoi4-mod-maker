"""State geography stage: parseable state shells or full state history (M2.4/M2.5)."""
from __future__ import annotations

import numpy as np

from export.stages.base import record_written, snapshot_output_files


NAME = "state_geography"
OWNED_FILES = (
    "history/states/",
)
PROFILES = ("foundation", "acceptance", "scaffold", "legacy_full")
REQUIRES = ("states", "coastal_set")
PROVIDES = ()


def run(ctx):
    from domain.export_contract import StageResult
    before = snapshot_output_files(ctx.output_dir)
    notes: list = []
    placeholders: list = []
    states = ctx.scratch.get("states")
    if not ctx.enabled("states"):
        notes.append("states layer disabled by scope; state files skipped")
        ctx.scratch["placeholders"] = placeholders
        return StageResult(stage=NAME, owned_files=OWNED_FILES, written=record_written(ctx, before),
                           notes=notes)
    province_map = np.asarray(ctx.province_map)
    land_id_set = set(ctx.scratch.get("land_id_set") or [])
    coastal_set = set(ctx.scratch.get("coastal_set") or ())
    if ctx.profile_name in ("foundation", "acceptance"):
        if ctx.state_mgr is not None and getattr(ctx.state_mgr, "states", None):
            count = write_foundation_shells(ctx.state_mgr, province_map, ctx.output_dir,
                                            land_id_set, placeholders, ctx.profile_name,
                                            omit_owners=(ctx.profile_name == "foundation"
                                                         or not ctx.enabled("countries")))
            notes.append("wrote %d geography shells without resources/buildings/manpower/victory points"
                         % count)
            ctx.placeholders.extend(placeholders)
        else:
            notes.append("no states in snapshot; state shells skipped")
    elif ctx.state_mgr is not None and getattr(ctx.state_mgr, "states", None):
        from export.mod_exporter import _write_states_from_mgr
        _write_states_from_mgr(ctx.state_mgr, ctx.country_mgr, province_map, ctx.output_dir,
                               tile_map=np.asarray(ctx.tile_map),
                               land_id_set=land_id_set, coastal_set=coastal_set)
        notes.append("wrote %d full states" % len(ctx.state_mgr.states))
        if ctx.profile_name == "scaffold":
            ctx.provenance.append("state resources/buildings/manpower are generated scaffold helpers, "
                                  "excluded from the foundation lock")
    else:
        region_list = ctx.scratch.get("region_list")
        if region_list is not None:
            from export.mod_exporter import _split_states_by_region, _write_states
            fallback = _split_states_by_region(region_list, land_id_set)
            _write_states(fallback, ctx.tag, province_map, ctx.output_dir)
            notes.append("wrote %d fallback states split by region" % len(fallback))
        else:
            notes.append("no states and no regions; state files skipped")
    ctx.scratch["placeholders"] = placeholders
    written = record_written(ctx, before)
    return StageResult(stage=NAME, owned_files=OWNED_FILES, written=written, notes=notes)

def write_foundation_shells(state_mgr, province_map, output_dir, land_id_set, placeholders,
                             profile_name: str, omit_owners: bool = False) -> int:
    """Write geography-only state shells for the foundation/acceptance profiles.

    The shared history writer always derives category buildings, so shells use
    this dedicated writer: id, name, authored category, owner placeholders,
    and province membership only. Resources, buildings, manpower, and victory
    points are never emitted here; every non-geographic placeholder is
    recorded for the manifest.
    """
    import os
    from domain.managers.state import normalize_state_category
    states_dir = os.path.join(output_dir, "history", "states")
    os.makedirs(states_dir, exist_ok=True)
    try:
        tool_version = __import__("version", fromlist=["VERSION"]).VERSION
    except (ImportError, AttributeError):
        tool_version = "unknown"
    count = 0
    for sid, state in sorted((getattr(state_mgr, "states", None) or {}).items()):
        land_provs = [int(p) for p in (getattr(state, "provinces", []) or []) if int(p) in land_id_set]
        if not land_provs:
            continue
        raw_name = (getattr(state, "name_en", "") or "").strip() or "STATE_%d" % int(sid)
        safe_name = "".join(c if (c.isalnum() or c in "_-") else "_" for c in raw_name)
        category = normalize_state_category(getattr(state, "category", "rural"))
        owner = (getattr(state, "owner_tag", "") or "").strip()
        # Foundation is geography-only.  Ownership belongs to acceptance or
        # scaffold content and must not leak into the foundation artifact.
        if omit_owners:
            placeholders.append({"state": int(sid), "field": "owner",
                                 "note": "owner omitted by the foundation profile; assign during content development",
                                 "profile": profile_name})
            owner = ""
        elif not owner:
            placeholders.append({"state": int(sid), "field": "owner",
                                 "note": "owner unset; assign during content development",
                                 "profile": profile_name})
        placeholders.append({"state": int(sid), "field": "resources/buildings/manpower/victory_points",
                             "note": "omitted by the %s profile" % profile_name,
                             "profile": profile_name})
        with open(os.path.join(states_dir, "%d-%s.txt" % (int(sid), safe_name)),
                  "w", encoding="utf-8") as handle:
            handle.write("# geography state shell generated by hoi4-map-maker %s (%s profile)\n"
                         % (tool_version, profile_name))
            handle.write("# non-geographic placeholders are listed in foundation_manifest.json\n")
            handle.write("state = {\n")
            handle.write("\tid = %d\n" % int(sid))
            handle.write('\tname = "STATE_WT_%d"\n' % int(sid))
            handle.write("\tstate_category = %s\n" % category)
            if bool(getattr(state, "impassable", False)):
                handle.write("\timpassable = yes\n")
            handle.write("\n\thistory = {\n")
            if owner:
                handle.write("\t\towner = %s\n" % owner)
                handle.write("\t\tadd_core_of = %s\n" % owner)
            else:
                handle.write("\t\t# owner_omitted: assign during content development\n")
            handle.write("\t}\n")
            handle.write("\n\tprovinces = {\n")
            for pid in sorted(land_provs):
                handle.write("\t\t%d\n" % pid)
            handle.write("\t}\n}\n")
        count += 1
    return count
