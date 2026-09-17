"""Game-profile resolution service (M1.2 compatibility layer).

Loads the bundled data-driven ``GameProfile`` for 1.19.x and exposes small
helpers so exporters, validators, and services can validate dimensions,
asset sizes, province counts, and file dispositions without hard-coding
global constants or preset allowlists.
"""
from __future__ import annotations

import os

from domain.game_profile import (
    BUNDLED_PROFILE_1_19,
    PROFILE_ID_1_19,
    GameProfile,
    load_profile_from_file,
    profile_from_dict,
)


_DEFAULT_PROFILE: GameProfile | None = None
_PROFILE_CACHE: dict[str, GameProfile] = {}


def _default_profile_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    candidate = os.path.join(repo_root, BUNDLED_PROFILE_1_19)
    if os.path.isfile(candidate):
        return candidate
    if os.path.isfile(BUNDLED_PROFILE_1_19):
        return os.path.abspath(BUNDLED_PROFILE_1_19)
    return candidate


def get_default_profile() -> GameProfile:
    global _DEFAULT_PROFILE
    if _DEFAULT_PROFILE is not None:
        return _DEFAULT_PROFILE
    path = _default_profile_path()
    if os.path.isfile(path):
        try:
            _DEFAULT_PROFILE = load_profile_from_file(path)
            _PROFILE_CACHE[_DEFAULT_PROFILE.profile_id] = _DEFAULT_PROFILE
            return _DEFAULT_PROFILE
        except (OSError, ValueError):
            pass
    fallback = GameProfile(profile_id=PROFILE_ID_1_19)
    _DEFAULT_PROFILE = fallback
    return fallback


def get_profile(profile_id: str | None = None) -> GameProfile:
    if not profile_id or profile_id == PROFILE_ID_1_19:
        return get_default_profile()
    cached = _PROFILE_CACHE.get(str(profile_id))
    if cached is not None:
        return cached
    default = get_default_profile()
    if str(profile_id) in (default.profile_id, "hoi4-1.19.x", "1.19"):
        return default
    return default


def load_profile_for_target(game_target=None) -> GameProfile:
    profile_id = None
    if game_target is not None:
        profile_id = getattr(game_target, "profile_id", None)
    return get_profile(profile_id)


def validate_map_dimensions(width: int, height: int, profile: GameProfile | None = None) -> list[str]:
    active = profile or get_default_profile()
    return active.validate_dimensions(width, height)


def is_supported_dimension(width: int, height: int, profile: GameProfile | None = None) -> bool:
    active = profile or get_default_profile()
    return active.is_supported_dimension(width, height)


def expected_asset_size(asset_key: str, map_w: int, map_h: int, profile: GameProfile | None = None) -> tuple[int, int] | None:
    active = profile or get_default_profile()
    size = active.expected_bmp_size(asset_key, map_w, map_h)
    if size is not None:
        return size
    return active.expected_dds_size(asset_key, map_w, map_h)


def profile_id_for_version(raw_version: str | None) -> str:
    text = str(raw_version or "").strip()
    parts = text.split(".")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"hoi4-{parts[0]}.{parts[1]}"
    return PROFILE_ID_1_19
