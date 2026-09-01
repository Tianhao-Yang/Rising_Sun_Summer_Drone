from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QFrame,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
)

from app.hud_view import HudView
from app.map.map_widget import MapWidget
from app.widgets.flight_status.phase_checklist_widget import PhaseChecklistWidget
from app.widgets.flight_status.warning_panel_widget import WarningPanelWidget

class HudInformationPanel(QFrame):
    """HUD-only two-position Checklist/Warning container."""

    CHECKLIST_STAGE = 0
    WARNING_STAGE = 1

    def __init__(self, parent=None):
        super().__init__(parent)

        self.stage = self.CHECKLIST_STAGE
        self.setFrameShape(QFrame.StyledPanel)

        self.checklist = PhaseChecklistWidget()
        self.warning_panel = WarningPanelWidget()

        # HUD deliberately has only two positions.  This button replaces the
        # multi-position/continuously resizable arrangement used elsewhere.
        self.stage_button = QPushButton()
        self.stage_button.setFixedHeight(24)
        self.stage_button.setCursor(Qt.PointingHandCursor)
        self.stage_button.clicked.connect(self.toggle_stage)
        self.stage_button.setStyleSheet(
            "QPushButton {"
            "background: #E6E6E6; color: #242424; border: none;"
            "font-size: 10px; font-weight: 600; padding: 2px 6px;"
            "}"
            "QPushButton:hover { background: #D8D8D8; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.checklist, 1)
        layout.addWidget(self.stage_button)
        layout.addWidget(self.warning_panel, 1)

        self.set_stage(self.CHECKLIST_STAGE)

    def bind_telemetry_state(self, telemetry_state):
        self.checklist.bind_telemetry_state(telemetry_state)
        self.warning_panel.bind_telemetry_state(telemetry_state)

    def toggle_stage(self):
        self.set_stage(
            self.WARNING_STAGE
            if self.stage == self.CHECKLIST_STAGE
            else self.CHECKLIST_STAGE
        )

    def set_stage(self, stage):
        """Snap to one of the HUD's two allowed display positions."""
        self.stage = (
            self.WARNING_STAGE
            if stage == self.WARNING_STAGE
            else self.CHECKLIST_STAGE
        )

        warning_open = self.stage == self.WARNING_STAGE
        self.checklist.set_compact_mode(warning_open)
        self.warning_panel.setVisible(warning_open)

        if warning_open:
            # Keep only the phase tabs; every remaining pixel belongs to the
            # complete Warning panel.
            self.checklist.setFixedHeight(self.checklist.compact_height())
            self.stage_button.setText("▲  SHOW CHECKLIST")
        else:
            # The checklist fills the former Information window. Its own
            # QScrollArea handles overflow without changing the HUD layout.
            self.checklist.setMinimumHeight(0)
            self.checklist.setMaximumHeight(16777215)
            self.stage_button.setText("▼  SHOW WARNINGS")


class HudPage(QWidget):

    def __init__(self):
        super().__init__()

        # =========================
        # Layout settings
        # =========================

        self.page_margin = 10
        self.panel_spacing = 10

        # Minimum width reserved for
        # Information + Map on the right
        self.right_panel_min_width = 320


        # =========================
        # HUD
        # =========================

        self.hud_view = HudView()

        self.hud_view.setAlignment(
            Qt.AlignLeft | Qt.AlignTop
        )


        # =========================
        # Checklist / Warning panel
        # =========================

        self.information_panel = HudInformationPanel()


        # =========================
        # Real Map
        # =========================

        self.map_widget = MapWidget()


        # =========================
        # Right side layout
        # =========================

        self.right_layout = QVBoxLayout()

        self.right_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        self.right_layout.setSpacing(
            self.panel_spacing
        )


        # Information on top
        self.right_layout.addWidget(
            self.information_panel,
            1,
        )


        # Real map on bottom
        self.right_layout.addWidget(
            self.map_widget,
            1,
        )


        # =========================
        # Main layout
        # =========================

        self.main_layout = QHBoxLayout()

        self.main_layout.setContentsMargins(
            self.page_margin,
            self.page_margin,
            self.page_margin,
            self.page_margin,
        )

        self.main_layout.setSpacing(
            self.panel_spacing
        )


        # HUD on the left
        self.main_layout.addWidget(
            self.hud_view
        )


        # Information + Map
        # use all remaining space
        self.main_layout.addLayout(
            self.right_layout,
            1,
        )


        self.setLayout(
            self.main_layout
        )


    # =========================
    # Shared telemetry state
    # =========================

    def bind_telemetry_state(self, telemetry_state):
        """Bind the HUD-side checklist and warning panel to live state."""
        self.information_panel.bind_telemetry_state(telemetry_state)


    # =========================
    # Resize page
    # =========================

    def resizeEvent(self, event):

        super().resizeEvent(event)

        self.update_hud_size()


    # =========================
    # Calculate HUD size
    # =========================

    def update_hud_size(self):

        # Available height inside the page
        available_height = (
            self.height()
            - 2 * self.page_margin
        )

        if available_height <= 0:
            return


        # =========================
        # HUD aspect ratio
        # =========================

        aspect_ratio = (
            self.hud_view.aspect_ratio()
        )

        if aspect_ratio <= 0:
            return


        # =========================
        # Ideal HUD width
        # =========================

        hud_width = int(
            available_height
            * aspect_ratio
        )


        # =========================
        # Maximum HUD width
        #
        # Keep enough room for
        # Information + Map
        # =========================

        max_hud_width = (
            self.width()
            - 2 * self.page_margin
            - self.panel_spacing
            - self.right_panel_min_width
        )


        hud_width = min(
            hud_width,
            max_hud_width,
        )


        # Prevent invalid tiny width
        hud_width = max(
            100,
            hud_width,
        )


        # =========================
        # Matching HUD height
        # =========================

        hud_height = int(
            hud_width
            / aspect_ratio
        )


        # =========================
        # Apply HUD size
        # =========================

        self.hud_view.setFixedSize(
            hud_width,
            hud_height,
        )