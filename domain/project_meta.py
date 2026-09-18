"""Project metadata contract (M1.3).

``project_meta.json`` lives inside ``.hoi4proj`` archives and records the
schema version, selected game/profile, lifecycle state, dimensions,
validation exceptions, adjacency review, foundation-lock reference, and
generator/tool version.

Old projects without metadata load in memory as a current ``draft`` with an
inferred target that requires user confirmation. Newer unknown schemas are
rejected without overwriting the on-disk archive.
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone


PROJECT_META_FILENAME = "project_meta.json"
CURRENT_SCHEMA_VERSION = 1
KNOWN_SCHEMA_VERSIONS = frozenset({1})

LIFECYCLE_STATES = ("draft", "candidate", "frozen", "accepted")

ADJACENCY_REVIEW_STATES = ("unreviewed", "none_intended", "defined")
LEGACY_ADJACENCY_REVIEW_STATES = {"reviewed": "defined"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tool_version() -> str:
    try:
        from version import VERSION
        return str(VERSION)
    except Exception:
        return "unknown"


@dataclass
class ProjectMeta:
    schema_version: int = CURRENT_SCHEMA_VERSION
    profile_id: str = "hoi4-1.19"
    game_raw_version: str | None = None
    game_install_dir: str | None = None
    lifecycle: str = "draft"
    width: int = 0
    height: int = 0
    validation_exceptions: list[dict] = field(default_factory=list)
    adjacency_review: str = "unreviewed"
    adjacency_review_note: str = ""
    adjacency_review_hash: str | None = None
    foundation_lock_ref: str | None = None
    foundation_lock_hash: str | None = None
    generator_version: str = ""
    tool_version: str = ""
    needs_target_confirmation: bool = False
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "schema_version": int(self.schema_version),
            "game": {
                "profile_id": self.profile_id,
                "raw_version": self.game_raw_version,
                "install_dir": self.game_install_dir,
            },
            "lifecycle": self.lifecycle,
            "dimensions": {"width": int(self.width), "height": int(self.height)},
            "validation_exceptions": [dict(v) for v in self.validation_exceptions],
            "adjacency_review": self.adjacency_review,
            "adjacency_review_note": self.adjacency_review_note,
            "adjacency_review_hash": self.adjacency_review_hash,
            "foundation_lock": {
                "ref": self.foundation_lock_ref,
                "hash": self.foundation_lock_hash,
            },
            "generator_version": self.generator_version,
            "tool_version": self.tool_version or _tool_version(),
            "needs_target_confirmation": bool(self.needs_target_confirmation),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectMeta":
        if not isinstance(data, dict):
            raise ValueError("project metadata must be a JSON object")
        raw_schema = data.get("schema_version", CURRENT_SCHEMA_VERSION)
        try:
            schema_version = int(raw_schema)
        except (TypeError, ValueError):
            raise ValueError(f"invalid schema_version: {raw_schema!r}")
        if schema_version not in KNOWN_SCHEMA_VERSIONS:
            raise UnknownSchemaError(schema_version, data)
        game = data.get("game", {}) or {}
        dims = data.get("dimensions", {}) or {}
        lock = data.get("foundation_lock", {}) or {}
        lifecycle = str(data.get("lifecycle", "draft"))
        if lifecycle not in LIFECYCLE_STATES:
            lifecycle = "draft"
        raw_adjacency_review = data.get("adjacency_review", "unreviewed")
        nested_adjacency = raw_adjacency_review if isinstance(raw_adjacency_review, dict) else {}
        adjacency_review = str(
            nested_adjacency.get("state", raw_adjacency_review)
        ).strip().lower()
        adjacency_review = LEGACY_ADJACENCY_REVIEW_STATES.get(
            adjacency_review, adjacency_review
        )
        if adjacency_review not in ADJACENCY_REVIEW_STATES:
            adjacency_review = "unreviewed"
        exceptions = data.get("validation_exceptions", []) or []
        if not isinstance(exceptions, list):
            exceptions = []
        return cls(
            schema_version=schema_version,
            profile_id=str(game.get("profile_id", "hoi4-1.19")),
            game_raw_version=game.get("raw_version"),
            game_install_dir=game.get("install_dir"),
            lifecycle=lifecycle,
            width=int(dims.get("width", 0) or 0),
            height=int(dims.get("height", 0) or 0),
            validation_exceptions=[dict(v) for v in exceptions if isinstance(v, dict)],
            adjacency_review=adjacency_review,
            adjacency_review_note=str(
                data.get("adjacency_review_note", nested_adjacency.get("note", "")) or ""
            ),
            adjacency_review_hash=(
                str(data.get("adjacency_review_hash", nested_adjacency.get("hash", ""))).strip()
                or None
            ),
            foundation_lock_ref=lock.get("ref"),
            foundation_lock_hash=lock.get("hash"),
            generator_version=str(data.get("generator_version", "") or ""),
            tool_version=str(data.get("tool_version", "") or _tool_version()),
            needs_target_confirmation=bool(data.get("needs_target_confirmation", False)),
            created_at=str(data.get("created_at", "") or ""),
            updated_at=str(data.get("updated_at", "") or ""),
        )


class UnknownSchemaError(ValueError):
    def __init__(self, schema_version: int, data: dict | None = None) -> None:
        super().__init__(
            f"unsupported project schema_version {schema_version}; "
            f"this tool supports {sorted(KNOWN_SCHEMA_VERSIONS)}"
        )
        self.schema_version = schema_version
        self.data = data or {}


class NewerSchemaError(UnknownSchemaError):
    pass


def default_meta(width: int = 0, height: int = 0, profile_id: str = "hoi4-1.19") -> ProjectMeta:
    now = _utc_now_iso()
    return ProjectMeta(
        schema_version=CURRENT_SCHEMA_VERSION,
        profile_id=profile_id,
        lifecycle="draft",
        width=int(width or 0),
        height=int(height or 0),
        adjacency_review="unreviewed",
        adjacency_review_note="",
        adjacency_review_hash=None,
        tool_version=_tool_version(),
        needs_target_confirmation=False,
        created_at=now,
        updated_at=now,
    )


def infer_meta_for_legacy_project(
    width: int = 0,
    height: int = 0,
    profile_id: str = "hoi4-1.19",
    game_raw_version: str | None = None,
    game_install_dir: str | None = None,
) -> ProjectMeta:
    now = _utc_now_iso()
    return ProjectMeta(
        schema_version=CURRENT_SCHEMA_VERSION,
        profile_id=profile_id,
        game_raw_version=game_raw_version,
        game_install_dir=game_install_dir,
        lifecycle="draft",
        width=int(width or 0),
        height=int(height or 0),
        validation_exceptions=[],
        adjacency_review="unreviewed",
        adjacency_review_note="",
        adjacency_review_hash=None,
        foundation_lock_ref=None,
        foundation_lock_hash=None,
        generator_version="",
        tool_version=_tool_version(),
        needs_target_confirmation=True,
        created_at=now,
        updated_at=now,
    )


def parse_meta_bytes(raw: bytes) -> ProjectMeta:
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"invalid {PROJECT_META_FILENAME}: {exc}") from exc
    return ProjectMeta.from_dict(data)


def meta_to_bytes(meta: ProjectMeta) -> bytes:
    payload = copy.deepcopy(meta.to_dict())
    payload["updated_at"] = _utc_now_iso()
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def read_meta_from_archive(path: str) -> ProjectMeta | None:
    from zipfile import ZipFile
    if not os.path.isfile(path):
        return None
    try:
        with ZipFile(path, "r") as zf:
            if PROJECT_META_FILENAME not in zf.namelist():
                return None
            return parse_meta_bytes(zf.read(PROJECT_META_FILENAME))
    except UnknownSchemaError:
        raise
    except Exception:
        return None


def backup_archive_before_migration(path: str, suffix: str = ".pre_m1.bak") -> str:
    import shutil
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    backup_path = str(path) + suffix
    counter = 1
    candidate = backup_path
    while os.path.exists(candidate):
        counter += 1
        candidate = f"{backup_path}.{counter}"
    shutil.copy2(path, candidate)
    return candidate
