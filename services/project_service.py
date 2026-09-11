"""Project IO Service — Business logic for saving/loading .hoi4proj.

The UI layer (MainWindow) is only responsible for popping up the file dialog box + displaying errors.
The actual save_project/load_project calls + data synchronization are all here."""

from __future__ import annotations


def save_project(
    path: str,
    canvas,
    state_mgr,
    country_mgr,
    continent_mgr,
    adjacency_mgr=None,
    railway_mgr=None,
    supply_mgr=None,
    adjacency_rule_mgr=None,
    strategic_region_mgr=None,
) -> None:
    """Save the project to .hoi4proj. If it fails, an exception will be thrown, and the UI layer will capture and display it."""
    from domain.project_io import save_project as _save
    _save(
        path,
        canvas.tile_map,
        canvas.province_map,
        canvas.terrain_map,
        canvas.height_map,
        state_mgr,
        country_mgr,
        canvas.river_map,
        continent_mgr=continent_mgr,
        adjacency_mgr=adjacency_mgr,
        railway_mgr=railway_mgr,
        supply_mgr=supply_mgr,
        adjacency_rule_mgr=adjacency_rule_mgr,
        strategic_region_mgr=strategic_region_mgr,
        provincial_terrain=canvas.map_data.provincial_terrain,
        tile_snapshot=canvas.map_data.tile_snapshot,
    )


def load_project(
    path: str,
    canvas,
    state_mgr,
    country_mgr,
    continent_mgr,
    adjacency_mgr=None,
    railway_mgr=None,
    supply_mgr=None,
    adjacency_rule_mgr=None,
    strategic_region_mgr=None,
) -> None:
    """Load from .hoi4proj and update canvas and manager in place. An exception will be thrown if it fails."""
    from domain.project_io import load_project as _load
    tm, pm, terrain, hm, rm, pt, tile_snapshot = _load(
        path, state_mgr, country_mgr,
        continent_mgr=continent_mgr,
        adjacency_mgr=adjacency_mgr,
        railway_mgr=railway_mgr,
        supply_mgr=supply_mgr,
        adjacency_rule_mgr=adjacency_rule_mgr,
        strategic_region_mgr=strategic_region_mgr,
    )
    canvas.tile_map = tm
    canvas.province_map = pm
    canvas.terrain_map = terrain
    canvas.height_map = hm
    if rm is not None:
        canvas.river_map = rm
    # Provincial level terrain (Feature A)
    canvas.map_data.provincial_terrain = pt if pt else {}
    # tile_snapshot (tile_map snapshot when province is generated)
    # Old project has no snapshot → use current tile_map as snapshot (assuming tile_map has not been modified when saving)
    canvas.map_data.tile_snapshot = tile_snapshot if tile_snapshot is not None else tm.copy()


def create_mod_skeleton(output_dir: str) -> None:
    """Create a basic empty directory structure for HOI4 MOD in the project export directory."""
    import os
    dirs = [
        "common/countries",
        "common/country_tags",
        "common/national_focus",
        "common/ideas",
        "common/technologies",
        "common/units",
        "history/countries",
        "history/states",
        "history/units",
        "map/strategicregions",
        "gfx/flags",
        "gfx/leaders",
        "localisation",
        "events",
    ]
    for d in dirs:
        os.makedirs(os.path.join(output_dir, d), exist_ok=True)
