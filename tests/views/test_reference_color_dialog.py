"""Tests for the visual reference-image color-role editor."""
from __future__ import annotations

from PIL import Image

from ui.i18n import set_language
from views.reference_color_dialog import ReferenceColorMappingDialog


def test_editor_lists_colors_and_returns_land_roles(qtbot, tmp_path):
    set_language("en")
    image = Image.new("RGB", (32, 20), (255, 255, 255))
    pixels = image.load()
    for y in range(2, 18):
        for x in range(3, 29):
            pixels[x, y] = (220, 140, 55)
        pixels[16, y] = (20, 20, 20)
    path = tmp_path / "reference.png"
    image.save(path)

    dialog = ReferenceColorMappingDialog(None, path, "land")
    qtbot.addWidget(dialog)

    assert dialog._table.rowCount() == 3
    assert set(dialog._role_columns) == {"land", "water"}
    dialog._accept()
    assert dialog.selection is not None
    assert dialog.selection.tolerance == 18
    assert dialog.selection.colors["land"] == [(220, 140, 55)]
    assert dialog.selection.colors["water"] == [(255, 255, 255)]


def test_editor_uses_operation_specific_role_columns(qtbot, tmp_path):
    image = Image.new("RGB", (20, 20), (207, 213, 16))
    image.save(tmp_path / "hydro.png")
    dialog = ReferenceColorMappingDialog(None, tmp_path / "hydro.png", "hydrology")
    qtbot.addWidget(dialog)
    assert set(dialog._role_columns) == {"lake", "river"}
    assert dialog._table.columnCount() == 4
