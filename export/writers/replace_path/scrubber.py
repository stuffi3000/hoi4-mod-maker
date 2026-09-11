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
    "common/scripted_triggers/00_scripted_triggers.txt",
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
    "common/scripted_triggers",
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
    # These country databases are evaluated every day even when the country
    # is neutral.  Their target lists include fixed vanilla state IDs (for
    # example 330 and the China warlord states), so leaving the files additive
    # produces invalid-state and invalid-event-target spam in a compact map.
    "common/decisions/CHI_decisions.txt": (
        "# Empty - TC MOD: vanilla CHI decisions target states and event targets absent from the exported map.\n"
    ),
    "common/decisions/FRA.txt": (
        "# Empty - TC MOD: vanilla FRA decisions target states absent from the exported map.\n"
    ),
    "common/decisions/PRC.txt": (
        "# Empty - TC MOD: vanilla PRC decisions use event targets that are not initialized in the exported map.\n"
    ),
}

# The country/formable decision files above are intentionally shadowed, but
# vanilla focus trees still contain references to some of their IDs.  Keep
# those references valid with invisible, never-available decisions.  This is
# preferable to restoring the original definitions (which would immediately
# evaluate their vanilla state IDs on a custom map).
_DECISION_STUB_IDS = (
    "ENG_the_mosley_plan",
    "ENG_abdication_crisis",
    "ENG_imperial_conference_decision",
    "ENG_propaganda_campaigns_in_canada",
    "ENG_trade_unions_demand_conscription_limitations_mission",
    "ENG_trade_unions_demand_construction_safety_legislation_mission",
    "ENG_trade_unions_demand_increase_in_paid_leave_mission",
    "ENG_trade_unions_demand_legislation_amendment_mission",
    "ENG_trade_unions_demand_mandatory_union_days_mission",
    "ENG_trade_unions_demand_minimum_pay_increase_mission",
    "ENG_trade_unions_demand_minister_appointment_mission",
    "ENG_trade_unions_demand_workplace_safety_legislation_mission",
    "CHL_anti_fascist_coalition_forming",
    "CHL_expand_the_carabineros",
    "CHL_ibanez_ruling_by_decree_mission",
    "CHL_integrate_quebec",
    "CHL_integrate_rio_grande_do_sul",
    "CHL_integrate_the_kingdom_of_mexico",
    "CHL_nacista_coup_attempt",
    "CHL_nacistas_gathering_support_mission",
    "CHI_60_divisions_plan",
    "CHI_bog_them_down",
    "CHI_breach_the_yellow_river",
    "CHI_build_a_carrier",
    "CHI_burma_campaign_mission",
    "CHI_declare_war_zone",
    "CHI_demonstrate_our_resolve_decision",
    "CHI_expand_the_burma_road",
    "CHI_flying_tigers",
    "CHI_forced_loans",
    "CHI_free_indochina_tsr",
    "CHI_growing_impatience",
    "CHI_growing_impatience_dummy",
    "CHI_indo_chinese_campaign_mission",
    "CHI_invest_in_officer_training",
    "CHI_kwantung_army_impatience_dummy",
    "CHI_overlordship_over_indochina",
    "CHI_overlordship_over_indochina_tsr",
    "CHI_release_korea",
    "CHI_scorched_earth_tactics",
    "CHI_soviet_volunteer_group",
    "CHI_holding_state_mission",
    "FRA_case_anton_mission",
    "FRA_invasion_in_central_africa",
    "FRA_invasion_in_indochina",
    "FRA_invasion_in_syria",
    "FRA_invasion_in_west_africa",
    "FRA_order_bombers_in_USA",
    "FRA_order_fighters_in_USA",
    "FRA_prepare_coup_in_central_africa",
    "FRA_prepare_coup_in_indochina",
    "FRA_prepare_coup_in_madagascar",
    "FRA_prepare_coup_in_north_africa",
    "FRA_prepare_coup_in_syria",
    "FRA_prepare_coup_in_west_africa",
    "FRA_promise_independence_to_central_africa",
    "FRA_promise_independence_to_indochina",
    "FRA_promise_independence_to_madagascar",
    "FRA_promise_independence_to_north_africa",
    "FRA_promise_independence_to_syria",
    "FRA_promise_independence_to_west_africa",
    "FRA_rally_the_leagues",
    "FRA_reorganize_aviation_industry_center",
    "FRA_reorganize_aviation_industry_north",
    "FRA_reorganize_aviation_industry_south_east",
    "FRA_reorganize_aviation_industry_south_west",
    "FRA_reorganize_aviation_industry_west",
    "FRA_unleash_la_cagoule",
    "NZL_demand_islands",
    "PRC_initialize_five_year_plan_mission",
    "PRC_initialize_shorter_market_plans_mission",
    "PRC_launch_100_regiments_campaign",
    "PRC_provoke_japan",
    "PRC_rural_surveys",
    "PRC_the_eastward_expedition_decision",
    "PRC_the_peoples_doubt",
    "PRC_the_westward_expedition_decision",
    "PRC_usurp_control_over_yanan_decision",
    "PRC_infiltrate_gansu",
    "PRC_infiltrate_shandong",
    "PRC_infiltrate_jiangsu",
    "PRC_infiltrate_henan",
    "PRC_infiltrate_beijing",
    "PRC_infiltrate_hebei",
    "PRC_infiltrate_shanxi",
    "PRC_infiltrate_suiyuan",
    "PRC_infiltrate_xian",
    "PRC_infiltrate_ordos",
    "PRC_infiltrate_east_hebei",
    "PRC_infiltrate_jehol",
    "PRC_infiltrate_south_chahar",
    "PRC_infiltrate_chahar",
    "PRC_infiltrate_heilungkiang",
    "PRC_infiltrate_liaoning",
    "byz_restore_byzantium",
    "form_baltic_federation",
    "form_commonwealth",
    "form_east_africa",
    "form_european_union",
    "form_greater_greece",
    "form_greater_proletarian_state",
    "form_hre",
    "form_nordic_league",
    "form_roman_empire",
    "form_the_horn_of_africa",
)


