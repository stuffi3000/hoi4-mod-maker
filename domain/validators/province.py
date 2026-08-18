"""
省份验证器 — 检测 HOI4 省份地图中的各种问题
"""
import numpy as np
from collections import defaultdict

from ui.i18n import tr_pair

from data.constants import (
    MAP_WIDTH, MAP_HEIGHT,
    TILE_LAND, TILE_SEA, TILE_LAKE,
    MIN_PROVINCE_PIXELS,
)


def validate_provinces(
    tile_map: np.ndarray,
    province_map: np.ndarray,
) -> dict:
    """
    验证省份地图，检测所有可能导致 HOI4 崩溃的问题。

    返回:
        {
            "x_crossings": int,          # X型交叉数量
            "x_crossing_positions": list, # 交叉位置列表 [(y, x), ...]
            "too_small": int,             # 过小省份数量
            "too_small_ids": list,        # 过小省份ID列表
            "not_contiguous": int,        # 不连续省份数量
            "not_contiguous_ids": list,   # 不连续省份ID列表
            "coastal_mismatch": int,      # 沿海状态不一致数量
            "coastal_mismatch_ids": list, # 不一致的省份ID列表
        }
    """
    results = {
        "x_crossings": 0,
        "x_crossing_positions": [],
        "too_small": 0,
        "too_small_ids": [],
        "not_contiguous": 0,
        "not_contiguous_ids": [],
        "coastal_mismatch": 0,
        "coastal_mismatch_ids": [],
        # 新增：HOI4 文档明确的硬规则
        "too_large": 0,           # 单省宽/高 > 地图 1/8 (TOO LARGE BOX 错误)
        "too_large_ids": [],
        "id_gaps": [],            # ID 不连续的位置（应在 1..N 之间无空洞）
        "total_provinces": 0,
        "count_warning": "",      # 总数预警字符串
    }

    if province_map.max() == 0:
        return results

    # 1. X型交叉检测
    x_positions = detect_x_crossings(province_map)
    results["x_crossings"] = len(x_positions)
    results["x_crossing_positions"] = x_positions

    # 2. 过小省份检测
    small_ids = detect_small_provinces(province_map)
    results["too_small"] = len(small_ids)
    results["too_small_ids"] = small_ids

    # 3. 连续性检测
    non_contiguous = detect_non_contiguous(province_map)
    results["not_contiguous"] = len(non_contiguous)
    results["not_contiguous_ids"] = non_contiguous

    # 4. 沿海一致性检测
    coastal_issues = detect_coastal_mismatch(tile_map, province_map)
    results["coastal_mismatch"] = len(coastal_issues)
    results["coastal_mismatch_ids"] = coastal_issues

    # 5. TOO LARGE BOX 检测（单省宽/高超过地图 1/8）
    too_large_ids = detect_too_large_provinces(province_map)
    results["too_large"] = len(too_large_ids)
    results["too_large_ids"] = too_large_ids

    # 6. ID gap 检测（应连续 1..N，否则 csv 串位）
    results["id_gaps"] = detect_id_gaps(province_map)

    # 7. 总数预警
    total = int(province_map.max())
    results["total_provinces"] = total
    if total > 21000:
        results["count_warning"] = tr_pair(f"危险：{total} > 21000，超过 HOI4 边界硬上限，必崩", f"Danger: {total} > 21000, exceeding HOI4's hard limit and guaranteed to crash")
    elif total > 14000:
        results["count_warning"] = tr_pair(f"警告：{total} > 14000，HOI4 文档建议上限", f"Warning: {total} > 14000, the limit recommended by HOI4 documentation")
    elif total > 13000:
        results["count_warning"] = tr_pair(f"提示：{total} 接近 vanilla 13000-14000 推荐区间", f"Note: {total} is close to the recommended vanilla range of 13000–14000")

    return results


