from pathlib import Path

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import QLabel, QTableView, QVBoxLayout, QWidget


class CsvTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame = pd.DataFrame()

    def set_frame(self, frame):
        self.beginResetModel()
        self.frame = frame
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame.index)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.frame.columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.ToolTipRole):
            return None
        value = self.frame.iat[index.row(), index.column()]
        if pd.isna(value):
            return "--"
        if isinstance(value, float):
            return f"{value:.6g}"
        return str(value)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return str(self.frame.columns[section])
        return str(section + 1)


class RawCsvTable(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.title = QLabel("No CSV loaded")
        self.model = CsvTableModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(24)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.title)
        layout.addWidget(self.table)

    def set_csv(self, csv_path, frame=None):
        path = Path(csv_path)
        if frame is None:
            frame = pd.read_csv(path, low_memory=False)
        self.title.setText(
            f"{path.name} — {len(frame):,} rows × {len(frame.columns)} columns"
        )
        self.model.set_frame(frame)
        self.table.scrollToTop()