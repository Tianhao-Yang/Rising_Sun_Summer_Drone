from pathlib import Path

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QSplitter, QTabWidget,
    QVBoxLayout, QWidget,
)

from app.pages.raw_csv_table import RawCsvTable


MODE_NAMES = {
    0: "STABILIZE", 1: "ACRO", 2: "ALT HOLD", 3: "AUTO",
    4: "GUIDED", 5: "LOITER", 6: "RTL", 7: "CIRCLE",
    9: "LAND", 11: "DRIFT", 13: "SPORT", 14: "FLIP",
    15: "AUTOTUNE", 16: "POSHOLD", 17: "BRAKE",
}
SERIES_COLORS = [
    "#d62728", "#1f77b4", "#2ca02c", "#9467bd",
    "#ff7f0e", "#17becf", "#8c564b", "#e377c2",
]


class FlightModeTimeline(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(58)
        self.elapsed = np.array([], dtype=float)
        self.modes = np.array([], dtype=float)
        self.cursor_time = None

    def set_data(self, elapsed, modes):
        self.elapsed = np.asarray(elapsed, dtype=float)
        self.modes = np.asarray(modes, dtype=float)
        self.update()

    def set_cursor_time(self, value):
        self.cursor_time = value
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#fafafa"))
        if len(self.elapsed) == 0:
            painter.drawText(self.rect(), Qt.AlignCenter, "No flight-mode data")
            return
        left, right, top, bottom = 8, self.width() - 8, 8, self.height() - 8
        duration = max(float(self.elapsed[-1] - self.elapsed[0]), 1e-9)
        starts = np.r_[0, np.flatnonzero(self.modes[1:] != self.modes[:-1]) + 1]
        ends = np.r_[starts[1:], len(self.elapsed)]
        for number, (start, end) in enumerate(zip(starts, ends)):
            start_t = float(self.elapsed[start])
            end_t = float(self.elapsed[end]) if end < len(self.elapsed) else float(self.elapsed[-1])
            x1 = left + int((start_t - self.elapsed[0]) / duration * (right - left))
            x2 = left + int((end_t - self.elapsed[0]) / duration * (right - left))
            color = QColor(SERIES_COLORS[number % len(SERIES_COLORS)])
            color.setAlpha(150)
            painter.fillRect(x1, top, max(2, x2 - x1), bottom - top, color)
            mode_number = int(self.modes[start])
            label = MODE_NAMES.get(mode_number, f"MODE {mode_number}")
            if x2 - x1 > 62:
                painter.drawText(
                    x1 + 4, top, x2 - x1 - 8, bottom - top,
                    Qt.AlignVCenter | Qt.AlignLeft, label,
                )
        if self.cursor_time is not None:
            x = left + int((self.cursor_time - self.elapsed[0]) / duration * (right - left))
            painter.setPen(QColor("#111111"))
            painter.drawLine(x, top, x, bottom)


class RcChannelPanel(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setMinimumWidth(270)
        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        self.bars, self.labels = {}, {}
        for channel in range(1, 19):
            name = QLabel(f"CH{channel}")
            bar = QProgressBar()
            bar.setRange(800, 2200)
            bar.setTextVisible(False)
            value = QLabel("--")
            value.setMinimumWidth(78)
            grid.addWidget(name, channel - 1, 0)
            grid.addWidget(bar, channel - 1, 1)
            grid.addWidget(value, channel - 1, 2)
            self.bars[channel], self.labels[channel] = bar, value
        self.setWidget(container)

    def update_row(self, row):
        for channel in range(1, 19):
            value = row.get(f"rc{channel}", np.nan)
            if pd.isna(value):
                self.bars[channel].setValue(800)
                self.labels[channel].setText("--")
                continue
            pwm = int(round(float(value)))
            self.bars[channel].setValue(max(800, min(2200, pwm)))
            state = "LOW" if pwm <= 1250 else "HIGH" if pwm >= 1750 else "MID"
            self.labels[channel].setText(f"{pwm} {state}")


class LogViewerPage(QWidget):
    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frame = pd.DataFrame()
        self.elapsed = np.array([], dtype=float)
        self.current_csv = None
        self.checkboxes, self.curves = {}, []

        back_button = QPushButton("← Back to Home")
        back_button.clicked.connect(self.back_requested.emit)
        self.file_label = QLabel("No CSV loaded")
        self.file_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        header = QHBoxLayout()
        header.addWidget(back_button)
        header.addWidget(self.file_label)
        header.addStretch()

        self.tabs = QTabWidget()
        self.visual_page = QWidget()
        self.raw_table = RawCsvTable()
        self.tabs.addTab(self.visual_page, "Visualized Data")
        self.tabs.addTab(self.raw_table, "Raw CSV")

        self.selector_widget = QWidget()
        self.selector_layout = QVBoxLayout(self.selector_widget)
        self.selector_layout.setContentsMargins(6, 6, 6, 6)
        self.selector_layout.addWidget(QLabel("Displayed values"))
        self.selector_layout.addStretch()
        selector_scroll = QScrollArea()
        selector_scroll.setWidgetResizable(True)
        selector_scroll.setWidget(self.selector_widget)
        selector_scroll.setMinimumWidth(230)

        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setLabel("bottom", "Elapsed time", units="s")
        self.plot.addLegend(offset=(10, 10))
        self.cursor = pg.InfiniteLine(
            angle=90,
            movable=True,
            pen=pg.mkPen("#ff0000", width=1),
            hoverPen=pg.mkPen("#ff0000", width=2),
        )
        # Red upward triangle at the bottom of the time cursor.  It moves with
        # the vertical line and marks the currently inspected log time.
        self.cursor.addMarker("^", position=0.0, size=16)
        self.plot.addItem(self.cursor, ignoreBounds=True)
        self.cursor.sigPositionChanged.connect(self._cursor_moved)

        self.mode_timeline = FlightModeTimeline()
        self.status_label = QLabel("Move the cursor to inspect a sample")
        self.status_label.setFrameShape(QFrame.StyledPanel)
        self.status_label.setMinimumHeight(38)
        chart_layout = QVBoxLayout()
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.addWidget(self.plot, 1)
        chart_layout.addWidget(QLabel("Flight mode"))
        chart_layout.addWidget(self.mode_timeline)
        chart_layout.addWidget(self.status_label)
        chart_widget = QWidget()
        chart_widget.setLayout(chart_layout)

        self.rc_panel = RcChannelPanel()
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(selector_scroll)
        splitter.addWidget(chart_widget)
        splitter.addWidget(self.rc_panel)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([230, 900, 280])
        visual_layout = QVBoxLayout(self.visual_page)
        visual_layout.setContentsMargins(6, 6, 6, 6)
        visual_layout.addWidget(splitter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.addLayout(header)
        layout.addWidget(self.tabs)

    def load_csv(self, csv_path):
        path = Path(csv_path)
        try:
            frame = pd.read_csv(path, low_memory=False)
            if frame.empty:
                raise ValueError("CSV contains no data rows.")
            elapsed = (
                pd.to_numeric(frame["elapsed_s"], errors="coerce")
                if "elapsed_s" in frame.columns
                else pd.Series(np.arange(len(frame), dtype=float))
            )
            valid = elapsed.notna()
            frame = frame.loc[valid].reset_index(drop=True)
            elapsed = elapsed.loc[valid].to_numpy(dtype=float)
            if len(frame) == 0:
                raise ValueError("CSV has no rows with a valid time value.")
        except Exception as error:
            QMessageBox.critical(self, "Unable to Open Log", str(error))
            return False

        self.current_csv, self.frame, self.elapsed = path, frame, elapsed
        self.file_label.setText(path.name)
        self.raw_table.set_csv(path, frame)
        self._build_selectors()
        if "flight_mode" in frame.columns:
            modes = pd.to_numeric(frame["flight_mode"], errors="coerce").ffill().fillna(-1)
            self.mode_timeline.set_data(elapsed, modes.to_numpy(dtype=float))
        else:
            self.mode_timeline.set_data([], [])
        self.tabs.setCurrentWidget(self.visual_page)
        self.cursor.setValue(float(elapsed[0]))
        self._update_sample(0)
        return True

    def _build_selectors(self):
        for checkbox in self.checkboxes.values():
            self.selector_layout.removeWidget(checkbox)
            checkbox.deleteLater()
        self.checkboxes.clear()
        preferred = {
            "roll_deg", "pitch_deg", "yaw_deg", "relative_alt_m",
            "groundspeed_mps", "battery_voltage_v", "battery_current_a",
            "motor1_pct", "motor2_pct", "motor3_pct", "motor4_pct",
        }
        excluded = {"elapsed_s", "flight_mode"}
        columns = []
        for column in self.frame.columns:
            if column not in excluded and pd.to_numeric(
                self.frame[column], errors="coerce"
            ).notna().any():
                columns.append(column)
        insert_at = max(0, self.selector_layout.count() - 1)
        for column in columns:
            checkbox = QCheckBox(column)
            checkbox.setChecked(column in preferred)
            checkbox.toggled.connect(self._redraw_plot)
            self.selector_layout.insertWidget(insert_at, checkbox)
            insert_at += 1
            self.checkboxes[column] = checkbox
        self._redraw_plot()

    def _redraw_plot(self):
        for curve in self.curves:
            self.plot.removeItem(curve)
        self.curves.clear()
        selected = [name for name, box in self.checkboxes.items() if box.isChecked()]
        visible_values = []
        for index, column in enumerate(selected):
            values = pd.to_numeric(self.frame[column], errors="coerce").to_numpy(dtype=float)
            finite_values = values[np.isfinite(values)]
            if finite_values.size:
                visible_values.append(finite_values)
            curve = self.plot.plot(
                self.elapsed, values, name=column,
                pen=pg.mkPen(SERIES_COLORS[index % len(SERIES_COLORS)], width=1.5),
            )
            self.curves.append(curve)
        if len(self.elapsed):
            start_time = float(self.elapsed[0])
            end_time = float(self.elapsed[-1])
            duration = max(end_time - start_time, 1e-6)

            # The user may zoom in, but cannot zoom/pan beyond the log's
            # actual first and last timestamps.
            view_box = self.plot.getViewBox()
            view_box.setLimits(
                xMin=start_time,
                xMax=end_time,
                maxXRange=duration,
            )
            self.plot.setXRange(start_time, end_time, padding=0.0)

            if visible_values:
                all_visible_values = np.concatenate(visible_values)
                data_min = float(np.min(all_visible_values))
                data_max = float(np.max(all_visible_values))
                data_span = data_max - data_min

                # Keep a small margin around all selected curves.  This is
                # also the widest permitted Y range; users may still zoom in.
                padding = data_span * 0.05 if data_span > 0.0 else max(abs(data_min) * 0.05, 0.5)
                y_min = data_min - padding
                y_max = data_max + padding
                view_box.setLimits(
                    yMin=y_min,
                    yMax=y_max,
                    maxYRange=max(y_max - y_min, 1e-6),
                )
                self.plot.setYRange(y_min, y_max, padding=0.0)

    def _cursor_moved(self):
        if len(self.elapsed):
            index = int(np.abs(self.elapsed - float(self.cursor.value())).argmin())
            self._update_sample(index)

    def _update_sample(self, index):
        row = self.frame.iloc[index]
        time_value = float(self.elapsed[index])
        mode_value = row.get("flight_mode", np.nan)
        if pd.isna(mode_value):
            mode_text = "--"
        else:
            mode_number = int(float(mode_value))
            mode_text = MODE_NAMES.get(mode_number, f"MODE {mode_number}")
        self.status_label.setText(
            f"t = {time_value:.3f} s    Mode: {mode_text}    "
            f"Armed: {row.get('armed', '--')}    "
            f"Safety: {row.get('safety_released', '--')}    "
            f"FSM: {row.get('fsm_state', '--')}"
        )
        self.mode_timeline.set_cursor_time(time_value)
        self.rc_panel.update_row(row)