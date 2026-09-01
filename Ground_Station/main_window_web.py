"""Web-publishing variant of the Red Sun ground-station main window.

This remains a normal PySide6 desktop window.  It does not try to run PySide6
inside a browser.  While the application is open it captures the existing
Flight Display and HUD widgets and sends JPEG frames plus a heartbeat to the
website backend.  The website decides that the mission is offline when the
heartbeat expires.

Environment variables:
    REDSUN_WEB_BASE_URL   Example: https://example.com/api/live
    REDSUN_WEB_TOKEN      Private upload token; never put this in website JS
    REDSUN_WEB_FPS        Capture rate, default 1.0 frame/second
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from PySide6.QtCore import QBuffer, QByteArray, QEvent, QIODevice, QPoint, QTimer, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.flight_runtime import FlightRuntime
from app.logo import LogoWidget
from app.pages.dashboard_page import DashboardPage
from app.pages.home_page import HomePage
from app.pages.hud_page import HudPage
from app.pages.log_viewer_page import LogViewerPage
from core.bluetooth_log_receiver import BluetoothLogReceiver
from core.flight_logging import configure_video_recording


class WebsitePublisher:
    """Capture existing Qt pages without opening another camera or COM port."""

    def __init__(self, dashboard_page, hud_page, parent=None):
        self.dashboard_page = dashboard_page
        self.hud_page = hud_page
        self.base_url = os.getenv("REDSUN_WEB_BASE_URL", "").rstrip("/")
        self.token = os.getenv("REDSUN_WEB_TOKEN", "")
        self.enabled = bool(self.base_url and self.token)
        self.session_id = f"ground-station-{int(time.time())}"
        self.executor = ThreadPoolExecutor(max_workers=1)
        self._upload_busy = threading.Event()

        try:
            fps = max(0.2, min(5.0, float(os.getenv("REDSUN_WEB_FPS", "1.0"))))
        except ValueError:
            fps = 1.0

        self.timer = QTimer(parent)
        self.timer.setInterval(round(1000 / fps))
        self.timer.timeout.connect(self.publish_once)

        if self.enabled:
            self.timer.start()
            print(f"[WEB] Publishing enabled at {fps:g} FPS", flush=True)
        else:
            print(
                "[WEB] Publishing disabled: set REDSUN_WEB_BASE_URL and "
                "REDSUN_WEB_TOKEN.",
                flush=True,
            )

    @staticmethod
    def _capture_widget(widget):
        """Render a page to JPEG even when another QStackedWidget page is visible."""
        size = widget.size()
        if size.width() < 100 or size.height() < 100:
            return None

        image = QImage(size, QImage.Format_RGB888)
        image.fill(Qt.black)
        painter = QPainter(image)
        if not painter.isActive():
            return None

        try:
            widget.render(painter, QPoint(0, 0))
        finally:
            painter.end()

        payload = QByteArray()
        buffer = QBuffer(payload)
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, "JPEG", 82)
        buffer.close()
        return bytes(payload)

    def publish_once(self):
        # Never queue old frames when the network is slow.
        if not self.enabled or self._upload_busy.is_set():
            return

        dashboard_jpeg = self._capture_widget(self.dashboard_page)
        hud_jpeg = self._capture_widget(self.hud_page)
        if not dashboard_jpeg or not hud_jpeg:
            return

        self._upload_busy.set()
        self.executor.submit(self._upload, dashboard_jpeg, hud_jpeg)

    def _upload(self, dashboard_jpeg, hud_jpeg):
        try:
            headers = {
                "Authorization": f"Bearer {self.token}",
                "X-RedSun-Session": self.session_id,
            }
            files = {
                "flight_display": ("flight-display.jpg", dashboard_jpeg, "image/jpeg"),
                "hud": ("hud.jpg", hud_jpeg, "image/jpeg"),
            }
            response = requests.post(
                f"{self.base_url}/frames",
                headers=headers,
                files=files,
                data={"captured_at": str(time.time())},
                timeout=8,
            )
            response.raise_for_status()
        except Exception as error:
            print(f"[WEB] Upload failed: {error}", flush=True)
        finally:
            self._upload_busy.clear()

    def shutdown(self):
        self.timer.stop()
        if self.enabled:
            try:
                requests.post(
                    f"{self.base_url}/offline",
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "X-RedSun-Session": self.session_id,
                    },
                    timeout=2,
                )
            except Exception:
                pass
        self.executor.shutdown(wait=False, cancel_futures=True)


class MainWindowWeb(QMainWindow):
    """Three-page desktop source for the public website."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Rising Sun No. 1")
        self.setWindowFlags(Qt.FramelessWindowHint)

        self.pages = QStackedWidget()
        self.home_page = HomePage()
        self.dashboard_page = DashboardPage()
        self.hud_page = HudPage()
        self.log_viewer_page = LogViewerPage()
        for page in (
            self.home_page,
            self.dashboard_page,
            self.hud_page,
            self.log_viewer_page,
        ):
            self.pages.addWidget(page)

        # One runtime and one TelemetryState are shared by every page.
        self.flight_runtime = FlightRuntime()
        self.dashboard_page.information_panel.bind_telemetry_state(
            self.flight_runtime.telemetry_state
        )
        self.dashboard_page.instrument_panel.bind_telemetry_state(
            self.flight_runtime.telemetry_state
        )
        self.hud_page.bind_telemetry_state(self.flight_runtime.telemetry_state)
        self.flight_runtime.frame_ready.connect(self.dashboard_page.hud_view.set_frame)
        self.flight_runtime.frame_ready.connect(self.hud_page.hud_view.set_frame)
        self.flight_runtime.map_state_ready.connect(
            self.dashboard_page.map_widget.update_flight_state
        )
        self.flight_runtime.map_state_ready.connect(
            self.hud_page.map_widget.update_flight_state
        )

        # Keep the existing local MP4 recording behavior.
        self.video_recording_controller = configure_video_recording(
            state=self.flight_runtime.telemetry_state,
            dashboard_page=self.dashboard_page,
            hud_page=self.hud_page,
            parent=self,
        )
        self.flight_runtime.raw_camera_frame_ready.connect(
            self.video_recording_controller.submit_camera_frame
        )

        self._build_window_chrome()
        self._connect_navigation()

        project_root = Path(__file__).resolve().parent
        self.bluetooth_log_receiver = BluetoothLogReceiver(
            log_root=project_root / "logs",
            serial_port="COM3",
            status_callback=lambda message: print(f"[PI LOG] {message}", flush=True),
        )
        self.bluetooth_log_receiver.start()

        self.website_publisher = WebsitePublisher(
            dashboard_page=self.dashboard_page,
            hud_page=self.hud_page,
            parent=self,
        )

        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)

        self.flight_runtime.start()
        self.show_home_page()

    def _build_window_chrome(self):
        self.logo = LogoWidget()
        self.minimize_button = QPushButton("−")
        self.close_button = QPushButton("×")
        for button in (self.minimize_button, self.close_button):
            button.setFixedSize(50, 36)
        self.minimize_button.clicked.connect(self.showMinimized)
        self.close_button.clicked.connect(self.close)
        self.minimize_button.setStyleSheet(
            "QPushButton{font-size:20px;border:none;background:transparent;}"
            "QPushButton:hover{background:#e5e5e5;}"
        )
        self.close_button.setStyleSheet(
            "QPushButton{font-size:20px;border:none;background:transparent;}"
            "QPushButton:hover{background:#e81123;color:white;}"
        )

        top_bar = QWidget()
        top_bar.setFixedHeight(36)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(10, 0, 0, 0)
        top_layout.setSpacing(0)
        top_layout.addWidget(self.logo)
        top_layout.addStretch()
        top_layout.addWidget(self.minimize_button)
        top_layout.addWidget(self.close_button)

        self.home_tab = QPushButton("Home")
        self.dashboard_tab = QPushButton("Flight Display")
        self.hud_tab = QPushButton("HUD")
        navigation = QWidget()
        navigation.setFixedHeight(42)
        navigation_layout = QHBoxLayout(navigation)
        navigation_layout.setContentsMargins(15, 0, 15, 0)
        navigation_layout.setSpacing(4)
        for button in (self.home_tab, self.dashboard_tab, self.hud_tab):
            navigation_layout.addWidget(button)
        navigation_layout.addStretch()

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(top_bar)
        layout.addWidget(navigation)
        layout.addWidget(self.pages)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def _connect_navigation(self):
        self.home_tab.clicked.connect(self.show_home_page)
        self.dashboard_tab.clicked.connect(self.show_dashboard_page)
        self.hud_tab.clicked.connect(self.show_hud_page)
        self.home_page.open_dashboard.connect(self.show_dashboard_page)
        self.home_page.open_log.connect(self.open_log_viewer)
        self.log_viewer_page.back_requested.connect(self.show_home_page)

    def update_tab_style(self):
        normal = (
            "QPushButton{border:none;background:transparent;font-size:14px;"
            "padding:7px 18px;border-radius:10px;}"
            "QPushButton:hover{background:#ededed;}"
        )
        active = (
            "QPushButton{border:none;background:white;font-size:14px;"
            "padding:7px 18px;border-radius:10px;font-weight:bold;}"
        )
        for button in (self.home_tab, self.dashboard_tab, self.hud_tab):
            button.setStyleSheet(normal)
        current = self.pages.currentWidget()
        if current is self.home_page:
            self.home_tab.setStyleSheet(active)
        elif current is self.dashboard_page:
            self.dashboard_tab.setStyleSheet(active)
        elif current is self.hud_page:
            self.hud_tab.setStyleSheet(active)

    def show_home_page(self):
        self.pages.setCurrentWidget(self.home_page)
        self.update_tab_style()

    def show_dashboard_page(self):
        self.pages.setCurrentWidget(self.dashboard_page)
        self.update_tab_style()

    def show_hud_page(self):
        self.pages.setCurrentWidget(self.hud_page)
        self.update_tab_style()

    def open_log_viewer(self, csv_path):
        if self.log_viewer_page.load_csv(csv_path):
            self.pages.setCurrentWidget(self.log_viewer_page)
            self.update_tab_style()

    def eventFilter(self, watched, event):
        event_type = event.type()
        if event_type == QEvent.KeyPress and event.modifiers() & Qt.ControlModifier:
            if event.key() in (Qt.Key_1, Qt.Key_2) and not event.isAutoRepeat():
                self.flight_runtime.set_test_alert_mode(
                    1 if event.key() == Qt.Key_1 else 2
                )
                return True
            if event.key() in (Qt.Key_4, Qt.Key_5) and not event.isAutoRepeat():
                self.flight_runtime.set_panel_test_alert_mode(
                    1 if event.key() == Qt.Key_4 else 2
                )
                return True
        elif event_type == QEvent.KeyRelease and not event.isAutoRepeat():
            if event.key() in (Qt.Key_1, Qt.Key_2, Qt.Key_Control):
                self.flight_runtime.set_test_alert_mode(0)
            if event.key() in (Qt.Key_4, Qt.Key_5, Qt.Key_Control):
                self.flight_runtime.set_panel_test_alert_mode(0)
        elif event_type == QEvent.ApplicationDeactivate:
            self.flight_runtime.set_test_alert_mode(0)
            self.flight_runtime.set_panel_test_alert_mode(0)
        return super().eventFilter(watched, event)

    def closeEvent(self, event):
        self.website_publisher.shutdown()
        self.bluetooth_log_receiver.stop()
        self.video_recording_controller.shutdown()
        self.flight_runtime.stop()
        event.accept()


# Optional compatibility: an existing launcher importing MainWindow can switch
# to this file without changing the class name it instantiates.
MainWindow = MainWindowWeb