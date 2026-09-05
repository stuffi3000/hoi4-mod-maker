"""
i18n 迁移脚本：把 ui/i18n.py 的 _translations 大字典
拆成 ui/i18n/{zh,en}/{feature}.py 小文件。

一次性工具，跑完就归档。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

SRC_FILE = Path(__file__).resolve().parent.parent / "ui" / "i18n.py"
OUT_ROOT = Path(__file__).resolve().parent.parent / "ui" / "i18n"
LANGS = ("en",)

# ---- Key -> bucket (目标文件名) 分类规则 ----
# 顺序敏感：更具体的前缀要先匹配
PREFIX_RULES: list[tuple[str, str]] = [
    # 具体优先 - 在 land_/density_ 之前
    ("new_land_", "new_land"),
    ("mode_density", "navigation"),
    ("mode_river_nav", "navigation"),
    ("density_", "density"),
    # 对话框前缀
    ("dlg_language_", "dialogs"),
    ("dlg_set_vp_", "dialogs"),
    ("dlg_merge_", "dialogs"),
    ("dlg_expand_", "dialogs"),
    ("dlg_regen_", "dialogs"),
    ("dlg_batch_state_", "dialogs"),
    ("dlg_sr_from_states_", "dialogs"),
    ("dlg_update_", "dialogs"),
    ("dlg_file_", "dialogs"),
    ("dlg_select_", "dialogs"),
    ("dlg_import_", "import_"),
    ("dlg_gen_mode_", "dialogs"),
    ("dlg_quick_init_", "dialogs"),
    ("dlg_init_", "dialogs"),
    ("dlg_country_", "country"),
    ("dlg_river_", "river"),
    ("dlg_continent_", "continent"),
    ("dlg_defmap_", "default_map"),
    ("dlg_about_", "dialogs"),
    ("dlg_auto_generate", "common"),
    ("dlg_confirm", "common"),
    ("dlg_warning", "common"),
    ("dlg_error", "common"),
    ("dlg_", "dialogs"),  # 兜底 dialogs
    # feature 前缀
    ("land_", "land"),
    ("tile_", "land"),
    ("river_", "river"),
    ("height_", "height"),
    ("terrain_", "terrain"),
    ("province_", "province"),
    ("state_", "state"),
    ("country_", "country"),
    ("continent_", "continent"),
    ("sr_", "strategic_region"),
    ("logistics_", "logistics"),
    ("rail_dlg_", "logistics"),
    ("rail_dlg_list_item_fmt", "logistics"),
    ("cm_dlg_", "colormap"),
    ("colormap_", "colormap"),
    ("dm_dlg_", "default_map"),
    ("defmap_", "default_map"),
    # 导航 / 菜单 / UI 结构
    ("mode_", "navigation"),
    ("nav_", "navigation"),
    ("tab_", "navigation"),
    ("group_", "navigation"),
    ("menu_", "menu"),
    ("action_", "menu"),
    ("app_title", "menu"),
    # 工具面板
    ("panel_", "toolbar"),
    ("tool_", "toolbar"),
    ("label_brush_", "toolbar"),
    # 状态栏
    ("status_", "status"),
    # 引导
    ("guide_", "dialogs"),
    # 右键菜单
    ("context_", "context_menu"),
    # 通用
    ("btn_", "common"),
    ("unit_", "common"),
    # 验证/导出/导入/崩溃
    ("validate_", "validate"),
    ("export_", "export"),
    ("import_", "import_"),
    # 欢迎页
    ("welcome_", "welcome"),
    # 补充：对话框子类
    ("adj_dlg_", "logistics"),        # 邻接对话框
    ("cont_dlg_", "continent"),        # 大陆对话框
    ("rule_dlg_", "logistics"),        # 邻接规则对话框
    ("prov_bld_", "province"),         # 省份建筑对话框
    # 地形变体（graphical terrain）
    ("gt_", "terrain"),
    # 属性地形 page
    ("pterrain_", "terrain"),
    # 文件操作（main_window_file_ops.py 相关对话框）
    ("file_ops_", "file_ops"),
    # 崩溃
    ("crash_", "crash"),
    # 模式提示条
    ("hint_mode_", "tips"),
    # 快捷键设置对话框
    ("shortcut_", "dialogs"),
]

# 兜底映射（前缀规则都没命中时按精确 key 匹配）
EXACT_RULES: dict[str, str] = {
    "app_title": "menu",
    "label_province_count": "province",
    "label_land_ratio": "province",
    "btn_generate": "province",
    "btn_cancel": "common",
    "section_tools": "toolbar",
}


def classify(key: str) -> str:
    if key in EXACT_RULES:
        return EXACT_RULES[key]
    for prefix, bucket in PREFIX_RULES:
        if key.startswith(prefix):
            return bucket
    return "unclassified"


# ---- 用 AST 提取 _translations 字典 ----
def extract_translations(src_path: Path) -> dict[str, dict[str, str]]:
    """解析 i18n.py，返回 {key: {"zh": "...", "en": "..."}}"""
    src = src_path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        target_name = None
        value_node = None
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "_translations":
                    target_name = tgt.id
                    value_node = node.value
                    break
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "_translations":
                target_name = node.target.id
                value_node = node.value
        if target_name and value_node is not None:
            source = ast.unparse(value_node)
            return eval(compile(ast.parse(source, mode="eval"), "<ast>", "eval"))
    raise RuntimeError("未找到 _translations 字典")


# ---- 生成输出 ----
HEADER = '''"""
{bucket} — {lang} 翻译

