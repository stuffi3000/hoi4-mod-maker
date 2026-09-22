"""Find dialog for locating map entities and showing fuzzy suggestions."""

from __future__ import annotations

from collections.abc import Callable

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from services.find_service import FindResult, FindService
from ui.i18n import tr
from ui.styles import _LINEEDIT_STYLE, _LIST_STYLE, _SECONDARY_BTN_STYLE


class FindDialog(QDialog):
    """Search provinces, states, and strategic regions from one small dialog."""

    _SCOPES = (
        ("all", "find_scope_all"),
        ("province", "find_scope_province"),
        ("state", "find_scope_state"),
        ("strategic_region", "find_scope_strategic_region"),
    )

    def __init__(
        self,
        search_service: FindService,
        result_callback: Callable[[FindResult], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._search_service = search_service
        self._result_callback = result_callback
        self._exact_results: list[FindResult] = []
        self._suggested_results: list[FindResult] = []
        self._init_ui()

    def _init_ui(self) -> None:
        self.setWindowTitle(tr("find_dialog_title"))
        self.setMinimumWidth(620)
        self.resize(700, 520)

        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText(tr("find_search_placeholder"))
        self._search_edit.setStyleSheet(_LINEEDIT_STYLE)
        self._search_edit.returnPressed.connect(self._perform_search)
        top_row.addWidget(self._search_edit, stretch=1)

        self._scope_combo = QComboBox()
        for scope, label_key in self._SCOPES:
            self._scope_combo.addItem(tr(label_key), scope)
        self._scope_combo.setMinimumWidth(150)
        top_row.addWidget(self._scope_combo)

        find_button = QPushButton(tr("find_button"))
        find_button.setStyleSheet(_SECONDARY_BTN_STYLE)
        find_button.clicked.connect(self._perform_search)
        top_row.addWidget(find_button)
        layout.addLayout(top_row)

        self._status_label = QLabel(tr("find_enter_hint"))
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        layout.addWidget(QLabel(tr("find_results_label")))
        self._results_list = QListWidget()
        self._results_list.setStyleSheet(_LIST_STYLE)
        self._results_list.setMinimumHeight(150)
        self._results_list.itemClicked.connect(self._on_exact_item_clicked)
        self._results_list.itemActivated.connect(self._on_exact_item_clicked)
        layout.addWidget(self._results_list)

        self._suggestions_label = QLabel(tr("find_suggestions_label"))
        self._suggestions_label.setVisible(False)
        layout.addWidget(self._suggestions_label)

        self._suggestions_list = QListWidget()
        self._suggestions_list.setStyleSheet(_LIST_STYLE)
        self._suggestions_list.setMaximumHeight(150)
        self._suggestions_list.setVisible(False)
        self._suggestions_list.itemClicked.connect(self._on_suggestion_clicked)
        self._suggestions_list.itemActivated.connect(self._on_suggestion_clicked)
        layout.addWidget(self._suggestions_list)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._search_edit.setFocus()

    def _perform_search(self) -> None:
        query = self._search_edit.text().strip()
        scope = str(self._scope_combo.currentData() or "all")
        self._exact_results = self._search_service.search(query, scope)
        self._suggested_results = []
        self._results_list.clear()
        self._suggestions_list.clear()
        self._suggestions_label.setVisible(False)
        self._suggestions_list.setVisible(False)

        for result in self._exact_results:
            self._add_result_item(self._results_list, result)

        if self._exact_results:
            if len(self._exact_results) == 1:
                self._status_label.setText(tr("find_one_result"))
                self._locate(self._exact_results[0])
            else:
                self._status_label.setText(
                    tr("find_multiple_results").format(count=len(self._exact_results))
                )
            return

        self._suggested_results = self._search_service.suggestions(query, scope)
        if self._suggested_results:
            self._status_label.setText(tr("find_no_exact_with_suggestions"))
            self._suggestions_label.setVisible(True)
            self._suggestions_list.setVisible(True)
            for result in self._suggested_results:
                self._add_result_item(self._suggestions_list, result)
        elif query:
            self._status_label.setText(tr("find_no_results"))
        else:
            self._status_label.setText(tr("find_enter_hint"))

    @staticmethod
    def _add_result_item(list_widget: QListWidget, result: FindResult) -> None:
        item = QListWidgetItem(result.display_name())
        item.setData(Qt.ItemDataRole.UserRole, result)
        list_widget.addItem(item)

    def _on_exact_item_clicked(self, item: QListWidgetItem) -> None:
        result = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(result, FindResult):
            self._locate(result)

    def _on_suggestion_clicked(self, item: QListWidgetItem) -> None:
        result = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(result, FindResult):
            return
        self._search_edit.setText(result.search_text)
        self._perform_search()

    def _locate(self, result: FindResult) -> None:
        self._result_callback(result)
