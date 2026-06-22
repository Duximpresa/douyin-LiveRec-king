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


class TaskDialog(QDialog):
    def __init__(self, parent=None, task: LiveTask | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑监控任务" if task else "添加监控任务")
        self.setMinimumWidth(580)
        self.anchor_edit = QLineEdit(task.anchor_name if task else "")
        self.anchor_edit.setPlaceholderText("选填；留空后将从抖音自动获取")
        self.url_edit = QLineEdit(task.url if task else "")
        self.url_edit.setPlaceholderText(
            "直播间、作者主页、v.douyin.com 分享短链或 mock://offline"
        )
        self.platform_combo = QComboBox()
        self.platform_combo.addItem("抖音", PlatformType.DOUYIN)
        self.enabled_check = QCheckBox("启用此任务")
        self.enabled_check.setChecked(task.enabled if task else True)

        form = QFormLayout()
        form.addRow("主播昵称：", self.anchor_edit)
        form.addRow("抖音地址：", self.url_edit)
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

    def _validate(self) -> None:
        if not self.url_edit.text().strip():
            self.url_edit.setFocus()
            return
        self.accept()

    def values(self) -> dict[str, object]:
        return {
            "anchor_name": self.anchor_edit.text().strip(),
            "url": self.url_edit.text().strip(),
            "platform": self.platform_combo.currentData(),
            "enabled": self.enabled_check.isChecked(),
        }
