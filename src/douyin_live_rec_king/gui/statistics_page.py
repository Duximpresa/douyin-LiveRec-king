"""Recording statistics page and CSV export controls."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..services.statistics import RecordingStatisticsService


class StatisticsPage(QWidget):
    def __init__(
        self, statistics_service: RecordingStatisticsService, parent=None
    ) -> None:
        super().__init__(parent)
        self.statistics_service = statistics_service
        self.summary_labels: dict[str, QLabel] = {}
        layout = QVBoxLayout(self)
        title = QLabel("录制统计")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        summary = QGridLayout()
        for index, key in enumerate(("all", "last_7_days", "last_30_days")):
            label = QLabel()
            label.setStyleSheet(
                "padding:12px;background:#f1f5f9;border-radius:8px;"
            )
            self.summary_labels[key] = label
            summary.addWidget(label, 0, index)
        layout.addLayout(summary)
        buttons = QHBoxLayout()
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh)
        buttons.addWidget(refresh)
        for text, kind in [
            ("导出完整历史 CSV", "history"),
            ("导出主播/平台汇总 CSV", "summary"),
            ("导出每日趋势 CSV", "daily"),
        ]:
            button = QPushButton(text)
            button.clicked.connect(
                lambda _=False, value=kind: self.export_csv(value)
            )
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.tabs = QTabWidget()
        self.anchor_table = QTableWidget()
        self.platform_table = QTableWidget()
        self.daily_table = QTableWidget()
        self.tabs.addTab(self.anchor_table, "按主播")
        self.tabs.addTab(self.platform_table, "按平台")
        self.tabs.addTab(self.daily_table, "每日趋势")
        layout.addWidget(self.tabs)
        self.refresh()

    @staticmethod
    def _duration(seconds: float) -> str:
        total = int(seconds)
        return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"

    def refresh(self) -> None:
        summary = self.statistics_service.summary()
        labels = {
            "all": "全部",
            "last_7_days": "最近 7 天",
            "last_30_days": "最近 30 天",
        }
        for key, title in labels.items():
            data = summary[key]
            self.summary_labels[key].setText(
                f"{title}\n"
                f"次数 {data['count']} · 成功率 {data['success_rate']:.1%}\n"
                f"时长 {self._duration(data['duration_seconds'])} · "
                f"容量 {data['size_bytes'] / 1024 / 1024 / 1024:.2f} GB"
            )
        self._fill(self.anchor_table, self.statistics_service.by_anchor(), "主播")
        self._fill(
            self.platform_table, self.statistics_service.by_platform(), "平台"
        )
        self._fill(self.daily_table, self.statistics_service.by_date(), "日期")

    def _fill(
        self, table: QTableWidget, rows: list[dict[str, object]], first: str
    ) -> None:
        headers = [first, "次数", "成功", "成功率", "时长", "容量"]
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row["key"],
                row["count"],
                row["success_count"],
                f"{row['success_rate']:.1%}",
                self._duration(float(row["duration_seconds"])),
                f"{float(row['size_bytes']) / 1024 / 1024:.1f} MB",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(row_index, column, item)
        table.resizeColumnsToContents()

    def export_csv(self, kind: str) -> None:
        default = f"recording_{kind}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 CSV", default, "CSV (*.csv)"
        )
        if not path:
            return
        target = self.statistics_service.export_csv(kind, Path(path))
        QMessageBox.information(self, "导出完成", str(target))
