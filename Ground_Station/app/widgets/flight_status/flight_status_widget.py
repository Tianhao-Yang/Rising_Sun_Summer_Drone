from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QSplitter,
    QSplitterHandle,
    QSizePolicy,
)

from .phase_checklist_widget import PhaseChecklistWidget
from .warning_panel_widget import WarningPanelWidget


class ThreeLevelSplitterHandle(QSplitterHandle):
    """Convert one completed vertical drag into one up/down level step."""

    step_requested = Signal(int)

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.press_y = None

    def mousePressEvent(self, event):
        self.press_y = event.globalPosition().y()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        release_y = event.globalPosition().y()
        super().mouseReleaseEvent(event)

        if self.press_y is None:
            return

        movement = release_y - self.press_y
        self.press_y = None

        # Ignore an ordinary click or tiny accidental movement.
        if abs(movement) < 5:
            self.step_requested.emit(0)
        elif movement < 0:
            # Handle moved upward: Warning panel grows by one level.
            self.step_requested.emit(1)
        else:
            # Handle moved downward: Warning panel shrinks by one level.
            self.step_requested.emit(-1)


class ThreeLevelSplitter(QSplitter):
    """QSplitter whose handle reports only the final drag direction."""

    step_requested = Signal(int)

    def createHandle(self):
        handle = ThreeLevelSplitterHandle(self.orientation(), self)
        handle.step_requested.connect(self.step_requested.emit)
        return handle


class FlightStatusWidget(QWidget):
    """Flight phase and Warning panel with three snap positions."""

    WARNING_COLLAPSED = 0
    # First visible level: Warning occupies 2/3 of Information Panel.
    WARNING_TWO_THIRDS = 1
    WARNING_MAXIMUM = 2

    # At the highest Warning level, this much Flight Stage remains visible.
    FLIGHT_STAGE_MINIMUM_HEIGHT = 0

    def __init__(self, parent=None):
        super().__init__(parent)

        self.telemetry_state = None
        self.warning_level = self.WARNING_TWO_THIRDS
        self.has_been_shown = False

        self.phase_widget = PhaseChecklistWidget()
        self.warning_widget = WarningPanelWidget()

        self.phase_widget.setMinimumHeight(
            self.FLIGHT_STAGE_MINIMUM_HEIGHT
        )
        self.phase_widget.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Ignored,
        )

        self.warning_widget.setMinimumHeight(0)
        self.warning_widget.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Ignored,
        )

        self.splitter = ThreeLevelSplitter(Qt.Vertical)
        self.splitter.addWidget(self.phase_widget)
        self.splitter.addWidget(self.warning_widget)
        self.splitter.setChildrenCollapsible(True)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, True)
        self.splitter.setHandleWidth(6)
        self.splitter.step_requested.connect(self.change_warning_level)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.splitter)

    def bind_telemetry_state(self, telemetry_state):
        self.telemetry_state = telemetry_state
        self.phase_widget.bind_telemetry_state(telemetry_state)
        self.warning_widget.bind_telemetry_state(telemetry_state)

    def showEvent(self, event):
        super().showEvent(event)
        self.has_been_shown = True
        QTimer.singleShot(0, self.apply_warning_level)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.has_been_shown:
            QTimer.singleShot(0, self.apply_warning_level)

    def change_warning_level(self, direction):
        """Move exactly one level per completed mouse drag."""
        if direction > 0:
            self.warning_level = min(
                self.WARNING_MAXIMUM,
                self.warning_level + 1,
            )
        elif direction < 0:
            self.warning_level = max(
                self.WARNING_COLLAPSED,
                self.warning_level - 1,
            )

        # Even a click with no movement restores the current snap position.
        self.apply_warning_level()

    def set_warning_level(self, level):
        """Optional programmatic level control: 0, 1, or 2."""
        self.warning_level = max(
            self.WARNING_COLLAPSED,
            min(self.WARNING_MAXIMUM, int(level)),
        )
        self.apply_warning_level()

    def apply_warning_level(self):
        sizes = self.splitter.sizes()
        available_height = sum(sizes)

        if available_height <= 0:
            available_height = max(
                0,
                self.splitter.height() - self.splitter.handleWidth(),
            )

        if available_height <= 0:
            return

        if self.warning_level == self.WARNING_COLLAPSED:
            stage_height = available_height
            warning_height = 0

        elif self.warning_level == self.WARNING_TWO_THIRDS:
            warning_height = (available_height * 2) // 3
            stage_height = available_height - warning_height

        else:
            stage_height = min(
                available_height,
                self.FLIGHT_STAGE_MINIMUM_HEIGHT,
            )
            warning_height = available_height - stage_height

        self.splitter.setSizes([
            stage_height,
            warning_height,
        ])