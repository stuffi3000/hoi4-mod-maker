"""
river — en 翻译

本文件由 tools/migrate_i18n.py 生成。后续手动维护。
"""

STRINGS: dict[str, str] = {
    "dlg_river_validate_title": "River Validation",
    "river_brush_btn": "Brush",
    "river_btn_validate": "Validate Rivers",
    "river_btn_validate_new": "✓ Validate Rivers",
    "river_eraser_btn": "Eraser",
    "river_eraser_range": "Eraser size:",
    "river_hint": "River rules: must be 1px wide, only up/down/left/right (no diagonal)Each river needs 1 source (green). Red=tributary merge, Yellow=forkBrush size only affects eraser range; rivers must be 1px wide",
    "river_label_size": "Size:",
    "river_marker_confluence": "Confluence",
    "river_marker_mouth": "Mouth",
    "river_marker_source": "Source",
    "river_pan_btn": "Pan",
    "river_section_brush_size": "Brush Size",
    "river_section_manual": "✏️ Manual Drawing (3 Steps)",
    "river_section_markers": "Markers (Single Pixel)",
    "river_section_tools": "Tools",
    "river_section_width": "Width Brush",
    "river_step1_title": "<b>Step 1:</b> Select river width",
    "river_step2_hint": """Click-drag from mountains to sea → release
⚠️ HOI4 rivers crash easily! Must follow:
  • Must be 1px wide (brush locked)
  • Must be orthogonal (H/V only, no diagonal)
  • Each river needs a [Source] marker (Step 3)""",
    "river_step2_title": "<b>Step 2:</b> Draw river on map",
    "river_step3_hint": """Each river needs ≥1 source (green)
Mouth marker (yellow) at sea entry
Flow-in (red) where rivers merge""",
    "river_step3_title": "<b>Step 3:</b> Add source/mouth markers",
    "river_tool_brush": "Brush",
    "river_tool_eraser": "Eraser",
    "river_tool_pan": "Pan",
    "river_validate_tooltip": "Check for diagonal pixels, missing sources, etc.",
    "river_width_tip_fmt": "{0} — HOI4 palette index {1} (higher = wider in-game)",
    "river_marker_source_tip": "🟢 Source: each river needs exactly 1, placed at the river's start (mountain side). Rivers without a source are NOT rendered by HOI4.",
    "river_marker_confluence_tip": "🔴 Confluence: place at the point where two rivers merge (small river joining a larger one).",
    "river_marker_mouth_tip": "🟡 Mouth: place at the river's end if it does not directly touch the sea — otherwise HOI4 treats it as a broken river.",
    "river_nav_tip": "💡 Middle-click = pan ｜ Ctrl+Z = undo ｜ Draw mistake? Click [Validate] above to check legality",
    "river_eraser_label_fmt": "Eraser: {0}px",
    "river_width_1": "Trickle",
    "river_width_2": "Small",
    "river_width_4": "Medium",
    "river_width_5": "Large",
    "river_width_7": "Wide",
    "river_width_8": "Huge",
    "river_width_9": "Widest",
    "river_width_note": "💡 Rivers must be 1px wide (HOI4 rule), slider only affects eraser",
    "river_section_auto_reference": "Generate from Inland-Water Reference",
    "river_auto_reference_hint": "Broad water shapes become lakes; thin shapes are skeletonized into 1px rivers with automatic source markers. Run this before province outline import for the cleanest province types.",
    "river_btn_auto_reference": "Generate Lakes + Rivers from Image...",
    "river_btn_auto_reference_tip": "Choose a full-map image with inland water. A color-role editor opens to select lake and river colors; tile and river layers are changed and undone together.",
    "river_auto_ref_dialog": "Generate Lakes and Rivers from Reference",
    "river_auto_ref_done": "Generated {lakes} lake pixels and {rivers} river pixels in {networks} networks. Ctrl+Z undoes both layers.",
}