def detect_x_crossings(province_map: np.ndarray) -> list[tuple[int, int]]:
    """
    检测 X 型交叉：2×2 像素块中出现4种不同省份ID。
    HOI4 不允许这种情况，会导致崩溃。

    返回交叉位置列表 [(y, x), ...]，坐标是2×2块的左上角。
    """
    positions = []

    # 取2×2窗口的四个角
    tl = province_map[:-1, :-1]  # 左上
    tr_ = province_map[:-1, 1:]  # 右上
    bl = province_map[1:, :-1]   # 左下
    br = province_map[1:, 1:]    # 右下

    # 四个值互不相同的位置就是 X 型交叉
    # 用集合大小判断：如果4个值全不同，说明有交叉
    # 优化：先找出至少有3种不同值的位置，再精确判断
    diff1 = tl != tr_
    diff2 = tl != bl
    diff3 = tl != br
    diff4 = tr_ != bl
    diff5 = tr_ != br
    diff6 = bl != br

    # 6个两两比较都不同 → 4个值互不相同
    all_different = diff1 & diff2 & diff3 & diff4 & diff5 & diff6

    ys, xs = np.where(all_different)
    positions = [(int(y), int(x)) for y, x in zip(ys, xs)]

    # === 横向 wrap 边缘检测 ===
    # HOI4 文档明确：地图横向循环，X-crossing 可能正好出现在
    # 最右列与最左列之间的"接缝"上。普通切片会漏掉。
    # 取最右列和最左列组成的虚拟 2×2：
    #   [last_col[y],    first_col[y]   ]
    #   [last_col[y+1],  first_col[y+1] ]
    last_col = province_map[:, -1]
    first_col = province_map[:, 0]
    tl_w = last_col[:-1]
    tr_w = first_col[:-1]
    bl_w = last_col[1:]
    br_w = first_col[1:]
    diff_w = (
        (tl_w != tr_w) & (tl_w != bl_w) & (tl_w != br_w)
        & (tr_w != bl_w) & (tr_w != br_w) & (bl_w != br_w)
    )
    # 只在全图尺寸时检测 wrap 边缘（子数组不做 wrap）
    h, w = province_map.shape
    if w == MAP_WIDTH:
        ys_w = np.where(diff_w)[0]
        for y in ys_w:
            positions.append((int(y), w - 1))

    return positions


def fix_x_crossings(province_map: np.ndarray) -> int:
    """
    修复 X 型交叉：将2×2块中右下角的像素改为左上角的省份ID。

    返回修复数量。
    """
    _h, w = province_map.shape
    fixed = 0
    positions = detect_x_crossings(province_map)
    for y, x in positions:
        # wrap 边缘特殊处理：x == 最右列时右边像素是 [y+1, 0]
        if x == w - 1:
            province_map[y + 1, 0] = province_map[y, x]
        else:
            province_map[y + 1, x + 1] = province_map[y, x]
        fixed += 1
    return fixed


def fix_x_crossings_preserving(
    province_map: np.ndarray,
    protected_mask: np.ndarray,
    tile_map: np.ndarray,
) -> int:
    """Fix X-crossings without changing protected or cross-type pixels.

    Incremental generation uses the pre-existing province pixels as the
    protected region.  A fix is applied only when one of the newly generated
    pixels can copy an ID from another corner with the same land/sea/lake type.
    """
    _h, w = province_map.shape
    fixed = 0
    for y, x in detect_x_crossings(province_map):
        right = 0 if x == w - 1 else x + 1
        coords = [(y, x), (y, right), (y + 1, x), (y + 1, right)]
        changed = False
        for dst_y, dst_x in coords:
            if protected_mask[dst_y, dst_x]:
                continue
            dst_tile = int(tile_map[dst_y, dst_x])
            for src_y, src_x in coords:
                if (src_y, src_x) == (dst_y, dst_x):
                    continue
                if int(tile_map[src_y, src_x]) == dst_tile:
                    province_map[dst_y, dst_x] = province_map[src_y, src_x]
                    fixed += 1
                    changed = True
                    break
            if changed:
                break
    return fixed


def detect_small_provinces(
    province_map: np.ndarray,
    min_pixels: int = MIN_PROVINCE_PIXELS,
) -> list[int]:
    """
    检测像素数少于 min_pixels 的省份。
    返回过小省份ID列表。
    """
    if province_map.max() == 0:
        return []

    # 统计每个省份的像素数
    ids, counts = np.unique(province_map, return_counts=True)
    small = []
    for pid, count in zip(ids, counts):
        if pid > 0 and count < min_pixels:
            small.append(int(pid))
    return small


