"""Prepare owned replace-path directories and narrow compatibility shadows.

``replace_path`` is directory-wide.  Creating placeholders for engine systems
such as decisions, on_actions, AI, or unit-name groups silently removes their
vanilla definitions.  The exporter therefore keeps those directories
additive and shadows only the exact vanilla files whose fixed map references
would otherwise run during a custom-map session.
"""

from __future__ import annotations

import os

from data.constants import REPLACE_PATHS


# Older exporter versions wrote these files to neutralise vanilla systems.
# They are safe to remove only when they carry the identifying generated-file
# markers below; a user-authored file at the same path is left untouched.
_LEGACY_FILES = (
    "common/achievements.txt",
    "common/ai_equipment/00_placeholder.txt",
    "common/ai_focuses/00_placeholder.txt",
    "common/ai_peace/00_placeholder.txt",
    "common/ai_strategy/00_placeholder.txt",
    "common/ai_strategy_plans/00_placeholder.txt",
    "common/ai_templates/00_generic_templates.txt",
    "common/ai_navy/fleet/00_placeholder.txt",
    "common/ai_navy/goals/goals_generic.txt",
    "common/ai_navy/taskforce/00_placeholder.txt",
    "common/decisions/00_placeholder.txt",
    "common/on_actions/00_placeholder_on_actions.txt",
    "common/on_actions/00_on_actions.txt",
    "common/on_actions/00_testing_on_actions.txt",
    "common/on_actions/01_tfv_on_actions.txt",
    "common/on_actions/02_dod_on_actions.txt",
    "common/on_actions/03_wtt_on_actions.txt",
    "common/on_actions/04_mtg_on_actions.txt",
    "common/on_actions/05_lar_on_actions.txt",
    "common/on_actions/06_bftb_on_actions.txt",
    "common/on_actions/07_nsb_on_actions.txt",
    "common/on_actions/08_bba_on_actions.txt",
    "common/on_actions/09_aat_on_actions.txt",
    "common/on_actions/10_toa_on_actions.txt",
    "common/on_actions/12_wuw_on_actions.txt",
    "common/on_actions/13_goe_on_actions.txt",
    "common/on_actions/14_sea_on_actions.txt",
    "common/raids/00_placeholder.txt",
    "common/strategic_locations/00_placeholder.txt",
    "common/units/names/00_generic_fallback.txt",
    "common/units/names_divisions/00_generic_fallback.txt",
    "common/units/names_ships/00_generic_fallback.txt",
    "common/units/names_railway_guns/00_generic_fallback.txt",
    "common/units/codenames_operatives/00_generic_fallback.txt",
    "events/GOE_Raj.txt",
    "events/NewsEvents.txt",
    "events/SEA_Japan.txt",
    "history/general/00_placeholder.txt",
    "history/general/00_exporter_placeholder.txt",
    "tutorial/tutorial.txt",
)

_GENERATED_MARKERS = (
    "# Empty — TC MOD",
    "# Empty - TC MOD",
    "# Empty — no vanilla generic files",
    "# Placeholder — vanilla",
    "# Emptied — TC MOD",
    "# Generic AI templates —",
    "# Self-built generic naval goals",
    "tutorial = { }",
)

_LEGACY_GENERATED_DIRS = (
    "common/on_actions",
    "common/ai_equipment",
    "common/ai_focuses",
    "common/ai_peace",
    "common/ai_strategy",
    "common/ai_strategy_plans",
    "common/ai_templates",
    "common/ai_navy",
    "common/units",
    "common/decisions",
    "common/raids",
    "events",
)

