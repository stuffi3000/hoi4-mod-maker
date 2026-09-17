"""Project save/load — serializes all data to .hoi4proj file
Use numpy compression to store large arrays and JSON to store metadata"""
import os
import json
import numpy as np
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

from domain.project_meta import (
    KNOWN_SCHEMA_VERSIONS,
    PROJECT_META_FILENAME,
    NewerSchemaError,
    ProjectMeta,
    UnknownSchemaError,
    infer_meta_for_legacy_project,
    meta_to_bytes,
)


def save_project(
    path: str,
    tile_map: np.ndarray,
    province_map: np.ndarray,
    terrain_map: np.ndarray,
    height_map: np.ndarray,
    state_mgr,   # StateManager
    country_mgr, # CountryManager
    river_map: np.ndarray | None = None,
    continent_mgr=None,  # ContinentManager, optional
    adjacency_mgr=None,  # AdjacencyManager (Phase 1)
    railway_mgr=None,    # RailwayManager
    supply_mgr=None,     # SupplyNodeManager
    adjacency_rule_mgr=None,  # AdjacencyRuleManager (A6)
    strategic_region_mgr=None,  # StrategicRegionManager (A7)
    provincial_terrain: dict[int, str] | None = None,
    tile_snapshot: np.ndarray | None = None,
    project_meta=None,
    allow_newer_overwrite: bool = False,
) -> None:
    """Save project to .hoi4proj file (zip format).

    ``project_meta`` may be a :class:`ProjectMeta` or a plain dict matching
    ``project_meta.json``. When omitted, no metadata file is written so older
    direct callers keep their previous behaviour; :class:`model.project.Project`
    always passes explicit metadata for new saves. Existing archives that
    contain a newer unknown schema are never overwritten unless
    ``allow_newer_overwrite`` is True."""
    meta_obj = None
    if project_meta is not None:
        if isinstance(project_meta, ProjectMeta):
            meta_obj = project_meta
        elif isinstance(project_meta, dict):
            meta_obj = ProjectMeta.from_dict(dict(project_meta))
        else:
            raise TypeError("project_meta must be ProjectMeta or dict")
        try:
            schema_version = int(meta_obj.schema_version)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"invalid project metadata schema_version: {meta_obj.schema_version!r}"
            ) from exc
        if schema_version not in KNOWN_SCHEMA_VERSIONS:
            raise UnknownSchemaError(schema_version, meta_obj.to_dict())

    if os.path.isfile(path) and not allow_newer_overwrite:
        try:
            with ZipFile(path, "r") as _existing:
                if PROJECT_META_FILENAME in _existing.namelist():
                    try:
                        ProjectMeta.from_dict(json.loads(_existing.read(PROJECT_META_FILENAME).decode("utf-8")))
                    except UnknownSchemaError as exc:
                        raise NewerSchemaError(exc.schema_version, exc.data) from exc
        except NewerSchemaError:
            raise
        except Exception:
            pass

    with ZipFile(path, "w", ZIP_DEFLATED) as zf:
        # Save numpy array
        arrays_to_save = [
            ("tile_map.npy", tile_map),
            ("province_map.npy", province_map),
            ("terrain_map.npy", terrain_map),
            ("height_map.npy", height_map),
        ]
        if river_map is not None:
            arrays_to_save.append(("river_map.npy", river_map))
        if tile_snapshot is not None:
            arrays_to_save.append(("tile_snapshot.npy", tile_snapshot))
        for name, arr in arrays_to_save:
            buf = BytesIO()
            np.save(buf, arr)
            zf.writestr(name, buf.getvalue())

        # Save State data
        states_data = {}
        for sid, s in state_mgr.states.items():
            states_data[str(sid)] = {
                "id": s.id,
                "name": s.name,
                "name_en": getattr(s, "name_en", "") or "",
                "provinces": s.provinces,
                "manpower": s.manpower,
                "category": s.category,
                "owner_tag": s.owner_tag,
                "victory_points": {str(k): v for k, v in s.victory_points.items()},
                # City/state English names are independent localisation fields.
                # Preserve them here so a saved project does not silently lose
                # its authored victory-point labels on the next reload.
                "vp_names": {
                    str(k): v for k, v in (getattr(s, "vp_names", {}) or {}).items()
                },
                "vp_names_en": {
                    str(k): v for k, v in (getattr(s, "vp_names_en", {}) or {}).items()
                },
                # Advanced fields
                "impassable": bool(getattr(s, "impassable", False)),
                "controller_tag": getattr(s, "controller_tag", "") or "",
                "local_supplies": float(getattr(s, "local_supplies", 0.0) or 0.0),
                "resources": dict(getattr(s, "resources", {}) or {}),
                "buildings": dict(getattr(s, "buildings", {}) or {}),
                "province_buildings": {
                    str(pid): dict(bmap) for pid, bmap in
                    (getattr(s, "province_buildings", {}) or {}).items()
                },
                "extra_cores": list(getattr(s, "extra_cores", []) or []),
                "claims": list(getattr(s, "claims", []) or []),
            }
        zf.writestr("states.json", json.dumps(states_data, ensure_ascii=False, indent=2))

        # Save country data
        countries_data = {}
        for tag, c in country_mgr.countries.items():
            countries_data[tag] = {
                "tag": c.tag,
                "name": c.name,
                "color": list(c.color),
                "capital": c.capital,
                "ruling_party": c.ruling_party,
                "popularities": c.popularities,
            }
        # Save state_owner mapping
        state_owners = {str(k): v for k, v in country_mgr._state_owner.items()}

        zf.writestr("countries.json", json.dumps({
            "countries": countries_data,
            "state_owners": state_owners,
        }, ensure_ascii=False, indent=2))

        # Save continent data (optional, not available in old projects)
        if continent_mgr is not None:
            zf.writestr(
                "continents.json",
                json.dumps(continent_mgr.to_dict(), ensure_ascii=False, indent=2),
            )

        # Save logistics data (Phase 1)
        if adjacency_mgr is not None:
            zf.writestr(
                "adjacencies.json",
                json.dumps(adjacency_mgr.to_dict(), ensure_ascii=False, indent=2),
            )
        if railway_mgr is not None:
            zf.writestr(
                "railways.json",
                json.dumps(railway_mgr.to_dict(), ensure_ascii=False, indent=2),
            )
        if supply_mgr is not None:
            zf.writestr(
                "supply_nodes.json",
                json.dumps(supply_mgr.to_dict(), ensure_ascii=False, indent=2),
            )
        if adjacency_rule_mgr is not None:
            zf.writestr(
                "adjacency_rules.json",
                json.dumps(adjacency_rule_mgr.to_dict(), ensure_ascii=False, indent=2),
            )
        if strategic_region_mgr is not None:
            zf.writestr(
                "strategic_regions.json",
                json.dumps(strategic_region_mgr.to_dict(), ensure_ascii=False, indent=2),
            )

        # Province-level terrain (Feature A: independent of graphical terrain_map)
        if provincial_terrain:
            zf.writestr(
                "provincial_terrain.json",
                json.dumps(
                    {str(k): v for k, v in provincial_terrain.items()},
                    ensure_ascii=False, indent=2,
                ),
            )

        # M1.3 project metadata (schema/GameTarget/lifecycle). Only written
        # when the caller supplies it so legacy direct callers are unchanged.
        if meta_obj is not None:
            zf.writestr(PROJECT_META_FILENAME, meta_to_bytes(meta_obj))


