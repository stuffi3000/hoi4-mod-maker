"""map/adjacencies.csv writer.

Reference Reference/Map modding.txt lines 485-502:
- 10 fields, semicolon separated
- End sentry: -1;-1;-1;-1;-1;-1;-1;-1;-1 (line 502, required, no hangup)
- UTF-8 without BOM (line 505 adjacency_rules mentions this requirement, adjacencies.csv does the same)
- LF line feed"""

from __future__ import annotations

import os


def write_adjacencies_csv(output_dir: str, adjacency_mgr=None) -> None:
    """Generate map/adjacencies.csv.

    adjacency_mgr: AdjacencyManager instance, can be None (write only header + sentry)."""
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "adjacencies.csv")

    lines: list[str] = []
    lines.append(
        "From;To;Type;Through;start_x;start_y;stop_x;stop_y;"
        "adjacency_rule_name;Comment"
    )

    if adjacency_mgr is not None:
        for entry in adjacency_mgr.get_all():
            lines.append(entry.to_csv_line())

    # Sentinel (required)
    lines.append("-1;-1;-1;-1;-1;-1;-1;-1;-1")

    # Write in binary mode, LF newline, UTF-8 without BOM
    content = "\n".join(lines) + "\n"
    with open(path, "wb") as f:
        f.write(content.encode("utf-8"))
