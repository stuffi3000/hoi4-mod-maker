"""
map/railways.txt 写入器.

参考: 参考/Map modding.txt 行 534-540
格式: Level Count ProvId1 ProvId2 ... (空格分隔, 每行一条)
- 不能空 (CLAUDE.md 约束, 空文件会崩)
- 无 BOM, LF 换行

导出逻辑：保留显式铁路路径；省份画笔产生的单省份占位则按地图邻接连接。
"""

from __future__ import annotations

import os
import numpy as np


def write_railways_txt(
    output_dir: str,
    railway_mgr=None,
    province_map: np.ndarray | None = None,
    fallback_pid: int = 1,
) -> None:
    """生成 map/railways.txt。

    显式路径按原顺序输出。省份画笔的 ``[pid, pid]`` 占位条目用
    province_map 推导相邻连接。
    """
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "railways.txt")

    lines: list[str] = []

    if railway_mgr is not None and province_map is not None:
        lines = _build_manager_railway_lines(railway_mgr, province_map)

    # 必须非空
    if not lines:
        lines.append(f"1 2 {fallback_pid} {fallback_pid}")

    content = "\n".join(lines) + "\n"
    with open(path, "wb") as f:
        f.write(content.encode("utf-8"))


def _build_railway_lines(
    levels: dict[int, int],
    province_map: np.ndarray,
) -> list[str]:
    """把省份等级映射转成相邻省份对的铁路线。

    算法: 扫描 province_map 找相邻省份对，
    如果两个省份都有铁路等级，生成一条 level=min 的铁路。
    去重后输出。
    """
    # 找所有相邻省份对（向量化，不逐像素循环）
    pm = province_map
    pairs: set[tuple[int, int]] = set()

    # 垂直相邻
    diff_v = pm[:-1, :] != pm[1:, :]
    ys, xs = np.where(diff_v)
    for i in range(len(ys)):
        a, b = int(pm[ys[i], xs[i]]), int(pm[ys[i] + 1, xs[i]])
        if a > 0 and b > 0 and a in levels and b in levels:
            pair = (min(a, b), max(a, b))
            pairs.add(pair)

    # 水平相邻
    diff_h = pm[:, :-1] != pm[:, 1:]
    ys, xs = np.where(diff_h)
    for i in range(len(ys)):
        a, b = int(pm[ys[i], xs[i]]), int(pm[ys[i], xs[i] + 1])
        if a > 0 and b > 0 and a in levels and b in levels:
            pair = (min(a, b), max(a, b))
            pairs.add(pair)

    # 生成铁路线: 每对相邻省份一条, level = min(两者等级)
    lines: list[str] = []
    for a, b in sorted(pairs):
        lvl = min(levels[a], levels[b])
        lines.append(f"{lvl} 2 {a} {b}")

    return lines


def _build_manager_railway_lines(railway_mgr, province_map: np.ndarray) -> list[str]:
    """Preserve authored paths and expand only brush placeholders."""
    entries = railway_mgr.get_all()
    present = set(int(p) for p in np.unique(province_map) if p > 0)
    explicit = [
        entry for entry in entries
        if len(entry.province_ids) >= 2
        and len(set(entry.province_ids)) >= 2
        and all(pid in present for pid in entry.province_ids)
    ]
    lines = [entry.to_line() for entry in explicit]
    explicit_pairs = {
        tuple(sorted((a, b)))
        for entry in explicit
        for a, b in zip(entry.province_ids, entry.province_ids[1:])
    }
    placeholders = {
        entry.province_ids[0] for entry in entries
        if entry.province_ids and len(set(entry.province_ids)) == 1
    }
    if placeholders:
        for line in _build_railway_lines(railway_mgr.province_levels(), province_map):
            parts = line.split()
            a, b = int(parts[2]), int(parts[3])
            if (a in placeholders or b in placeholders) and (a, b) not in explicit_pairs:
                lines.append(line)
    return lines
