"""
province — en 翻译

本文件由 tools/migrate_i18n.py 生成。后续手动维护。
"""

STRINGS: dict[str, str] = {
    "btn_generate": "Generate",
    "label_land_ratio": "Land Density Ratio:",
    "label_province_count": "Province Count:",
    "prov_bld_bunker": "Bunker",
    "prov_bld_cancel": "Cancel",
    "prov_bld_coastal": "Coastal",
    "prov_bld_naval": "Naval Base",
    "prov_bld_province_id": "Province ID",
    "prov_bld_save": "Save",
    "prov_bld_tip": """Configure defensive buildings for each land province in this state.
0 = none. Bunker applies to all land; coastal_bunker and naval_base should only be set for coastal provinces.""",
    "prov_bld_title_fmt": "Province Buildings — {0} (ID {1})",
    "province_btn_find": "Locate",
    "province_btn_find_tip": "Enter a province ID, press Enter or click Locate — the map jumps to that province and highlights it.",
    "province_search_placeholder": "Enter province ID …",
    "province_btn_expand": "Expand Province",
    "province_btn_expand_tip": "🖌 Pixel-level brush: enable, click a province to pick it, then drag — pixels under the cursor are assigned to that province. Auto-disables on release.",
    "province_btn_merge": "Merge Provinces",
    "province_btn_merge_tip": "Enable, click the first province, then the second → whole-province merge. Auto-disables.",
    "province_btn_split": "Split Selected Province",
    "province_btn_split_tip": "Click a province first, then click this button → auto-split along the median line.",
    "province_coastal_no": "No",
    "province_coastal_yes": "Yes",
    "province_hint_click_info": "Click province to view info",
    "province_hint_default": "💡 Generate provinces automatically, then refine the same map by hand. Ctrl-click or Shift-click to select multiple provinces; right-click a selection to delete it.",
    "province_hint_expand": "🟠 Expand (pixel brush) — 1) Click a province 2) Drag the brush; pixels under the cursor join that province.",
    "province_hint_merge": "🟠 Merge — 1) Click first province 2) Click second → whole-province merge.",
    "province_hint_split": "🟠 Split — Draw a line across a province; release to split along it.",
    "province_hint_paint": "🟠 Province Brush — select an existing province first, or click New Province, then drag to paint. Painting stays on the same land/sea/lake type.",
    "province_hint_fill": "🟠 Fill Unassigned — select a target province, then click a connected blank (ID 0) area. Use Merge for existing provinces.",
    "province_info_coastal": "Coastal",
    "province_info_compact_default": "ID: — | — | — | 0px",
    "province_info_id": "Province ID",
    "province_info_pixels": "Pixels",
    "province_info_terrain": "Terrain",
    "province_info_type": "Type",
    "province_section_info": "Province Info",
    "province_section_generation": "Province Generation",
    "province_label_generation_count": "Target province count:",
    "province_label_sea_density": "Sea density:",
    "province_label_lake_density": "Lake density:",
    "province_scope_all": "all provinces",
    "province_scope_land": "land provinces",
    "province_scope_sea": "sea provinces",
    "province_scope_lake": "lake provinces",
    "province_generation_hint": (
        "Choose a scope below. Generate All replaces every province type; "
        "single-type generation preserves the other types."
    ),
    "province_btn_generate_all": "Generate All Provinces",
    "province_btn_generate_land": "Generate Land Provinces",
    "province_btn_generate_sea": "Generate Sea Provinces",
    "province_btn_generate_lake": "Generate Lake Provinces",
    "province_btn_generate_all_tip": (
        "Generate land, sea, and lake provinces using the target count and density settings."
    ),
    "province_btn_generate_land_tip": (
        "Generate only land provinces. Existing sea and lake provinces are preserved."
    ),
    "province_btn_generate_sea_tip": (
        "Generate only sea provinces. Existing land and lake provinces are preserved."
    ),
    "province_btn_generate_lake_tip": (
        "Generate only lake provinces. Existing land and sea provinces are preserved."
    ),
    "province_generation_scope_confirm_title": "Replace Province Type?",
    "province_generation_scope_confirm": (
        "Existing {scope} provinces will be regenerated while the other province types are preserved. Continue?"
    ),
    "province_generation_empty_title": "No Matching Tiles",
    "province_generation_empty": "There are no {scope} tiles to generate provinces for.",
    "province_btn_validate": "Validate Provinces",
    "province_section_tools": "Province Tools",
    "province_section_manual_draw": "Manual Province Drawing",
    "province_btn_import_ref": "Import reference…",
    "province_btn_import_ref_tip": "Load a background image that remains visible while you trace province borders on the map.",
    "province_ref_hint": "The same movable reference layer used by Land drawing is visible here.",
    "province_tool_select": "Select",
    "province_tool_select_tip": "Click to select one province. Ctrl-click or Shift-click to select multiple provinces; right-click a selected province to delete the selection.",
    "province_tool_brush": "Brush",
    "province_tool_brush_tip": "Paint the selected province with a circular brush. Start from the province and drag outward so it remains contiguous.",
    "province_tool_fill": "Fill",
    "province_tool_fill_tip": "Assign a connected unassigned area (ID 0) to the selected province. Existing provinces are protected; use Merge for those.",
    "province_btn_new": "New Province",
    "province_btn_new_tip": "Allocate the first missing province ID (or the next ID) and enter Brush mode. The first stroke determines whether it is land, sea, or lake.",
    "province_label_brush_size": "Brush size:",
    "province_target_none": "Target: none — select a province or create a new one.",
    "province_target_selected": "Target: Province {pid}",
    "province_target_new": "Target: new Province {pid} — draw its first pixels.",
    "province_status_select": "Province select mode",
    "province_status_brush": "Province brush: select a province first, or create a new one, then drag to paint",
    "province_status_fill": "Province fill: click an unassigned area to give it to the selected province",
    "province_status_new": "New Province {pid} selected — draw its first pixels",
    "province_btn_auto_ref": "Generate Provinces from Outlines...",
    "province_btn_auto_ref_tip": "Choose a full-map image with a uniform land fill and province outlines. A color-role editor opens to select land- and sea-province outline colors. Undoable with Ctrl+Z.",
    "province_auto_ref_dialog": "Generate Provinces from Reference Outlines",
    "province_auto_ref_confirm_title": "Replace Province Map?",
    "province_auto_ref_confirm": "This will replace all existing province IDs. Province-linked state and country data may no longer match. The map replacement itself is undoable. Continue?",
    "province_auto_ref_done": "Imported {count} provinces from reference outlines. Automatic validation and repair are complete. Ctrl+Z to undo.",
    "province_auto_ref_report_title": "Province Import Complete",
    "province_auto_ref_report": (
        "Imported provinces:\n"
        "Land: {land}\n"
        "Sea: {sea}\n"
        "Lake: {lake}\n\n"
        "Modified provinces: {modified}\n"
        "Border adjustments: {border_adjusted}\n"
        "Too-small provinces merged: {too_small_merged}\n"
        "Too-small isolated provinces removed: {too_small_removed}\n"
        "Disconnected provinces repaired: {not_contiguous}\n"
        "Oversized provinces split: {too_large_split}\n"
        "Province ID gaps compacted: {id_gaps}\n\n"
        "Remaining validation issues: {remaining}\n"
        "Coastal land provinces noted for export metadata: {coastal}"
    ),
    "province_random_target_label": "Total pieces:",
    "province_random_target_tip": "Total number of provinces the current selection should become, not the number added.",
    "province_btn_random_split": "Random Split Selection",
    "province_btn_random_split_tip": "Split all Ctrl/Shift-selected provinces into this many connected pieces in total. New pieces inherit state, region, continent, and province terrain. Ctrl+Z to undo.",
    "province_random_split_done": "Split {selected} selected province(s) into {count} connected provinces. Ctrl+Z to undo.",
}
