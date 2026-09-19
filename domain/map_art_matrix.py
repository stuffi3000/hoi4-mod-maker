"""Complete map-art disposition matrix (M6.6).

Every map-art path relevant to the current exporter is explicitly
classified as generated, preserved, inherited, omitted (optional),
unsupported, or blocked, with an actionable reason and provenance. The
matrix is profile-driven: generated DDS entries defer their
generate/preserve/blocked verdict to domain.dds_format, known
vanilla-supplied art defaults to inherited, optional structural files
defer to the existing structural policy, and any other imported visual
asset is preserved byte-for-byte so no imported structural or visual
asset is ever silently dropped.

Layout of the vanilla map/terrain directory (64 files in HOI4 1.19.3.0
per the readiness audit) covers atlas/normal data, borders, city
lights, colormaps, fog of war, ice, mud, reflections, river surfaces,
snow, straits, underwater shading, and tree tint/season data. The tool
generates only the five overview DDS files; everything else is either
inherited from the selected game install at runtime or preserved from
the import. Exact vanilla filenames outside the generated set and the
atlas pair are matched by family glob patterns below, so the matrix
stays explicit without hard-coding all 64 names.
"""
from __future__ import annotations

import fnmatch


MATRIX_VERSION = "map-art-matrix/6.6"

GENERATED_DDS_ART = (
    "map/terrain/colormap_rgb_cityemissivemask_a.dds",
    "map/terrain/colormap_water_0.dds",
    "map/terrain/colormap_water_1.dds",
    "map/terrain/colormap_water_2.dds",
    "map/terrain/fow_rgb_waterspec_a.dds",
)

KNOWN_INHERITED_MAP_ART = (
    "map/terrain/atlas0.dds",
    "map/terrain/atlas_normal0.dds",
)

INHERITED_REASON = (
    "provided by the selected game install at runtime; the tool does not "
    "ship it (confirm it is compatible with the custom map, or replace it "
    "manually and re-import for validation)"
)

INHERITED_PROVENANCE = "game-install"

MAP_ART_FAMILIES = (
    ("atlas", ("map/terrain/atlas*.dds",), "terrain material atlas tiles"),
    (
        "atlas-normal",
        ("map/terrain/atlas_normal*.dds",),
        "terrain atlas normal (bump lighting) maps",
    ),
    (
        "colormap",
        ("map/terrain/colormap*.dds",),
        "strategic-overview colormaps",
    ),
    ("water", ("map/terrain/*water*.dds",), "water shading colormaps"),
    (
        "fog-of-war",
        ("map/terrain/fow*.dds", "map/terrain/*fog*.dds"),
        "fog-of-war shading and water-specular maps",
    ),
    (
        "city-lights",
        ("map/terrain/*citylight*.dds", "map/terrain/*city_light*.dds"),
        "city night-light art",
    ),
    ("snow", ("map/terrain/*snow*.dds",), "snow overlay art"),
    ("ice", ("map/terrain/*ice*.dds",), "ice overlay art"),
    ("river", ("map/terrain/*river*.dds",), "river surface art"),
    ("borders", ("map/terrain/*border*.dds",), "province/state border art"),
    (
        "reflections",
        ("map/terrain/*reflection*.dds",),
        "water reflection art",
    ),
    ("mud", ("map/terrain/*mud*.dds",), "mud overlay art"),
    ("straits", ("map/terrain/*strait*.dds",), "strait crossing art"),
    (
        "underwater",
        ("map/terrain/*underwater*.dds",),
        "underwater shading art",
    ),
    (
        "tree-tint",
        ("map/terrain/*tree*.dds", "map/terrain/*season*.dds"),
        "tree tint and seasonal variation art",
    ),
    ("terrain-misc", ("map/terrain/*.dds",), "other terrain art"),
)


def _normalize(rel_path):
    try:
        return str(rel_path or "").replace("\\", "/").strip()
    except (TypeError, ValueError):
        return ""


