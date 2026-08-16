"""Translation history window with CSV export."""

import csv
from datetime import datetime

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

MAX_HISTORY = 1000


class TranslationHistory:
    """In-memory history of (timestamp, original, translation) records."""

    def __init__(self):
        self.records: list[tuple[str, str, str]] = []

    def add(self, original: str, translation: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.records.append((ts, original, translation))
        if len(self.records) > MAX_HISTORY:
            del self.records[: len(self.records) - MAX_HISTORY]

    def clear(self):
        self.records.clear()

    def export_csv(self, path: str):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["Time", "Original", "Translation"])
            writer.writerows(self.records)


class HistoryDialog(QDialog):
    """Table view over the translation history."""

    def __init__(self, history: TranslationHistory, parent=None):
        super().__init__(parent)
        self._history = history
        self.setWindowTitle("Translation History")
        self.resize(640, 420)

        layout = QVBoxLayout(self)
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Time", "Original", "Translation"])
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        export_btn = QPushButton("Export CSV...")
        export_btn.clicked.connect(self._export)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(export_btn)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self.refresh()

    def refresh(self):
        records = self._history.records
        self._table.setRowCount(len(records))
        for row, (ts, original, translation) in enumerate(reversed(records)):
            self._table.setItem(row, 0, QTableWidgetItem(ts))
            self._table.setItem(row, 1, QTableWidgetItem(original))
            self._table.setItem(row, 2, QTableWidgetItem(translation))

    def _export(self):
        default = f"translations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export history", default, "CSV files (*.csv)")
        if path:
            try:
                self._history.export_csv(path)
                QMessageBox.information(self, "Export", f"Saved {len(self._history.records)} records to:\n{path}")
            except OSError as e:
                QMessageBox.warning(self, "Export failed", str(e))

    def _clear(self):
        self._history.clear()
        self.refresh()
