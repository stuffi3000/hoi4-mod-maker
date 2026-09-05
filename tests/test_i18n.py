"""English-only i18n behavior and catalog-tool smoke tests."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOOLS = PROJECT_ROOT / "tools"


@pytest.fixture
def i18n():
    import ui.i18n as module

    module.reload_translations()
    return module


def test_only_english_catalog_is_loaded(i18n):
    assert i18n.available_languages() == ["en"]
    assert set(i18n._languages) == {"en"}
    assert i18n.get_language() == "en"


def test_english_catalog_contains_no_cjk_or_cyrillic_text(i18n):
    non_english = re.compile(r"[\u3400-\u9fff\u0400-\u04ff]")
    offenders = {
        key: value
        for key, value in i18n._languages["en"].items()
        if non_english.search(value)
    }
    assert not offenders, f"English translations contain non-English text: {offenders}"


def test_fresh_install_defaults_to_english(i18n, monkeypatch):
    captured = {}

    class FakeSettings:
        def __init__(self, organization, application):
            captured["scope"] = (organization, application)

        def value(self, key, default):
            captured["value"] = (key, default)
            return default

    monkeypatch.setattr("PyQt5.QtCore.QSettings", FakeSettings)
    assert i18n._load_saved_language() == "en"
    assert captured["scope"] == ("HOI4MapMaker", "Settings")
    assert captured["value"] == ("language", "en")


def test_saved_non_english_locale_is_normalized(i18n, monkeypatch):
    class FakeSettings:
        def __init__(self, organization, application):
            pass

        def value(self, key, default):
            return "zh"

    monkeypatch.setattr("PyQt5.QtCore.QSettings", FakeSettings)
    assert i18n._load_saved_language() == "en"


def test_set_language_always_keeps_english(i18n):
    i18n.set_language("zh")
    assert i18n.get_language() == "en"
    assert i18n.available_languages() == ["en"]
    i18n.set_language("ru")
    assert i18n.get_language() == "en"


def test_english_mode_missing_key_returns_key(i18n):
    key = "app_title"
    english = i18n._languages["en"].pop(key)
    try:
        i18n.set_language("en")
        assert i18n.tr(key) == key
    finally:
        i18n._languages["en"][key] = english


def test_tr_positional_args(i18n):
    result = i18n.tr("status_pos", 123, 456)
    assert "123" in result and "456" in result


def test_tr_named_kwargs(i18n):
    result = i18n.tr("dlg_batch_state_done", sid=5, n=12)
    assert "5" in result and "12" in result
    assert "{sid}" not in result and "{n}" not in result


def test_tr_missing_key_returns_key(i18n):
    assert i18n.tr("__nonexistent_key__") == "__nonexistent_key__"


def test_tr_pair_is_always_english(i18n):
    for locale in ("en", "zh", "ru"):
        i18n.set_language(locale)
        assert i18n.tr_pair("非英文 {0}", "English {0}", 42) == "English 42"


def test_tr_placeholder_mismatch_logs_warning(i18n, caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="ui.i18n"):
        result = i18n.tr("dlg_batch_state_done", 5, 12)
    assert "placeholder mismatch" in caplog.text
    assert "{sid}" in result


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOLS / args[0]), *args[1:]],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_audit_summary_is_english_only():
    result = _run("i18n_audit.py", "summary")
    assert result.returncode == 0, result.stderr
    assert "English-only" in result.stdout
    assert "en" in result.stdout
    assert "zh" not in result.stdout and "ru" not in result.stdout


def test_audit_check_placeholders_passes():
    result = _run("i18n_audit.py", "check-placeholders")
    assert result.returncode == 0, result.stdout + "\n" + result.stderr


def test_audit_rejects_non_english_catalogs():
    result = _run("i18n_audit.py", "missing", "ru")
    assert result.returncode == 2
    assert "not found" in result.stderr


def test_add_key_e2e_writes_only_english_catalog():
    test_key = "__pytest_add_key_temp__"
    path = PROJECT_ROOT / "ui" / "i18n" / "en" / "menu.py"
    try:
        result = _run("add_i18n_key.py", "menu", test_key, "Test value")
        assert result.returncode == 0, result.stderr
        assert "[en]" in result.stdout
        assert test_key in path.read_text(encoding="utf-8")
    finally:
        source = path.read_text(encoding="utf-8")
        path.write_text(
            "\n".join(line for line in source.split("\n") if test_key not in line),
            encoding="utf-8",
        )


def test_add_key_skips_existing_without_force():
    result = _run("add_i18n_key.py", "menu", "menu_view", "Duplicate")
    assert result.returncode == 0
    assert "skipped_exists" in result.stdout
