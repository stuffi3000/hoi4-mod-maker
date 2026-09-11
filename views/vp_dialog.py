"""Victory point dialog box — numerical value + city name are filled in at once.

Effect: Sets the province's victory point value (0 = removed) and city name;
     The name is displayed next to the red dot on the map, and after exporting it is the city name on the game map.
Call: ask_vp(parent, pid, cur_vp, cur_name) → (value, name, ok)"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QSpinBox,
)

from ui.i18n import tr


def ask_vp(
    parent,
    pid: int,
    cur_vp: int = 0,
    cur_name: str = "",
) -> tuple[int, str, bool]:
    """The VP setting dialog box pops up and returns (value, city name, confirmation or not)."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("dlg_vp_title_fmt", pid))
    form = QFormLayout(dlg)

    spin = QSpinBox(dlg)
    spin.setRange(0, 50)
    spin.setValue(cur_vp if cur_vp > 0 else 1)
    form.addRow(tr("dlg_vp_value_label"), spin)

    name_edit = QLineEdit(cur_name, dlg)
    name_edit.setPlaceholderText(tr("dlg_vp_name_placeholder"))
    form.addRow(tr("dlg_vp_name_label"), name_edit)

    buttons = QDialogButtonBox(
        QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg)
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    form.addRow(buttons)

    ok = dlg.exec_() == QDialog.Accepted
    return spin.value(), name_edit.text().strip(), ok