本文件由 tools/migrate_i18n.py 生成。后续手动维护。
"""

STRINGS: dict[str, str] = {{
'''

FOOTER = "}\n"


def py_repr(value: str) -> str:
    """生成可读的 Python 字符串字面量。优先用双引号，字符串里有 " 就用三重引号"""
    if "\n" in value:
        # 多行字符串
        safe = value.replace('"""', '\\"\\"\\"')
        return f'"""{safe}"""'
    # 单行 - 用双引号，转义内部双引号
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_bucket(bucket: str, lang: str, entries: dict[str, str]) -> Path:
    out_dir = OUT_ROOT / lang
    out_dir.mkdir(parents=True, exist_ok=True)
    # 确保 __init__.py 存在
    init_file = out_dir / "__init__.py"
    if not init_file.exists():
        init_file.write_text("", encoding="utf-8")

    out_file = out_dir / f"{bucket}.py"
    lines = [HEADER.format(bucket=bucket, lang=lang)]
    for k in sorted(entries.keys()):
        lines.append(f"    {py_repr(k)}: {py_repr(entries[k])},\n")
    lines.append(FOOTER)
    out_file.write_text("".join(lines), encoding="utf-8")
    return out_file


def main() -> None:
    print(f"读取 {SRC_FILE} ...")
    translations = extract_translations(SRC_FILE)
    total = len(translations)
    print(f"共 {total} 条翻译条目\n")

    # 按 bucket 分桶
    buckets: dict[str, dict[str, dict[str, str]]] = {}
    for key, values in translations.items():
        bucket = classify(key)
        for lang in LANGS:
            buckets.setdefault(bucket, {}).setdefault(lang, {})[key] = values.get(
                lang, key
            )

    # 报告
    print("bucket summary:")
    for bucket in sorted(buckets.keys()):
        n = len(buckets[bucket][LANGS[0]])
        marker = "  [UNCLASSIFIED]" if bucket == "unclassified" else ""
        print(f"  {bucket:<20} {n:>4}{marker}")

    if "unclassified" in buckets:
        print("\nunclassified keys:")
        for k in sorted(buckets["unclassified"][LANGS[0]].keys()):
            print(f"  - {k}")
        print("\nupdate PREFIX_RULES/EXACT_RULES and retry")
        return

    # 写文件
    print(f"\n写入 {OUT_ROOT}/ ...")
    written = 0
    for bucket, lang_map in buckets.items():
        for lang, entries in lang_map.items():
            path = write_bucket(bucket, lang, entries)
            written += 1
    print(f"共写入 {written} 个文件 ({len(buckets)} 个 bucket × {len(LANGS)} 语言)")

    # 校验 key 集合完整
    expected_keys = set(translations.keys())
    actual_keys: set[str] = set()
    for lang_map in buckets.values():
        actual_keys.update(lang_map[LANGS[0]].keys())
    missing = expected_keys - actual_keys
    extra = actual_keys - expected_keys
    if missing:
        print(f"[FAIL] missing keys: {sorted(missing)}")
    if extra:
        print(f"[FAIL] extra keys: {sorted(extra)}")
    if not missing and not extra:
        print(f"[OK] all {total} keys migrated")


if __name__ == "__main__":
    main()
