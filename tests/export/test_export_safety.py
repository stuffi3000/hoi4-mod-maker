"""Regression tests for map data that can make HOI4 fail during startup."""

from __future__ import annotations

import numpy as np

from data.constants import REPLACE_PATHS, TILE_LAKE, TILE_LAND, TILE_SEA
from domain.managers.state import StateData, StateManager
from domain.validators.province import (
    build_coastal_land_to_sea,
    get_coastal_provinces,
)
from export.mod_exporter import (
    _compute_coastal_once,
    _compute_coastal_province_level,
    _repair_too_large_provinces,
)
from export.writers.common.countries import (
    write_country_characters,
    write_dynamic_countries,
    write_neutral_country_histories,
)
from export.writers.history.states import write_states_from_mgr
from export.writers.map.buildings import write_buildings
from export.writers.map.descriptor import write_descriptor
from export.writers.replace_path.scrubber import (
    write_ai_strategy_overrides,
    write_replace_path_dirs,
)


def _seam_map() -> tuple[np.ndarray, np.ndarray]:
    """Land at the right edge touches sea at the wrapped left edge."""
    tile_map = np.array(
        [[TILE_SEA, TILE_LAND], [TILE_SEA, TILE_LAND]], dtype=np.uint8
    )
    province_map = np.array([[2, 1], [2, 1]], dtype=np.int32)
    return tile_map, province_map


def test_coastal_calculations_include_the_horizontal_map_seam():
    tile_map, province_map = _seam_map()

    coastal, land_to_sea = _compute_coastal_once(province_map, [1], [2])

    assert coastal == {1}
    assert land_to_sea == {1: 2}
    assert _compute_coastal_province_level(province_map, [1], [2]) == {1}
    assert get_coastal_provinces(tile_map, province_map) == {1}
    assert build_coastal_land_to_sea(tile_map, province_map) == {1: 2}


def test_state_writer_normalises_categories_and_moves_invalid_naval_base(tmp_path):
    _tile_map, province_map = _seam_map()
    state_mgr = StateManager()
    state = StateData(
        id=1,
        name="Safety Test",
        provinces=[1, 2],
        category="small",
        # Province 1 is inland; province 2 is the only coastal province.
        province_buildings={1: {"naval_base": 1}},
    )
    state_mgr.states[1] = state

    write_states_from_mgr(
        state_mgr,
        country_mgr=None,
        province_map=province_map,
        output_dir=str(tmp_path),
        land_id_set={1, 2},
        coastal_set={2},
    )

    text = (tmp_path / "history" / "states" / "1-STATE_1.txt").read_text(
        encoding="utf-8"
    )
    assert "state_category = rural" in text
    assert "\t\t\t1 = {\n\t\t\t\tnaval_base" not in text
    assert "\t\t\t2 = {\n\t\t\t\tnaval_base" in text


def test_state_writer_clamps_coastal_buildings_to_category_slots(tmp_path):
    """A coastal pastoral state must not receive both a factory and dockyard."""
    tile_map, province_map = _seam_map()
    state_mgr = StateManager()
    state_mgr.states[1] = StateData(
        id=1,
        name="Pastoral Coast",
        provinces=[1],
        category="pastoral",
    )

    write_states_from_mgr(
        state_mgr,
        country_mgr=None,
        province_map=province_map,
        output_dir=str(tmp_path),
        land_id_set={1},
        coastal_set={1},
    )

    text = (tmp_path / "history" / "states" / "1-STATE_1.txt").read_text(
        encoding="utf-8"
    )
    assert "\t\t\tindustrial_complex = 1" in text
    assert "\t\t\tdockyard =" not in text


def test_export_repairs_exact_province_bbox_boundary():
    """Trim an edge pixel when a province reaches the engine's 1/8 limit."""
    province_map = np.zeros((64, 64), dtype=np.int32)
    province_map[9, 23] = 1
    province_map[10, 23] = 3
    province_map[11:17, 20:27] = 3
    province_map[17, 23] = 3
    province_map[18, 23] = 2

    tile_map = np.full_like(province_map, TILE_SEA, dtype=np.uint8)
    tile_map[province_map == 1] = TILE_LAND
    tile_map[province_map == 2] = TILE_LAND
    tile_map[province_map == 3] = TILE_LAKE

    changed = _repair_too_large_provinces(province_map, tile_map)

    assert changed == [3]
    ys, xs = np.where(province_map == 3)
    assert (ys.max() - ys.min() + 1) == 7
    assert (xs.max() - xs.min() + 1) == 7


