"""
MOD 输出验证器 — 检查导出的所有文件是否符合 HOI4 格式要求
不启动游戏就能发现大部分格式错误

用法:
    python -m export.verify_mod  D:/path/to/exported/mod
"""
import os
import struct
import sys
import re
from collections import Counter


_VALID_STATE_CATEGORIES = frozenset({
    "wasteland", "enclave", "tiny_island", "small_island", "large_island",
    "pastoral", "rural", "town", "large_town", "city", "large_city",
    "metropolis", "megalopolis",
})


class ModVerifier:
    """逐文件检查 HOI4 MOD 输出，报告所有发现的问题"""

    def __init__(self, mod_dir: str, *, quiet: bool = False):
        self.mod_dir = mod_dir
        self.errors: list[str] = []    # 必定崩溃
        self.warnings: list[str] = []  # 可能有问题
        self._quiet = quiet

    def _run_all_checks(self) -> None:
        """执行所有验证检查（内部方法，不打印）"""
        self._check_required_files()
        self._check_provinces_bmp()
        self._check_definition_csv()
        self._check_default_map()
        self._check_heightmap_bmp()
        self._check_terrain_bmp()
        self._check_rivers_bmp()
        self._check_states()
        self._check_strategic_regions()
        self._check_supply_files()
        self._check_countries()
        self._check_ideologies()
        self._check_state_categories()
        self._check_bookmarks()
        self._check_localisation()
        self._check_descriptor()
        self._check_seasons()
        self._cross_validate()

    def verify_all(self) -> bool:
        """运行所有检查，返回 True = 通过"""
        print(f"Verifying mod: {self.mod_dir}\n")

        self._run_all_checks()

        # 报告
        print("\n" + "=" * 60)
        if self.errors:
            print(f"\n❌ Found {len(self.errors)} errors (these may cause crashes):")
            for i, e in enumerate(self.errors, 1):
                print(f"  {i}. {e}")
        if self.warnings:
            print(f"\n⚠️  Found {len(self.warnings)} warnings:")
            for i, w in enumerate(self.warnings, 1):
                print(f"  {i}. {w}")
        if not self.errors and not self.warnings:
            print("\n✅ All checks passed!")

        return len(self.errors) == 0

    @classmethod
    def verify_quiet(cls, mod_dir: str) -> tuple[list[str], list[str]]:
        """静默运行所有检查，返回 (errors, warnings)。
        不打印任何内容，适合 UI 调用。"""
        v = cls(mod_dir, quiet=True)
        v._run_all_checks()
        return v.errors, v.warnings

    def _log(self, msg: str) -> None:
        if not self._quiet:
            print(msg)

    def _path(self, *parts):
        return os.path.join(self.mod_dir, *parts)

    def _exists(self, *parts):
        return os.path.exists(self._path(*parts))

    def _replaces_path(self, relative_path: str) -> bool:
        """Return whether the internal descriptor replaces *relative_path*."""
        descriptor = self._path("descriptor.mod")
        if not os.path.isfile(descriptor):
            return False
        try:
            with open(descriptor, "r", encoding="utf-8-sig", errors="replace") as file:
                content = file.read()
        except OSError:
            return False
        pattern = rf'^\s*replace_path\s*=\s*"{re.escape(relative_path)}"'
        return re.search(pattern, content, re.MULTILINE) is not None

    # ──────────────── 检查项 ────────────────

    def _check_required_files(self):
        """检查所有必需文件是否存在"""
        self._log("[1/16] Checking required files...")
        required = [
            ("map/provinces.bmp", "province map"),
            ("map/definition.csv", "province definitions"),
            ("map/default.map", "map configuration"),
            ("map/heightmap.bmp", "heightmap"),
            ("map/terrain.bmp", "terrain map"),
            ("map/rivers.bmp", "river map"),
            ("map/trees.bmp", "tree map"),
            ("map/continent.txt", "continent definitions"),
            ("map/adjacencies.csv", "adjacency definitions"),
            ("map/adjacency_rules.txt", "adjacency rules"),
            ("map/ambient_object.txt", "ambient objects"),
            ("map/seasons.txt", "season definitions"),
            ("map/positions.txt", "province positions"),
            ("map/supply_nodes.txt", "supply hubs"),
            ("map/railways.txt", "railways"),
            ("map/buildings.txt", "buildings"),
            ("descriptor.mod", "mod descriptor"),
        ]
        for path, name in required:
            if not self._exists(path):
                self.errors.append(f"Missing required file: {path} ({name})")

    def _check_provinces_bmp(self):
        """检查 provinces.bmp 格式"""
        self._log("[2/16] Checking provinces.bmp...")
        path = self._path("map", "provinces.bmp")
        if not os.path.exists(path):
            return

        with open(path, "rb") as f:
            sig = f.read(2)
            if sig != b"BM":
                self.errors.append("provinces.bmp is not a valid BMP file")
                return

            f.seek(18)
            w = struct.unpack("<i", f.read(4))[0]
            h = struct.unpack("<i", f.read(4))[0]
            f.read(2)  # planes
            bits = struct.unpack("<H", f.read(2))[0]

            valid_sizes = {(2048, 1024), (3072, 1536), (4096, 2048), (5632, 2048)}
            if (w, abs(h)) not in valid_sizes:
                self.errors.append(
                    f"provinces.bmp size is {w}x{abs(h)}; expected one of "
                    f"2048x1024, 3072x1536, 4096x2048, or 5632x2048"
                )
            if bits != 24:
                self.errors.append(f"provinces.bmp bit depth is {bits}; expected 24")
            if h < 0:
                self.errors.append("provinces.bmp is top-down; it must be bottom-up (height must be positive)")

            # 检查是否有 (0,0,0) 像素
            f.seek(10)
            offset = struct.unpack("<I", f.read(4))[0]
            f.seek(offset)

            row_bytes = w * 3
            padding = (4 - (row_bytes % 4)) % 4
            has_black = False
            for _ in range(min(10, h)):  # 抽查前10行
                row = f.read(row_bytes)
                f.read(padding)
                for x in range(0, len(row), 3):
                    if row[x] == 0 and row[x + 1] == 0 and row[x + 2] == 0:
                        has_black = True
                        break
                if has_black:
                    break
            if has_black:
                self.errors.append("provinces.bmp contains RGB(0,0,0) pixels, which will crash HOI4")

    def _check_definition_csv(self):
        """检查 definition.csv 格式"""
        self._log("[3/16] Checking definition.csv...")
        path = self._path("map", "definition.csv")
        if not os.path.exists(path):
            return

        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            lines = f.readlines()

        if not lines:
            self.errors.append("definition.csv is empty")
            return

        # 第一行必须是ID=0
        first = lines[0].strip()
        if not first.startswith("0;"):
            self.errors.append(f"definition.csv: the first line must begin with '0;'; actual value: '{first[:20]}'")

        seen_colors = set()
        seen_ids = set()
        valid_types = {"land", "sea", "lake"}
        self._province_ids = set()
        self._land_province_ids = set()
        self._sea_province_ids = set()
        self._coastal_province_ids = set()
        self._province_color_to_id = {}

        for i, line in enumerate(lines):
            line = line.rstrip("\n")
            if line.endswith(" ") or line.endswith("\t"):
                self.errors.append(f"definition.csv line {i + 1}: trailing space/tab")
            parts = line.strip().split(";")
            if len(parts) != 8:
                self.errors.append(f"definition.csv line {i + 1}: {len(parts)} fields; expected 8")
                continue

            pid = int(parts[0])
            r, g, b = int(parts[1]), int(parts[2]), int(parts[3])
            ptype = parts[4]

            if pid in seen_ids:
                self.errors.append(f"definition.csv: duplicate province ID {pid}")
            seen_ids.add(pid)

            if pid > 0:
                self._province_ids.add(pid)
                if ptype == "land":
                    self._land_province_ids.add(pid)
                    if parts[5].strip().lower() == "true":
                        self._coastal_province_ids.add(pid)
                elif ptype == "sea":
                    self._sea_province_ids.add(pid)

                color = (r, g, b)
                if color == (0, 0, 0):
                    self.errors.append(f"definition.csv province {pid}: color (0,0,0) is forbidden by HOI4")
                if color in seen_colors:
                    self.errors.append(f"definition.csv province {pid}: color {color} duplicates another province")
                seen_colors.add(color)
                self._province_color_to_id[color] = pid

            if ptype not in valid_types:
                self.warnings.append(f"definition.csv province {pid}: type='{ptype}' is non-standard")
            elif ptype != "land" and parts[5].strip().lower() == "true":
                self.errors.append(f"definition.csv province {pid}: only land provinces may be coastal")

        self._log(f"    → {len(self._province_ids)} provinces ({len(self._land_province_ids)} land)")

    def _check_default_map(self):
        """检查 default.map"""
        self._log("[4/16] Checking default.map...")
        path = self._path("map", "default.map")
        if not os.path.exists(path):
            return

        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            content = f.read()

        required_refs = [
            "definition.csv", "provinces.bmp", "positions.txt",
            "terrain.bmp", "rivers.bmp", "heightmap.bmp",
            "trees.bmp", "continent.txt", "adjacencies.csv",
            "seasons.txt",
        ]
        for ref in required_refs:
            if ref not in content:
                self.errors.append(f"default.map: missing reference to {ref}")

        if "sea_starts" in content:
            self.errors.append("default.map contains sea_starts (unsupported in 1.17; use the type in definition.csv instead)")
        if "max_provinces" in content:
            self.warnings.append("default.map contains max_provinces (possibly unsupported in 1.17)")

    def _get_provinces_bmp_size(self) -> tuple[int, int] | None:
        """读取 provinces.bmp 的尺寸，用于和其他 BMP 做一致性校验"""
        path = self._path("map", "provinces.bmp")
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            if f.read(2) != b"BM":
                return None
            f.seek(18)
            w = struct.unpack("<i", f.read(4))[0]
            h = abs(struct.unpack("<i", f.read(4))[0])
            return (w, h)

    def _check_heightmap_bmp(self):
        """检查 heightmap.bmp"""
        self._log("[5/16] Checking heightmap.bmp...")
        size = self._get_provinces_bmp_size()
        if size:
            self._check_8bit_bmp("map/heightmap.bmp", "heightmap.bmp", size[0], size[1])

    def _check_terrain_bmp(self):
        """检查 terrain.bmp"""
        self._log("[6/16] Checking terrain.bmp...")
        size = self._get_provinces_bmp_size()
        if size:
            self._check_8bit_bmp("map/terrain.bmp", "terrain.bmp", size[0], size[1])

    def _check_rivers_bmp(self):
        """检查 rivers.bmp"""
        self._log("[7/16] Checking rivers.bmp...")
        size = self._get_provinces_bmp_size()
        if size:
            self._check_8bit_bmp("map/rivers.bmp", "rivers.bmp", size[0], size[1])

    def _check_8bit_bmp(self, rel_path, name, expected_w, expected_h):
        path = self._path(rel_path)
        if not os.path.exists(path):
            return
        with open(path, "rb") as f:
            sig = f.read(2)
            if sig != b"BM":
                self.errors.append(f"{name} is not a valid BMP file")
                return
            f.seek(18)
            w = struct.unpack("<i", f.read(4))[0]
            h = struct.unpack("<i", f.read(4))[0]
            f.read(2)
            bits = struct.unpack("<H", f.read(2))[0]

            if w != expected_w or abs(h) != expected_h:
                self.errors.append(f"{name} size is {w}x{abs(h)}; expected {expected_w}x{expected_h}")
            if bits != 8:
                self.errors.append(f"{name} bit depth is {bits}; expected 8")

    def _check_states(self):
        """检查 State 文件"""
        self._log("[8/16] Checking states...")
        state_dir = self._path("history", "states")
        if not os.path.isdir(state_dir):
            self.errors.append("Missing history/states/ directory")
            return

        files = [f for f in os.listdir(state_dir) if f.endswith(".txt")]
        if not files:
            self.errors.append("history/states/ is empty; at least one state is required")
            return

        self._state_provinces = set()  # 所有State中的省份
        self._state_ids = set()
        self._state_prov_lists = {}    # {state_id: [pid...]} — 供战略区交叉检查用

        for fn in files:
            with open(os.path.join(state_dir, fn), "r", encoding="utf-8-sig", errors="replace") as f:
                content = f.read()

            # 提取 State ID
            id_match = re.search(r'id\s*=\s*(\d+)', content)
            if id_match:
                self._state_ids.add(int(id_match.group(1)))

            category_match = re.search(r'state_category\s*=\s*(\S+)', content)
            if category_match and category_match.group(1) not in _VALID_STATE_CATEGORIES:
                self.errors.append(
                    f"{fn}: undefined state_category '{category_match.group(1)}'"
                )

            # 提取省份列表
            prov_match = re.search(r'provinces\s*=\s*\{([^}]+)\}', content)
            if prov_match:
                prov_text = prov_match.group(1)
                provs = [int(x) for x in prov_text.split() if x.isdigit()]
                for p in provs:
                    if p in self._state_provinces:
                        self.errors.append(f"{fn}: province {p} belongs to multiple states (must be unique)")
                    self._state_provinces.add(p)
                if id_match:
                    self._state_prov_lists[int(id_match.group(1))] = provs

            # A provincial naval base or coastal bunker on an inland province
            # is rejected by map loading.  definition.csv has already been
            # parsed, so the coastal set is available here.
            for building_match in re.finditer(
                r'^\s*(\d+)\s*=\s*\{([^{}]*)\}', content,
                re.MULTILINE | re.DOTALL,
            ):
                province_id = int(building_match.group(1))
                block = building_match.group(2)
                if ("naval_base" in block or "coastal_bunker" in block) and (
                    province_id not in getattr(self, "_coastal_province_ids", set())
                ):
                    self.errors.append(
                        f"{fn}: province {province_id} has a naval/coastal building but is not coastal"
                    )

            # 检查 owner
            if "owner" not in content:
                self.errors.append(f"{fn}: missing owner field")

        self._log(f"    → {len(files)} state files, {len(self._state_provinces)} provinces assigned")

    def _check_strategic_regions(self):
        """检查战略区域"""
        self._log("[9/16] Checking strategic regions...")
        sr_dir = self._path("map", "strategicregions")
        if not os.path.isdir(sr_dir):
            self.errors.append("Missing map/strategicregions/ directory")
            return

        files = [f for f in os.listdir(sr_dir) if f.endswith(".txt")]
        if not files:
            self.errors.append("map/strategicregions/ directory is empty")
            return

        self._region_provinces = set()
        pid_to_rid = {}  # {pid: region_id} — 供 state 跨区检查用
        for fn in files:
            with open(os.path.join(sr_dir, fn), "r", encoding="utf-8-sig", errors="replace") as f:
                content = f.read()
            id_match = re.search(r'id\s*=\s*(\d+)', content)
            rid = int(id_match.group(1)) if id_match else 0
            if rid == 0:
                self.errors.append(f"Strategic region {fn}: missing id field")
            prov_match = re.search(r'provinces\s*=\s*\{([^}]+)\}', content)
            if prov_match:
                provs = [int(x) for x in prov_match.group(1).split() if x.isdigit()]
                for p in provs:
                    if p in self._region_provinces:
                        self.errors.append(f"Strategic region {fn}: province {p} belongs to multiple strategic regions (must be unique)")
                    self._region_provinces.add(p)
                    if rid > 0:  # 缺 id 的文件不参与跨区判断, 避免误报
                        pid_to_rid[p] = rid

            if "weather" not in content:
                self.errors.append(f"Strategic region {fn}: missing weather block")

        # state ↔ 战略区交叉检查: 一个 state 的省份必须都在同一战略区
        # (nudge: "provinces are not belong to same strategic region")
        cross = []
        for sid, provs in sorted(getattr(self, "_state_prov_lists", {}).items()):
            rids = {pid_to_rid[p] for p in provs if p in pid_to_rid}
            if len(rids) > 1:
                cross.append(sid)
        if cross:
            preview = ", ".join(str(s) for s in cross[:10])
            more = f"; {len(cross)} total" if len(cross) > 10 else ""
            self.warnings.append(
                f"Provinces in {len(cross)} states span multiple strategic regions "
                f"(State {preview}{more}). The in-game nudge tool will warn but not crash; "
                f"this usually means a state contains exclaves or offshore islands"
            )

        self._log(f"    → {len(files)} regions covering {len(self._region_provinces)} provinces")

    def _check_supply_files(self):
        """检查补给文件"""
        self._log("[10/16] Checking supply system...")
        for fname in ["supply_nodes.txt", "railways.txt", "buildings.txt"]:
            path = self._path("map", fname)
            if os.path.exists(path):
                size = os.path.getsize(path)
                if size == 0:
                    self.errors.append(f"map/{fname} is empty (not allowed)")
            else:
                self.errors.append(f"Missing map/{fname}")

        self._check_coastal_port_spawns()

    def _check_coastal_port_spawns(self):
        """Ensure each definition.csv coastal province has a valid port spawn.

        HOI4 discovers coastlines while loading the province map.  A province
        marked coastal without a matching ``naval_base_spawn`` is a known
        startup-crash condition, so this is deliberately an error rather than
        a cosmetic warning.
        """
        coastal = getattr(self, "_coastal_province_ids", set())
        if not coastal:
            return

        path = self._path("map", "buildings.txt")
        bmp_path = self._path("map", "provinces.bmp")
        if not os.path.isfile(path) or not os.path.isfile(bmp_path):
            return

        try:
            with open(path, "r", encoding="utf-8-sig", errors="replace") as port_file:
                port_lines = port_file.readlines()
            with open(bmp_path, "rb") as bmp:
                if bmp.read(2) != b"BM":
                    return
                bmp.seek(10)
                offset = struct.unpack("<I", bmp.read(4))[0]
                bmp.seek(18)
                width = struct.unpack("<i", bmp.read(4))[0]
                height = abs(struct.unpack("<i", bmp.read(4))[0])
                row_bytes = width * 3
                row_stride = row_bytes + ((4 - row_bytes % 4) % 4)

                port_provinces: set[int] = set()
                for line_number, line in enumerate(port_lines, start=1):
                    parts = line.strip().split(";")
                    if len(parts) < 7 or parts[1] != "naval_base_spawn":
                        continue
                    try:
                        x = float(parts[2])
                        z = float(parts[4])
                        sea_id = int(parts[6])
                        pixel_x = int(x)
                        pixel_y = height - 1 - int(z)
                    except ValueError:
                        self.errors.append(
                            f"map/buildings.txt line {line_number}: malformed naval_base_spawn"
                        )
                        continue
                    if not (0 <= pixel_x < width and 0 <= pixel_y < height):
                        self.errors.append(
                            f"map/buildings.txt line {line_number}: naval_base_spawn is outside the map"
                        )
                        continue
                    bmp.seek(offset + (height - 1 - pixel_y) * row_stride + pixel_x * 3)
                    bgr = bmp.read(3)
                    if len(bgr) != 3:
                        self.errors.append(
                            f"map/buildings.txt line {line_number}: cannot read port province pixel"
                        )
                        continue
                    province_id = getattr(self, "_province_color_to_id", {}).get(
                        (bgr[2], bgr[1], bgr[0])
                    )
                    if province_id is None:
                        self.errors.append(
                            f"map/buildings.txt line {line_number}: port is not over a defined province"
                        )
                        continue
                    if province_id not in coastal:
                        self.errors.append(
                            f"map/buildings.txt line {line_number}: port province {province_id} is not coastal"
                        )
                    else:
                        port_provinces.add(province_id)
                    if sea_id not in getattr(self, "_sea_province_ids", set()):
                        self.errors.append(
                            f"map/buildings.txt line {line_number}: port sea province {sea_id} is not sea"
                        )
        except OSError as exc:
            self.errors.append(f"Could not validate naval_base_spawn entries: {exc}")
            return

        missing = coastal - port_provinces
        if missing:
            sample = sorted(missing)[:10]
            self.errors.append(
                f"{len(missing)} coastal provinces have no naval_base_spawn: {sample}"
            )

    def _check_countries(self):
        """检查国家文件"""
        self._log("[11/16] Checking countries...")
        # 兼容新旧两种 TAG 注册文件名：新版用 02_worldtest_countries.txt 避免覆盖 vanilla
        ct_dir = self._path("common", "country_tags")
        tag_file = None
        for candidate in ("02_worldtest_countries.txt", "00_countries.txt"):
            p = os.path.join(ct_dir, candidate)
            if os.path.exists(p):
                tag_file = p
                break
        if tag_file is None:
            self.errors.append(
                "Missing common/country_tags/02_worldtest_countries.txt (or legacy 00_countries.txt)"
            )
            return

        with open(tag_file, "r", encoding="utf-8-sig", errors="replace") as f:
            content = f.read()

        self._country_tags = re.findall(r'^([A-Z]{3})\s*=', content, re.MULTILINE)
        if not self._country_tags:
            self.errors.append(f"{os.path.basename(tag_file)}: no country TAGs found")
            return

        for tag in self._country_tags:
            # common/countries/TAG.txt
            if not self._exists("common", "countries", f"{tag}.txt"):
                self.errors.append(f"Missing common/countries/{tag}.txt")

            # history/countries/TAG.txt — 必须与 country_tags 注册路径严格一致
            if not self._exists("history", "countries", f"{tag}.txt"):
                self.errors.append(f"Missing history/countries/{tag}.txt")

            # history/units/TAG_1936.txt
            if not self._exists("history", "units", f"{tag}_1936.txt"):
                self.errors.append(f"Missing history/units/{tag}_1936.txt")

        self._log(f"    → {len(self._country_tags)} countries: {', '.join(self._country_tags)}")

    def _check_ideologies(self):
        """检查意识形态"""
        self._log("[12/16] Checking ideologies...")
        path = self._path("common", "ideologies", "00_ideologies.txt")
        if not os.path.exists(path):
            if self._replaces_path("common/ideologies"):
                self.warnings.append("Missing ideology file (the game will crash if common/ideologies is replaced)")
            return

        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            content = f.read()

        required = ["democratic", "fascism", "communism", "neutrality"]
        for ideo in required:
            if ideo not in content:
                self.errors.append(f"Ideologies: missing {ideo}")

        if "types" not in content:
            self.errors.append("Ideologies: missing required types sub-block (the game will crash without it)")

    def _check_state_categories(self):
        """检查 State 类别"""
        self._log("[13/16] Checking state categories...")
        sc_dir = self._path("common", "state_category")
        if not os.path.isdir(sc_dir):
            if self._replaces_path("common/state_category"):
                self.warnings.append("Missing common/state_category/ (the game will crash if this path is replaced)")
            return

        files = [f for f in os.listdir(sc_dir) if f.endswith(".txt")]
        # 检查 town（默认类别）是否存在
        has_town = any(
            "town" in open(os.path.join(sc_dir, f), "r",
                           encoding="utf-8-sig", errors="replace").read()
            for f in files
        )
        if not has_town:
            self.errors.append("state_category: missing the 'town' category used by default for states")

    def _check_bookmarks(self):
        """检查 Bookmark"""
        self._log("[14/16] Checking bookmarks...")
        bm_dir = self._path("common", "bookmarks")
        if not os.path.isdir(bm_dir):
            self.warnings.append("Missing common/bookmarks/ (the game will crash if this path is replaced)")
            return

        files = [f for f in os.listdir(bm_dir) if f.endswith(".txt")]
        if not files:
            self.errors.append("common/bookmarks/ directory is empty")
            return

        for fn in files:
            with open(os.path.join(bm_dir, fn), "r", encoding="utf-8-sig", errors="replace") as f:
                content = f.read()
            if "randomize_weather" not in content:
                self.errors.append(f"Bookmark {fn}: missing required randomize_weather")
            if "date" not in content:
                self.errors.append(f"Bookmark {fn}: missing date field")

    def _check_localisation(self):
        """检查本地化"""
        self._log("[15/16] Checking localization...")
        loc_dir = self._path("localisation")
        if not os.path.isdir(loc_dir):
            self.warnings.append("Missing localisation/ directory")
            return

        yml_files = [f for f in os.listdir(loc_dir) if f.endswith("_l_english.yml")]
        if not yml_files:
            self.warnings.append("No *_l_english.yml files found in localisation/")
            return

        for fn in yml_files:
            path = os.path.join(loc_dir, fn)
            with open(path, "rb") as f:
                bom = f.read(3)
                if bom != b"\xef\xbb\xbf":
                    self.errors.append(f"Localization {fn}: missing required UTF-8 BOM")
            with open(path, "r", encoding="utf-8-sig") as f:
                first_line = f.readline().strip()
                if first_line != "l_english:":
                    self.errors.append(f"Localization {fn}: first line must be 'l_english:'; actual value: '{first_line}'")

    def _check_descriptor(self):
        """检查 descriptor.mod"""
        self._log("[16/16] Checking descriptor.mod...")
        path = self._path("descriptor.mod")
        if not os.path.exists(path):
            return

        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            content = f.read()

        # path= 不能出现在内部 descriptor（只有外层 .mod 才有）
        # 注意不能误匹配 replace_path=
        import re
        if re.search(r'^path\s*=', content, re.MULTILINE):
            self.errors.append("The internal descriptor.mod must not contain a path= field")

        # 检查外层 .mod 文件
        mod_dir_name = os.path.basename(self.mod_dir)
        outer = os.path.join(os.path.dirname(self.mod_dir), f"{mod_dir_name}.mod")
        if os.path.exists(outer):
            with open(outer, "r", encoding="utf-8-sig", errors="replace") as f:
                outer_content = f.read()
            if "path=" not in outer_content:
                self.errors.append(f"Outer {mod_dir_name}.mod is missing a path= field")
        else:
            self.errors.append(f"Missing outer .mod file: {outer}")

        # 检查 replace_path 指向的目录是否存在
        for m in re.finditer(r'replace_path="([^"]+)"', content):
            rp = m.group(1)
            if not self._exists(rp):
                self.errors.append(f"Directory referenced by replace_path=\"{rp}\" does not exist")

    def _check_seasons(self):
        """检查 seasons.txt"""
        path = self._path("map", "seasons.txt")
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            content = f.read()
        for season in ["winter", "spring", "summer", "autumn"]:
            if season not in content:
                self.errors.append(f"seasons.txt: missing {season} definition")

    def _cross_validate(self):
        """交叉验证：省份分配完整性"""
        self._log("\n[Cross-validation] Checking province assignments...")

        if not hasattr(self, '_land_province_ids'):
            return

        # 每个陆地省份必须在某个 State 中
        if hasattr(self, '_state_provinces'):
            unassigned = self._land_province_ids - self._state_provinces
            if unassigned:
                sample = sorted(list(unassigned))[:10]
                self.errors.append(
                    f"{len(unassigned)} land provinces do not belong to any state: {sample}..."
                )

        # 每个省份必须在某个战略区域中
        if hasattr(self, '_region_provinces') and hasattr(self, '_province_ids'):
            unassigned_sr = self._province_ids - self._region_provinces
            if unassigned_sr:
                sample = sorted(list(unassigned_sr))[:10]
                self.errors.append(
                    f"{len(unassigned_sr)} provinces do not belong to any strategic region: {sample}..."
                )


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m export.verify_mod <MOD directory path>")
        print("Example: python -m export.verify_mod D:/Documents/Paradox Interactive/Hearts of Iron IV/mod/TestMOD")
        sys.exit(1)

    mod_dir = sys.argv[1]
    if not os.path.isdir(mod_dir):
        print(f"Error: directory does not exist: {mod_dir}")
        sys.exit(1)

    v = ModVerifier(mod_dir)
    ok = v.verify_all()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
