"""map/supply_nodes.txt writer.

Reference: Reference/Map modding.txt lines 528-532
Format: Level ProvinceID (one per line, separated by spaces)
- Cannot be empty, empty file will collapse (CLAUDE.md)
- UTF-8 without BOM, LF newline"""

from __future__ import annotations

import os


def write_supply_nodes_txt(
    output_dir: str,
    supply_mgr=None,
    fallback_pid: int = 1,
) -> None:
    """Generate map/supply_nodes.txt.

    supply_mgr: SupplyNodeManager instance. Write placeholder when None or empty.
    fallback_pid: Fallback province ID used when empty."""
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "supply_nodes.txt")

    lines: list[str] = []
    if supply_mgr is not None:
        for node in supply_mgr.get_all():
            lines.append(node.to_line())

    if not lines:
        lines.append(f"1 {fallback_pid}")

    content = "\n".join(lines) + "\n"
    with open(path, "wb") as f:
        f.write(content.encode("utf-8"))