def load_project(
    path: str,
    state_mgr,
    country_mgr,
    continent_mgr=None,
    adjacency_mgr=None,
    railway_mgr=None,
    supply_mgr=None,
    adjacency_rule_mgr=None,
    strategic_region_mgr=None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray | None, dict[int, str], np.ndarray | None]:
    """Load project files.

    Return (tile_map, province_map, terrain_map, height_map, river_map)
    Populate both state_mgr and country_mgr
    river_map may be None (older project files don't have it)

    Archives that declare a newer unknown ``project_meta.json`` schema are
    rejected with :class:`NewerSchemaError` before any manager is mutated,
    so legacy data is never silently overwritten."""
    with ZipFile(path, "r") as _pre:
        if PROJECT_META_FILENAME in _pre.namelist():
            try:
                ProjectMeta.from_dict(json.loads(_pre.read(PROJECT_META_FILENAME).decode("utf-8")))
            except UnknownSchemaError as exc:
                raise NewerSchemaError(exc.schema_version, exc.data) from exc
    with ZipFile(path, "r") as zf:
        # Load numpy array
        tile_map = np.load(BytesIO(zf.read("tile_map.npy")))
        province_map = np.load(BytesIO(zf.read("province_map.npy")))
        terrain_map = np.load(BytesIO(zf.read("terrain_map.npy")))
        height_map = np.load(BytesIO(zf.read("height_map.npy")))

        # River data (compatible with older versions)
        river_map = None
        if "river_map.npy" in zf.namelist():
            river_map = np.load(BytesIO(zf.read("river_map.npy")))
            # Fixed old version bug: river_map all 0 means old version initialization error (0=source=green)
            # The correct blank background is 255
            if river_map is not None and int(river_map.max()) == 0:
                river_map[:] = 255

        # Load State data
        state_mgr.clear()
        states_raw = json.loads(zf.read("states.json"))
        from domain.managers.state import StateData
        for sid_str, data in states_raw.items():
            sid = int(sid_str)
            state = StateData(
                id=data["id"],
                name=data["name"],
                name_en=data.get("name_en", "") or "",
                provinces=data["provinces"],
                manpower=data["manpower"],
                category=data["category"],
                owner_tag=data.get("owner_tag", ""),
                victory_points={int(k): v for k, v in data.get("victory_points", {}).items()},
                vp_names={
                    int(k): str(v) for k, v in (data.get("vp_names") or {}).items()
                },
                vp_names_en={
                    int(k): str(v)
                    for k, v in (data.get("vp_names_en") or {}).items()
                },
                impassable=bool(data.get("impassable", False)),
                controller_tag=data.get("controller_tag", ""),
                local_supplies=float(data.get("local_supplies", 0.0) or 0.0),
                resources={k: int(v) for k, v in (data.get("resources") or {}).items()},
                buildings={k: int(v) for k, v in (data.get("buildings") or {}).items()},
                province_buildings={
                    int(pid): {bk: int(bv) for bk, bv in (bmap or {}).items()}
                    for pid, bmap in (data.get("province_buildings") or {}).items()
                },
                extra_cores=list(data.get("extra_cores") or []),
                claims=list(data.get("claims") or []),
            )
            state_mgr._states[sid] = state
            for pid in state.provinces:
                state_mgr._province_to_state[pid] = sid
            state_mgr._next_id = max(state_mgr._next_id, sid + 1)

        # Load country data
        country_mgr.clear()
        countries_raw = json.loads(zf.read("countries.json"))
        from domain.managers.country import CountryData
        for tag, data in countries_raw.get("countries", {}).items():
            country = CountryData(
                tag=data["tag"],
                name=data["name"],
                color=tuple(data["color"]),
                capital=data.get("capital", 0),
                ruling_party=data.get("ruling_party", "neutrality"),
                popularities=data.get("popularities", {
                    "democratic": 10, "fascism": 5, "communism": 5, "neutrality": 80,
                }),
            )
            country_mgr._countries[tag] = country

        for sid_str, tag in countries_raw.get("state_owners", {}).items():
            country_mgr._state_owner[int(sid_str)] = tag

        # Load continent data (old project does not have it, keep the default)
        if continent_mgr is not None and "continents.json" in zf.namelist():
            continent_mgr.clear()
            continent_mgr.from_dict(json.loads(zf.read("continents.json")))

        # Logistics data (Phase 1, not available in old projects)
        if adjacency_mgr is not None and "adjacencies.json" in zf.namelist():
            adjacency_mgr.clear()
            adjacency_mgr.from_dict(json.loads(zf.read("adjacencies.json")))
        if railway_mgr is not None and "railways.json" in zf.namelist():
            railway_mgr.clear()
            railway_mgr.from_dict(json.loads(zf.read("railways.json")))
        if supply_mgr is not None and "supply_nodes.json" in zf.namelist():
            supply_mgr.clear()
            supply_mgr.from_dict(json.loads(zf.read("supply_nodes.json")))
        if adjacency_rule_mgr is not None and "adjacency_rules.json" in zf.namelist():
            adjacency_rule_mgr.clear()
            adjacency_rule_mgr.from_dict(json.loads(zf.read("adjacency_rules.json")))
        if strategic_region_mgr is not None and "strategic_regions.json" in zf.namelist():
            strategic_region_mgr.clear()
            strategic_region_mgr.from_dict(json.loads(zf.read("strategic_regions.json")))

        # tile_snapshot (tile_map snapshot when the province is generated, old projects do not have it)
        tile_snapshot = None
        if "tile_snapshot.npy" in zf.namelist():
            tile_snapshot = np.load(BytesIO(zf.read("tile_snapshot.npy")))

        # Provincial level terrain (Feature A)
        provincial_terrain: dict[int, str] = {}
        if "provincial_terrain.json" in zf.namelist():
            raw_pt = json.loads(zf.read("provincial_terrain.json"))
            provincial_terrain = {int(k): v for k, v in raw_pt.items()}

    return tile_map, province_map, terrain_map, height_map, river_map, provincial_terrain, tile_snapshot


