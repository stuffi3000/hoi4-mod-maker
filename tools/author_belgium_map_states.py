"""Author administrative HOI4 states for the Belgium Map v1.1 project.

The province layer was generated from Eurostat's 2016 commune geometry.  This
script traces those polygons back to their source identifiers, then groups the
resulting provinces using the administrative scheme selected for this map:

* Belgium: NUTS 3 / administrative arrondissements;
* France: 2016 arrondissements, with large ones split by 2016 EPCI;
* Germany: NUTS 3 / Kreis level, with large Rheinland-Palatinate groups split
  by Verbandsgemeinde;
* Netherlands: NUTS 3 / COROP;
* Luxembourg: cantons; and
* United Kingdom: parent local-authority identifiers supplied by Eurostat.

It also creates the six map countries, population-based manpower, state
categories, city victory points, conservative starting buildings/resources,
and state-safe strategic regions.  Source downloads are cached outside the
repository, so the project remains reproducible without committing third-party
data.

The script uses ``numpy``, ``scipy``, ``shapely`` and ``pyproj``.  Optional
French EPCI splitting additionally needs ``xlrd`` (use ``--skip-epci`` when it
is unavailable).  It is intentionally a one-shot authoring tool rather than a
runtime dependency of the editor.

Example::

    python tools/author_belgium_map_states.py

Use ``--dry-run`` first to inspect the generated report.  A first real run
creates a sibling ``.pre_state_authoring.bak`` before replacing the project.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import struct
import sys
import tempfile
import unicodedata
import urllib.parse
import urllib.request
import zipfile
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.constants import TILE_LAND, TILE_SEA
from domain.managers.continent import ContinentManager
from domain.managers.country import CountryManager
from domain.managers.state import StateManager
from domain.managers.strategic_region import StrategicRegionManager
from domain.project_io import load_project, save_project
from services.export_service import pre_export_check_and_fix


DEFAULT_PROJECT = ROOT / "projects" / "Belgium_Map_v1_1.hoi4proj"
DEFAULT_SOURCE_DIR = Path(r"C:\Users\stuff\Documents\HOI4\Belgium\base map\qgis\EU data")
DEFAULT_REPORT = ROOT / "projects" / "Belgium_Map_v1_1.state_authoring.json"
DEFAULT_CACHE = Path(tempfile.gettempdir()) / "hoi4_belgium_map_state_authoring"

COMMUNE_ATTRIBUTES_URL = (
    "https://gisco-services.ec.europa.eu/distribution/v2/communes/csv/COMM_AT_2016.csv"
)
NUTS_2016_URL = (
    "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/"
    "NUTS_RG_01M_2016_3035_LEVL_3.geojson"
)
FR_COMMUNE_2016_URL = "https://www.insee.fr/fr/statistiques/fichier/2114819/comsimp2016-txt.zip"
FR_ARRONDISSEMENT_2016_URL = "https://www.insee.fr/fr/statistiques/fichier/2114819/arrond2016-txt.zip"
FR_EPCI_2016_URL = (
    "https://www.insee.fr/fr/statistiques/fichier/2510634/"
    "Intercommunalite_Metropole_au_01-01-2016.zip"
)
RLP_VERBANDSGEMEINDE_URL = (
    "https://download.data.public.lu/resources/"
    "verbandsgemeinden-rhineland-palatinate-2024/20231220-152428/"
    "verbandsgemeinden-rhineland-palatinate-2024-2374-verbandsgemeinde-rlp-2024-0.geojson"
)
LUX_CANTON_URL = (
    "https://download.data.public.lu/resources/cantons-in-luxembourg-2024/"
    "20231220-152949/cantons-in-luxembourg-2024-2380-cantons-lux-2024-0.geojson"
)
GEONAMES_CITIES_URL = "https://download.geonames.org/export/dump/cities500.zip"
EUROSTAT_DENSITY_URL = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/demo_r_d3dens"
)

TARGET_COUNTRIES = ("BE", "FR", "DE", "NL", "LU", "UK")
COUNTRY_ORDER = {code: position for position, code in enumerate(TARGET_COUNTRIES)}
GEONAMES_TO_PROJECT_COUNTRY = {"BE": "BE", "FR": "FR", "DE": "DE", "NL": "NL", "LU": "LU", "GB": "UK"}

COUNTRIES: dict[str, dict[str, Any]] = {
    "BE": {
        "tag": "BEL", "name": "Belgium", "color": (183, 18, 41), "party": "democratic",
        "popularities": {"democratic": 73, "fascism": 2, "communism": 4, "neutrality": 21},
        "capital_names": ("Brussels", "Bruxelles"),
    },
    "FR": {
        "tag": "FRA", "name": "France", "color": (0, 85, 164), "party": "democratic",
        "popularities": {"democratic": 68, "fascism": 3, "communism": 14, "neutrality": 15},
        "capital_names": ("Paris",),
    },
    "DE": {
        "tag": "GER", "name": "Germany", "color": (107, 33, 28), "party": "fascism",
        "popularities": {"democratic": 2, "fascism": 91, "communism": 2, "neutrality": 5},
        "capital_names": ("Berlin",),
    },
    "NL": {
        "tag": "HOL", "name": "Netherlands", "color": (232, 116, 15), "party": "democratic",
        "popularities": {"democratic": 71, "fascism": 3, "communism": 3, "neutrality": 23},
        "capital_names": ("Amsterdam",),
    },
    "LU": {
        "tag": "LUX", "name": "Luxembourg", "color": (0, 150, 200), "party": "neutrality",
        "popularities": {"democratic": 43, "fascism": 2, "communism": 2, "neutrality": 53},
        "capital_names": ("Luxembourg", "Luxembourg City"),
    },
    "UK": {
        "tag": "ENG", "name": "United Kingdom", "color": (187, 10, 48), "party": "democratic",
        "popularities": {"democratic": 72, "fascism": 2, "communism": 3, "neutrality": 23},
        "capital_names": ("London",),
    },
}

# Used only where Eurostat has no density observation for an older NUTS code.
FALLBACK_DENSITY = {"BE": 371.0, "DE": 230.0, "FR": 118.0, "NL": 507.0, "LU": 232.0, "UK": 270.0}

# Historical industrial centres represented on this cropped map.  The script
# deliberately does not invent diffuse mineral deposits based on terrain.
STEEL_CENTRES = {
    "BE": ("Liège", "Charleroi", "Mons", "La Louvière", "Seraing"),
    "FR": ("Lille", "Dunkerque", "Valenciennes", "Douai", "Maubeuge", "Metz", "Thionville", "Longwy"),
    "DE": ("Essen", "Dortmund", "Duisburg", "Köln", "Cologne", "Saarbrücken", "Wuppertal"),
    "LU": ("Esch-sur-Alzette", "Differdange", "Dudelange"),
}


class AuthoringError(RuntimeError):
    """A recoverable error explaining why the project was not changed."""


@dataclass(frozen=True)
class Commune:
    country: str
    comm_id: str
    name: str
    nsi_code: str
    name_nsi: str
    nuts: str


@dataclass
class ProvinceInfo:
    pid: int
    commune: Commune
    land_pixels: int
    x: float
    y: float

    @property
    def country(self) -> str:
        return self.commune.country

    @property
    def nuts(self) -> str:
        return self.commune.nuts

    @property
    def area_km2(self) -> float:
        return 0.0


@dataclass
class Group:
    key: str
    country: str
    name: str
    name_en: str
    scheme: str
    pids: list[int]
    nuts2: str
    detached_index: int = 0


@dataclass(frozen=True)
class City:
    pid: int
    country: str
    name: str
    name_en: str
    population: int


def _normalise(text: str) -> str:
    """Return a resilient key for matching labels from different datasets."""
    folded = unicodedata.normalize("NFKD", text or "")
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]", "", folded.casefold())


def _clean_label(value: str, fallback: str = "") -> str:
    value = re.sub(r"\s+", " ", (value or "").replace("\x00", " ")).strip()
    return value or fallback


def _code(value: Any, width: int | None = None) -> str:
    text = _clean_label(str(value))
    if text.endswith(".0"):
        text = text[:-2]
    if width is not None and text.isdigit():
        return text.zfill(width)
    return text


def _cached_download(cache_dir: Path, filename: str, url: str) -> Path:
    """Download a stable public source once, retaining it outside the repo."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = cache_dir / filename
    if destination.is_file() and destination.stat().st_size > 0:
        return destination
    request = urllib.request.Request(url, headers={"User-Agent": "hoi4-map-state-authoring/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = response.read()
    except OSError as exc:
        raise AuthoringError(f"Could not download {url}: {exc}") from exc
    if not data:
        raise AuthoringError(f"Downloaded an empty response from {url}")
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.write_bytes(data)
    os.replace(temporary, destination)
    return destination


def _read_world_file(path: Path) -> tuple[float, float, float, float, float, float]:
    values = [line.strip().replace(",", ".") for line in path.read_text(encoding="utf-8").splitlines()]
    if len(values) != 6:
        raise AuthoringError(f"Expected six world-file values in {path}")
    try:
        return tuple(float(value) for value in values)  # type: ignore[return-value]
    except ValueError as exc:
        raise AuthoringError(f"Invalid world file: {path}") from exc


def _world_to_pixel(
    x: float, y: float, world: tuple[float, float, float, float, float, float]
) -> tuple[int, int]:
    pixel_x, rotation_y, rotation_x, pixel_y, origin_x, origin_y = world
    if rotation_x or rotation_y:
        raise AuthoringError("Rotated source world files are not supported")
    return int(round((x - origin_x) / pixel_x)), int(round((y - origin_y) / pixel_y))


def _pixel_to_world(
    column: float, row: float, world: tuple[float, float, float, float, float, float]
) -> tuple[float, float]:
    pixel_x, _rotation_y, _rotation_x, pixel_y, origin_x, origin_y = world
    return origin_x + column * pixel_x, origin_y + row * pixel_y


def _sample_land_pid(province_map: np.ndarray, tile_map: np.ndarray, column: int, row: int) -> int:
    """Sample a point, tolerating a one-pixel raster/vector alignment edge."""
    height, width = province_map.shape
    for radius in (0, 1, 2, 4, 7):
        x0, x1 = max(0, column - radius), min(width, column + radius + 1)
        y0, y1 = max(0, row - radius), min(height, row + radius + 1)
        if x0 >= x1 or y0 >= y1:
            continue
        pids = province_map[y0:y1, x0:x1]
        land = tile_map[y0:y1, x0:x1] == TILE_LAND
        values = pids[land & (pids > 0)]
        if values.size:
            counts = np.bincount(values.astype(np.int64))
            return int(np.argmax(counts))
    return 0


def _land_statistics(
    province_map: np.ndarray, tile_map: np.ndarray
) -> tuple[set[int], np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Calculate per-province pixel counts and projected centroids efficiently."""
    maximum = int(province_map.max())
    flat = province_map.ravel()
    total = np.bincount(flat, minlength=maximum + 1)
    land = np.bincount(
        flat,
        weights=(tile_map.ravel() == TILE_LAND).astype(np.uint8),
        minlength=maximum + 1,
    )
    land_pids = {pid for pid in range(1, maximum + 1) if total[pid] and land[pid] * 2 > total[pid]}

    # Avoid allocating two full image-sized coordinate grids merely for centroids.
    sum_y = np.zeros(maximum + 1, dtype=np.float64)
    sum_x = np.zeros(maximum + 1, dtype=np.float64)
    x_weights = np.arange(province_map.shape[1], dtype=np.float64)
    for row, values in enumerate(province_map):
        row_count = np.bincount(values, minlength=maximum + 1)
        sum_y += row * row_count
        sum_x += np.bincount(values, weights=x_weights, minlength=maximum + 1)
    return land_pids, total, land, sum_x, sum_y


def _build_adjacency(province_map: np.ndarray) -> dict[int, set[int]]:
    """Build a province graph from shared four-neighbour pixel edges."""
    maximum = int(province_map.max())
    base = maximum + 1
    pairs: set[int] = set()
    for first, second in ((province_map[:, :-1], province_map[:, 1:]), (province_map[:-1, :], province_map[1:, :])):
        mask = (first != second) & (first > 0) & (second > 0)
        if not np.any(mask):
            continue
        left = first[mask].astype(np.int64, copy=False)
        right = second[mask].astype(np.int64, copy=False)
        lo = np.minimum(left, right)
        hi = np.maximum(left, right)
        pairs.update(int(value) for value in np.unique(lo * base + hi))
    graph: dict[int, set[int]] = defaultdict(set)
    for packed in pairs:
        left, right = divmod(packed, base)
        graph[left].add(right)
        graph[right].add(left)
    return graph


def _components(pids: Iterable[int], graph: dict[int, set[int]]) -> list[list[int]]:
    pending = set(pids)
    result: list[list[int]] = []
    while pending:
        first = min(pending)
        pending.remove(first)
        queue = deque([first])
        component = [first]
        while queue:
            current = queue.popleft()
            for neighbour in graph.get(current, ()):
                if neighbour in pending:
                    pending.remove(neighbour)
                    queue.append(neighbour)
                    component.append(neighbour)
        result.append(sorted(component))
    return sorted(result, key=lambda component: (-len(component), component[0]))


def _dbf_layout(path: Path) -> tuple[int, int, int, dict[str, tuple[int, int]]]:
    with path.open("rb") as stream:
        header = stream.read(32)
        if len(header) != 32:
            raise AuthoringError(f"Invalid DBF header: {path}")
        records = struct.unpack("<I", header[4:8])[0]
        header_size = struct.unpack("<H", header[8:10])[0]
        record_size = struct.unpack("<H", header[10:12])[0]
        fields: dict[str, tuple[int, int]] = {}
        offset = 1
        while stream.tell() < header_size:
            descriptor = stream.read(32)
            if not descriptor or descriptor[0] == 0x0D:
                break
            name = descriptor[:11].split(b"\x00", 1)[0].decode("ascii", "replace").strip()
            length = descriptor[16]
            fields[name] = (offset, length)
            offset += length
    return records, header_size, record_size, fields


def _read_dbf_row(
    stream: io.BufferedReader,
    index: int,
    header_size: int,
    record_size: int,
    fields: dict[str, tuple[int, int]],
    wanted: Iterable[str],
) -> dict[str, str]:
    stream.seek(header_size + index * record_size)
    row = stream.read(record_size)
    if not row or row[:1] == b"*":
        return {}
    values: dict[str, str] = {}
    for name in wanted:
        definition = fields.get(name)
        if definition is None:
            continue
        start, length = definition
        raw = row[start:start + length].rstrip(b" \x00")
        values[name] = raw.decode("utf-8", "replace").strip()
    return values


def _shx_entries(path: Path) -> list[tuple[int, int]]:
    raw = path.read_bytes()
    if len(raw) < 100 or (len(raw) - 100) % 8:
        raise AuthoringError(f"Invalid SHX file: {path}")
    return [struct.unpack(">2i", raw[position:position + 8]) for position in range(100, len(raw), 8)]


def _shape_parts(stream: io.BufferedReader, offset_words: int, length_words: int) -> tuple[tuple[float, float, float, float], list[np.ndarray]]:
    stream.seek(offset_words * 2)
    record_header = stream.read(8)
    content = stream.read(length_words * 2)
    if len(record_header) != 8 or len(content) < 44:
        return (0.0, 0.0, 0.0, 0.0), []
    shape_type = struct.unpack("<i", content[:4])[0]
    if shape_type not in (5, 15, 25):
        return (0.0, 0.0, 0.0, 0.0), []
    bbox = struct.unpack("<4d", content[4:36])
    part_count, point_count = struct.unpack("<2i", content[36:44])
    if part_count <= 0 or point_count <= 0:
        return bbox, []
    part_start = 44
    point_start = part_start + part_count * 4
    if point_start + point_count * 16 > len(content):
        return bbox, []
    starts = struct.unpack(f"<{part_count}i", content[part_start:point_start])
    raw_points = np.frombuffer(content, dtype="<f8", count=point_count * 2, offset=point_start).reshape((-1, 2))
    result = []
    for part_index, start in enumerate(starts):
        end = starts[part_index + 1] if part_index + 1 < len(starts) else point_count
        if 0 <= start < end <= point_count:
            result.append(raw_points[start:end])
    return bbox, result


def _load_official_communes(cache_dir: Path) -> tuple[dict[tuple[str, str, str], list[Commune]], dict[tuple[str, str], list[Commune]]]:
    path = _cached_download(cache_dir, "COMM_AT_2016.csv", COMMUNE_ATTRIBUTES_URL)
    by_full: dict[tuple[str, str, str], list[Commune]] = defaultdict(list)
    by_name: dict[tuple[str, str], list[Commune]] = defaultdict(list)
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            country = _code(row.get("CNTR_CODE", "")).upper()
            if country not in TARGET_COUNTRIES:
                continue
            commune = Commune(
                country=country,
                comm_id=_code(row.get("COMM_ID", "")),
                name=_clean_label(row.get("COMM_NAME", "")),
                nsi_code=_code(row.get("NSI_CODE", "")),
                name_nsi=_clean_label(row.get("NAME_NSI", "")),
                nuts=_code(row.get("NUTS_CODE", "")),
            )
            keys = {_normalise(commune.name), _normalise(row.get("NAME_ASCI", "")), _normalise(commune.name_nsi)}
            for key in keys - {""}:
                by_name[(country, key)].append(commune)
                by_full[(country, key, commune.nuts[:5])].append(commune)
    return by_full, by_name


def _match_commune(
    local: dict[str, str],
    by_full: dict[tuple[str, str, str], list[Commune]],
    by_name: dict[tuple[str, str], list[Commune]],
) -> Commune | None:
    country = _code(local.get("CNTR_CODE", "")).upper()
    if country not in TARGET_COUNTRIES:
        return None
    raw_names = (local.get("COMM_NAME", ""), local.get("NAME_ASCI", ""), local.get("NAME_NSI", ""))
    nuts_candidates = []
    for field in (local.get("NUTS_CODE", ""), local.get("NAME_LATN", "")):
        match = re.search(r"\b([A-Z]{2,3}\d{2,3})\b", field or "")
        if match:
            nuts_candidates.append(match.group(1)[:5])
    candidates: list[Commune] = []
    for raw_name in raw_names:
        key = _normalise(raw_name)
        if not key:
            continue
        for nuts in nuts_candidates:
            candidates.extend(by_full.get((country, key, nuts), ()))
        if not candidates:
            candidates.extend(by_name.get((country, key), ()))
        if candidates:
            break
    if not candidates:
        return None
    local_nsi = _code(local.get("NSI_CODE", ""))
    exact_nsi = [candidate for candidate in candidates if local_nsi and candidate.nsi_code == local_nsi]
    if exact_nsi:
        candidates = exact_nsi
    elif nuts_candidates:
        exact_nuts = [candidate for candidate in candidates if candidate.nuts[:5] in nuts_candidates]
        if exact_nuts:
            candidates = exact_nuts
    return sorted(candidates, key=lambda candidate: candidate.comm_id)[0]


def _map_source_communes(
    source_dir: Path,
    province_map: np.ndarray,
    tile_map: np.ndarray,
    world: tuple[float, float, float, float, float, float],
    by_full: dict[tuple[str, str, str], list[Commune]],
    by_name: dict[tuple[str, str], list[Commune]],
) -> tuple[dict[int, Commune], dict[str, int]]:
    """Map source polygon representatives back to the generated province IDs."""
    try:
        from shapely.geometry import Polygon, box
    except ImportError as exc:
        raise AuthoringError("State authoring needs shapely; install the project GIS dependencies.") from exc

    shp = source_dir / "COMM_RG_01M_2016_3035.shp"
    shx = source_dir / "COMM_RG_01M_2016_3035.shx"
    dbf = source_dir / "COMM_RG_01M_2016_3035.dbf"
    missing = [str(path) for path in (shp, shx, dbf) if not path.is_file()]
    if missing:
        raise AuthoringError("Missing Eurostat commune source file(s): " + ", ".join(missing))

    pixel_x, _rotation_y, _rotation_x, pixel_y, origin_x, origin_y = world
    height, width = province_map.shape
    map_box = box(
        origin_x - pixel_x / 2.0,
        origin_y + pixel_y * (height - 0.5),
        origin_x + pixel_x * (width - 0.5),
        origin_y - pixel_y / 2.0,
    )
    xmin, ymin, xmax, ymax = map_box.bounds
    entries = _shx_entries(shx)
    dbf_records, dbf_header, dbf_record_size, dbf_fields = _dbf_layout(dbf)
    if len(entries) != dbf_records:
        raise AuthoringError("Commune SHX/DBF record counts differ")

    wanted = ("CNTR_CODE", "COMM_NAME", "NAME_ASCI", "NAME_NSI", "NAME_LATN", "NUTS_CODE", "NSI_CODE")
    winning: dict[int, tuple[float, Commune]] = {}
    stats = Counter()
    with shp.open("rb") as shp_stream, dbf.open("rb") as dbf_stream:
        for index, (offset_words, length_words) in enumerate(entries):
            # The 36 bytes after the record header give shape type + extent.  Avoid
            # reading full geometry for 110k polygons outside the map crop.
            shp_stream.seek(offset_words * 2 + 8)
            preview = shp_stream.read(36)
            if len(preview) != 36 or struct.unpack("<i", preview[:4])[0] not in (5, 15, 25):
                continue
            sxmin, symin, sxmax, symax = struct.unpack("<4d", preview[4:36])
            if sxmax < xmin or sxmin > xmax or symax < ymin or symin > ymax:
                continue
            local = _read_dbf_row(dbf_stream, index, dbf_header, dbf_record_size, dbf_fields, wanted)
            commune = _match_commune(local, by_full, by_name)
            if commune is None:
                stats["unmatched_source_records"] += 1
                continue
            _bbox, parts = _shape_parts(shp_stream, offset_words, length_words)
            best = None
            best_area = 0.0
            for ring in parts:
                if len(ring) < 4:
                    continue
                try:
                    polygon = Polygon(ring)
                    if not polygon.is_valid:
                        polygon = polygon.buffer(0)
                    clipped = polygon.intersection(map_box)
                except Exception:
                    continue
                if clipped.is_empty or clipped.area <= best_area:
                    continue
                best = clipped
                best_area = float(clipped.area)
            if best is None:
                stats["outside_or_invalid_source_records"] += 1
                continue
            point = best.representative_point()
            column, row = _world_to_pixel(point.x, point.y, world)
            pid = _sample_land_pid(province_map, tile_map, column, row)
            if not pid:
                stats["source_records_without_land_pid"] += 1
                continue
            stats["mapped_source_records"] += 1
            previous = winning.get(pid)
            if previous is None or best_area > previous[0]:
                winning[pid] = (best_area, commune)
                if previous is not None:
                    stats["merged_pid_representative_replaced"] += 1
            elif previous is not None:
                stats["merged_pid_representative_retained"] += 1
    return {pid: entry[1] for pid, entry in winning.items()}, dict(stats)


def _map_fragment_centres_from_source_polygons(
    source_dir: Path,
    target_pids: set[int],
    centres: dict[int, tuple[float, float]],
    world: tuple[float, float, float, float, float, float],
    by_full: dict[tuple[str, str, str], list[Commune]],
    by_name: dict[tuple[str, str], list[Commune]],
    province_map: np.ndarray,
) -> tuple[dict[int, Commune], int]:
    """Recover repair-created fragments by testing their centres against source polygons.

    The normal representative-point pass is deliberately light-weight.  Only
    the IDs it cannot identify need this more expensive, but exact, polygon
    containment lookup.  Restricting the STRtree to source features touching
    this map crop keeps the one-time repair path small.
    """
    if not target_pids:
        return {}, 0
    try:
        from shapely.geometry import Point, Polygon, box
        from shapely.strtree import STRtree
    except ImportError as exc:
        raise AuthoringError("Fragment recovery needs shapely.") from exc
    shp = source_dir / "COMM_RG_01M_2016_3035.shp"
    shx = source_dir / "COMM_RG_01M_2016_3035.shx"
    dbf = source_dir / "COMM_RG_01M_2016_3035.dbf"
    pixel_x, _rotation_y, _rotation_x, pixel_y, origin_x, origin_y = world
    height, width = province_map.shape
    map_box = box(
        origin_x - pixel_x / 2.0,
        origin_y + pixel_y * (height - 0.5),
        origin_x + pixel_x * (width - 0.5),
        origin_y - pixel_y / 2.0,
    )
    xmin, ymin, xmax, ymax = map_box.bounds
    entries = _shx_entries(shx)
    dbf_records, dbf_header, dbf_record_size, dbf_fields = _dbf_layout(dbf)
    if len(entries) != dbf_records:
        raise AuthoringError("Commune SHX/DBF record counts differ")
    wanted = ("CNTR_CODE", "COMM_NAME", "NAME_ASCI", "NAME_NSI", "NAME_LATN", "NUTS_CODE", "NSI_CODE")
    geometries: list[Any] = []
    geometry_communes: list[Commune] = []
    with shp.open("rb") as shp_stream, dbf.open("rb") as dbf_stream:
        for index, (offset_words, length_words) in enumerate(entries):
            shp_stream.seek(offset_words * 2 + 8)
            preview = shp_stream.read(36)
            if len(preview) != 36 or struct.unpack("<i", preview[:4])[0] not in (5, 15, 25):
                continue
            sxmin, symin, sxmax, symax = struct.unpack("<4d", preview[4:36])
            if sxmax < xmin or sxmin > xmax or symax < ymin or symin > ymax:
                continue
            local = _read_dbf_row(dbf_stream, index, dbf_header, dbf_record_size, dbf_fields, wanted)
            commune = _match_commune(local, by_full, by_name)
            if commune is None:
                continue
            _bbox, parts = _shape_parts(shp_stream, offset_words, length_words)
            best = None
            best_area = 0.0
            for ring in parts:
                if len(ring) < 4:
                    continue
                try:
                    polygon = Polygon(ring)
                    if not polygon.is_valid:
                        polygon = polygon.buffer(0)
                    clipped = polygon.intersection(map_box)
                except Exception:
                    continue
                if not clipped.is_empty and clipped.area > best_area:
                    best, best_area = clipped, float(clipped.area)
            if best is not None:
                geometries.append(best)
                geometry_communes.append(commune)
    if not geometries:
        return {}, 0
    tree = STRtree(geometries)
    recovered: dict[int, Commune] = {}
    for pid in sorted(target_pids):
        column, row = centres[pid]
        x, y = _pixel_to_world(column, row, world)
        point = Point(x, y)
        for hit in tree.query(point):
            if isinstance(hit, (int, np.integer)):
                index = int(hit)
            else:
                try:
                    index = geometries.index(hit)
                except ValueError:
                    continue
            if geometries[index].covers(point):
                recovered[pid] = geometry_communes[index]
                break
    return recovered, len(geometries)


def _fill_unmapped_provinces(
    land_pids: set[int],
    mapped: dict[int, Commune],
    graph: dict[int, set[int]],
    centres: dict[int, tuple[float, float]],
) -> tuple[dict[int, Commune], int, int]:
    """Adopt a mapped neighbour for rare IDs changed by the raster repair pass."""
    pending = set(land_pids) - set(mapped)
    filled = 0
    while pending:
        choices: list[tuple[int, Commune]] = []
        for pid in sorted(pending):
            neighbours = [mapped[other] for other in graph.get(pid, ()) if other in mapped]
            if neighbours:
                choices.append((pid, Counter(neighbours).most_common(1)[0][0]))
        if not choices:
            break
        for pid, commune in choices:
            mapped[pid] = commune
            pending.remove(pid)
            filled += 1
    # Raster repair can leave a tiny island or a one-province landmass with no
    # shared border.  It has no neighbouring source ID to inherit, so use its
    # nearest mapped province as a documented final fallback.  This is only
    # reached after exact source-polygon matching and shared-border adoption.
    nearest_filled = 0
    if pending:
        known_pids = np.asarray(sorted(mapped), dtype=np.int64)
        known_centres = np.asarray([centres[pid] for pid in known_pids], dtype=np.float64)
        for pid in sorted(pending):
            point = np.asarray(centres[pid], dtype=np.float64)
            nearest = int(known_pids[np.argmin(np.sum((known_centres - point) ** 2, axis=1))])
            mapped[pid] = mapped[nearest]
            nearest_filled += 1
    return mapped, filled, nearest_filled


def _read_tabular_zip(path: Path, wanted_suffix: str) -> list[dict[str, str]]:
    """Read the first matching INSEE tab-separated file, handling Latin-1 COG text."""
    with zipfile.ZipFile(path) as archive:
        name = next((item for item in archive.namelist() if item.lower().endswith(wanted_suffix.lower())), None)
        if name is None:
            raise AuthoringError(f"{path.name} does not contain {wanted_suffix}")
        data = archive.read(name)
    text = data.decode("latin-1")
    return list(csv.DictReader(io.StringIO(text), delimiter="\t"))


def _load_french_arrondissements(cache_dir: Path) -> tuple[dict[str, tuple[str, str]], dict[tuple[str, str], str]]:
    communes_file = _cached_download(cache_dir, "comsimp2016-txt.zip", FR_COMMUNE_2016_URL)
    arr_file = _cached_download(cache_dir, "arrond2016-txt.zip", FR_ARRONDISSEMENT_2016_URL)
    commune_rows = _read_tabular_zip(communes_file, "comsimp2016.txt")
    arr_rows = _read_tabular_zip(arr_file, "arrond2016.txt")
    commune_to_arr: dict[str, tuple[str, str]] = {}
    for row in commune_rows:
        dep = _code(row.get("DEP", ""))
        code = _code(row.get("COM", ""), 3)
        arr = _code(row.get("AR", ""))
        if dep and code and arr:
            commune_to_arr[f"{dep}{code}"] = (dep, arr)
    arr_names: dict[tuple[str, str], str] = {}
    for row in arr_rows:
        dep = _code(row.get("DEP", ""))
        arr = _code(row.get("AR", ""))
        name = _clean_label(row.get("NCCENR", "") or row.get("NCC", "") or row.get("LIBELLE", ""))
        if dep and arr:
            arr_names[(dep, arr)] = name.title() if name.isupper() else name
    return commune_to_arr, arr_names


def _load_french_epci(cache_dir: Path) -> dict[str, tuple[str, str]]:
    """Return 2016 commune -> (EPCI id, EPCI name), if xlrd is available."""
    try:
        import xlrd  # type: ignore[import-not-found]
    except ImportError as exc:
        raise AuthoringError(
            "French EPCI splitting needs xlrd. Install xlrd or rerun with --skip-epci."
        ) from exc
    path = _cached_download(cache_dir, "Intercommunalite_Metropole_au_01-01-2016.zip", FR_EPCI_2016_URL)
    with zipfile.ZipFile(path) as archive:
        name = next((item for item in archive.namelist() if item.lower().endswith(".xls")), None)
        if name is None:
            raise AuthoringError("The 2016 EPCI download has no XLS workbook")
        content = archive.read(name)
    book = xlrd.open_workbook(file_contents=content)
    try:
        sheet = book.sheet_by_name("Composition_communale")
    except xlrd.biffh.XLRDError as exc:
        raise AuthoringError("The 2016 EPCI workbook has no Composition_communale sheet") from exc
    result: dict[str, tuple[str, str]] = {}
    # The archive's first five rows are titles and column labels; identify rows
    # defensively rather than assuming every historical download is identical.
    for row_index in range(sheet.nrows):
        values = [_code(sheet.cell_value(row_index, col)) for col in range(min(sheet.ncols, 6))]
        if len(values) < 4 or not re.fullmatch(r"(?:\d{5}|2[AB]\d{3})", values[0]):
            continue
        epci_id, epci_name = values[2], _clean_label(str(sheet.cell_value(row_index, 3)))
        if epci_id and epci_name:
            result[values[0]] = (epci_id, epci_name)
    if not result:
        raise AuthoringError("No commune/EPCI links were read from the 2016 EPCI workbook")
    return result


def _load_nuts_names(cache_dir: Path) -> dict[str, str]:
    path = _cached_download(cache_dir, "NUTS_RG_01M_2016_3035_LEVL_3.geojson", NUTS_2016_URL)
    data = json.loads(path.read_text(encoding="utf-8"))
    names: dict[str, str] = {}
    for feature in data.get("features", []):
        properties = feature.get("properties", {})
        code = _code(properties.get("NUTS_ID", ""))
        name = _clean_label(
            properties.get("NUTS_NAME", "")
            or properties.get("NAME_LATN", "")
            or properties.get("NAME_ENGL", ""),
            code,
        )
        if code:
            names[code] = name
    return names


def _load_polygon_lookup(cache_dir: Path, filename: str, url: str) -> tuple[list[Any], list[dict[str, Any]]]:
    try:
        from shapely.geometry import shape
    except ImportError as exc:
        raise AuthoringError("Administrative polygon assignment needs shapely.") from exc
    path = _cached_download(cache_dir, filename, url)
    data = json.loads(path.read_text(encoding="utf-8"))
    geometries: list[Any] = []
    properties: list[dict[str, Any]] = []
    for feature in data.get("features", []):
        geometry = feature.get("geometry")
        if not geometry:
            continue
        candidate = shape(geometry)
        if candidate.is_empty:
            continue
        geometries.append(candidate)
        properties.append(feature.get("properties", {}))
    if not geometries:
        raise AuthoringError(f"No usable polygons found in {filename}")
    return geometries, properties


def _assign_polygons_to_provinces(
    pids: Iterable[int],
    centres: dict[int, tuple[float, float]],
    world: tuple[float, float, float, float, float, float],
    geometries: list[Any],
    properties: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Assign projected province centres to a small WGS84 administrative layer."""
    try:
        from pyproj import Transformer
        from shapely.geometry import Point
        from shapely.strtree import STRtree
    except ImportError as exc:
        raise AuthoringError("Administrative polygon assignment needs pyproj and shapely.") from exc
    tree = STRtree(geometries)
    transform = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True)
    result: dict[int, dict[str, Any]] = {}
    for pid in pids:
        centre = centres.get(pid)
        if centre is None:
            continue
        x, y = _pixel_to_world(centre[0], centre[1], world)
        longitude, latitude = transform.transform(x, y)
        point = Point(longitude, latitude)
        hits = tree.query(point)
        for hit in hits:
            # Shapely 2 returns indexes; older installations return geometry
            # objects.  Keeping this compatibility costs little and makes reruns
            # useful on an older workstation.
            if isinstance(hit, (int, np.integer)):
                index = int(hit)
            else:
                try:
                    index = geometries.index(hit)
                except ValueError:
                    continue
            if geometries[index].covers(point):
                result[pid] = properties[index]
                break
    return result


def _province_centres(
    total_pixels: np.ndarray, sum_x: np.ndarray, sum_y: np.ndarray
) -> dict[int, tuple[float, float]]:
    return {
        pid: (float(sum_x[pid] / total_pixels[pid]), float(sum_y[pid] / total_pixels[pid]))
        for pid in range(1, len(total_pixels))
        if total_pixels[pid] > 0
    }


def _load_cities(
    cache_dir: Path,
    province_map: np.ndarray,
    tile_map: np.ndarray,
    world: tuple[float, float, float, float, float, float],
    province_country: dict[int, str],
) -> list[City]:
    """Read GeoNames populated places and attach them to map provinces."""
    try:
        from pyproj import Transformer
    except ImportError as exc:
        raise AuthoringError("City assignment needs pyproj.") from exc
    path = _cached_download(cache_dir, "cities500.zip", GEONAMES_CITIES_URL)
    transform = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
    best_per_pid: dict[int, City] = {}
    with zipfile.ZipFile(path) as archive:
        name = next((item for item in archive.namelist() if item.endswith("cities500.txt")), None)
        if name is None:
            raise AuthoringError("GeoNames cities500 download has no cities500.txt")
        with archive.open(name) as raw:
            for binary_line in raw:
                fields = binary_line.decode("utf-8", "replace").rstrip("\n").split("\t")
                if len(fields) < 15:
                    continue
                country = GEONAMES_TO_PROJECT_COUNTRY.get(fields[8])
                if country is None:
                    continue
                try:
                    latitude, longitude = float(fields[4]), float(fields[5])
                    population = int(fields[14] or 0)
                except ValueError:
                    continue
                if population <= 0:
                    continue
                x, y = transform.transform(longitude, latitude)
                column, row = _world_to_pixel(x, y, world)
                pid = _sample_land_pid(province_map, tile_map, column, row)
                if not pid or province_country.get(pid) != country:
                    continue
                city = City(
                    pid=pid,
                    country=country,
                    name=_clean_label(fields[1], fields[2]),
                    name_en=_clean_label(fields[2], fields[1]),
                    population=population,
                )
                existing = best_per_pid.get(pid)
                if existing is None or city.population > existing.population:
                    best_per_pid[pid] = city
    return sorted(best_per_pid.values(), key=lambda city: (city.country, -city.population, city.name))


def _load_eurostat_density(cache_dir: Path, nuts_codes: Iterable[str]) -> tuple[dict[str, float], dict[str, str]]:
    """Fetch 2016 NUTS3 population density, returning source notes per code."""
    codes = sorted({code for code in nuts_codes if code})
    values: dict[str, float] = {}
    provenance: dict[str, str] = {}
    for start in range(0, len(codes), 80):
        batch = codes[start:start + 80]
        query = urllib.parse.urlencode([("time", "2016"), ("unit", "PER_KM2")] + [("geo", code) for code in batch])
        digest = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
        path = _cached_download(cache_dir, f"demo_r_d3dens_2016_{digest}.json", f"{EUROSTAT_DENSITY_URL}?{query}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            dimensions = payload["dimension"]
            ids = payload["id"]
            sizes = payload["size"]
            geo_position = ids.index("geo")
            stride = math.prod(sizes[geo_position + 1:])
            indexes = dimensions["geo"]["category"]["index"]
            raw_values = payload.get("value", {})
            for code, position in indexes.items():
                raw = raw_values.get(str(int(position) * stride))
                if raw is not None:
                    values[code] = float(raw)
                    provenance[code] = "Eurostat demo_r_d3dens, 2016"
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AuthoringError(f"Could not parse Eurostat density response {path.name}: {exc}") from exc
    return values, provenance


def _majority_nuts2(pids: Iterable[int], provinces: dict[int, ProvinceInfo]) -> str:
    nuts2 = [provinces[pid].nuts[:4] for pid in pids if pid in provinces and provinces[pid].nuts]
    return Counter(nuts2).most_common(1)[0][0] if nuts2 else ""


def _make_group(
    key: str,
    country: str,
    name: str,
    scheme: str,
    pids: Iterable[int],
    provinces: dict[int, ProvinceInfo],
) -> Group:
    ordered = sorted(set(pids))
    return Group(
        key=key,
        country=country,
        name=_clean_label(name, key),
        name_en=_clean_label(name, key),
        scheme=scheme,
        pids=ordered,
        nuts2=_majority_nuts2(ordered, provinces),
    )


def _split_group_components(
    groups: Iterable[Group], graph: dict[int, set[int]], provinces: dict[int, ProvinceInfo]
) -> list[Group]:
    """Split rare exclaves so each state can live in one strategic region."""
    result: list[Group] = []
    for group in groups:
        parts = _components(group.pids, graph)
        for index, part in enumerate(parts, start=1):
            if index == 1:
                result.append(group)
                group.pids = part
                continue
            locality = _clean_label(provinces[part[0]].commune.name_nsi or provinces[part[0]].commune.name, f"component {index}")
            suffix = f" – {locality}"
            result.append(
                Group(
                    key=f"{group.key}:detached:{index}",
                    country=group.country,
                    name=group.name + suffix,
                    name_en=group.name_en + suffix,
                    scheme=group.scheme + " detached component",
                    pids=part,
                    nuts2=group.nuts2,
                    detached_index=index,
                )
            )
    return result


def _unique_group_names(groups: list[Group]) -> None:
    """Avoid duplicate localisation labels while retaining authoritative names."""
    by_name: dict[str, list[Group]] = defaultdict(list)
    for group in groups:
        by_name[_normalise(group.name)].append(group)
    for identical in by_name.values():
        if len(identical) < 2:
            continue
        for group in identical:
            group.name = f"{group.name} ({COUNTRIES[group.country]['name']})"
            group.name_en = f"{group.name_en} ({COUNTRIES[group.country]['name']})"


def _build_groups(
    provinces: dict[int, ProvinceInfo],
    graph: dict[int, set[int]],
    nuts_names: dict[str, str],
    french_arr: dict[str, tuple[str, str]],
    french_arr_names: dict[tuple[str, str], str],
    french_epci: dict[str, tuple[str, str]],
    lux_cantons: dict[int, dict[str, Any]],
    rlp_vgs: dict[int, dict[str, Any]],
    fr_split_threshold: int,
    epci_min_provinces: int,
    rlp_split_threshold: int,
    vg_min_provinces: int,
) -> list[Group]:
    """Turn province-level source identifiers into the selected state scheme."""
    groups: list[Group] = []
    by_country: dict[str, list[int]] = defaultdict(list)
    for pid, info in provinces.items():
        by_country[info.country].append(pid)

    # Belgium: NUTS3 is exactly the arrondissement level used by the proposal.
    for country in ("BE", "NL", "DE"):
        initial: dict[str, list[int]] = defaultdict(list)
        for pid in by_country[country]:
            initial[provinces[pid].nuts or "UNKNOWN"].append(pid)
        for nuts, pids in sorted(initial.items()):
            display = nuts_names.get(nuts, nuts)
            if country == "BE":
                display = re.sub(r"^Arr\.\s*", "", display, flags=re.IGNORECASE)
                groups.append(_make_group(f"BE:ARR:{nuts}", country, f"Arrondissement {display}", "Belgian arrondissement (NUTS 3)", pids, provinces))
                continue
            if country == "NL":
                groups.append(_make_group(f"NL:COROP:{nuts}", country, display, "Dutch COROP / NUTS 3", pids, provinces))
                continue

            # Germany normally remains at Kreis/NUTS3.  Large Rheinland-
            # Palatinate groups use the published Verbandsgemeinde layer.
            if nuts.startswith("DEB") and len(pids) >= rlp_split_threshold:
                assigned: set[int] = set()
                vg_groups: dict[str, tuple[str, list[int]]] = {}
                for pid in pids:
                    feature = rlp_vgs.get(pid)
                    if feature is None:
                        continue
                    vg_code = _code(feature.get("code", "")) or _clean_label(feature.get("name", ""))
                    vg_name = _clean_label(feature.get("name", ""), vg_code)
                    vg_groups.setdefault(vg_code, (vg_name, []))[1].append(pid)
                for vg_code, (vg_name, vg_pids) in sorted(vg_groups.items()):
                    if len(vg_pids) >= vg_min_provinces:
                        groups.append(_make_group(
                            f"DE:VG:{vg_code}", country, f"Verbandsgemeinde {vg_name}",
                            "Rhineland-Palatinate Verbandsgemeinde", vg_pids, provinces,
                        ))
                        assigned.update(vg_pids)
                remaining = sorted(set(pids) - assigned)
                if remaining:
                    groups.append(_make_group(
                        f"DE:KREIS:{nuts}:remainder", country, display,
                        "German Kreis / NUTS 3 (Verbandsgemeinde remainder)", remaining, provinces,
                    ))
            else:
                groups.append(_make_group(f"DE:KREIS:{nuts}", country, display, "German Kreis / NUTS 3", pids, provinces))

    # France: arrondissement base, selectively split only materially large
    # groups by the membership in the 2016 EPCI table.
    france_arr_groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for pid in by_country["FR"]:
        nsi = provinces[pid].commune.nsi_code
        arr = french_arr.get(nsi)
        if arr is None:
            # A small number of changed/cross-border codes are still grouped
            # at their source NUTS3 instead of being guessed into an arrondissement.
            arr = (provinces[pid].nuts, "")
        france_arr_groups[arr].append(pid)
    for (department, arr_code), pids in sorted(france_arr_groups.items()):
        arr_label = french_arr_names.get((department, arr_code), nuts_names.get(department, department))
        base_name = f"Arrondissement de {arr_label}"
        if not french_epci or len(pids) < fr_split_threshold:
            groups.append(_make_group(f"FR:ARR:{department}:{arr_code}", "FR", base_name, "French arrondissement (2016)", pids, provinces))
            continue
        assigned: set[int] = set()
        epci_groups: dict[str, tuple[str, list[int]]] = {}
        for pid in pids:
            entry = french_epci.get(provinces[pid].commune.nsi_code)
            if entry is None:
                continue
            epci_id, epci_name = entry
            epci_groups.setdefault(epci_id, (epci_name, []))[1].append(pid)
        for epci_id, (epci_name, epci_pids) in sorted(epci_groups.items()):
            if len(epci_pids) >= epci_min_provinces:
                groups.append(_make_group(
                    f"FR:EPCI:{epci_id}", "FR", epci_name,
                    "French EPCI (2016; split from large arrondissement)", epci_pids, provinces,
                ))
                assigned.update(epci_pids)
        remaining = sorted(set(pids) - assigned)
        if remaining:
            suffix = " (remainder)" if assigned else ""
            groups.append(_make_group(
                f"FR:ARR:{department}:{arr_code}:remainder", "FR", base_name + suffix,
                "French arrondissement (2016; EPCI remainder)", remaining, provinces,
            ))

    # Luxembourg: feature assignment uses cantons rather than the single NUTS3
    # region.  Any edge pixels not covered by a centroid retain their proper
    # surrounding canton state instead of being dropped.
    lux_groups: dict[str, tuple[str, list[int]]] = {}
    for pid in by_country["LU"]:
        feature = lux_cantons.get(pid)
        code = _code(feature.get("code", "")) if feature else "UNMATCHED"
        name = _clean_label(feature.get("name", ""), code) if feature else "Luxembourg canton remainder"
        lux_groups.setdefault(code, (name, []))[1].append(pid)
    for code, (name, pids) in sorted(lux_groups.items()):
        groups.append(_make_group(f"LU:CANTON:{code}", "LU", f"Canton {name}", "Luxembourg canton", pids, provinces))

    # Eurostat's COMM layer carries the parent local-authority code/name for
    # UK small areas.  It is the only national administrative hierarchy common
    # to every part of the cropped English map.
    uk_groups: dict[str, tuple[str, list[int]]] = {}
    for pid in by_country["UK"]:
        commune = provinces[pid].commune
        code = commune.nsi_code or commune.name_nsi or commune.nuts
        name = commune.name_nsi or commune.nuts or "United Kingdom local authority"
        uk_groups.setdefault(code, (name, []))[1].append(pid)
    for code, (name, pids) in sorted(uk_groups.items()):
        groups.append(_make_group(f"UK:LA:{code}", "UK", name, "United Kingdom local authority", pids, provinces))

    groups = _split_group_components(groups, graph, provinces)
    _unique_group_names(groups)
    known = set().union(*(set(group.pids) for group in groups)) if groups else set()
    expected = set(provinces)
    if known != expected:
        missing = expected - known
        duplicate_count = sum(len(group.pids) for group in groups) - len(known)
        raise AuthoringError(
            f"Administrative grouping did not form a partition (missing={len(missing)}, duplicate assignments={duplicate_count})"
        )
    return sorted(groups, key=lambda group: (COUNTRY_ORDER[group.country], group.name.casefold(), group.key))


def _victory_point_value(population: int) -> int:
    if population >= 2_000_000:
        return 50
    if population >= 1_000_000:
        return 40
    if population >= 500_000:
        return 30
    if population >= 200_000:
        return 20
    if population >= 100_000:
        return 10
    if population >= 50_000:
        return 5
    return 3


def _state_category(manpower: int, largest_city: int) -> str:
    if manpower >= 3_000_000 or largest_city >= 2_000_000:
        return "megalopolis"
    if manpower >= 1_200_000 or largest_city >= 900_000:
        return "large_city"
    if manpower >= 450_000 or largest_city >= 300_000:
        return "city"
    if manpower >= 150_000 or largest_city >= 100_000:
        return "large_town"
    if manpower >= 50_000:
        return "town"
    if manpower >= 20_000:
        return "rural"
    return "pastoral"


def _state_buildings(manpower: int, largest_city: int, coastal: bool, city_pid: int | None) -> tuple[dict[str, int], dict[int, dict[str, int]]]:
    category_infrastructure = {
        "pastoral": 1, "rural": 1, "town": 2, "large_town": 2,
        "city": 3, "large_city": 4, "megalopolis": 5,
    }
    category = _state_category(manpower, largest_city)
    buildings: dict[str, int] = {"infrastructure": category_infrastructure[category]}
    civilian = 0
    for threshold in (150_000, 400_000, 900_000, 1_800_000, 3_000_000):
        civilian += manpower >= threshold
    if civilian:
        buildings["industrial_complex"] = civilian
    military = 0
    for threshold in (600_000, 1_700_000):
        military += manpower >= threshold or largest_city >= threshold // 2
    if military:
        buildings["arms_factory"] = military
    if largest_city >= 250_000 or manpower >= 900_000:
        buildings["air_base"] = 1 + int(largest_city >= 1_000_000)
    province_buildings: dict[int, dict[str, int]] = {}
    if coastal and city_pid is not None and largest_city >= 70_000:
        buildings["dockyard"] = 1 + int(largest_city >= 500_000)
        province_buildings[city_pid] = {"naval_base": 1 + int(largest_city >= 500_000)}
    return buildings, province_buildings


def _state_resources(country: str, state_name: str, cities: Iterable[City], manpower: int) -> dict[str, int]:
    searchable = " ".join([state_name, *(city.name for city in cities)]).casefold()
    if any(centre.casefold() in searchable for centre in STEEL_CENTRES.get(country, ())):
        return {"steel": 8 if manpower < 500_000 else 16 if manpower < 1_500_000 else 24}
    return {}


def _create_strategic_regions(
    province_map: np.ndarray,
    tile_map: np.ndarray,
    state_mgr: StateManager,
    state_groups: dict[int, Group],
    graph: dict[int, set[int]],
    land_pids: set[int],
    sea_pids: set[int],
) -> StrategicRegionManager:
    """Make connected, state-safe regions from NUTS2-scale state clusters."""
    manager = StrategicRegionManager()
    regional_pids: dict[tuple[str, str], list[int]] = defaultdict(list)
    for sid, state in state_mgr.states.items():
        group = state_groups[sid]
        regional_pids[(group.country, group.nuts2 or group.country)].extend(state.provinces)
    pid_to_region: dict[int, int] = {}
    for (country, nuts2), pids in sorted(regional_pids.items(), key=lambda item: (COUNTRY_ORDER[item[0][0]], item[0][1])):
        for component_index, component in enumerate(_components(pids, graph), start=1):
            region = manager.create_region(f"{COUNTRIES[country]['name']} {nuts2}")
            if component_index > 1:
                region.name += f" {component_index}"
            region.province_ids = component
            region.weather_preset = "temperate"
            for pid in component:
                pid_to_region[pid] = region.id

    all_pids = {int(pid) for pid in np.unique(province_map) if pid > 0}
    lake_pids = all_pids - land_pids - sea_pids
    # Inland water can share the adjacent land strategic region: it remains
    # pixel-connected and avoids turning every small lake into its own region.
    # This does not affect state membership because states contain land only.
    for component in _components(lake_pids, graph):
        bordering_regions = sorted({
            pid_to_region[neighbour]
            for pid in component
            for neighbour in graph.get(pid, ())
            if neighbour in pid_to_region
        })
        if bordering_regions:
            region = manager.get(bordering_regions[0])
            if region is not None:
                region.province_ids.extend(component)
                for pid in component:
                    pid_to_region[pid] = region.id
                continue
        # A genuinely isolated lake has no valid land attachment; keep it a
        # standalone shallow-water region rather than assigning it arbitrarily.
        region = manager.create_region("Inland water")
        region.province_ids = component
        region.naval_terrain = "water_shallow_sea"
        region.weather_preset = "temperate"
        for pid in component:
            pid_to_region[pid] = region.id

    # True sea provinces stay separate from land strategic regions.
    for component_index, component in enumerate(_components(sea_pids, graph), start=1):
        region = manager.create_region("North Sea" if component_index == 1 else f"Water region {component_index}")
        region.province_ids = component
        region.naval_terrain = "water_deep_ocean"
        region.weather_preset = "temperate"
    return manager


def _is_coastal(pids: Iterable[int], graph: dict[int, set[int]], sea_pids: set[int]) -> bool:
    return any(neighbour in sea_pids for pid in pids for neighbour in graph.get(pid, ()))


def _round_manpower(value: float) -> int:
    return max(1_000, int(round(value / 100.0) * 100))


def _build_report_state(
    state: Any,
    group: Group,
    area_km2: float,
    cities: list[City],
) -> dict[str, Any]:
    return {
        "id": state.id,
        "name": state.name,
        "name_en": state.name_en,
        "country": group.country,
        "owner_tag": state.owner_tag,
        "scheme": group.scheme,
        "nuts2_strategic_region_key": group.nuts2,
        "province_count": len(state.provinces),
        "province_ids": list(state.provinces),
        "area_km2": round(area_km2, 3),
        "manpower": state.manpower,
        "category": state.category,
        "buildings": state.buildings,
        "province_buildings": state.province_buildings,
        "resources": state.resources,
        "victory_points": [
            {
                "province_id": pid,
                "value": value,
                "name": state.vp_names.get(pid, ""),
                "name_en": state.vp_names_en.get(pid, ""),
            }
            for pid, value in sorted(state.victory_points.items())
        ],
        "cities_considered": [
            {"province_id": city.pid, "name": city.name, "population": city.population}
            for city in sorted(cities, key=lambda city: -city.population)
        ],
    }


def author_project(args: argparse.Namespace) -> dict[str, Any]:
    project = Path(args.project).resolve()
    source_dir = Path(args.source_dir).resolve()
    report_path = Path(args.report).resolve()
    cache_dir = Path(args.cache_dir).resolve()
    if not project.is_file():
        raise AuthoringError(f"Project not found: {project}")
    if not source_dir.is_dir():
        raise AuthoringError(f"Eurostat source directory not found: {source_dir}")

    states = StateManager()
    countries = CountryManager()
    continents = ContinentManager()
    old_regions = StrategicRegionManager()
    tile_map, province_map, terrain_map, height_map, river_map, provincial_terrain, tile_snapshot = load_project(
        str(project), states, countries, continent_mgr=continents, strategic_region_mgr=old_regions,
    )
    if (states.states or countries.countries) and not args.replace_existing:
        raise AuthoringError(
            "The project already has authored states/countries. Use --replace-existing only after reviewing "
            "the .pre_state_authoring.bak backup."
        )
    if int(province_map.max()) == 0:
        raise AuthoringError("Project has no province map")
    world = _read_world_file(source_dir / "test3.pgw")
    land_pids, total_pixels, land_pixels, sum_x, sum_y = _land_statistics(province_map, tile_map)
    centres = _province_centres(total_pixels, sum_x, sum_y)
    graph = _build_adjacency(province_map)
    sea_counts = np.bincount(
        province_map.ravel(), weights=(tile_map.ravel() == TILE_SEA).astype(np.uint8), minlength=len(total_pixels),
    )
    sea_pids = {pid for pid in range(1, len(total_pixels)) if sea_counts[pid] * 2 > total_pixels[pid]}

    by_full, by_name = _load_official_communes(cache_dir)
    mapped, mapping_stats = _map_source_communes(source_dir, province_map, tile_map, world, by_full, by_name)
    fragment_matches, spatial_polygon_candidates = _map_fragment_centres_from_source_polygons(
        source_dir, land_pids - set(mapped), centres, world, by_full, by_name, province_map,
    )
    mapped.update(fragment_matches)
    mapped, filled_by_neighbour, filled_by_nearest = _fill_unmapped_provinces(land_pids, mapped, graph, centres)

    provinces: dict[int, ProvinceInfo] = {}
    for pid in sorted(land_pids):
        centre = centres.get(pid)
        if centre is None:
            raise AuthoringError(f"Land province {pid} has no pixel centre")
        provinces[pid] = ProvinceInfo(
            pid=pid,
            commune=mapped[pid],
            land_pixels=int(land_pixels[pid]),
            x=centre[0],
            y=centre[1],
        )
    province_country = {pid: info.country for pid, info in provinces.items()}

    nuts_names = _load_nuts_names(cache_dir)
    french_arr, french_arr_names = _load_french_arrondissements(cache_dir)
    french_epci = {} if args.skip_epci else _load_french_epci(cache_dir)
    lux_geometries, lux_properties = _load_polygon_lookup(cache_dir, "cantons-lux-2024.geojson", LUX_CANTON_URL)
    lux_cantons = _assign_polygons_to_provinces(
        (pid for pid, info in provinces.items() if info.country == "LU"), centres, world, lux_geometries, lux_properties,
    )
    rlp_geometries, rlp_properties = _load_polygon_lookup(cache_dir, "verbandsgemeinde-rlp-2024.geojson", RLP_VERBANDSGEMEINDE_URL)
    rlp_vgs = _assign_polygons_to_provinces(
        (pid for pid, info in provinces.items() if info.country == "DE" and info.nuts.startswith("DEB")),
        centres, world, rlp_geometries, rlp_properties,
    )
    groups = _build_groups(
        provinces=provinces,
        graph=graph,
        nuts_names=nuts_names,
        french_arr=french_arr,
        french_arr_names=french_arr_names,
        french_epci=french_epci,
        lux_cantons=lux_cantons,
        rlp_vgs=rlp_vgs,
        fr_split_threshold=args.fr_split_threshold,
        epci_min_provinces=args.epci_min_provinces,
        rlp_split_threshold=args.rlp_split_threshold,
        vg_min_provinces=args.vg_min_provinces,
    )

    cities = _load_cities(cache_dir, province_map, tile_map, world, province_country)
    states.clear()
    countries.clear()
    state_groups: dict[int, Group] = {}
    for group in groups:
        state = states.create_state(group.pids)
        state.name = group.name
        state.name_en = group.name_en
        state.owner_tag = COUNTRIES[group.country]["tag"]
        state_groups[state.id] = group

    # Create countries before assigning their state ownership.  Vanilla tags are
    # intentional here: these are the historical countries represented by map.
    for country_code in TARGET_COUNTRIES:
        spec = COUNTRIES[country_code]
        country = countries.create_country(spec["tag"], spec["name"], spec["color"], allow_vanilla_tag=True)
        country.ruling_party = spec["party"]
        country.popularities = dict(spec["popularities"])
    for sid, state in states.states.items():
        countries.assign_state(sid, state.owner_tag)

    city_by_state: dict[int, list[City]] = defaultdict(list)
    for city in cities:
        sid = states.get_state_of_province(city.pid)
        if sid:
            city_by_state[sid].append(city)

    pixel_area_km2 = abs(world[0] * world[3]) / 1_000_000.0
    state_area = {
        sid: sum(int(land_pixels[pid]) * pixel_area_km2 for pid in state.provinces)
        for sid, state in states.states.items()
    }
    nuts_pids: dict[str, list[int]] = defaultdict(list)
    for pid, info in provinces.items():
        nuts_pids[info.nuts].append(pid)
    try:
        densities, density_provenance = _load_eurostat_density(cache_dir, nuts_pids)
        density_error = ""
    except AuthoringError as exc:
        # The fallback is explicit in the audit report, rather than pretending
        # an unavailable live API returned data.
        densities, density_provenance, density_error = {}, {}, str(exc)

    pid_to_state = {pid: sid for sid, state in states.states.items() for pid in state.provinces}
    estimated_population: dict[int, float] = defaultdict(float)
    density_sources: dict[str, dict[str, Any]] = {}
    for nuts, pids in nuts_pids.items():
        if not pids:
            continue
        country = provinces[pids[0]].country
        density = densities.get(nuts, FALLBACK_DENSITY[country])
        source = density_provenance.get(nuts, f"fallback national density for {country}")
        area = sum(int(land_pixels[pid]) * pixel_area_km2 for pid in pids)
        total_population = area * density
        per_state_area: dict[int, float] = defaultdict(float)
        per_state_cities: dict[int, int] = defaultdict(int)
        for pid in pids:
            per_state_area[pid_to_state[pid]] += int(land_pixels[pid]) * pixel_area_km2
        for city in cities:
            if city.pid in provinces and provinces[city.pid].nuts == nuts:
                per_state_cities[pid_to_state[city.pid]] += city.population
        city_sum = sum(per_state_cities.values())
        urban_population = min(total_population * 0.75, float(city_sum)) if city_sum else 0.0
        rural_population = total_population - urban_population
        for sid, sid_area in per_state_area.items():
            estimated_population[sid] += rural_population * sid_area / area
            if city_sum:
                estimated_population[sid] += urban_population * per_state_cities.get(sid, 0) / city_sum
        density_sources[nuts] = {
            "density_per_km2": density,
            "source": source,
            "map_land_area_km2": round(area, 3),
            "estimated_map_population": round(total_population),
        }

    for sid, state in states.states.items():
        city_list = city_by_state.get(sid, [])
        largest = max((city.population for city in city_list), default=0)
        largest_city = max(city_list, key=lambda city: city.population, default=None)
        manpower = _round_manpower(estimated_population[sid])
        state.manpower = manpower
        state.category = _state_category(manpower, largest)
        state.buildings, state.province_buildings = _state_buildings(
            manpower,
            largest,
            _is_coastal(state.provinces, graph, sea_pids),
            largest_city.pid if largest_city else None,
        )
        state.resources = _state_resources(state_groups[sid].country, state.name, city_list, manpower)
        for city in city_list:
            if city.population >= args.vp_min_population:
                state.victory_points[city.pid] = _victory_point_value(city.population)
                state.vp_names[city.pid] = city.name
                state.vp_names_en[city.pid] = city.name_en

    capital_report: list[dict[str, Any]] = []
    for country_code in TARGET_COUNTRIES:
        tag = COUNTRIES[country_code]["tag"]
        country_cities = sorted((city for city in cities if city.country == country_code), key=lambda city: -city.population)
        wanted = {_normalise(name) for name in COUNTRIES[country_code]["capital_names"]}
        capital_city = next((city for city in country_cities if _normalise(city.name) in wanted or _normalise(city.name_en) in wanted), None)
        is_substitute = capital_city is None
        if capital_city is None and country_cities:
            capital_city = country_cities[0]
        if capital_city is None:
            owned_states = countries.get_states_of_country(tag)
            if not owned_states:
                raise AuthoringError(f"No authored territory exists for {tag}")
            capital_pid = states.get_state(owned_states[0]).provinces[0]  # type: ignore[union-attr]
            capital_name = f"Province {capital_pid}"
        else:
            capital_pid = capital_city.pid
            capital_name = capital_city.name
            sid = states.get_state_of_province(capital_pid)
            capital_state = states.get_state(sid)
            if capital_state is not None:
                capital_state.victory_points[capital_pid] = max(
                    capital_state.victory_points.get(capital_pid, 0), _victory_point_value(capital_city.population)
                )
                capital_state.vp_names[capital_pid] = capital_city.name
                capital_state.vp_names_en[capital_pid] = capital_city.name_en
        countries.set_capital(tag, capital_pid)
        capital_report.append({
            "tag": tag,
            "official_capital_on_map": not is_substitute,
            "map_capital": capital_name,
            "province_id": capital_pid,
        })

    regions = _create_strategic_regions(province_map, tile_map, states, state_groups, graph, land_pids, sea_pids)
    precheck = pre_export_check_and_fix(
        tile_map, province_map, terrain_map, states, countries,
        continent_mgr=continents, strategic_region_mgr=regions,
    )
    assigned = {pid for state in states.states.values() for pid in state.provinces}
    if assigned != land_pids:
        raise AuthoringError(f"Validation found {len(land_pids - assigned)} unassigned land province(s)")
    if sum(len(state.provinces) for state in states.states.values()) != len(assigned):
        raise AuthoringError("A land province belongs to more than one state")
    if any(not countries.get_owner_of_state(sid) for sid in states.states):
        raise AuthoringError("At least one state has no country owner")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": bool(args.dry_run),
        "project": str(project),
        "source_map": {
            "communes": str(source_dir / "COMM_RG_01M_2016_3035.shp"),
            "world_file": str(source_dir / "test3.pgw"),
            "crs": "EPSG:3035",
            "pixel_area_km2": pixel_area_km2,
        },
        "administrative_sources": {
            "official_communes_2016": COMMUNE_ATTRIBUTES_URL,
            "nuts_2016": NUTS_2016_URL,
            "france_arrondissements_2016": FR_ARRONDISSEMENT_2016_URL,
            "france_epci_2016": None if args.skip_epci else FR_EPCI_2016_URL,
            "luxembourg_cantons": LUX_CANTON_URL,
            "rhineland_palatinate_verbandsgemeinden": RLP_VERBANDSGEMEINDE_URL,
            "city_victory_points": GEONAMES_CITIES_URL,
            "population_density": EUROSTAT_DENSITY_URL,
        },
        "parameters": {
            "fr_split_threshold": args.fr_split_threshold,
            "epci_min_provinces": args.epci_min_provinces,
            "rlp_split_threshold": args.rlp_split_threshold,
            "vg_min_provinces": args.vg_min_provinces,
            "vp_min_population": args.vp_min_population,
            "population_method": "2016 NUTS3 density × cropped projected land area; urban city population redistributes up to 75% within each NUTS3",
        },
        "province_mapping": {
            **mapping_stats,
            "land_provinces": len(land_pids),
            "mapped_from_source": len(mapped) - filled_by_neighbour - filled_by_nearest,
            "mapped_from_fragment_polygon_containment": len(fragment_matches),
            "fragment_polygon_candidates": spatial_polygon_candidates,
            "filled_from_adjacent_source_commune": filled_by_neighbour,
            "filled_from_nearest_source_commune": filled_by_nearest,
            "country_counts": dict(sorted(Counter(info.country for info in provinces.values()).items())),
        },
        "density_sources": density_sources,
        "density_api_note": density_error,
        "summary": {
            "states": len(states.states),
            "countries": len(countries.countries),
            "strategic_regions": regions.count(),
            "victory_points": sum(len(state.victory_points) for state in states.states.values()),
            "land_provinces_assigned": len(assigned),
            "total_manpower": sum(state.manpower for state in states.states.values()),
            "state_schemes": dict(sorted(Counter(group.scheme for group in state_groups.values()).items())),
        },
        "capitals": capital_report,
        "states": [
            _build_report_state(state, state_groups[sid], state_area[sid], city_by_state.get(sid, []))
            for sid, state in sorted(states.states.items())
        ],
        "countries": [
            {
                "tag": country.tag,
                "name": country.name,
                "ruling_party": country.ruling_party,
                "capital_province": country.capital,
                "state_count": len(countries.get_states_of_country(tag)),
            }
            for tag, country in sorted(countries.countries.items())
        ],
        "pre_export_validation": {
            "warnings": list(precheck.warnings),
            "fixed": list(precheck.fixed),
            "stats": precheck.stats,
        },
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.dry_run:
        backup = project.with_name(project.stem + ".pre_state_authoring.bak")
        if not backup.exists():
            shutil.copy2(project, backup)
        temporary = project.with_suffix(project.suffix + ".state_authoring.tmp")
        try:
            save_project(
                str(temporary), tile_map, province_map, terrain_map, height_map, states, countries,
                river_map=river_map, continent_mgr=continents, strategic_region_mgr=regions,
                provincial_terrain=provincial_terrain, tile_snapshot=tile_snapshot,
            )
            os.replace(temporary, project)
        finally:
            if temporary.exists():
                temporary.unlink()

        # A serialization round trip makes sure localisation and authored state
        # metadata did not disappear on their way into the project archive.
        check_states = StateManager()
        check_countries = CountryManager()
        check_regions = StrategicRegionManager()
        load_project(str(project), check_states, check_countries, strategic_region_mgr=check_regions)
        if len(check_states.states) != len(states.states) or len(check_countries.countries) != len(countries.countries):
            raise AuthoringError("Project round-trip verification did not preserve all authored states/countries")
        if sum(len(state.victory_points) for state in check_states.states.values()) != report["summary"]["victory_points"]:
            raise AuthoringError("Project round-trip verification did not preserve all victory points")
        if check_regions.count() != regions.count():
            raise AuthoringError("Project round-trip verification did not preserve strategic regions")
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--dry-run", action="store_true", help="Generate an audit report without replacing the project")
    parser.add_argument("--replace-existing", action="store_true", help="Replace existing states/countries after a deliberate rerun")
    parser.add_argument("--skip-epci", action="store_true", help="Use French arrondissements only when xlrd is unavailable")
    parser.add_argument("--fr-split-threshold", type=int, default=160, help="Minimum commune provinces before a French arrondissement may split")
    parser.add_argument("--epci-min-provinces", type=int, default=35, help="Minimum mapped provinces retained as an individual EPCI state")
    parser.add_argument("--rlp-split-threshold", type=int, default=120, help="Minimum German NUTS3 provinces before RLP Verbandsgemeinde splitting")
    parser.add_argument("--vg-min-provinces", type=int, default=25, help="Minimum mapped provinces retained as an individual Verbandsgemeinde state")
    parser.add_argument("--vp-min-population", type=int, default=25_000, help="GeoNames population threshold for a normal victory point")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        report = author_project(args)
    except AuthoringError as exc:
        print(f"State authoring failed: {exc}", file=sys.stderr)
        return 2
    summary = report["summary"]
    mode = "Dry run" if args.dry_run else "Authored"
    print(
        f"{mode}: {summary['states']} states, {summary['countries']} countries, "
        f"{summary['victory_points']} victory points, {summary['land_provinces_assigned']} land provinces assigned."
    )
    print(f"Audit report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
