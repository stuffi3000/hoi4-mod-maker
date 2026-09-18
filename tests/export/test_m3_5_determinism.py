"""M3.5 deterministic foundation-output tests."""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest

from services import export_manifest
from services.export_service import export_planned_mod
from services.export_manifest import collect_deterministic_inventory
from tests.export.test_m3_4_manifest import _base_plan


pytestmark = pytest.mark.integration


@pytest.fixture
def m3_5_tmp(request):
    root = Path("tmp/m3-5-test-tmp") / ("%s-%s" % (request.node.name[:40], uuid.uuid4().hex[:8]))
    root.mkdir(parents=True, exist_ok=True)
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _created_report_line(path: Path) -> str:
    return next(line for line in path.read_text(encoding="utf-8").splitlines()
                if line.startswith("Created: "))


def test_identical_foundation_exports_have_same_deterministic_inventory(m3_5_tmp, monkeypatch):
    plans = [_base_plan(), _base_plan()]
    timestamps = iter([
        "2026-01-01T00:00:01+00:00",
        "2026-01-01T00:00:02+00:00",
        "2026-01-01T00:00:03+00:00",
        "2026-01-01T00:00:04+00:00",
        "2026-01-01T00:00:11+00:00",
        "2026-01-01T00:00:12+00:00",
        "2026-01-01T00:00:13+00:00",
        "2026-01-01T00:00:14+00:00",
    ])
    monkeypatch.setattr(export_manifest, "_utc_now_iso", lambda: next(timestamps))

    first_dir = m3_5_tmp / "first"
    second_dir = m3_5_tmp / "second"
    export_planned_mod(plans[0], str(first_dir))
    export_planned_mod(plans[1], str(second_dir))

    first_manifest = json.loads((first_dir / "foundation_manifest.json").read_text(encoding="utf-8"))
    second_manifest = json.loads((second_dir / "foundation_manifest.json").read_text(encoding="utf-8"))
    first_lock = json.loads((first_dir / "foundation.lock.json").read_text(encoding="utf-8"))
    second_lock = json.loads((second_dir / "foundation.lock.json").read_text(encoding="utf-8"))
    assert first_manifest["metadata"]["created_at"] != second_manifest["metadata"]["created_at"]
    assert first_lock["metadata"]["created_at"] != second_lock["metadata"]["created_at"]
    assert _created_report_line(first_dir / "foundation_report.md") != _created_report_line(second_dir / "foundation_report.md")

    first_inventory = collect_deterministic_inventory(str(first_dir))
    second_inventory = collect_deterministic_inventory(str(second_dir))
    assert first_inventory == second_inventory
    assert {entry["rel_path"] for entry in first_inventory} == {
        path.relative_to(first_dir).as_posix()
        for path in first_dir.rglob("*")
        if path.is_file()
    }
