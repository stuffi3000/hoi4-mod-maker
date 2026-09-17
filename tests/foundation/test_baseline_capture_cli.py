"""Safety tests for the opt-in baseline capture command."""

from __future__ import annotations

import pytest

from tools import capture_foundation_baseline as capture_cli

pytestmark = pytest.mark.unit


def test_capture_refuses_to_overwrite_existing_report(monkeypatch, tmp_path, capsys):
    output = tmp_path / "baseline.json"
    output.write_text("original\n", encoding="utf-8")
    monkeypatch.setattr(capture_cli, "capture_summary", lambda *args, **kwargs: {})

    result = capture_cli.main(
        [
            "--project",
            str(tmp_path / "project.hoi4proj"),
            "--output",
            str(output),
        ]
    )

    assert result == 2
    assert output.read_text(encoding="utf-8") == "original\n"
    assert "Refusing to overwrite" in capsys.readouterr().err
