from PySide6.QtCore import Qt, QEvent
from PySide6.QtWidgets import (
    QMainWindow,
    QStackedWidget,
    QWidget,
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QApplication,
)

from app.logo import LogoWidget
from app.pages.home_page import HomePage
from app.pages.dashboard_page import DashboardPage
from app.pages.hud_page import HudPage
from app.pages.log_viewer_page import LogViewerPage
from app.flight_runtime import FlightRuntime
from pathlib import Path
from core.bluetooth_log_receiver import BluetoothLogReceiver
from core.flight_logging import configure_video_recording


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        # =========================
        # Main window settings
        # =========================

        self.setWindowTitle("Drone HUD")

        # Remove normal Windows title bar
        self.setWindowFlags(
            Qt.FramelessWindowHint
        )


        # =========================
        # Page container
        # =========================

        self.pages = QStackedWidget()


        # =========================
        # Create pages
        # =========================

        self.home_page = HomePage()

        self.dashboard_page = DashboardPage()

        self.hud_page = HudPage()

        self.log_viewer_page = LogViewerPage()


        # Add pages to stacked widget
        self.pages.addWidget(
            self.home_page
        )

        self.pages.addWidget(
            self.dashboard_page
        )

        self.pages.addWidget(
            self.hud_page
        )

        self.pages.addWidget(
            self.log_viewer_page
        )


        # =========================
        # Flight runtime
        # =========================

        # FlightRuntime owns:
        #
        # - USB camera
        # - TelemetryState
        # - Telemetry thread
        # - HUD rendering

        self.flight_runtime = FlightRuntime()

        # Listen application-wide so key release is detected even when a
        # child widget (HUD, map, etc.) owns keyboard focus.
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)


        # =========================
        # Connect telemetry
        # to instrument panel
        # =========================

        # IMPORTANT:
        #
        # InformationWidget uses the SAME
        # TelemetryState as the HUD.
        #
        # It does NOT open COM8 again.

        self.dashboard_page.information_panel.bind_telemetry_state(
            self.flight_runtime.telemetry_state
        )

        # The four lower flight instruments must use the exact same shared
        # TelemetryState as the HUD and InformationWidget. Without this bind,
        # InstrumentPanel's update timer never starts.
        self.dashboard_page.instrument_panel.bind_telemetry_state(
            self.flight_runtime.telemetry_state
        )

        # HUD Page creates its own PhaseChecklistWidget and
        # WarningPanelWidget. Bind both of them to the same shared state;
        # otherwise their tabs appear but their contents stay empty.
        self.hud_page.bind_telemetry_state(
            self.flight_runtime.telemetry_state
        )


        # =========================
        # Send HUD frame
        # to Flight Display
        # =========================

        self.flight_runtime.frame_ready.connect(
            self.dashboard_page.hud_view.set_frame
        )


                # =========================
        # Send HUD frame
        # to HUD Page
        # =========================

        self.flight_runtime.frame_ready.connect(
            self.hud_page.hud_view.set_frame
        )


        # =========================
        # Ground video recording
        # =========================

        # Keep this controller as a MainWindow attribute so Qt/Python cannot
        # garbage-collect it.  It directly observes the same TelemetryState
        # used by the HUD and creates the three MP4 files on ARM.
        self.video_recording_controller = configure_video_recording(
            state=self.flight_runtime.telemetry_state,
            dashboard_page=self.dashboard_page,
            hud_page=self.hud_page,
            parent=self,
        )

        self.flight_runtime.raw_camera_frame_ready.connect(
            self.video_recording_controller.submit_camera_frame
        )


        # =========================
        # Send telemetry state
        # to Flight Display Map
        # =========================

        self.flight_runtime.map_state_ready.connect(
            self.dashboard_page
            .map_widget
            .update_flight_state
        )


        # =========================
        # Send telemetry state
        # to HUD Page Map
        # =========================

        self.flight_runtime.map_state_ready.connect(
            self.hud_page
            .map_widget
            .update_flight_state
        )


        # =========================
        # Start camera + telemetry + HUD
        # =========================

        self.flight_runtime.start()


        # =========================
        # Home page signal
        # =========================

        # Home Page -> Flight Display
        self.home_page.open_dashboard.connect(
            self.show_dashboard_page
        )

        # Double-clicking a CSV in Home opens that file in Log Viewer.
        self.home_page.open_log.connect(
            self.open_log_viewer
        )

        self.log_viewer_page.back_requested.connect(
            self.show_home_page
        )


        # =========================
        # Logo
        # =========================

        self.logo = LogoWidget()


        # =========================
        # Window buttons
        # =========================

        self.minimize_button = QPushButton(
            "−"
        )

        self.close_button = QPushButton(
            "×"
        )


        self.minimize_button.setFixedSize(
            50,
            36,
        )

        self.close_button.setFixedSize(
            50,
            36,
        )


        # =========================
        # Minimize button style
        # =========================

        self.minimize_button.setStyleSheet(
            """
            QPushButton {
                font-size: 20px;
                border: none;
                background-color: transparent;
                padding: 0px;
                margin: 0px;
            }

            QPushButton:hover {
                background-color: #E5E5E5;
            }
            """
        )


        # =========================
        # Close button style
        # =========================

        self.close_button.setStyleSheet(
            """
            QPushButton {
                font-size: 20px;
                border: none;
                background-color: transparent;
                padding: 0px;
                margin: 0px;
            }

            QPushButton:hover {
                background-color: #E81123;
                color: white;
            }
            """
        )


        # =========================
        # Window button functions
        # =========================

        self.minimize_button.clicked.connect(
            self.showMinimized
        )

        self.close_button.clicked.connect(
            self.close
        )


        # =========================
        # Top bar
        # =========================

        top_bar_widget = QWidget()

        top_bar_widget.setFixedHeight(
            36
        )


        top_bar_layout = QHBoxLayout(
            top_bar_widget
        )


        top_bar_layout.setContentsMargins(
            10,
            0,
            0,
            0,
        )

        top_bar_layout.setSpacing(
            0
        )


        # Logo
        top_bar_layout.addWidget(
            self.logo
        )


        # Push buttons to right
        top_bar_layout.addStretch()


        # Minimize
        top_bar_layout.addWidget(
            self.minimize_button
        )


        # Close
        top_bar_layout.addWidget(
            self.close_button
        )


        # =========================
        # Navigation buttons
        # =========================

        self.home_tab = QPushButton(
            "Home"
        )

        self.dashboard_tab = QPushButton(
            "Flight Display"
        )

        self.hud_tab = QPushButton(
            "HUD"
        )


        # =========================
        # Navigation functions
        # =========================

        self.home_tab.clicked.connect(
            self.show_home_page
        )

        self.dashboard_tab.clicked.connect(
            self.show_dashboard_page
        )

        self.hud_tab.clicked.connect(
            self.show_hud_page
        )


        # =========================
        # Navigation bar
        # =========================

        navigation_widget = QWidget()

        navigation_widget.setFixedHeight(
            42
        )


        navigation_layout = QHBoxLayout(
            navigation_widget
        )


        navigation_layout.setContentsMargins(
            15,
            0,
            15,
            0,
        )

        navigation_layout.setSpacing(
            4
        )


        # Home
        navigation_layout.addWidget(
            self.home_tab
        )


        # Flight Display
        navigation_layout.addWidget(
            self.dashboard_tab
        )


        # HUD
        navigation_layout.addWidget(
            self.hud_tab
        )


        navigation_layout.addStretch()


        # =========================
        # Main layout
        # =========================

        main_layout = QVBoxLayout()


        main_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        main_layout.setSpacing(
            0
        )


        # First row:
        # Logo + minimize + close
        main_layout.addWidget(
            top_bar_widget
        )


        # Second row:
        # Home / Flight Display / HUD
        main_layout.addWidget(
            navigation_widget
        )


        # Page area
        main_layout.addWidget(
            self.pages
        )


        # =========================
        # Central container
        # =========================

        container = QWidget()

        container.setLayout(
            main_layout
        )

        self.setCentralWidget(
            container
        )


        # =========================
        # Raspberry Pi Bluetooth logs
        # =========================

        # This uses the Windows incoming Bluetooth port.  It is independent
        # from Pixhawk telemetry on COM8 and runs in its own background thread.
        project_root = Path(__file__).resolve().parent.parent
        self.bluetooth_log_receiver = BluetoothLogReceiver(
            log_root=project_root / "logs",
            serial_port="COM3",
            status_callback=self.on_bluetooth_log_status,
        )
        self.bluetooth_log_receiver.start()


        # =========================
        # Start page
        # =========================

        self.show_home_page()


    def on_bluetooth_log_status(self, message):
        """Background-safe status sink; do not update Qt widgets here."""
        print(f"[PI LOG] {message}", flush=True)


    # =========================
    # Tab style
    # =========================

    def update_tab_style(self):

        normal_style = """
            QPushButton {
                border: none;
                background-color: transparent;
                font-size: 14px;
                padding: 7px 18px;
                border-radius: 10px;
            }

            QPushButton:hover {
                background-color: #EDEDED;
            }
        """


        active_style = """
            QPushButton {
                border: none;
                background-color: white;
                font-size: 14px;
                padding: 7px 18px;
                border-radius: 10px;
                font-weight: bold;
            }
        """


        # First reset all tabs
        self.home_tab.setStyleSheet(
            normal_style
        )

        self.dashboard_tab.setStyleSheet(
            normal_style
        )

        self.hud_tab.setStyleSheet(
            normal_style
        )


        # Determine current page
        current_page = (
            self.pages.currentWidget()
        )


        # Highlight Home
        if current_page is self.home_page:

            self.home_tab.setStyleSheet(
                active_style
            )


        # Highlight Flight Display
        elif current_page is self.dashboard_page:

            self.dashboard_tab.setStyleSheet(
                active_style
            )


        # Highlight HUD
        elif current_page is self.hud_page:

            self.hud_tab.setStyleSheet(
                active_style
            )


    # =========================
    # Show Home Page
    # =========================

    def show_home_page(self):

        self.pages.setCurrentWidget(
            self.home_page
        )

        self.update_tab_style()


    # =========================
    # Show Flight Display
    # =========================

    def show_dashboard_page(self):

        self.pages.setCurrentWidget(
            self.dashboard_page
        )

        self.update_tab_style()


    # =========================
    # Show HUD Page
    # =========================

    def show_hud_page(self):

        self.pages.setCurrentWidget(
            self.hud_page
        )

        self.update_tab_style()


    # =========================
    # Open CSV Log Viewer
    # =========================

    def open_log_viewer(self, csv_path):

        if not self.log_viewer_page.load_csv(csv_path):
            return

        self.pages.setCurrentWidget(
            self.log_viewer_page
        )

        self.update_tab_style()


    # =========================
    # Hold-to-test warnings
    # =========================

    def eventFilter(self, watched, event):
        event_type = event.type()

        if event_type == QEvent.KeyPress:
            if event.modifiers() & Qt.ControlModifier:
                if event.key() == Qt.Key_1:
                    if not event.isAutoRepeat():
                        self.flight_runtime.set_test_alert_mode(1)
                    return True

                if event.key() == Qt.Key_2:
                    if not event.isAutoRepeat():
                        self.flight_runtime.set_test_alert_mode(2)
                    return True

                if event.key() == Qt.Key_4:
                    if not event.isAutoRepeat():
                        self.flight_runtime.set_panel_test_alert_mode(1)
                    return True

                if event.key() == Qt.Key_5:
                    if not event.isAutoRepeat():
                        self.flight_runtime.set_panel_test_alert_mode(2)
                    return True

        elif event_type == QEvent.KeyRelease:
            if event.key() in (Qt.Key_1, Qt.Key_2):
                if not event.isAutoRepeat():
                    self.flight_runtime.set_test_alert_mode(0)
                return True

            if event.key() in (Qt.Key_4, Qt.Key_5):
                if not event.isAutoRepeat():
                    self.flight_runtime.set_panel_test_alert_mode(0)
                return True

            if event.key() == Qt.Key_Control:
                if not event.isAutoRepeat():
                    self.flight_runtime.set_test_alert_mode(0)
                    self.flight_runtime.set_panel_test_alert_mode(0)
                return True

        elif event_type == QEvent.ApplicationDeactivate:
            self.flight_runtime.set_test_alert_mode(0)
            self.flight_runtime.set_panel_test_alert_mode(0)

        return super().eventFilter(watched, event)


    # =========================
    # Close application
    # =========================

    def closeEvent(self, event):

        # Stop:
        # - HUD timer
        # - USB camera
        # - Telemetry thread

        if hasattr(self, "bluetooth_log_receiver"):
            self.bluetooth_log_receiver.stop()

        if hasattr(self, "video_recording_controller"):
            self.video_recording_controller.shutdown()

        if hasattr(self, "flight_runtime"):
            self.flight_runtime.stop()

        event.accept()