def test_buildings_writer_places_a_seam_port_on_a_land_pixel(tmp_path):
    tile_map, province_map = _seam_map()

    write_buildings(
        {1: [1]},
        province_map,
        tile_map,
        str(tmp_path),
        land_to_sea={1: 2},
    )

    lines = (tmp_path / "map" / "buildings.txt").read_text(encoding="utf-8").splitlines()
    assert "1;naval_base_spawn;1.50;11.00;1.50;0.00;2" in lines


def test_replace_path_cleanup_removes_only_legacy_generated_overlays(tmp_path):
    generated = tmp_path / "common" / "on_actions" / "15_mun_on_actions.txt"
    generated.parent.mkdir(parents=True)
    generated.write_text("# Empty - TC MOD override\non_actions = { }\n", encoding="utf-8")
    custom = generated.parent / "my_custom_action.txt"
    custom.write_text("on_actions = { }\n", encoding="utf-8")

    write_replace_path_dirs(str(tmp_path))

    assert not generated.exists()
    assert custom.exists()


def test_replace_paths_are_declared_and_created(tmp_path):
    write_replace_path_dirs(str(tmp_path))

    for relative_path in REPLACE_PATHS:
        assert (tmp_path / relative_path).is_dir()

    mod_root = tmp_path / "fantasy"
    mod_root.mkdir()
    write_descriptor("Fantasy", str(mod_root))
    for descriptor in (mod_root / "descriptor.mod", tmp_path / "fantasy.mod"):
        descriptor_text = descriptor.read_text(encoding="utf-8")
        for relative_path in REPLACE_PATHS:
            assert f'replace_path="{relative_path}"' in descriptor_text


def test_ai_strategy_overrides_shadow_map_incompatible_vanilla_files(tmp_path):
    write_ai_strategy_overrides(str(tmp_path))

    hol = tmp_path / "common" / "ai_strategy" / "HOL.txt"
    sov = tmp_path / "common" / "ai_strategy" / "SOV.txt"
    assert hol.read_text(encoding="utf-8").startswith("# Empty - TC MOD")
    assert sov.read_text(encoding="utf-8").startswith("# Empty - TC MOD")

    theaters = tmp_path / "common" / "ai_faction_theaters" / "ai_faction_theaters.txt"
    theater_text = theaters.read_text(encoding="utf-8")
    assert theater_text.startswith("# Empty - TC MOD")
    assert "regions = { 1 }" in theater_text

    tutorial = tmp_path / "tutorial" / "tutorial.txt"
    tutorial_text = tutorial.read_text(encoding="utf-8")
    assert tutorial_text.startswith("# Empty - TC MOD")
    assert tutorial_text.rstrip().endswith("tutorial = { }")

    on_actions = tmp_path / "common" / "on_actions" / "14_sea_on_actions.txt"
    on_actions_text = on_actions.read_text(encoding="utf-8")
    assert on_actions_text.startswith("# Empty - TC MOD")
    assert on_actions_text.rstrip().endswith("on_actions = { }")

    decisions = tmp_path / "common" / "decisions" / "ENG.txt"
    assert decisions.read_text(encoding="utf-8").startswith("# Empty - TC MOD")
    formables = tmp_path / "common" / "decisions" / "formable_nation_decisions.txt"
    assert formables.read_text(encoding="utf-8").startswith("# Empty - TC MOD")

    decision_stubs = tmp_path / "common" / "decisions" / "zz_tc_map_safety.txt"
    decision_stub_text = decision_stubs.read_text(encoding="utf-8")
    assert "ENG_abdication_crisis = {" in decision_stub_text
    assert "PRC_infiltrate_liaoning = {" in decision_stub_text
    assert "CHI_holding_state_mission = {" in decision_stub_text
    assert "visible = { always = no }" in decision_stub_text

    for relative_path in (
        "common/decisions/CHI_decisions.txt",
        "common/decisions/FRA.txt",
        "common/decisions/PRC.txt",
        "events/NewsEvents.txt",
        "events/SEA_Japan.txt",
    ):
        shadow_text = (tmp_path / relative_path).read_text(encoding="utf-8")
        assert shadow_text.startswith("# Empty - TC MOD")

    sea_japan_text = (tmp_path / "events" / "SEA_Japan.txt").read_text(
        encoding="utf-8"
    )
    assert "id = SEA_border_incidents_events.5" in sea_japan_text
    assert "title = generic.1.t" in sea_japan_text

    patch = tmp_path / "common" / "scripted_triggers" / "zz_tc_map_safety.txt"
    patch_text = patch.read_text(encoding="utf-8")
    assert "is_controlled_by_ROOT_or_subject = { always = no }" in patch_text
    assert "FRA_controls_north_africa = { always = no }" in patch_text
    assert "has_anyone_else_claimed_ROM = { always = no }" in patch_text


