"""
river — zh 翻译

本文件由 tools/migrate_i18n.py 生成。后续手动维护。
"""

STRINGS: dict[str, str] = {
    "dlg_river_validate_title": "河流验证",
    "river_brush_btn": "画笔",
    "river_btn_validate": "验证河流",
    "river_btn_validate_new": "✓ 验证河流是否合法",
    "river_eraser_btn": "橡皮",
    "river_eraser_range": "橡皮范围:",
    "river_hint": "河流规则: 必须1像素宽，只走上下左右(不能斜走)每条河需要1个源头(绿)。红=支流汇入 黄=分叉画笔大小仅影响橡皮擦范围，河流本身必须1像素宽",
    "river_label_size": "大小:",
    "river_marker_confluence": "汇入点",
    "river_marker_mouth": "入海口",
    "river_marker_source": "源头",
    "river_pan_btn": "平移",
    "river_section_brush_size": "画笔大小",
    "river_section_manual": "✏️ 手动画河流（3 步）",
    "river_section_markers": "标记 (单像素)",
    "river_section_tools": "工具",
    "river_section_width": "宽度画笔",
    "river_step1_title": "<b>步骤 1：</b>选河流宽度",
    "river_step2_hint": """从山上某点按住鼠标 → 拖到海边 → 松手
⚠️ HOI4 河流崩溃高发！必须遵守：
  • 必须 1 像素宽（画笔已锁定）
  • 必须正交（上下左右），不能斜线
  • 每条河必须有【源头】（步骤 3）""",
    "river_step2_title": "<b>步骤 2：</b>在地图上画河",
    "river_step3_hint": """每条河至少 1 个源头（绿）
入海口（黄）放河流末端
汇入点（红）= 两条河合并处""",
    "river_step3_title": "<b>步骤 3：</b>加起点/终点标记",
    "river_tool_brush": "画笔",
    "river_tool_eraser": "橡皮",
    "river_tool_pan": "平移",
    "river_validate_tooltip": "检查是否有对角线像素、缺失源头等问题",
    "river_width_tip_fmt": "{0} — HOI4 调色板索引 {1}（数字越大，游戏内河流越宽）",
    "river_marker_source_tip": "🟢 源头：每条河必须有 1 个，放在河流起点（山地一侧）。无源头的河 HOI4 不渲染。",
    "river_marker_confluence_tip": "🔴 汇入点：两条河合流处必须放（小河汇入大河的位置）。",
    "river_marker_mouth_tip": "🟡 入海口：河流末端放此标记（如果不直接接海，HOI4 会判定为断河）。",
    "river_nav_tip": "💡 中键拖动 = 平移 ｜ Ctrl+Z = 撤销 ｜ 画错记得点上方【验证】检查合法性",
    "river_eraser_label_fmt": "橡皮: {0}px",
    "river_width_1": "细流",
    "river_width_2": "小河",
    "river_width_4": "中河",
    "river_width_5": "大河",
    "river_width_7": "宽河",
    "river_width_8": "巨河",
    "river_width_9": "最宽",
    "river_width_note": "💡 河流必须 1px 宽（HOI4 规则），滑块只影响橡皮擦范围",
    "river_section_auto_reference": "从内陆水域参考图生成",
    "river_auto_reference_hint": "宽水域形状会转换为湖泊，细线会骨架化为 1px 河流并自动添加源头。为了获得干净的省份类型，建议在导入省界前运行。",
    "river_btn_auto_reference": "从图像生成湖泊和河流…",
    "river_btn_auto_reference_tip": "选择一张黄/绿色陆地、白色海洋和灰/棕/蓝色内陆水域的整图图像。地块层和河流层将一起更改并可一起撤销。",
    "river_auto_ref_dialog": "从参考图生成湖泊和河流",
    "river_auto_ref_done": "已生成 {lakes} 个湖泊像素和 {rivers} 个河流像素，共 {networks} 个河网。Ctrl+Z 可同时撤销两个图层。",
}
