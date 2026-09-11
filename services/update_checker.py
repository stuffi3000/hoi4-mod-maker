"""Version Update Check — Checks GitHub Releases in the background on startup."""
from __future__ import annotations

import json
import urllib.request
from typing import Optional

from version import VERSION

GITHUB_API_URL = "https://api.github.com/repos/AmonStreeling/hoi4-mod-maker/releases/latest"
GITHUB_RELEASES_URL = "https://github.com/AmonStreeling/hoi4-mod-maker/releases"


def check_for_update() -> Optional[dict]:
    """Check if there is a new version. Return None if it is the latest, otherwise return {version, body, url}.
    Network errors silently return None (do not disturb the user)."""
    try:
        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={"User-Agent": "hoi4-map-maker", "Accept": "application/vnd.github.v3+json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        remote_version = data.get("tag_name", "").lstrip("v")
        if not remote_version:
            return None

        if _is_newer(remote_version, VERSION):
            return {
                "version": remote_version,
                "body": data.get("body", ""),
                "url": data.get("html_url", GITHUB_RELEASES_URL),
            }
        return None
    except Exception:
        return None


def _is_newer(remote: str, local: str) -> bool:
    """Compare version numbers, remote > local returns True.
    Supported formats: 1.0.0 / 1.0.0-beta.1, etc."""
    def _parse(v: str) -> tuple:
        # Remove suffixes like -beta.1 to compare main versions
        main = v.split("-")[0]
        parts = []
        for p in main.split("."):
            try:
                parts.append(int(p))
            except ValueError:
                parts.append(0)
        # Those with pre-release suffix are lower than those without.
        pre = v.split("-", 1)[1] if "-" in v else ""
        return tuple(parts), pre

    r_main, r_pre = _parse(remote)
    l_main, l_pre = _parse(local)

    if r_main > l_main:
        return True
    if r_main == l_main:
        # Same main version: no pre > yes pre (1.0.0 > 1.0.0-beta.1)
        if not r_pre and l_pre:
            return True
        # Both have pre: compare by string
        if r_pre and l_pre and r_pre > l_pre:
            return True
    return False
