"""buildings.txt / unitstacks.txt 等 entity 文件."""
import os
import numpy as np
from data.constants import (
    TILE_LAND, TILE_SEA,
    VALID_3D_BUILDING_TYPES,
)
# 不 import MAP_WIDTH/HEIGHT — 一律用 province_map.shape 取动态尺寸.
from domain.validators.province import get_coastal_provinces, build_coastal_land_to_sea


from export.writers.map._coords import safe_coord as _safe_coord


def write_buildings(states, province_map, tile_map, output_dir, sea_ids=None,
                    land_to_sea=None,
                    pid_count=None, sum_x=None, sum_y=None):
    """写 buildings.txt。
    如果传入预计算的 land_to_sea/pid_count/sum_x/sum_y，直接使用；否则自行计算。
    """
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)

    n = int(province_map.max()) + 1
    # 用实际数组形状, 不能用全局 MAP_WIDTH/HEIGHT (用户可能选其他尺寸)
    map_h, map_w = province_map.shape

    # 使用预计算数据，或自行计算质心
    if pid_count is None:
        flat_pm = province_map.ravel()
        pid_count = np.bincount(flat_pm, minlength=n)
        ys_grid, xs_grid = np.mgrid[0:map_h, 0:map_w]
        sum_y = np.bincount(flat_pm, weights=ys_grid.ravel().astype(np.float64), minlength=n)
        sum_x = np.bincount(flat_pm, weights=xs_grid.ravel().astype(np.float64), minlength=n)

    # 使用预计算的 land_to_sea，或自行计算
    # **关键**: 必须和 definition.csv 的 coastal 字段完全同步 — 任何被 CSV 标为
    # coastal=true 的省，在这里都必须有 naval_base_spawn，否则 HOI4 进图崩溃
    # (map.cpp:1628 "coastal but has no port building")
    if land_to_sea is None:
        land_to_sea = build_coastal_land_to_sea(tile_map, province_map)

    pid_to_state = {}
    for sid, provs in states.items():
        for p in provs:
            pid_to_state[int(p)] = sid

    # 每个 state 必须有全部建筑类型的 3D 位置，否则 HOI4 初始化除零崩溃
    lines = []
    # 所有 state 都需要的建筑位置
    REQUIRED_STATE_ENTITIES = (
        "arms_factory", "industrial_complex", "air_base",
        "anti_air_building", "bunker", "fuel_silo", "radar_station",
        "nuclear_reactor_spawn", "rocket_site_spawn", "synthetic_refinery",
        "supply_node",
    )
    # 沿海 state 额外需要的建筑位置
    COASTAL_STATE_ENTITIES = ("dockyard", "coastal_bunker")

    # 收集哪些 state 是沿海的
    coastal_states = set()
    for land_pid in (land_to_sea or {}):
        s = pid_to_state.get(land_pid)
        if s is not None:
            coastal_states.add(s)

    for sid, provs in states.items():
        if not provs:
            continue

        # BUG-5 修复 v2: 分散建筑到 state 内不同 land province 中心
        # (v1 用螺旋偏移把建筑推到邻 state / 海里, mapbuildings.cpp:716/679 报错 → 已回滚)
        # 收集该 state 内所有合法 land province 的安全中心坐标
        valid_centroids: list[tuple[float, float]] = []
        for p in provs:
            if p < n and pid_count[p] > 0:
                cx_p, cy_p = _safe_coord(p, province_map, pid_count, sum_x, sum_y)
                iy, ix = int(round(cy_p)), int(round(cx_p))
                # 严格校验坐标落在 LAND 像素上 (避免 mapbuildings.cpp:679 not over land)
                if 0 <= iy < map_h and 0 <= ix < map_w and tile_map[iy, ix] == TILE_LAND:
                    # Write the centre of the validated pixel, not a floating
                    # centroid near a pixel edge.  The engine floors building
                    # coordinates when it checks the terrain below them.
                    valid_centroids.append((ix + 0.5, iy + 0.5))

        # 没有合法 land 中心: 退回到老逻辑 (provs[0] 中心, 不分散但保证有坐标)
        if not valid_centroids:
            pid = provs[0]
            if pid >= n or pid_count[pid] == 0:
                continue
            cx, cy = _safe_coord(pid, province_map, pid_count, sum_x, sum_y)
            iy, ix = int(round(cy)), int(round(cx))
            if not (0 <= iy < map_h and 0 <= ix < map_w and tile_map[iy, ix] == TILE_LAND):
                ys, xs = np.where((province_map == pid) & (tile_map == TILE_LAND))
                if len(ys) == 0:
                    continue
                iy, ix = int(ys[0]), int(xs[0])
            valid_centroids = [(ix + 0.5, iy + 0.5)]

        btypes = list(REQUIRED_STATE_ENTITIES)
        if sid in coastal_states:
            btypes.extend(COASTAL_STATE_ENTITIES)
        # 每个建筑轮流分配到一个 land province 的中心 (不跨 state, 不入海)
        for i, btype in enumerate(btypes):
            cx_b, cy_b = valid_centroids[i % len(valid_centroids)]
            hoi4_y = map_h - cy_b
            lines.append(
                f"{sid};{btype};{cx_b:.2f};11.00;{hoi4_y:.2f};0.00;0"
            )

    # 只给真正沿海的省份写 naval_base_spawn
    # 关键: HOI4 按 floor 方式把坐标转回像素索引判 "over the land"。若坐标刚好
    # 落在像素边界（如 x=2778.93 → floor 到像素 2778，而 land 像素是 2779），
    # 会被判到邻居 sea 像素 → "not over the land" → port 忽略 → 省 coastal
    # 但无 port → HOI4 崩溃 (map.cpp:1628)
    # 对策: 总是取**整数像素 + 0.5**（像素中心），让取整方向稳定。
    h_map, w_map = province_map.shape
    failed_coastal: set[int] = set()
    for land_pid, sea_pid in land_to_sea.items():
        sid = pid_to_state.get(land_pid)
        if sid is None:
            continue
        if land_pid >= n or pid_count[land_pid] == 0:
            continue
        # 第一选择: 质心最近的合法 land 像素 (province_map==pid AND tile_map==LAND)
        # 不直接用 _safe_coord 的质心，因为质心可能在海或边界上
        valid_ys, valid_xs = np.where(
            (province_map == land_pid) & (tile_map == TILE_LAND)
        )
        if len(valid_ys) == 0:
            failed_coastal.add(land_pid)
            continue
        cx_centroid, cy_centroid = _safe_coord(
            land_pid, province_map, pid_count, sum_x, sum_y)
        dist = (valid_ys.astype(float) - cy_centroid) ** 2 + \
               (valid_xs.astype(float) - cx_centroid) ** 2
        best = int(np.argmin(dist))
        iy, ix = int(valid_ys[best]), int(valid_xs[best])
        # 写坐标用**像素中心** (整数 + 0.5)，避免 HOI4 取整落到边界外
        cx_out = ix + 0.5
        cy_out = iy + 0.5
        hoi4_y = map_h - cy_out
        lines.append(
            f"{sid};naval_base_spawn;{cx_out:.2f};11.00;{hoi4_y:.2f};0.00;{sea_pid}"
        )

    if not lines:
        lines.append("1;bunker;100.00;11.00;100.00;0.00;0")

    with open(os.path.join(d, "buildings.txt"), "wb") as f:
        f.write("\n".join(lines).encode("utf-8"))

    return failed_coastal


