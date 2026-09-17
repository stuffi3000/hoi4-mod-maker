"""M1.1 GameTarget tests with fake installs (no real HOI4 required)."""
from __future__ import annotations

import json
import os

import pytest

import services.game_assets as ga
from services.game_assets import (
    GameAssets,
    GameTarget,
    check_required_files,
    descriptor_version_for_raw,
    normalize_install_dir,
    profile_id_for_raw,
    resolve_game_target,
    target_install_dir,
    target_supported_version,
)

pytestmark = pytest.mark.unit


def _make_fake_install(root, raw_version="1.19.3.0", with_checksum=False):
    game = os.path.join(str(root), "game")
    terrain_dir = os.path.join(game, "common", "terrain")
    os.makedirs(terrain_dir, exist_ok=True)
    with open(os.path.join(terrain_dir, "00_terrain.txt"), "w", encoding="utf-8") as handle:
        handle.write("terrain = { t = { type = plains color = { 0 } texture = 1 } }")
    settings = {"rawVersion": raw_version}
    if with_checksum:
        settings["checksum"] = "abc123"
    with open(os.path.join(game, "launcher-settings.json"), "w", encoding="utf-8") as handle:
        json.dump(settings, handle)
    for rel in ("map/terrain/atlas0.dds", "map/terrain/atlas_normal0.dds"):
        full = os.path.join(game, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as handle:
            handle.write(b"fake")
    return game


def test_normalize_install_dir(tmp_path):
    base = str(tmp_path)
    assert normalize_install_dir(None) is None
    assert normalize_install_dir("   ") is None
    joined = os.path.join(base, "a", "..", "b")
    assert normalize_install_dir(joined) == os.path.abspath(os.path.normpath(joined))


def test_version_helpers():
    assert descriptor_version_for_raw("1.19.3.0") == "1.19.*"
    assert descriptor_version_for_raw("1.19.2.0") == "1.19.*"
    assert descriptor_version_for_raw("bad") is None
    assert descriptor_version_for_raw(None) is None
    assert profile_id_for_raw("1.19.3.0") == "hoi4-1.19"
    assert profile_id_for_raw("bad") == "hoi4-1.19"


def test_resolve_explicit_target_reads_fake_install(tmp_path):
    game = _make_fake_install(tmp_path, raw_version="1.19.3.0", with_checksum=True)
    target = resolve_game_target(game)
    assert isinstance(target, GameTarget)
    assert target.install_dir == os.path.abspath(os.path.normpath(game))
    assert target.raw_version == "1.19.3.0"
    assert target.display_version == "1.19.3"
    assert target.revision == "0"
    assert target.checksum == "abc123"
    assert target.supported_version == "1.19.*"
    assert target.profile_id == "hoi4-1.19"
    assert target.source == "explicit"
    assert target.validated_at
    assert target.required_files
    assert target.is_usable
    assert target.missing_files == []
    assert target.normalized_install_dir == target.install_dir


def test_resolve_target_missing_files_reported(tmp_path):
    game = os.path.join(str(tmp_path), "empty_game")
    os.makedirs(game, exist_ok=True)
    target = resolve_game_target(game)
    assert target.install_dir is not None
    assert not target.is_usable
    assert target.raw_version is None
    assert target.supported_version
    assert "common/terrain/00_terrain.txt" in target.missing_files


def test_resolve_target_sources(tmp_path, monkeypatch):
    game = _make_fake_install(tmp_path)
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"hoi4_game_dir": game}), encoding="utf-8")
    monkeypatch.setattr(ga, "CONFIG_PATH", str(cfg))
    target = resolve_game_target()
    assert target.source == "user_config"
    assert target.install_dir == os.path.abspath(os.path.normpath(game))
    project_target = resolve_game_target(game, source="project")
    assert project_target.source == "project"


def test_resolve_target_fallback_without_install(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg.json"
    cfg.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ga, "CONFIG_PATH", str(cfg))
    monkeypatch.setattr(ga, "DEFAULT_HOI4_PATH", str(tmp_path / "nope"))
    target = resolve_game_target()
    assert target.source == "default"
    assert target.install_dir is None
    assert not target.is_usable


def test_target_serialization_round_trip(tmp_path):
    game = _make_fake_install(tmp_path)
    target = resolve_game_target(game, source="project")
    data = target.to_dict()
    assert data["profile_id"] == "hoi4-1.19"
    assert data["source"] == "project"
    restored = GameTarget.from_dict(data)
    assert restored == target


def test_target_helpers_and_backwards_compat(tmp_path):
    game = _make_fake_install(tmp_path, raw_version="1.19.2.0")
    target = resolve_game_target(game)
    assert target_install_dir(target) == target.install_dir
    assert target_supported_version(target) == "1.19.*"
    assert ga.resolve_supported_version(target) == "1.19.*"
    assert ga.resolve_supported_version() in ("1.19.*", "1.19.*")
    assets = GameAssets.from_target(target)
    assert assets.install_dir == target.install_dir
    legacy = GameAssets(install_dir=target)
    assert legacy.install_dir == target.install_dir


def test_explicit_target_does_not_fall_back_to_install_discovery(monkeypatch):
    class _MissingTarget:
        install_dir = None
        supported_version = "1.19.*"

    monkeypatch.setattr(
        ga,
        "find_hoi4_install",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected discovery")),
    )
    assert GameAssets.from_target(_MissingTarget()).install_dir is None
    assert GameAssets(install_dir=_MissingTarget()).install_dir is None


def test_check_required_files(tmp_path):
    game = _make_fake_install(tmp_path)
    availability = check_required_files(game)
    assert availability["common/terrain/00_terrain.txt"] is True
    assert availability["launcher-settings.json"] is True
    empty = check_required_files(None)
    assert all(v is False for v in empty.values())