def detect_non_contiguous(province_map: np.ndarray) -> list[int]:
    """
    检测不连续的省份 — 用整图一次性标记连通分量，O(n)复杂度。
    不再逐省份扫描，而是对整张地图做一次 label，再比较省份ID和连通分量。
    """
    from scipy.ndimage import label

    max_pid = int(province_map.max())
    if max_pid == 0:
        return []

    # 对整张图做连通分量标记（相邻且值相同的像素归为一组）
    # structure: 4-connectivity
    struct = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.int32)
    labeled, num_features = label(province_map, structure=struct)

    # 如果省份是连续的，同一个pid应该只对应1个连通分量
    # 用 bincount 统计每个pid对应了多少个不同的label
    flat_pm = province_map.ravel()
    flat_lb = labeled.ravel()

    # 对每个pid，找它对应的所有label值，看是否>1个
    # 优化：构建 pid → set(labels) 的映射
    # 先用 pandas-free 方法：按pid分组统计唯一label数
    pid_label_pairs = flat_pm.astype(np.int64) * (num_features + 1) + flat_lb
    unique_pairs = np.unique(pid_label_pairs)

    # 从 pair 还原 pid
    pair_pids = unique_pairs // (num_features + 1)
    # 统计每个pid出现了几个不同的pair（= 几个不同的label）
    pid_counts = np.bincount(pair_pids.astype(np.intp), minlength=max_pid + 1)

    non_contiguous = []
    for pid in range(1, max_pid + 1):
        if pid_counts[pid] > 1:
            non_contiguous.append(pid)

    return non_contiguous


def detect_coastal_mismatch(
    tile_map: np.ndarray,
    province_map: np.ndarray,
) -> list[int]:
    """
    检测沿海状态不一致的省份。
    规则：如果一个 land 省份的任何像素与一个 sea 省份的像素相邻，
    则该 land 省份必须标记为 coastal=true。

    返回应该标记为 coastal 但当前可能未标记的省份ID列表。
    （这里只检测哪些陆地省份是沿海的，供导出时使用）
    """
    coastal_provinces = set()

    # 陆地和海洋省份的 mask
    # 注意：湖泊(TILE_LAKE)不算沿海依据 —— HOI4 规则是只有临海(sea)的陆地省才是 coastal。
    # 若把湖也算进去，csv 里该省会被标 coastal=true，但 buildings.txt 的 naval_base
    # 只会对临"海"省写入（sea_ids 不含湖），两边不一致会触发 MAP_ERROR 甚至崩溃。
    land_mask = tile_map == TILE_LAND
    sea_mask = tile_map == TILE_SEA

    # 检查每个陆地像素的4邻域是否有海洋像素
    # 上方
    coastal_up = land_mask[1:, :] & sea_mask[:-1, :]
    # 下方
    coastal_down = land_mask[:-1, :] & sea_mask[1:, :]
    # 左方
    coastal_left = land_mask[:, 1:] & sea_mask[:, :-1]
    # 右方
    coastal_right = land_mask[:, :-1] & sea_mask[:, 1:]

    # 收集沿海陆地像素对应的省份ID
    if np.any(coastal_up):
        ys, xs = np.where(coastal_up)
        for pid in np.unique(province_map[ys + 1, xs]):
            if pid > 0:
                coastal_provinces.add(int(pid))

    if np.any(coastal_down):
        ys, xs = np.where(coastal_down)
        for pid in np.unique(province_map[ys, xs]):
            if pid > 0:
                coastal_provinces.add(int(pid))

    if np.any(coastal_left):
        ys, xs = np.where(coastal_left)
        for pid in np.unique(province_map[ys, xs + 1]):
            if pid > 0:
                coastal_provinces.add(int(pid))

    if np.any(coastal_right):
        ys, xs = np.where(coastal_right)
        for pid in np.unique(province_map[ys, xs]):
            if pid > 0:
                coastal_provinces.add(int(pid))

    return sorted(coastal_provinces)