# These country-specific vanilla strategy files target states and ideas that
# do not exist in an exported map.  A file at the same relative path in the
# mod shadows the vanilla file without replacing the whole AI-strategy
# directory (which would also remove safe generic strategies).
_AI_STRATEGY_OVERRIDES = {
    # These files contain hard-coded vanilla state/strategic-region IDs.
    # SOV additionally checks ideas that are absent from the exported set.
    "common/ai_strategy/ENG.txt": (
        "# Empty - TC MOD: vanilla ENG strategy targets states/regions outside the exported map.\n"
    ),
    "common/ai_strategy/ETH.txt": (
        "# Empty - TC MOD: vanilla ETH strategy targets states/regions outside the exported map.\n"
    ),
    "common/ai_strategy/FRA.txt": (
        "# Empty - TC MOD: vanilla FRA strategy targets states/regions outside the exported map.\n"
    ),
    "common/ai_strategy/GER.txt": (
        "# Empty - TC MOD: vanilla GER strategy targets states/regions outside the exported map.\n"
    ),
    "common/ai_strategy/HOL.txt": (
        "# Empty - TC MOD: vanilla HOL strategy targets states outside the exported map.\n"
    ),
    "common/ai_strategy/ITA.txt": (
        "# Empty - TC MOD: vanilla ITA strategy targets states/regions outside the exported map.\n"
    ),
    "common/ai_strategy/JAP.txt": (
        "# Empty - TC MOD: vanilla JAP strategy targets states outside the exported map.\n"
    ),
    "common/ai_strategy/ROM.txt": (
        "# Empty - TC MOD: vanilla ROM strategy targets states outside the exported map.\n"
    ),
    "common/ai_strategy/SOV.txt": (
        "# Empty - TC MOD: vanilla SOV strategy references ideas not shipped by the mod.\n"
    ),
    "common/ai_strategy/USA.txt": (
        "# Empty - TC MOD: vanilla USA strategy targets states outside the exported map.\n"
    ),
}

# These vanilla decision files are evaluated continuously for countries
# that still exist in an additive country-tag database.  Their availability
# checks use fixed vanilla state IDs (Maryland and Haiti) and therefore emit a
# tight invalid-state loop on a compact exported map.  Shadowing the exact
# files preserves the rest of the vanilla decision database without a
# directory-wide replace_path.
_DECISION_OVERRIDES = {
    "common/decisions/ENG.txt": (
        "# Empty - TC MOD: vanilla ENG decisions target states absent from the exported map.\n"
    ),
    "common/decisions/CHL.txt": (
        "# Empty - TC MOD: vanilla CHL decisions target states absent from the exported map.\n"
    ),
    "common/decisions/formable_nation_decisions.txt": (
        "# Empty - TC MOD: vanilla formable decisions target states absent from the exported map.\n"
    ),
    "common/decisions/TOA_formable_nation_decisions.txt": (
        "# Empty - TC MOD: vanilla TOA formable decisions target states absent from the exported map.\n"
    ),
}

_AI_FACTION_THEATER_OVERRIDE = (
    "# Empty - TC MOD: vanilla theaters target strategic regions that are not in the exported map.\n"
    "# Keep one inert definition so the database remains non-empty without invalid region IDs.\n"
    "exported_map = {\n"
    "\tname = theater_exported_map\n"
    "\tregions = { 1 }\n"
    "\tcancel = { has_war = no }\n"
    "\tai_will_do = { base = 0 }\n"
    "}\n"
)

_TUTORIAL_OVERRIDE = (
    "# Empty - TC MOD: vanilla tutorial targets states and provinces absent from the exported map.\n"
    "tutorial = { }\n"
)

_ON_ACTION_FILE_NAMES = (
    "00_on_actions.txt",
    "00_testing_on_actions.txt",
    "01_tfv_on_actions.txt",
    "02_dod_on_actions.txt",
    "03_wtt_on_actions.txt",
    "04_mtg_on_actions.txt",
    "05_lar_on_actions.txt",
    "06_bftb_on_actions.txt",
    "07_nsb_on_actions.txt",
    "08_bba_on_actions.txt",
    "09_aat_on_actions.txt",
    "10_toa_on_actions.txt",
    "12_wuw_on_actions.txt",
    "13_goe_on_actions.txt",
    "14_sea_on_actions.txt",
    "15_mun_on_actions.txt",
    "16_taog_on_actions.txt",
)