def read_project_meta(path: str):
    """Return the on-disk ProjectMeta or None when the archive predates M1.3."""
    if not os.path.isfile(path):
        return None
    with ZipFile(path, "r") as zf:
        if PROJECT_META_FILENAME not in zf.namelist():
            return None
        raw = zf.read(PROJECT_META_FILENAME)
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"invalid {PROJECT_META_FILENAME}: {exc}") from exc
    try:
        return ProjectMeta.from_dict(data)
    except UnknownSchemaError as exc:
        raise NewerSchemaError(exc.schema_version, exc.data) from exc


def load_project_with_meta(path: str, state_mgr, country_mgr, continent_mgr=None, adjacency_mgr=None, railway_mgr=None, supply_mgr=None, adjacency_rule_mgr=None, strategic_region_mgr=None):
    """Load arrays/managers plus project metadata."""
    on_disk = read_project_meta(path)
    result = load_project(path, state_mgr, country_mgr, continent_mgr=continent_mgr, adjacency_mgr=adjacency_mgr, railway_mgr=railway_mgr, supply_mgr=supply_mgr, adjacency_rule_mgr=adjacency_rule_mgr, strategic_region_mgr=strategic_region_mgr)
    tile_map, province_map = result[0], result[1]
    height = int(tile_map.shape[0]) if tile_map is not None else 0
    width = int(tile_map.shape[1]) if tile_map is not None else 0
    if on_disk is not None:
        meta = on_disk
        if not meta.width or not meta.height:
            meta.width = width
            meta.height = height
        return (*result, meta)
    inferred = infer_meta_for_legacy_project(width=width, height=height)
    return (*result, inferred)
