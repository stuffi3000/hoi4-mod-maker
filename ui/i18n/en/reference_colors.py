"""Reference image color-role editor translations (English)."""

STRINGS: dict[str, str] = {
    "reference_color_editor_title": "Reference image color mapping",
    "reference_color_editor_hint": (
        "Assign the detected colors to the roles used by this generator. "
        "You can assign one color to more than one role. Land/sea province "
        "roles refer to outline colors."
    ),
    "reference_color_editor_color": "Color",
    "reference_color_editor_pixels": "Pixels",
    "reference_color_editor_tolerance": "Color tolerance:",
    "reference_color_editor_tolerance_tip": (
        "RGB distance used to include anti-aliased shades around each selected color."
    ),
    "reference_color_editor_palette_note": (
        "The palette shows the most common representative colors found in the image."
    ),
    "reference_color_editor_apply": "Generate",
    "reference_color_editor_cancel": "Cancel",
    "reference_color_editor_no_selection": "Select at least one color before generating.",
    "reference_color_editor_no_land_province": (
        "Select at least one land-province outline color."
    ),
    "reference_color_editor_preview_unavailable": "Preview unavailable",
    "reference_role_land": "Land",
    "reference_role_water": "Water",
    "reference_role_land_province": "Land province outline",
    "reference_role_sea_province": "Sea province outline",
    "reference_role_lake": "Lake",
    "reference_role_river": "River",
}