def _is_legacy_generated_file(path: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as file:
            head = file.read(512)
    except OSError:
        return False
    return any(marker in head for marker in _GENERATED_MARKERS)


def _remove_legacy_overlays(output_dir: str) -> None:
    """Remove stale exporter-owned overlays without deleting user files."""
    for relative_path in _LEGACY_FILES:
        path = os.path.join(output_dir, *relative_path.split("/"))
        if os.path.isfile(path) and _is_legacy_generated_file(path):
            os.remove(path)

    # New game versions occasionally add another on_actions filename.  Scan
    # the relevant legacy directories too, but still require a generated-file
    # marker before touching anything.
    for relative_dir in _LEGACY_GENERATED_DIRS:
        directory = os.path.join(output_dir, *relative_dir.split("/"))
        if not os.path.isdir(directory):
            continue
        for root, _dirs, filenames in os.walk(directory):
            for filename in filenames:
                path = os.path.join(root, filename)
                if _is_legacy_generated_file(path):
                    os.remove(path)


def write_replace_path_dirs(output_dir: str) -> None:
    """Prepare the generated directories listed in :data:`REPLACE_PATHS`."""
    _remove_legacy_overlays(output_dir)

    for relative_path in REPLACE_PATHS:
        os.makedirs(os.path.join(output_dir, *relative_path.split("/")), exist_ok=True)


def write_ai_strategy_overrides(output_dir: str) -> None:
    """Shadow vanilla strategies that reference unavailable map databases.

    The exporter intentionally does not add ``common/ai_strategy`` to
    ``REPLACE_PATHS``.  Directory replacement would discard the remaining
    vanilla generic strategies, while these country files are known to
    reference removed state/region/idea IDs during map startup.
    """
    for relative_path, content in _AI_STRATEGY_OVERRIDES.items():
        path = os.path.join(output_dir, *relative_path.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            file.write(content)

    for relative_path, content in _DECISION_OVERRIDES.items():
        path = os.path.join(output_dir, *relative_path.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            file.write(content)

    # The vanilla faction-theater database is a single file.  Its region IDs
    # are tied to the 48-region vanilla map and are rejected by a compact
    # exported map.  Shadow that file at the same path with one inert theater
    # instead of replacing the whole ``common`` tree or adding another
    # replace_path entry.
    theater_path = os.path.join(
        output_dir, "common", "ai_faction_theaters", "ai_faction_theaters.txt"
    )
    os.makedirs(os.path.dirname(theater_path), exist_ok=True)
    with open(theater_path, "w", encoding="utf-8") as file:
        file.write(_AI_FACTION_THEATER_OVERRIDE)

    # The vanilla tutorial is loaded during every new-session setup even when
    # the tutorial UI is not opened.  Its hard-coded state/province IDs are
    # invalid for a custom map and can be dereferenced during map entry.
    tutorial_path = os.path.join(output_dir, "tutorial", "tutorial.txt")
    os.makedirs(os.path.dirname(tutorial_path), exist_ok=True)
    with open(tutorial_path, "w", encoding="utf-8") as file:
        file.write(_TUTORIAL_OVERRIDE)

    # Vanilla on_actions contain hard-coded state/province/character targets
    # (for example, 14_sea_on_actions and 16_taog_on_actions).  They run as
    # soon as a new session starts and repeatedly dereference objects that a
    # custom map does not have.  Shadow each shipped file at its exact path;
    # this keeps the directory additive and avoids another replace_path entry.
    on_actions_dir = os.path.join(output_dir, "common", "on_actions")
    os.makedirs(on_actions_dir, exist_ok=True)
    for filename in _ON_ACTION_FILE_NAMES:
        path = os.path.join(on_actions_dir, filename)
        with open(path, "w", encoding="utf-8") as file:
            file.write(
                "# Empty - TC MOD: vanilla on_actions target objects absent from the exported map.\n"
                "on_actions = { }\n"
            )
