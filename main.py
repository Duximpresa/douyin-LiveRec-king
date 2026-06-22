"""Development and frozen entry point with startup crash reporting."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path


def _crash_log() -> Path:
    root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    return root / "startup-error.log"


if __name__ == "__main__":
    try:
        from douyin_live_rec_king.app import main

        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException:
        details = traceback.format_exc()
        try:
            _crash_log().write_text(details, encoding="utf-8")
        except OSError:
            pass
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            app = QApplication.instance() or QApplication([])
            QMessageBox.critical(
                None,
                "douyin-LiveRec-king 启动失败",
                f"程序无法启动，错误已写入：\n{_crash_log()}\n\n{details[-1200:]}",
            )
        except BaseException:
            pass
        raise