def _decision_stub_text() -> str:
    """Return deterministic invisible decision definitions for missing IDs."""
    lines = [
        "# TC MOD compatibility: IDs referenced by shadowed vanilla content.",
        "# They remain valid but can never be shown, activated, or timed.",
        "political_actions = {",
    ]
    for decision_id in sorted(set(_DECISION_STUB_IDS)):
        lines.extend(
            [
                f"\t{decision_id} = {{",
                "\t\tallowed = { always = no }",
                "\t\tvisible = { always = no }",
                "\t\tavailable = { always = no }",
                "\t\tai_will_do = { base = 0 }",
                "\t\tdays_mission_timeout = 1",
                "\t}",
            ]
        )
    lines.append("}")
    return "\n".join(lines) + "\n"

# Scripted triggers are shared by focuses, decisions, and news events.  The
# shipped files are all-or-nothing databases, so replacing a country file
# wholesale would turn every other trigger in that file into an unknown
# trigger.  Define safe, duplicate-name overrides in a late ``zz_`` file
# instead; the game loads it after the vanilla files and uses these inert
# definitions when a custom-map session evaluates them.
_SCRIPTED_TRIGGER_PATCH = (
    "# TC MOD compatibility: vanilla predicates below target states/event\n"
    "# targets that are not initialized in the exported map.\n"
    "is_controlled_by_ROOT_or_subject = { always = no }\n"
    "is_not_controlled_by_ROOT_or_subject = { always = yes }\n"
    "is_controlled_by_ROOT_or_ally = { always = no }\n"
    "is_not_controlled_by_ROOT_or_ally = { always = yes }\n"
    "state_is_fully_controlled_by_ROOT_subject_or_faction_member = { always = no }\n"
    "FRA_controls_north_africa = { always = no }\n"
    "FRA_controls_syria = { always = no }\n"
    "FRA_controls_indochina = { always = no }\n"
    "FRA_controls_west_africa = { always = no }\n"
    "FRA_controls_central_africa = { always = no }\n"
    "FRA_has_inefficient_economy = { always = no }\n"
    "FRA_has_worker_shortage = { always = no }\n"
    "is_owned_or_subject_trigger = { always = no }\n"
    "USA_can_sell_weapons_trigger = { always = no }\n"
    "has_any_occupation_cost_trigger = { always = no }\n"
    "is_vichy_france = { always = no }\n"
    "is_available_fighter_ROM = { always = no }\n"
    "is_available_heavy_fighter_ROM = { always = no }\n"
    "is_available_cas_ROM = { always = no }\n"
    "is_available_tac_ROM = { always = no }\n"
    "has_anyone_else_claimed_ROM = { always = no }\n"
)

