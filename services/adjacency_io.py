"""Portable import helpers for HOI4 adjacency layers (M4.2).

The functions accept either file paths or text so import tests can use small
original fixtures without touching a game installation. They return the
repository manager dataclasses and never clear or mutate a caller manager.
"""
from __future__ import annotations

import csv
import os
import re
from pathlib import Path
from typing import Any

from domain.managers.adjacency import AdjacencyEntry
from domain.managers.adjacency_rule import ALL_PASS_TYPES, ALL_RELATIONS, AdjacencyRule


def _source_text(source: str | os.PathLike[str]) -> str:
    if isinstance(source, os.PathLike) or (
        isinstance(source, str)
        and "\n" not in source
        and "\r" not in source
        and os.path.isfile(source)
    ):
        return Path(source).read_text(encoding="utf-8-sig", errors="replace")
    return str(source)


def _int_field(value: str, default: int = -1) -> int:
    try:
        return int(str(value or "").strip())
    except (TypeError, ValueError):
        return default


def parse_adjacencies_csv(source: str | os.PathLike[str]) -> list[AdjacencyEntry]:
    """Parse supported ``adjacencies.csv`` rows, including comments."""
    result: list[AdjacencyEntry] = []
    reader = csv.reader(_source_text(source).splitlines(), delimiter=";")
    for row in reader:
        if not row:
            continue
        first = str(row[0]).strip()
        if not first or first.startswith("#") or first.lower() == "from":
            continue
        if len(row) < 4:
            continue
        from_id = _int_field(row[0], -1)
        to_id = _int_field(row[1], -1)
        if from_id < 0 or to_id < 0:
            continue
        entry_type = str(row[2]).strip().lower() or "sea"
        comment = ";".join(str(value) for value in row[9:]).strip() if len(row) > 9 else ""
        result.append(
            AdjacencyEntry(
                from_id=from_id,
                to_id=to_id,
                type=entry_type,
                through_id=_int_field(row[3], -1),
                start_x=_int_field(row[4], -1) if len(row) > 4 else -1,
                start_y=_int_field(row[5], -1) if len(row) > 5 else -1,
                stop_x=_int_field(row[6], -1) if len(row) > 6 else -1,
                stop_y=_int_field(row[7], -1) if len(row) > 7 else -1,
                rule_name=str(row[8]).strip() if len(row) > 8 else "",
                comment=comment,
            )
        )
    return result


def _value(text: str, key: str) -> str:
    match = re.search(
        rf"\b{re.escape(key)}\s*=\s*(?:\"([^\"]*)\"|([^\s#}}]+))",
        text,
    )
    if not match:
        return ""
    return (match.group(1) if match.group(1) is not None else match.group(2)).strip()


def _block_value(text: str, key: str) -> str:
    match = re.search(rf"\b{re.escape(key)}\s*=\s*\{{([^}}]*)\}}", text, re.DOTALL)
    return match.group(1) if match else ""


def _parse_yes_no_block(text: str) -> dict[str, bool]:
    return {
        pass_type: _value(text, pass_type).lower() == "yes"
        for pass_type in ALL_PASS_TYPES
    }


def _find_blocks(text: str, keyword: str) -> list[tuple[int, int, str]]:
    """Find balanced ``keyword = { ... }`` blocks without a script parser."""
    found: list[tuple[int, int, str]] = []
    for match in re.finditer(rf"\b{re.escape(keyword)}\s*=\s*\{{", text):
        opening = text.find("{", match.start(), match.end())
        depth = 0
        quoted = False
        escaped = False
        closing = None
        index = opening
        while index < len(text):
            char = text[index]
            if escaped:
                escaped = False
            elif char == "\\" and quoted:
                escaped = True
            elif char == '"':
                quoted = not quoted
            elif not quoted and char == "{":
                depth += 1
            elif not quoted and char == "}":
                depth -= 1
                if depth == 0:
                    closing = index
                    break
            index += 1
        if closing is not None:
            found.append((match.start(), closing + 1, text[opening + 1:closing]))
    return found


def parse_adjacency_rules(source: str | os.PathLike[str]) -> list[AdjacencyRule]:
    """Parse ``adjacency_rule`` blocks and retain leading comments."""
    text = _source_text(source)
    result: list[AdjacencyRule] = []
    for start, _end, body in _find_blocks(text, "adjacency_rule"):
        name = _value(body, "name")
        if not name:
            continue
        relations = {
            relation: _parse_yes_no_block(_block_value(body, relation))
            for relation in ALL_RELATIONS
        }
        required = [
            value
            for token in re.findall(r"-?\d+", _block_value(body, "required_provinces"))
            if (value := _int_field(token, -1)) >= 0
        ]
        icon = _int_field(_value(body, "icon"), -1)
        if icon < 0:
            icon = _int_field(_value(body, "icon_province"), -1)

        comment_lines: list[str] = []
        for line in reversed(text[:start].splitlines()):
            stripped = line.strip()
            if not stripped:
                if comment_lines:
                    break
                continue
            if stripped.startswith("#"):
                comment = stripped[1:].strip()
                if comment.lower().startswith("auto-generated by hoi4 mod maker"):
                    continue
                if comment.lower().startswith("adjacency rules"):
                    continue
                comment_lines.append(comment)
                continue
            break
        comment_lines.reverse()
        result.append(
            AdjacencyRule(
                name=name,
                contested=relations["contested"],
                enemy=relations["enemy"],
                friend=relations["friend"],
                neutral=relations["neutral"],
                required_provinces=required,
                icon_province=icon,
                comment="\n".join(comment_lines),
            )
        )
    return result


def adjacency_wraps_horizontal(entry: AdjacencyEntry, width: int | None) -> bool:
    """Return whether an entry's explicit coordinates cross the map seam."""
    if width is None or int(width) <= 1:
        return False
    if min(entry.start_x, entry.stop_x) < 0:
        return False
    delta = abs(int(entry.start_x) - int(entry.stop_x))
    return delta > int(width) // 2 or {int(entry.start_x), int(entry.stop_x)} == {
        0, int(width) - 1
    }


def adjacency_geometry(entry: AdjacencyEntry, width: int | None, height: int | None) -> dict[str, Any]:
    """Return UI-friendly coordinates and map-wrap metadata."""
    return {
        "start": (int(entry.start_x), int(entry.start_y)),
        "stop": (int(entry.stop_x), int(entry.stop_y)),
        "wrap_horizontal": adjacency_wraps_horizontal(entry, width),
        "in_bounds": (
            width is not None and height is not None
            and all(
                -1 <= int(value) < limit
                for value, limit in (
                    (entry.start_x, width),
                    (entry.stop_x, width),
                    (entry.start_y, height),
                    (entry.stop_y, height),
                )
            )
        ),
    }


__all__ = [
    "adjacency_geometry",
    "adjacency_wraps_horizontal",
    "parse_adjacencies_csv",
    "parse_adjacency_rules",
]
