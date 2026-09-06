"""Create only the complete replace_path directories an export owns.

``replace_path`` is directory-wide.  Creating placeholders for engine systems
such as decisions, on_actions, AI, or unit-name groups silently removes their
vanilla definitions and is less safe than retaining the vanilla content.  This
module therefore limits itself to generated map/history directories and clears
the known legacy overlays from an existing exporter output folder.
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
