"""Dialogs used by the task-management page."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from ..models import LiveTask, PlatformType
from ..platforms.registry import platform_metadata, registered_platforms


class TaskDialog(QDialog):
    def __init__(self, parent=None, task: LiveTask | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑监控任务" if task else "添加监控任务")
        self.setMinimumWidth(580)
        self.anchor_edit = QLineEdit(task.anchor_name if task else "")
        self.anchor_edit.setPlaceholderText("选填；留空后将从抖音自动获取")
        self.url_edit = QLineEdit(task.url if task else "")
        self.platform_combo = QComboBox()
        for metadata in registered_platforms():
            self.platform_combo.addItem(metadata.display_name, metadata.type)
        selected_platform = task.platform if task else PlatformType.DOUYIN
        selected_index = self.platform_combo.findData(selected_platform)
        self.platform_combo.setCurrentIndex(max(0, selected_index))
        self.platform_combo.currentIndexChanged.connect(self._platform_changed)
        self.enabled_check = QCheckBox("启用此任务")
        self.enabled_check.setChecked(task.enabled if task else True)

        form = QFormLayout()
        form.addRow("主播昵称：", self.anchor_edit)
        self.url_label = QLabel()
        form.addRow(self.url_label, self.url_edit)
        form.addRow("平台：", self.platform_combo)
        form.addRow("", self.enabled_check)
        hint = QLabel(
            "手动填写或编辑过的昵称会永久优先；留空时程序会自动获取平台昵称。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)
        self._platform_changed()

    def _platform_changed(self, *_args) -> None:
        platform = PlatformType(self.platform_combo.currentData())
        metadata = platform_metadata(platform)
        self.url_label.setText(f"{metadata.display_name} 地址：")
        self.url_edit.setPlaceholderText(metadata.url_placeholder)

    def _validate(self) -> None:
        if not self.url_edit.text().strip():
            self.url_edit.setFocus()
            return
        self.accept()

    def values(self) -> dict[str, object]:
        return {
            "anchor_name": self.anchor_edit.text().strip(),
            "url": self.url_edit.text().strip(),
            "platform": PlatformType(self.platform_combo.currentData()),
            "enabled": self.enabled_check.isChecked(),
        }