def write_empty_unitstacks(output_dir):
    """写空 map/*.txt 文件覆盖原版，避免 vanilla 的 13000+ 省份 ID 引用崩溃。

    原版 map/ 目录里的这些文件按省份 ID 引用坐标/规则；vanilla IDs 在我们的
    地图里全部无效，会触发 map.cpp:1135 错误。空文件让 HOI4 用默认值。

    【特例 cities.txt】不能为空！它是配置文件（指向 cities.bmp 的元数据），
    第一行 types_source = "map/cities.bmp" 告诉 HOI4 城市 mask 在哪。空文件
    会触发 "Missing cities mask bitmap" → 进图崩溃。写最小配置即可。
    """
    d = os.path.join(output_dir, "map")
    os.makedirs(d, exist_ok=True)
    # adjacency_rules.txt 由 writers/map/adjacency_rules.py 单独写, 这里不再创建空文件
    for name in (
        "unitstacks.txt",
        "airports.txt",
        "rocket_sites.txt",
    ):
        open(os.path.join(d, name), "w").close()

    # cities.txt：最小配置，只指向 cities.bmp，不定义任何 city_group
    # → HOI4 找到 mask 文件但不渲染任何 3D 城市模型（地图上无城市建筑）
    with open(os.path.join(d, "cities.txt"), "w", encoding="utf-8") as f:
        f.write('types_source = "map/cities.bmp"\n')
        f.write("pixel_step_x = 2\n")
        f.write("pixel_step_y = 2\n")
