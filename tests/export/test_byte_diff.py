"""Phase 2 byte diff test — ensure that the output before and after mod_exporter is removed is completely consistent.

Strategy:
1. First run: Use a small test project to export MOD and record the sha256 of all files to baseline.json
2. Subsequent runs: Export again and compare all file hashes. If any one does not match, the test fails.
3. This test is a safety net when refactoring mod_exporter

⚠ Known sources of false failures: Part of the exported content is vanilla files copied and cleaned from the main game
(such as common/decisions/categories/*). **These files will change after Steam updates the game**,
byte-diff will fail without any code changes. Confirm that failed files are all vanilla
If the content is derived and the mtime of the game directory is later than the baseline time, just delete baseline.json and rebuild.
(Occurred once each on 2026-06-12 and 2026-07-04, please see project memory for troubleshooting records)."""

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pytest

from domain.managers.state import StateManager
from domain.managers.country import CountryManager
from domain.managers.continent import ContinentManager
from export.mod_exporter import export_full_mod
from data.constants import MAP_WIDTH, MAP_HEIGHT, TILE_LAND, TILE_SEA


BASELINE_FILE = Path(__file__).parent.parent / "fixtures" / "export_baseline.json"


def _build_tiny_project():
    """Construct a mini test project: all land + 2 provinces + 1 state + 1 country."""
    tile_map = np.full((MAP_HEIGHT, MAP_WIDTH), TILE_LAND, dtype=np.uint8)
    # Border sea (to avoid coastal errors)
    tile_map[0, :] = TILE_SEA
    tile_map[-1, :] = TILE_SEA
    tile_map[:, 0] = TILE_SEA
    tile_map[:, -1] = TILE_SEA

    province_map = np.zeros((MAP_HEIGHT, MAP_WIDTH), dtype=np.int32)
    # Province 1: Left Half of the Land, Province 2: Right Half of the Land, Province 3: Border Sea
    mid = MAP_WIDTH // 2
    province_map[1:-1, 1:mid] = 1
    province_map[1:-1, mid:-1] = 2
    province_map[tile_map == TILE_SEA] = 3

    state_mgr = StateManager()
    from domain.managers.state import StateData
    s1 = StateData(id=1, name="TestState", provinces=[1, 2],
                   manpower=100000, category="town", owner_tag="TST")
    state_mgr._states[1] = s1
    state_mgr._province_to_state = {1: 1, 2: 1}
    state_mgr._next_id = 2

    country_mgr = CountryManager()
    country_mgr.create_country("TST", "TestLand", (100, 100, 200))
    country_mgr.set_capital("TST", 1)
    country_mgr.assign_state(1, "TST")

    continent_mgr = ContinentManager()

    return tile_map, province_map, state_mgr, country_mgr, continent_mgr


def _hash_all_files(output_dir: str) -> dict[str, str]:
    """Recursively collect all files under output_dir and return {relative path: sha256}."""
    result: dict[str, str] = {}
    root = Path(output_dir)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(root)).replace(os.sep, "/")
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        result[rel] = h.hexdigest()
    return result


def _run_export_to_tmp() -> dict[str, str]:
    tile_map, province_map, state_mgr, country_mgr, continent_mgr = _build_tiny_project()
    tmpdir = tempfile.mkdtemp(prefix="hoi4_export_test_")
    try:
        export_full_mod(
            tile_map=tile_map,
            province_map=province_map,
            output_dir=tmpdir,
            mod_name="ByteDiffTest",
            tag="TST",
            state_mgr=state_mgr,
            country_mgr=country_mgr,
            continent_mgr=continent_mgr,
        )
        return _hash_all_files(tmpdir)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.mark.slow
def test_export_byte_diff_matches_baseline():
    """All exported file hashes must match baseline.json exactly.

    First run (baseline does not exist): generate baseline.json, test skipped.
    Subsequent runs: comparison."""
    current = _run_export_to_tmp()

    if not BASELINE_FILE.exists():
        BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(BASELINE_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2, sort_keys=True)
        pytest.skip(f"Baseline created: {BASELINE_FILE} ({len(current)} files)")

    with open(BASELINE_FILE, "r", encoding="utf-8") as f:
        baseline: dict[str, str] = json.load(f)

    missing = set(baseline.keys()) - set(current.keys())
    extra = set(current.keys()) - set(baseline.keys())
    changed = {
        k for k in baseline.keys() & current.keys()
        if baseline[k] != current[k]
    }

    msg_parts = []
    if missing:
        msg_parts.append(f"Missing {len(missing)} files: {sorted(missing)[:5]}")
    if extra:
        msg_parts.append(f"Found {len(extra)} extra files: {sorted(extra)[:5]}")
    if changed:
        msg_parts.append(f"Content changed in {len(changed)} files: {sorted(changed)[:5]}")

    assert not msg_parts, " | ".join(msg_parts)