def is_generated_dds_art(rel_path):
    """Return True for the five overview DDS files the writers own."""
    return _normalize(rel_path) in GENERATED_DDS_ART


def is_map_art_path(rel_path):
    """Return True for any map-art path covered by this matrix."""
    norm = _normalize(rel_path)
    if not norm:
        return False
    if norm in GENERATED_DDS_ART or norm in KNOWN_INHERITED_MAP_ART:
        return True
    if norm == "map/world_normal.bmp":
        return True
    for _family, patterns, _note in MAP_ART_FAMILIES:
        for pattern in patterns:
            try:
                if fnmatch.fnmatchcase(norm, pattern):
                    return True
            except (TypeError, ValueError):
                continue
    return False


def family_for_path(rel_path):
    """Return the vanilla art family name for a map-art path.

    Returns "" for non-map-art paths. The first matching family wins so
    classification is deterministic; generated colormaps match colormap
    before the looser water pattern.
    """
    norm = _normalize(rel_path)
    if not norm:
        return ""
    if norm in GENERATED_DDS_ART:
        if "fow" in norm:
            return "fog-of-war"
        if "water" in norm:
            return "colormap"
        return "colormap"
    if norm in KNOWN_INHERITED_MAP_ART:
        return "atlas" if norm == "map/terrain/atlas0.dds" else "atlas-normal"
    if norm == "map/world_normal.bmp":
        return "world-normal"
    for family, patterns, _note in MAP_ART_FAMILIES:
        for pattern in patterns:
            try:
                if fnmatch.fnmatchcase(norm, pattern):
                    return family
            except (TypeError, ValueError):
                continue
    return ""


def inherited_reason_for(rel_path):
    """Actionable reason used for inherited (game-supplied) art."""
    family = family_for_path(rel_path)
    if family:
        return "%s: %s" % (family, INHERITED_REASON)
    return INHERITED_REASON


def matrix_inherited_paths(profile=None):
    """Explicit inherited art paths: atlas pair plus profile entries."""
    paths = set(KNOWN_INHERITED_MAP_ART)
    if profile is not None:
        try:
            declared = getattr(profile, "inherited_files", None) or []
        except (AttributeError, TypeError, ValueError):
            declared = []
        try:
            for entry in declared:
                norm = _normalize(entry)
                if norm:
                    paths.add(norm)
        except TypeError:
            pass
    return sorted(paths)


def matrix_paths_for_profile(profile=None):
    """Every explicit matrix path for a profile, sorted and deterministic."""
    paths = set(GENERATED_DDS_ART)
    for entry in matrix_inherited_paths(profile):
        paths.add(entry)
    if profile is not None:
        try:
            dds_map = getattr(profile, "dds", None) or {}
            if isinstance(dds_map, dict):
                for entry in dds_map:
                    norm = _normalize(entry)
                    if norm:
                        paths.add(norm)
        except (AttributeError, TypeError, ValueError):
            pass
    return sorted(paths)


def classify_leftover_map_art(rel_path, has_bytes=False, dirty=False):
    """Classify an imported map-art file no writer loop owns.

    Clean imports are always preserved byte-for-byte; dirty map art has
    no regenerating writer and is blocked with an explicit remedy, never
    silently dropped or mislabeled as generated. Returns
    (disposition, reason, provenance).
    """
    norm = _normalize(rel_path)
    family = family_for_path(norm)
    label = ("%s " % family) if family else ""
    if dirty:
        return (
            "blocked",
            "dirty %smap art has no regenerating writer; restore the clean "
            "imported bytes or provide a compatible replacement file"
            % label,
            "map-art-matrix",
        )
    if has_bytes:
        return (
            "preserved",
            "clean imported %smap art is preserved byte-for-byte" % label,
            "project-assets",
        )
    return (
        "omitted",
        "no imported bytes for %smap art and no writer owns it" % label,
        "map-art-matrix",
    )
