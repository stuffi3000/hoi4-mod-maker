"""Versioned game/map profile contracts (M1.2).

Data-driven description of the HOI4 1.19.x map contract. Profiles are plain
dataclasses loaded from JSON under ``data/game_profiles/`` so new game
versions can be added without code changes.

The four UI size presets in ``data.constants.MAP_SIZE_PRESETS`` remain UI
conveniences only. A profile validates dimensions by divisibility, total-pixel
and wrap rules; any multiple-of-256 size that passes those rules is
representable (for example 5632x2304 and 3328x3840). Custom sizes still
require an engine-acceptance run before a foundation freeze, but they are not
rejected as invalid.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


PROFILE_ID_1_19 = "hoi4-1.19"
BUNDLED_PROFILE_1_19 = os.path.join("data", "game_profiles", "hoi4_1_19.json")


@dataclass(frozen=True)
class DimensionRules:
    divisibility: int = 256
    min_width: int = 1024
    min_height: int = 1024
    max_width: int = 8192
    max_height: int = 8192
    max_total_pixels: int = 13238272
    wrap_horizontal: bool = True
    wrap_vertical: bool = False
    ui_presets: dict[str, list[int]] = field(default_factory=dict)
    observed_mod_dimensions: list[list[int]] = field(default_factory=list)
    notes: str = ""


@dataclass(frozen=True)
class ProvinceGuidance:
    hard_max: int = 21000
    soft_max: int = 14000
    recommended: int = 13000
    min_pixels: int = 8
    max_bbox_ratio: float = 0.125
    ids_must_be_contiguous: bool = True


@dataclass(frozen=True)
class BmpContract:
    width_source: str = "full_map"
    height_source: str = "full_map"
    width_divisor: int = 1
    height_divisor: int = 1
    bits_per_pixel: int = 8
    compression: str = "BI_RGB"
    bottom_up: bool = True
    palette_entries: int | None = None
    notes: str = ""


@dataclass(frozen=True)
class DdsContract:
    width_source: str = "half_map"
    height_source: str = "half_map"
    width_divisor: int = 2
    height_divisor: int = 2
    four_cc: str = "DXT5"
    mip_count: int = 1
    has_dx10_header: bool = False
    notes: str = ""


@dataclass(frozen=True)
class GameProfile:
    profile_id: str = PROFILE_ID_1_19
    display_name: str = "Hearts of Iron IV 1.19.x"
    game_versions: list[str] = field(default_factory=list)
    supported_version_pattern: str = "1.19.*"
    dimensions: DimensionRules = field(default_factory=DimensionRules)
    provinces: ProvinceGuidance = field(default_factory=ProvinceGuidance)
    bmp: dict[str, BmpContract] = field(default_factory=dict)
    dds: dict[str, DdsContract] = field(default_factory=dict)
    required_files: list[str] = field(default_factory=list)
    optional_files: list[str] = field(default_factory=list)
    deprecated_files: list[str] = field(default_factory=list)
    inherited_files: list[str] = field(default_factory=list)
    terrain_definition_source: str = "common/terrain/00_terrain.txt"
    terrain_indices: dict[str, int] = field(default_factory=dict)
    tree_indices: list[int] = field(default_factory=list)
    tree_palette_entries: int = 256
    replace_paths: list[str] = field(default_factory=list)
    descriptor_policy: str = ""
    notes: str = ""

    def validate_dimensions(self, width: int, height: int) -> list[str]:
        errors: list[str] = []
        try:
            width = int(width)
            height = int(height)
        except (TypeError, ValueError):
            return ["Map dimensions must be integers"]
        dim = self.dimensions
        if width <= 0 or height <= 0:
            errors.append(f"Map dimensions must be positive, got {width}x{height}")
            return errors
        if width % dim.divisibility != 0:
            errors.append(
                f"Map width {width} is not a multiple of {dim.divisibility}"
            )
        if height % dim.divisibility != 0:
            errors.append(
                f"Map height {height} is not a multiple of {dim.divisibility}"
            )
        if width < dim.min_width or height < dim.min_height:
            errors.append(
                f"Map size {width}x{height} is below minimum "
                f"{dim.min_width}x{dim.min_height}"
            )
        if width > dim.max_width or height > dim.max_height:
            errors.append(
                f"Map size {width}x{height} exceeds maximum "
                f"{dim.max_width}x{dim.max_height}"
            )
        if width * height > dim.max_total_pixels:
            errors.append(
                f"Total map pixels {width * height} exceed limit "
                f"{dim.max_total_pixels}"
            )
        return errors

    def is_supported_dimension(self, width: int, height: int) -> bool:
        return not self.validate_dimensions(width, height)

    def is_ui_preset(self, width: int, height: int) -> bool:
        for preset in self.dimensions.ui_presets.values():
            if list(preset) == [int(width), int(height)]:
                return True
        return False

    def expected_bmp_size(self, asset_key: str, map_w: int, map_h: int) -> tuple[int, int] | None:
        contract = self.bmp.get(asset_key)
        if contract is None:
            return None
        width = int(map_w) // int(contract.width_divisor or 1)
        height = int(map_h) // int(contract.height_divisor or 1)
        return (width, height)

    def expected_dds_size(self, asset_key: str, map_w: int, map_h: int) -> tuple[int, int] | None:
        contract = self.dds.get(asset_key)
        if contract is None:
            return None
        width = int(map_w) // int(contract.width_divisor or 1)
        height = int(map_h) // int(contract.height_divisor or 1)
        return (width, height)

    def asset_disposition(self, rel_path: str) -> str:
        normalized = str(rel_path).replace("\\", "/")
        if normalized in self.required_files:
            return "required"
        if normalized in self.optional_files:
            return "optional"
        if normalized in self.deprecated_files:
            return "deprecated"
        if normalized in self.inherited_files:
            return "inherited"
        return "unknown"

    def province_count_warning(self, count: int) -> str:
        try:
            count = int(count)
        except (TypeError, ValueError):
            return ""
        if count > self.provinces.hard_max:
            return (
                f"Danger: {count} > {self.provinces.hard_max}, exceeding "
                "HOI4 hard limit and guaranteed to crash"
            )
        if count > self.provinces.soft_max:
            return (
                f"Warning: {count} > {self.provinces.soft_max}, the limit "
                "recommended by HOI4 documentation"
            )
        if count > self.provinces.recommended:
            return (
                f"Note: {count} is close to the recommended vanilla range of "
                f"{self.provinces.recommended}-{self.provinces.soft_max}"
            )
        return ""

    def to_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "display_name": self.display_name,
            "game_versions": list(self.game_versions),
            "supported_version_pattern": self.supported_version_pattern,
            "dimensions": {
                "divisibility": self.dimensions.divisibility,
                "min_width": self.dimensions.min_width,
                "min_height": self.dimensions.min_height,
                "max_width": self.dimensions.max_width,
                "max_height": self.dimensions.max_height,
                "max_total_pixels": self.dimensions.max_total_pixels,
                "wrap_horizontal": self.dimensions.wrap_horizontal,
                "wrap_vertical": self.dimensions.wrap_vertical,
                "ui_presets": dict(self.dimensions.ui_presets),
                "observed_mod_dimensions": [list(v) for v in self.dimensions.observed_mod_dimensions],
                "notes": self.dimensions.notes,
            },
            "provinces": {
                "hard_max": self.provinces.hard_max,
                "soft_max": self.provinces.soft_max,
                "recommended": self.provinces.recommended,
                "min_pixels": self.provinces.min_pixels,
                "max_bbox_ratio": self.provinces.max_bbox_ratio,
                "ids_must_be_contiguous": self.provinces.ids_must_be_contiguous,
            },
            "bmp": {
                key: {
                    "width_source": value.width_source,
                    "height_source": value.height_source,
                    "width_divisor": value.width_divisor,
                    "height_divisor": value.height_divisor,
                    "bits_per_pixel": value.bits_per_pixel,
                    "compression": value.compression,
                    "bottom_up": value.bottom_up,
                    "palette_entries": value.palette_entries,
                    "notes": value.notes,
                }
                for key, value in self.bmp.items()
            },
            "dds": {
                key: {
                    "width_source": value.width_source,
                    "height_source": value.height_source,
                    "width_divisor": value.width_divisor,
                    "height_divisor": value.height_divisor,
                    "four_cc": value.four_cc,
                    "mip_count": value.mip_count,
                    "has_dx10_header": value.has_dx10_header,
                    "notes": value.notes,
                }
                for key, value in self.dds.items()
            },
            "required_files": list(self.required_files),
            "optional_files": list(self.optional_files),
            "deprecated_files": list(self.deprecated_files),
            "inherited_files": list(self.inherited_files),
            "terrain_definition_source": self.terrain_definition_source,
            "terrain_indices": dict(self.terrain_indices),
            "tree_indices": list(self.tree_indices),
            "tree_palette_entries": self.tree_palette_entries,
            "replace_paths": list(self.replace_paths),
            "descriptor_policy": self.descriptor_policy,
            "notes": self.notes,
        }


def profile_from_dict(data: dict) -> GameProfile:
    dim_raw = data.get("dimensions", {}) or {}
    prov_raw = data.get("provinces", {}) or {}
    dimensions = DimensionRules(
        divisibility=int(dim_raw.get("divisibility", 256)),
        min_width=int(dim_raw.get("min_width", 1024)),
        min_height=int(dim_raw.get("min_height", 1024)),
        max_width=int(dim_raw.get("max_width", 8192)),
        max_height=int(dim_raw.get("max_height", 8192)),
        max_total_pixels=int(dim_raw.get("max_total_pixels", 13238272)),
        wrap_horizontal=bool(dim_raw.get("wrap_horizontal", True)),
        wrap_vertical=bool(dim_raw.get("wrap_vertical", False)),
        ui_presets={str(k): [int(v[0]), int(v[1])] for k, v in (dim_raw.get("ui_presets", {}) or {}).items()},
        observed_mod_dimensions=[[int(v[0]), int(v[1])] for v in (dim_raw.get("observed_mod_dimensions", []) or [])],
        notes=str(dim_raw.get("notes", "")),
    )
    provinces = ProvinceGuidance(
        hard_max=int(prov_raw.get("hard_max", 21000)),
        soft_max=int(prov_raw.get("soft_max", 14000)),
        recommended=int(prov_raw.get("recommended", 13000)),
        min_pixels=int(prov_raw.get("min_pixels", 8)),
        max_bbox_ratio=float(prov_raw.get("max_bbox_ratio", 0.125)),
        ids_must_be_contiguous=bool(prov_raw.get("ids_must_be_contiguous", True)),
    )
    bmp: dict[str, BmpContract] = {}
    for key, raw in (data.get("bmp", {}) or {}).items():
        bmp[str(key)] = BmpContract(
            width_source=str(raw.get("width_source", "full_map")),
            height_source=str(raw.get("height_source", "full_map")),
            width_divisor=int(raw.get("width_divisor", 1)),
            height_divisor=int(raw.get("height_divisor", 1)),
            bits_per_pixel=int(raw.get("bits_per_pixel", 8)),
            compression=str(raw.get("compression", "BI_RGB")),
            bottom_up=bool(raw.get("bottom_up", True)),
            palette_entries=raw.get("palette_entries"),
            notes=str(raw.get("notes", "")),
        )
    dds: dict[str, DdsContract] = {}
    for key, raw in (data.get("dds", {}) or {}).items():
        dds[str(key)] = DdsContract(
            width_source=str(raw.get("width_source", "half_map")),
            height_source=str(raw.get("height_source", "half_map")),
            width_divisor=int(raw.get("width_divisor", 2)),
            height_divisor=int(raw.get("height_divisor", 2)),
            four_cc=str(raw.get("four_cc", "DXT5")),
            mip_count=int(raw.get("mip_count", 1)),
            has_dx10_header=bool(raw.get("has_dx10_header", False)),
            notes=str(raw.get("notes", "")),
        )
    return GameProfile(
        profile_id=str(data.get("profile_id", PROFILE_ID_1_19)),
        display_name=str(data.get("display_name", "Hearts of Iron IV 1.19.x")),
        game_versions=[str(v) for v in (data.get("game_versions", []) or [])],
        supported_version_pattern=str(data.get("supported_version_pattern", "1.19.*")),
        dimensions=dimensions,
        provinces=provinces,
        bmp=bmp,
        dds=dds,
        required_files=[str(v) for v in (data.get("required_files", []) or [])],
        optional_files=[str(v) for v in (data.get("optional_files", []) or [])],
        deprecated_files=[str(v) for v in (data.get("deprecated_files", []) or [])],
        inherited_files=[str(v) for v in (data.get("inherited_files", []) or [])],
        terrain_definition_source=str(data.get("terrain_definition_source", "common/terrain/00_terrain.txt")),
        terrain_indices={str(k): int(v) for k, v in (data.get("terrain_indices", {}) or {}).items()},
        tree_indices=[int(v) for v in (data.get("tree_indices", []) or [])],
        tree_palette_entries=int(data.get("tree_palette_entries", 256)),
        replace_paths=[str(v) for v in (data.get("replace_paths", []) or [])],
        descriptor_policy=str(data.get("descriptor_policy", "")),
        notes=str(data.get("notes", "")),
    )


def load_profile_from_file(path: str) -> GameProfile:
    with open(path, "r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    return profile_from_dict(data)


def bundled_profile_path(profile_id: str = PROFILE_ID_1_19) -> str | None:
    candidates = [BUNDLED_PROFILE_1_19]
    for candidate in candidates:
        if os.path.isfile(candidate):
            try:
                profile = load_profile_from_file(candidate)
            except (OSError, ValueError):
                continue
            if profile.profile_id == profile_id:
                return candidate
    if os.path.isfile(BUNDLED_PROFILE_1_19):
        return BUNDLED_PROFILE_1_19
    return None