def build_coastal_land_to_sea(
    tile_map: np.ndarray,
    province_map: np.ndarray,
) -> dict[int, int]:
    """返回 {coastal_land_pid: adjacent_sea_pid} 映射（**像素级**邻接）。

    保证和 get_coastal_provinces 的结果**完全一致** — 任何被标记为 coastal 的
    陆地省都能在这里找到配对的海洋省。buildings.txt 就用这个结果写
    naval_base_spawn，避免"CSV 标 coastal 但 buildings 没 port"的崩溃。
    """
    land_mask = tile_map == TILE_LAND
    sea_mask = tile_map == TILE_SEA
    out: dict[int, int] = {}

    # 4 方向扫描：每个像素对 (land, sea) 检查是否真的是 land 在 a 侧、sea 在 b 侧
    # 上: (y, x) is land, (y-1, x) is sea  → land pid from (y, x), sea pid from (y-1, x)
    m_up = land_mask[1:, :] & sea_mask[:-1, :]
    if np.any(m_up):
        ys, xs = np.where(m_up)
        lp = province_map[ys + 1, xs]
        sp = province_map[ys, xs]
        for i in range(len(lp)):
            pid = int(lp[i])
            if pid > 0 and pid not in out:
                out[pid] = int(sp[i])

    m_down = land_mask[:-1, :] & sea_mask[1:, :]
    if np.any(m_down):
        ys, xs = np.where(m_down)
        lp = province_map[ys, xs]
        sp = province_map[ys + 1, xs]
        for i in range(len(lp)):
            pid = int(lp[i])
            if pid > 0 and pid not in out:
                out[pid] = int(sp[i])

    m_left = land_mask[:, 1:] & sea_mask[:, :-1]
    if np.any(m_left):
        ys, xs = np.where(m_left)
        lp = province_map[ys, xs + 1]
        sp = province_map[ys, xs]
        for i in range(len(lp)):
            pid = int(lp[i])
            if pid > 0 and pid not in out:
                out[pid] = int(sp[i])

    m_right = land_mask[:, :-1] & sea_mask[:, 1:]
    if np.any(m_right):
        ys, xs = np.where(m_right)
        lp = province_map[ys, xs]
        sp = province_map[ys, xs + 1]
        for i in range(len(lp)):
            pid = int(lp[i])
            if pid > 0 and pid not in out:
                out[pid] = int(sp[i])

    return out


def detect_too_large_provinces(province_map: np.ndarray) -> list[int]:
    """
    检测单个省份的 bounding box 是否超过地图宽/高的 1/8。
    HOI4 文档原文：
        "Province X has TOO LARGE BOX. Perhaps pixels are spread around the world"
        触发条件：width/height > 1/8 of total map width/height

    注意：横向 wrap 的省份（横跨地图东西边界）会有虚假的"超宽"，
    本函数不处理 wrap，因为 HOI4 引擎本身就是按 bbox 判断的，
    一个跨 wrap 的省份在 HOI4 看来确实是"超宽"的，需要拆分。
    """
    max_w = MAP_WIDTH // 8
    max_h = MAP_HEIGHT // 8

    if province_map.max() == 0:
        return []

    # 向量化求每个 ID 的 bbox
    flat = province_map.ravel()
    ys, xs = np.indices(province_map.shape)
    flat_y = ys.ravel()
    flat_x = xs.ravel()

    n = int(province_map.max()) + 1
    # 用 bincount 类技巧求 min/max 太麻烦；这里用 np.maximum.at / minimum.at
    min_y = np.full(n, MAP_HEIGHT, dtype=np.int32)
    max_y = np.full(n, -1, dtype=np.int32)
    min_x = np.full(n, MAP_WIDTH, dtype=np.int32)
    max_x = np.full(n, -1, dtype=np.int32)
    np.minimum.at(min_y, flat, flat_y)
    np.maximum.at(max_y, flat, flat_y)
    np.minimum.at(min_x, flat, flat_x)
    np.maximum.at(max_x, flat, flat_x)

    too_large = []
    for pid in range(1, n):
        if max_y[pid] < 0:
            continue
        h = max_y[pid] - min_y[pid] + 1
        w = max_x[pid] - min_x[pid] + 1
        if w > max_w or h > max_h:
            too_large.append(pid)
    return too_large


def detect_id_gaps(province_map: np.ndarray) -> list[int]:
    """
    检测 ID gap：1..max 之间应该没有缺失的 ID。
    HOI4 文档原文：
        "if province 23 doesn't exist, province 24 will take on
         the terrain, type, coastal status, and continent of province 25"
    返回缺失的 ID 列表。
    """
    if province_map.max() == 0:
        return []
    present = set(int(x) for x in np.unique(province_map))
    present.discard(0)
    max_id = int(province_map.max())
    expected = set(range(1, max_id + 1))
    missing = sorted(expected - present)
    return missing


def get_coastal_provinces(
    tile_map: np.ndarray,
    province_map: np.ndarray,
) -> set[int]:
    """
    获取所有沿海陆地省份的ID集合。
    用于导出 definition.csv 时设置 coastal 字段。
    """
    return set(detect_coastal_mismatch(tile_map, province_map))
