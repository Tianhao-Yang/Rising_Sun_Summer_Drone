from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
)

from app.hud_view import HudView

# Real offline map
from app.map.map_widget import MapWidget

# Real instrument panel
from app.instruments.instrument_panel import InstrumentPanel
# Information panel
from app.widgets.information_widget import InformationWidget


class DashboardPage(QWidget):

    def __init__(self):
        super().__init__()


        # =========================
        # Layout settings
        # =========================

        self.page_margin = 10
        self.panel_spacing = 10

        # HUD occupies this percentage
        # of the available page height.
        #
        # Increase -> HUD larger
        # Decrease -> HUD smaller
        self.hud_height_ratio = 0.70


        # =========================
        # HUD
        # =========================

        self.hud_view = HudView()

        self.hud_view.setAlignment(
            Qt.AlignLeft | Qt.AlignTop
        )


        # =========================
        # HUD container
        # =========================

        self.hud_container = QWidget()

        self.hud_layout = QVBoxLayout(
            self.hud_container
        )

        self.hud_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        self.hud_layout.setSpacing(
            0
        )

        self.hud_layout.addWidget(
            self.hud_view,
            alignment=Qt.AlignLeft | Qt.AlignTop,
        )


        # =========================
        # Real Instruments panel
        # =========================

        self.instrument_panel = InstrumentPanel()


        # =========================
        # Information panel
        # =========================
        self.information_panel = InformationWidget()


        # =========================
        # Real Map
        # =========================

        self.map_widget = MapWidget()


        # =========================
        # LEFT COLUMN
        #
        # HUD
        # Instruments
        # =========================

        self.left_widget = QWidget()

        self.left_layout = QVBoxLayout(
            self.left_widget
        )

        self.left_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        self.left_layout.setSpacing(
            self.panel_spacing
        )


        # HUD on top
        self.left_layout.addWidget(
            self.hud_container,
            0,
        )


        # Instruments use remaining height
        self.left_layout.addWidget(
            self.instrument_panel,
            1,
        )


        # =========================
        # RIGHT COLUMN
        #
        # Information
        # Map
        # =========================

        self.right_widget = QWidget()

        self.right_layout = QVBoxLayout(
            self.right_widget
        )

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
            3,
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


        # Left side:
        # HUD + Instruments
        self.main_layout.addWidget(
            self.left_widget,
            0,
        )


        # Right side:
        # Information + Map
        self.main_layout.addWidget(
            self.right_widget,
            1,
        )


        self.setLayout(
            self.main_layout
        )

        


        # =========================
        # OPTIONAL TEST DATA
        # =========================
        #
        # You can temporarily uncomment
        # this block to test the gauges.
        #
        # self.instrument_panel.set_flight_data(
        #     pitch=10,
        #     roll=-15,
        #     speed=25,
        #     altitude=128,
        #     vertical_speed=3.5,
        #     heading=75,
        # )


    # =========================
    # Resize event
    # =========================

    def resizeEvent(self, event):

        super().resizeEvent(event)

        self.update_hud_size()


    # =========================
    # Calculate HUD size
    # =========================

    def update_hud_size(self):

        # Available page height
        available_height = (
            self.height()
            - 2 * self.page_margin
        )

        if available_height <= 0:
            return


        # =========================
        # HUD height
        # =========================

        hud_height = int(
            available_height
            * self.hud_height_ratio
        )


        # =========================
        # HUD aspect ratio
        # =========================

        aspect_ratio = (
            self.hud_view.aspect_ratio()
        )

        if aspect_ratio <= 0:
            return


        # =========================
        # Calculate HUD width
        # =========================

        hud_width = int(
            hud_height
            * aspect_ratio
        )


        # =========================
        # Prevent HUD from taking
        # the entire page width
        # =========================

        max_hud_width = int(
            self.width() * 0.70
        )

        if hud_width > max_hud_width:

            hud_width = max_hud_width

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


        # =========================
        # Left column width
        # follows exact HUD width
        # =========================

        self.left_widget.setFixedWidth(
            hud_width
        )

        self.hud_container.setFixedWidth(
            hud_width
        )

        self.instrument_panel.setFixedWidth(
            hud_width
        )