# News events are global and can evaluate their map targets for every country,
# even when no country-specific focus is active.  Their hard-coded Singapore,
# Hong Kong, New Delhi, and Rangoon states are not present in the export.
_EVENT_OVERRIDES = {
    "events/NewsEvents.txt": (
        "# Empty - TC MOD: vanilla news events target provinces/states absent from the exported map.\n"
    ),
    "events/SEA_Japan.txt": (
        "# Empty - TC MOD: vanilla SEA news events target provinces/states absent from the exported map.\n"
        "# Keep the callback IDs used by vanilla JAP border-incident decisions.\n"
        "add_namespace = SEA_border_incidents_events\n"
        "country_event = {\n"
        "\tid = SEA_border_incidents_events.1\n"
        "\ttitle = generic.1.t\n"
        "\tdesc = generic.1.d_neutral_good\n"
        "\tis_triggered_only = yes\n"
        "\toption = { name = OK }\n"
        "}\n"
        "country_event = {\n"
        "\tid = SEA_border_incidents_events.2\n"
        "\ttitle = generic.1.t\n"
        "\tdesc = generic.1.d_neutral_good\n"
        "\tis_triggered_only = yes\n"
        "\toption = { name = OK }\n"
        "}\n"
        "country_event = {\n"
        "\tid = SEA_border_incidents_events.3\n"
        "\ttitle = generic.1.t\n"
        "\tdesc = generic.1.d_neutral_good\n"
        "\tis_triggered_only = yes\n"
        "\toption = { name = OK }\n"
        "}\n"
        "country_event = {\n"
        "\tid = SEA_border_incidents_events.4\n"
        "\ttitle = generic.1.t\n"
        "\tdesc = generic.1.d_neutral_good\n"
        "\tis_triggered_only = yes\n"
        "\toption = { name = OK }\n"
        "}\n"
        "country_event = {\n"
        "\tid = SEA_border_incidents_events.5\n"
        "\ttitle = generic.1.t\n"
        "\tdesc = generic.1.d_neutral_good\n"
        "\tis_triggered_only = yes\n"
        "\toption = { name = OK }\n"
        "}\n"
        "country_event = {\n"
        "\tid = SEA_border_incidents_events.6\n"
        "\ttitle = generic.1.t\n"
        "\tdesc = generic.1.d_neutral_good\n"
        "\tis_triggered_only = yes\n"
        "\toption = { name = OK }\n"
        "}\n"
        "country_event = {\n"
        "\tid = SEA_border_incidents_events.7\n"
        "\ttitle = generic.1.t\n"
        "\tdesc = generic.1.d_neutral_good\n"
        "\tis_triggered_only = yes\n"
        "\toption = { name = OK }\n"
        "}\n"
        "country_event = {\n"
        "\tid = SEA_border_incidents_events.8\n"
        "\ttitle = generic.1.t\n"
        "\tdesc = generic.1.d_neutral_good\n"
        "\tis_triggered_only = yes\n"
        "\toption = { name = OK }\n"
        "}\n"
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

    decision_stub_path = os.path.join(
        output_dir, "common", "decisions", "zz_tc_map_safety.txt"
    )
    os.makedirs(os.path.dirname(decision_stub_path), exist_ok=True)
    with open(decision_stub_path, "w", encoding="utf-8") as file:
        file.write(_decision_stub_text())

    for relative_path, content in _EVENT_OVERRIDES.items():
        path = os.path.join(output_dir, *relative_path.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            file.write(content)

    scripted_trigger_patch_path = os.path.join(
        output_dir, "common", "scripted_triggers", "zz_tc_map_safety.txt"
    )
    os.makedirs(os.path.dirname(scripted_trigger_patch_path), exist_ok=True)
    with open(scripted_trigger_patch_path, "w", encoding="utf-8") as file:
        file.write(_SCRIPTED_TRIGGER_PATCH)

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
