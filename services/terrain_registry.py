"""Selected terrain registry (M6.3).

Dependency-free parser/service for the selected GameTarget's
``common/terrain/00_terrain.txt``. Each graphical terrain entry exposes a
stable entry name/id, province terrain type, every color/palette index,
texture index, spawn_city flag, and snow/perm_snow behavior.

The parser is pure, deterministic, and non-mutating. It supports custom
mod text and dependency input by merging multiple texts, reports
malformed/no-file diagnostics instead of raising, and keeps a deterministic
ordering (sorted by first palette index, then entry name).

``data/terrain_types.py`` remains the built-in fallback/editor catalog.
When a selected registry is available, validation truth comes from the
registry's legal palette indices, not from the built-in table.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

TERRAIN_DEFINITION_RELPATH = "common/terrain/00_terrain.txt"

_BOOL_TRUE = frozenset({"yes", "true", "1", "on"})
_BOOL_FALSE = frozenset({"no", "false", "0", "off"})

_TYPE_RE = re.compile(r"type\s*=\s*([A-Za-z_][\w]*)")
_COLOR_RE = re.compile(r"color\s*=\s*\{([^}]*)\}")
_TEXTURE_RE = re.compile(r"texture\s*=\s*(\d+)")
_SPAWN_CITY_RE = re.compile(r"spawn_city\s*=\s*([A-Za-z0-9_]+)")
_PERM_SNOW_RE = re.compile(r"perm(?:anent)?_snow\s*=\s*([A-Za-z0-9_]+)")
_SNOW_BOOL_RE = re.compile(r"(?<![\w])snow\s*=\s*([A-Za-z0-9_]+)")
_SNOW_BLOCK_RE = re.compile(r"(?<![\w])snow\s*=\s*\{")
_ENTRY_HEAD_RE = re.compile(r"([A-Za-z_][\w]*)\s*=\s*\{")
_TERRAIN_BLOCK_RE = re.compile(r"(?<![\w])terrain\s*=\s*\{")


def _parse_bool_token(token: str | None, default: bool = False) -> bool:
    if token is None:
        return bool(default)
    text = str(token).strip().lower()
    if text in _BOOL_TRUE:
        return True
    if text in _BOOL_FALSE:
        return False
    return bool(default)


def _strip_comments(text: str) -> str:
    return re.sub(r"#[^\n]*", "", str(text))


def _find_matching_brace(text: str, open_index: int) -> int:
    depth = 0
    index = int(open_index)
    total = len(text)
    while index < total:
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _extract_terrain_inner(text: str) -> tuple[str | None, str]:
    cleaned = _strip_comments(text)
    match = _TERRAIN_BLOCK_RE.search(cleaned)
    if match is None:
        return (None, cleaned)
    open_index = cleaned.find("{", match.start())
    if open_index < 0:
        return (None, cleaned)
    close_index = _find_matching_brace(cleaned, open_index)
    if close_index < 0:
        return (None, cleaned)
    return (cleaned[open_index + 1:close_index], cleaned)


@dataclass(frozen=True)
class TerrainRegistryEntry:
    name: str = ""
    terrain_type: str = ""
    color_indices: tuple[int, ...] = ()
    texture: int | None = None
    spawn_city: bool = False
    snow: bool = False
    perm_snow: bool = False
    source: str = ""

    @property
    def id(self) -> str:
        return str(self.name)

    @property
    def entry_id(self) -> str:
        return str(self.name)

    @property
    def type(self) -> str:
        return str(self.terrain_type)

    @property
    def province_type(self) -> str:
        return str(self.terrain_type)

    @property
    def palette_indices(self) -> tuple[int, ...]:
        return tuple(self.color_indices)

    @property
    def indices(self) -> tuple[int, ...]:
        return tuple(self.color_indices)

    def to_dict(self) -> dict:
        return {
            "name": str(self.name),
            "id": str(self.name),
            "type": str(self.terrain_type),
            "terrain_type": str(self.terrain_type),
            "color_indices": [int(v) for v in self.color_indices],
            "palette_indices": [int(v) for v in self.color_indices],
            "texture": None if self.texture is None else int(self.texture),
            "spawn_city": bool(self.spawn_city),
            "snow": bool(self.snow),
            "perm_snow": bool(self.perm_snow),
            "source": str(self.source),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TerrainRegistryEntry":
        raw_colors = data.get("color_indices", data.get("palette_indices", data.get("indices", ())))
        try:
            colors = tuple(int(v) for v in (raw_colors or ()))
        except (TypeError, ValueError):
            colors = ()
        texture = data.get("texture", None)
        try:
            texture_value = None if texture is None else int(texture)
        except (TypeError, ValueError):
            texture_value = None
        return cls(
            name=str(data.get("name", data.get("id", ""))),
            terrain_type=str(data.get("terrain_type", data.get("type", ""))),
            color_indices=tuple(colors),
            texture=texture_value,
            spawn_city=bool(data.get("spawn_city", False)),
            snow=bool(data.get("snow", False)),
            perm_snow=bool(data.get("perm_snow", False)),
            source=str(data.get("source", "")),
        )


@dataclass(frozen=True)
class TerrainRegistry:
    entries: tuple[TerrainRegistryEntry, ...] = ()
    diagnostics: tuple[str, ...] = ()
    source: str = ""

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)

    @property
    def legal_palette_indices(self) -> frozenset[int]:
        out: set[int] = set()
        for entry in self.entries:
            for value in entry.color_indices:
                try:
                    number = int(value)
                except (TypeError, ValueError):
                    continue
                if 0 <= number <= 255:
                    out.add(number)
        return frozenset(out)

    @property
    def legal_indices(self) -> frozenset[int]:
        return self.legal_palette_indices

    @property
    def by_name(self) -> dict[str, TerrainRegistryEntry]:
        return {str(entry.name): entry for entry in self.entries}

    @property
    def by_index(self) -> dict[int, TerrainRegistryEntry]:
        mapping: dict[int, TerrainRegistryEntry] = {}
        for entry in self.entries:
            for value in entry.color_indices:
                try:
                    number = int(value)
                except (TypeError, ValueError):
                    continue
                if number not in mapping:
                    mapping[number] = entry
        return mapping

    @property
    def has_entries(self) -> bool:
        return bool(self.entries)

    def to_dict(self) -> dict:
        return {
            "entries": [entry.to_dict() for entry in self.entries],
            "diagnostics": list(self.diagnostics),
            "source": str(self.source),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TerrainRegistry":
        raw_entries = data.get("entries", ()) or ()
        entries = tuple(TerrainRegistryEntry.from_dict(item) for item in raw_entries if isinstance(item, dict))
        diagnostics = tuple(str(v) for v in (data.get("diagnostics", ()) or ()))
        return cls(entries=entries, diagnostics=diagnostics, source=str(data.get("source", "")))


def _parse_single_entry(name: str, body: str, source: str, diagnostics: list[str]) -> TerrainRegistryEntry | None:
    type_match = _TYPE_RE.search(body)
    terrain_type = str(type_match.group(1)).strip() if type_match else ""
    if not terrain_type:
        diagnostics.append("terrain entry %r has no province type" % str(name))
    color_match = _COLOR_RE.search(body)
    if color_match is None:
        diagnostics.append("terrain entry %r has no color/palette indices" % str(name))
        return None
    raw_tokens = re.split(r"[\s,]+", color_match.group(1).strip())
    color_indices: list[int] = []
    for token in raw_tokens:
        if not token:
            continue
        try:
            number = int(token)
        except (TypeError, ValueError):
            diagnostics.append("terrain entry %r has malformed color token %r" % (str(name), token))
            continue
        if 0 <= number <= 255:
            color_indices.append(number)
        else:
            diagnostics.append("terrain entry %r has out-of-range palette index %d" % (str(name), number))
    if not color_indices:
        diagnostics.append("terrain entry %r has no usable palette indices" % str(name))
        return None
    texture_match = _TEXTURE_RE.search(body)
    texture: int | None = None
    if texture_match is not None:
        try:
            texture = int(texture_match.group(1))
        except (TypeError, ValueError):
            texture = None
    else:
        diagnostics.append("terrain entry %r has no texture index" % str(name))
    spawn_match = _SPAWN_CITY_RE.search(body)
    spawn_city = _parse_bool_token(spawn_match.group(1) if spawn_match else None, default=False)
    perm_match = _PERM_SNOW_RE.search(body)
    perm_snow = _parse_bool_token(perm_match.group(1) if perm_match else None, default=False)
    snow_value = False
    snow_bool_match = _SNOW_BOOL_RE.search(body)
    if snow_bool_match is not None:
        token = str(snow_bool_match.group(1)).strip()
        if token == "{" or token.startswith("{"):
            snow_value = True
        elif token.lower() in _BOOL_TRUE:
            snow_value = True
        elif token.lower() in _BOOL_FALSE:
            snow_value = False
        else:
            snow_value = _parse_bool_token(token, default=False)
    if _SNOW_BLOCK_RE.search(body) is not None:
        snow_value = True
    if perm_snow:
        snow_value = True
    return TerrainRegistryEntry(
        name=str(name),
        terrain_type=str(terrain_type),
        color_indices=tuple(color_indices),
        texture=texture,
        spawn_city=bool(spawn_city),
        snow=bool(snow_value),
        perm_snow=bool(perm_snow),
        source=str(source),
    )


def parse_terrain_registry(text: str, source: str = "<text>") -> TerrainRegistry:
    label = str(source or "<text>")
    raw = "" if text is None else str(text)
    if not raw.strip():
        return TerrainRegistry(entries=(), diagnostics=("terrain text is empty",), source=label)
    inner, _cleaned = _extract_terrain_inner(raw)
    diagnostics: list[str] = []
    if inner is None:
        diagnostics.append("no terrain block found; parsing whole text for graphical entries")
        scan_text = _strip_comments(raw)
    else:
        scan_text = inner
    entries: list[TerrainRegistryEntry] = []
    seen_indices: dict[int, str] = {}
    position = 0
    total = len(scan_text)
    while position < total:
        head = _ENTRY_HEAD_RE.search(scan_text, position)
        if head is None:
            break
        entry_name = str(head.group(1))
        open_index = scan_text.find("{", head.start())
        if open_index < 0:
            diagnostics.append("terrain entry %r has unterminated block" % entry_name)
            break
        close_index = _find_matching_brace(scan_text, open_index)
        if close_index < 0:
            diagnostics.append("terrain entry %r has unterminated block" % entry_name)
            break
        body = scan_text[open_index + 1:close_index]
        if "color" in body:
            entry = _parse_single_entry(entry_name, body, label, diagnostics)
            if entry is not None:
                entries.append(entry)
                for value in entry.color_indices:
                    if value in seen_indices and seen_indices[value] != entry_name:
                        diagnostics.append(
                            "palette index %d appears in %r and %r" % (value, seen_indices[value], entry_name)
                        )
                    elif value not in seen_indices:
                        seen_indices[value] = entry_name
        position = close_index + 1
    if not entries:
        diagnostics.append("no graphical terrain entries found")
    entries.sort(key=lambda item: ((min(item.color_indices) if item.color_indices else 9999), str(item.name)))
    return TerrainRegistry(entries=tuple(entries), diagnostics=tuple(diagnostics), source=label)


def parse_terrain_registry_text(text: str, source: str = "<text>") -> TerrainRegistry:
    return parse_terrain_registry(text, source=source)


def combine_terrain_registries(*registries: TerrainRegistry, source: str = "<merged>") -> TerrainRegistry:
    merged: dict[str, TerrainRegistryEntry] = {}
    order: list[str] = []
    diagnostics: list[str] = []
    for registry in registries:
        if registry is None:
            continue
        try:
            items = list(registry.entries)
        except (TypeError, ValueError, AttributeError):
            continue
        try:
            extra = list(registry.diagnostics)
        except (TypeError, ValueError, AttributeError):
            extra = []
        for item in extra:
            text = str(item)
            if text and text not in diagnostics:
                diagnostics.append(text)
        for entry in items:
            key = str(getattr(entry, "name", ""))
            if not key:
                continue
            if key not in merged:
                order.append(key)
            merged[key] = entry
    seen: dict[int, str] = {}
    for key in order:
        entry = merged[key]
        try:
            colors = list(entry.color_indices)
        except (TypeError, ValueError):
            colors = []
        for value in colors:
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if number in seen and seen[number] != key:
                note = "palette index %d appears in %r and %r" % (number, seen[number], key)
                if note not in diagnostics:
                    diagnostics.append(note)
            elif number not in seen:
                seen[number] = key
    ordered = sorted(merged.values(), key=lambda item: ((min(item.color_indices) if item.color_indices else 9999), str(item.name)))
    return TerrainRegistry(entries=tuple(ordered), diagnostics=tuple(diagnostics), source=str(source or "<merged>"))


def registry_from_texts(texts, sources=None, source: str = "<merged>") -> TerrainRegistry:
    if texts is None:
        return TerrainRegistry(entries=(), diagnostics=("no terrain texts supplied",), source=str(source))
    if isinstance(texts, (str, bytes)):
        items = [texts]
    else:
        try:
            items = list(texts)
        except TypeError:
            items = [texts]
    if sources is None:
        labels = ["<text#%d>" % (index + 1) for index in range(len(items))]
    elif isinstance(sources, (str, bytes)):
        labels = [str(sources)]
    else:
        try:
            labels = [str(v) for v in list(sources)]
        except TypeError:
            labels = [str(sources)]
    while len(labels) < len(items):
        labels.append("<text#%d>" % (len(labels) + 1))
    parsed = [parse_terrain_registry(item, source=labels[index]) for index, item in enumerate(items)]
    return combine_terrain_registries(*parsed, source=str(source))


def _read_text_file(path: str) -> tuple[str | None, str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return (handle.read(), "")
    except OSError as exc:
        return (None, "cannot read terrain file %s: %s" % (str(path), exc))


def load_terrain_registry(
    install_dir: str | None,
    dependency_dirs=None,
    extra_texts=None,
    extra_sources=None,
) -> TerrainRegistry:
    diagnostics: list[str] = []
    registries: list[TerrainRegistry] = []
    base_label = TERRAIN_DEFINITION_RELPATH
    if not install_dir:
        diagnostics.append("no game install directory supplied for %s" % TERRAIN_DEFINITION_RELPATH)
    else:
        candidate = os.path.join(str(install_dir), *TERRAIN_DEFINITION_RELPATH.split("/"))
        text, error = _read_text_file(candidate)
        if text is None:
            diagnostics.append(error or ("terrain file missing: %s" % candidate))
        else:
            registries.append(parse_terrain_registry(text, source=candidate))
    if dependency_dirs is not None:
        if isinstance(dependency_dirs, (str, bytes, os.PathLike)):
            dirs = [dependency_dirs]
        else:
            try:
                dirs = list(dependency_dirs)
            except TypeError:
                dirs = [dependency_dirs]
        for item in dirs:
            if not item:
                continue
            candidate = os.path.join(str(item), *TERRAIN_DEFINITION_RELPATH.split("/"))
            if not os.path.isfile(candidate):
                continue
            text, error = _read_text_file(candidate)
            if text is None:
                diagnostics.append(error)
            elif text.strip():
                registries.append(parse_terrain_registry(text, source=candidate))
    if extra_texts is not None:
        if isinstance(extra_texts, (str, bytes)):
            texts = [extra_texts]
        else:
            try:
                texts = list(extra_texts)
            except TypeError:
                texts = [extra_texts]
        if extra_sources is None:
            labels = ["<dependency#%d>" % (index + 1) for index in range(len(texts))]
        elif isinstance(extra_sources, (str, bytes)):
            labels = [str(extra_sources)]
        else:
            try:
                labels = [str(v) for v in list(extra_sources)]
            except TypeError:
                labels = [str(extra_sources)]
        while len(labels) < len(texts):
            labels.append("<dependency#%d>" % (len(labels) + 1))
        for index, item in enumerate(texts):
            if item is None:
                continue
            content = str(item)
            if not content.strip():
                continue
            registries.append(parse_terrain_registry(content, source=labels[index]))
    if not registries:
        return TerrainRegistry(entries=(), diagnostics=tuple(diagnostics or ("terrain registry file not found",)), source=str(install_dir or ""))
    merged = combine_terrain_registries(*registries, source=str(install_dir or "<merged>"))
    combined_diagnostics = list(diagnostics) + list(merged.diagnostics)
    seen: list[str] = []
    for item in combined_diagnostics:
        if item not in seen:
            seen.append(item)
    return TerrainRegistry(entries=merged.entries, diagnostics=tuple(seen), source=merged.source)


def registry_for_target(game_target=None, dependency_texts=None, dependency_dirs=None) -> TerrainRegistry:
    install: str | None = None
    try:
        if game_target is not None:
            install = getattr(game_target, "install_dir", None)
    except (AttributeError, TypeError, ValueError):
        install = None
    return load_terrain_registry(install, dependency_dirs=dependency_dirs, extra_texts=dependency_texts)


def selected_registry_for_target(game_target=None, dependency_texts=None, dependency_dirs=None) -> TerrainRegistry:
    return registry_for_target(game_target, dependency_texts=dependency_texts, dependency_dirs=dependency_dirs)


def builtin_registry() -> TerrainRegistry:
    try:
        from data.terrain_types import GRAPHICAL_TERRAINS
    except (ImportError, AttributeError, TypeError, ValueError):
        return TerrainRegistry(entries=(), diagnostics=("built-in terrain catalog unavailable",), source="<builtin>")
    entries: list[TerrainRegistryEntry] = []
    for item in GRAPHICAL_TERRAINS:
        try:
            name = str(getattr(item, "id", ""))
            terrain_type = str(getattr(item, "type", ""))
            palette = int(getattr(item, "palette_index", 0))
            texture_value = getattr(item, "texture", None)
            try:
                texture = None if texture_value is None else int(texture_value)
            except (TypeError, ValueError):
                texture = None
            perm = bool(getattr(item, "perm_snow", False))
            spawn = bool(getattr(item, "spawn_city", False))
        except (TypeError, ValueError, AttributeError):
            continue
        entries.append(TerrainRegistryEntry(
            name=name,
            terrain_type=terrain_type,
            color_indices=(palette,),
            texture=texture,
            spawn_city=spawn,
            snow=bool(perm),
            perm_snow=bool(perm),
            source="<builtin>",
        ))
    entries.sort(key=lambda item: ((min(item.color_indices) if item.color_indices else 9999), str(item.name)))
    return TerrainRegistry(entries=tuple(entries), diagnostics=(), source="<builtin>")


def legal_palette_indices(registry) -> frozenset[int]:
    if registry is None:
        return frozenset()
    getter = getattr(registry, "legal_palette_indices", None)
    if callable(getter):
        try:
            return frozenset(int(v) for v in getter())
        except (TypeError, ValueError):
            return frozenset()
    if getter is not None:
        try:
            return frozenset(int(v) for v in getter)
        except (TypeError, ValueError):
            pass
    try:
        items = list(registry.entries)  # type: ignore[union-attr]
    except (TypeError, ValueError, AttributeError):
        items = []
    out: set[int] = set()
    for entry in items:
        try:
            colors = list(getattr(entry, "color_indices", ()))
        except (TypeError, ValueError, AttributeError):
            continue
        for value in colors:
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if 0 <= number <= 255:
                out.add(number)
    if out:
        return frozenset(out)
    try:
        from collections.abc import Mapping as _Mapping
        if isinstance(registry, _Mapping):
            values: list = []
            values.extend(list(registry.keys()))
            values.extend(list(registry.values()))
            collected: set[int] = set()
            for value in values:
                try:
                    if isinstance(value, bool):
                        continue
                    number = int(value)  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    continue
                if 0 <= number <= 255:
                    collected.add(number)
            return frozenset(collected)
    except (TypeError, ValueError):
        pass
    return frozenset(out)


__all__ = [
    "TERRAIN_DEFINITION_RELPATH",
    "TerrainRegistry",
    "TerrainRegistryEntry",
    "builtin_registry",
    "combine_terrain_registries",
    "legal_palette_indices",
    "load_terrain_registry",
    "parse_terrain_registry",
    "parse_terrain_registry_text",
    "registry_for_target",
    "registry_from_texts",
    "selected_registry_for_target",
]
