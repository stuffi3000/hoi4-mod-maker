"""CLI exit-code and console-encoding regression tests."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest

import cli_export

pytestmark = pytest.mark.unit


def _fake_project_result():
    tile_map = np.ones((2, 2), dtype=np.uint8)
    province_map = np.ones((2, 2), dtype=np.int32)
    terrain_map = np.zeros((2, 2), dtype=np.uint8)
    height_map = np.array([[1, 2], [3, 4]], dtype=np.uint8)
    return tile_map, province_map, terrain_map, height_map, None, {}, None


def _patch_common_cli(monkeypatch, tmp_path: Path):
    project = tmp_path / "project.hoi4proj"
    project.write_bytes(b"project placeholder")
    monkeypatch.setattr(cli_export, "configure_console_streams", lambda: None)
    monkeypatch.setattr(
        cli_export,
        "load_project",
        lambda *args, **kwargs: _fake_project_result(),
    )

    import services.export_service as export_service

    monkeypatch.setattr(
        export_service,
        "pre_export_check_and_fix",
        lambda *args, **kwargs: export_service.ExportReport(),
    )
    monkeypatch.setattr(
        export_service,
        "fill_default_state_data",
        lambda *args, **kwargs: 0,
    )
    return project


def _write_valid_output(output_dir: str):
    root = Path(output_dir)
    for relative_path in cli_export.CRITICAL_FILES:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("valid\n", encoding="utf-8")
    for relative_path in cli_export.CRITICAL_DIRECTORIES:
        path = root / relative_path
        path.mkdir(parents=True, exist_ok=True)
        (path / "placeholder.txt").write_text("valid\n", encoding="utf-8")
    (Path(str(root) + ".mod")).write_text("valid\n", encoding="utf-8")


def test_success_returns_zero_only_after_final_verification(monkeypatch, tmp_path, capsys):
    project = _patch_common_cli(monkeypatch, tmp_path)

    def export_stub(**kwargs):
        _write_valid_output(kwargs["output_dir"])

    monkeypatch.setattr(cli_export, "export_full_mod", export_stub)
    result = cli_export.main([str(project), str(tmp_path / "output")])

    assert result == cli_export.EXIT_SUCCESS
    assert "[OK] Exported" in capsys.readouterr().out


def test_validation_blocker_returns_distinct_code_and_no_success(monkeypatch, tmp_path, capsys):
    project = _patch_common_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli_export, "export_full_mod", lambda **kwargs: None)

    result = cli_export.main([str(project), str(tmp_path / "output")])
    output = capsys.readouterr().out

    assert result == cli_export.EXIT_VALIDATION_ERROR
    assert "[VALIDATION FAILED]" in output
    assert "[OK] Exported" not in output


def test_writer_exception_returns_command_error(monkeypatch, tmp_path, capsys):
    project = _patch_common_cli(monkeypatch, tmp_path)

    def fail_export(**kwargs):
        raise RuntimeError("writer failed")

    monkeypatch.setattr(cli_export, "export_full_mod", fail_export)
    result = cli_export.main([str(project), str(tmp_path / "output")])
    output = capsys.readouterr()

    assert result == cli_export.EXIT_COMMAND_ERROR
    assert "writer failed" in output.err
    assert "[OK] Exported" not in output.out


def test_safe_print_uses_ascii_fallback():
    class AsciiOnlyStream(io.StringIO):
        @property
        def encoding(self):
            return "ascii"

        def write(self, text):
            text.encode("ascii")
            return super().write(text)

    stream = AsciiOnlyStream()
    cli_export._safe_print("Export passed ✓", file=stream)

    assert "Export passed" in stream.getvalue()
    assert "\\u2713" in stream.getvalue()