def test_localisation_uses_english_replace_and_cleans_legacy_root(tmp_path):
    from export.writers.localisation.yml import write_localisation_full

    legacy = tmp_path / "localisation" / "zz_TestMod_states_l_english.yml"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("l_english:\n VICTORY_POINTS_1068:0 \"old\"\n", encoding="utf-8")

    state_mgr = StateManager()
    state = state_mgr.create_state()
    state.name = "Custom State"
    state.victory_points = {1068: 10}

    write_localisation_full("TestMod", state_mgr, None, [state.id], str(tmp_path))

    generated = (
        tmp_path
        / "localisation"
        / "english"
        / "replace"
        / "zz_TestMod_states_l_english.yml"
    )
    assert generated.exists()
    assert 'VICTORY_POINTS_1068:0 "Custom State"' in generated.read_text(
        encoding="utf-8-sig"
    )
    assert not legacy.exists()


def test_neutral_histories_cover_visible_vanilla_tags_without_shadowing_exported(
    tmp_path, monkeypatch
):
    import export.writers.common.countries as countries_writer

    monkeypatch.setattr(
        countries_writer,
        "get_vanilla_tags",
        lambda: frozenset({"BEL", "SOV", "D01", "TST"}),
    )
    history_dir = tmp_path / "history" / "countries"
    history_dir.mkdir(parents=True)
    (history_dir / "BEL.txt").write_text("# project history\n", encoding="utf-8")

    generated = write_neutral_country_histories(
        str(tmp_path), exported_tags={"BEL", "TST"}, capital_state_id=7
    )

    assert generated == ["SOV"]
    text = (history_dir / "SOV.txt").read_text(encoding="utf-8")
    assert "capital = 7" in text
    assert "neutrality = 100" in text
    assert not (history_dir / "D01.txt").exists()
    assert (history_dir / "BEL.txt").read_text(encoding="utf-8") == "# project history\n"


def test_generated_characters_do_not_shadow_vanilla_tag_files(tmp_path):
    legacy = tmp_path / "common" / "characters" / "BEL.txt"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        "characters = { BEL_leader_despotism = { "
        "portraits = { civilian = { large = GFX_Portrait_Europe_Generic_1 } } } }\n",
        encoding="utf-8",
    )

    write_country_characters("BEL", str(tmp_path))

    assert not legacy.exists()
    generated = tmp_path / "common" / "characters" / "zz_fantasy_BEL.txt"
    assert generated.exists()
    generated_text = generated.read_text(encoding="utf-8")
    assert generated_text.startswith(
        "# Generated - TC MOD character definitions"
    )
    assert "specialization_industry" not in generated_text
    assert "specialization_army" not in generated_text
    for specialization in ("air", "land", "naval", "nuclear"):
        assert f"specialization_{specialization} = 2" in generated_text


def test_dynamic_country_pool_writes_independent_tags_and_files(tmp_path):
    write_dynamic_countries(str(tmp_path), count=3)

    tags_text = (
        tmp_path / "common" / "country_tags" / "zz_dynamic_countries.txt"
    ).read_text(encoding="utf-8")
    assert "dynamic_tags = yes" in tags_text
    for index in range(1, 4):
        tag = f"D{index:02d}"
        assert f'{tag} = "countries/{tag}.txt"' in tags_text
        country_text = (
            tmp_path / "common" / "countries" / f"{tag}.txt"
        ).read_text(encoding="utf-8")
        assert "use_legacy_ai_pp_spend = yes" in country_text
        assert country_text.count("color = {") == 1
