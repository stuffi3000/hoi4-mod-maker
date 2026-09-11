"""Art asset export assist — decide whether to write back the original bytes or regenerate them.

When importing MOD, the tool reads non-structured files such as colormap / world_normal into project.assets.
The related assets are marked dirty when the user edits the canvas. When exporting:
  clean → write back the original bytes directly (retain the original art)
  dirty or not in assets → adjust generator_fn to generate a new version"""
from __future__ import annotations

import os
from typing import Callable


def write_or_restore(
    rel_path: str,
    output_dir: str,
    assets: dict[str, bytes] | None,
    dirty_assets: set[str] | None,
    generator_fn: Callable[[], None],
) -> str:
    """Depending on the dirty status, decide whether to write back the original asset or generate a new file.

    Parameters:
        rel_path: MOD relative path, such as "map/terrain/colormap_rgb_cityemissivemask_a.dds"
                  (Slash separated, consistent with the key of project.assets)
        output_dir: export root directory (MOD root)
        assets: project.assets (may be None, indicating no assets were imported)
        dirty_assets: project.dirty_assets (may be None)
        generator_fn: function called when regeneration is required (no parameters, internally writes the file itself)

    Return:
        "restored" | "generated" | "skipped"
    """
    if assets is None:
        assets = {}
    if dirty_assets is None:
        dirty_assets = set()

    # clean asset → write back the original bytes
    if rel_path in assets and rel_path not in dirty_assets:
        dst = os.path.join(output_dir, rel_path.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(assets[rel_path])
        return "restored"

    # Otherwise execute the generation
    generator_fn()
    return "generated"


def classify_assets(
    rel_paths: list[str],
    assets: dict[str, bytes] | None,
    dirty_assets: set[str] | None,
) -> tuple[int, int, int]:
    """Statistics: (restored, generated, total_paths).

    Used for UI to display "Keep X / Respawn Y".
    """
    if assets is None:
        assets = {}
    if dirty_assets is None:
        dirty_assets = set()
    restored = 0
    generated = 0
    for p in rel_paths:
        if p in assets and p not in dirty_assets:
            restored += 1
        else:
            generated += 1
    return restored, generated, len(rel_paths)
