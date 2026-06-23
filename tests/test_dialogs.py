import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from douyin_live_rec_king.gui.dialogs import TaskDialog
from douyin_live_rec_king.models import PlatformType


def test_task_dialog_returns_typed_platform() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = TaskDialog()
    dialog.url_edit.setText("https://www.douyin.com/follow/live/713112138925")

    values = dialog.values()

    assert values["platform"] is PlatformType.DOUYIN
    assert values["url"] == "https://www.douyin.com/follow/live/713112138925"
    dialog.close()
    app.processEvents()
