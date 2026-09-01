import time
import threading

from PySide6.QtCore import (
    QObject,
    Signal,
    QTimer,
)

from config import (
    CAMERA_RECONNECT_INTERVAL,
)

from core.camera import (
    create_no_camera_screen,
    open_usb_camera,
)

from core.state import TelemetryState

from core.telemetry import (
    telemetry_worker,
)

from hud.renderer import (
    draw_telemetry,
    draw_disconnect_messages,
)


class FlightRuntime(QObject):

    frame_ready = Signal(object)
    # Raw BGR camera image before HUD drawing mutates the display frame.
    raw_camera_frame_ready = Signal(object)

    # gps_valid
    # latitude
    # longitude
    # heading
    # armed
    map_state_ready = Signal(
        bool,
        object,
        object,
        object,
        bool,
    )

    def __init__(self):
        super().__init__()

        # =========================
        # Telemetry state
        # =========================

        self.telemetry_state = (
            TelemetryState()
        )

        # 0 = live warnings, 1 = yellow test, 2 = red flashing test.
        self.test_alert_mode = 0


        # =========================
        # Telemetry thread control
        # =========================

        self.stop_event = (
            threading.Event()
        )

        self.telemetry_thread = (
            threading.Thread(
                target=telemetry_worker,
                args=(
                    self.telemetry_state,
                    self.stop_event,
                ),
                daemon=True,
            )
        )


        # =========================
        # Camera
        # =========================

        self.cap = None

        self.no_camera_screen = (
            create_no_camera_screen()
        )

        self.last_camera_connection_attempt = (
            0.0
        )


        # =========================
        # Frame timer
        # =========================

        self.timer = QTimer(self)

        self.timer.setInterval(
            20
        )

        self.timer.timeout.connect(
            self.update_frame
        )


    # =========================
    # Start runtime
    # =========================

    def set_test_alert_mode(self, mode):
        """Select live, yellow-test, or critical-test HUD warnings."""
        self.test_alert_mode = max(0, min(2, int(mode)))

        # Latch completed checks. Returning to mode 0 must not clear them;
        # they reset naturally when a new TelemetryState is created.
        with self.telemetry_state.lock:
            if self.test_alert_mode == 1:
                self.telemetry_state.hud_warning_yellow_checked = True
            elif self.test_alert_mode == 2:
                self.telemetry_state.hud_warning_red_checked = True

    def set_panel_test_alert_mode(self, mode):
        """Select live/yellow/red indicators and latch completed checks."""
        mode = max(0, min(2, int(mode)))
        with self.telemetry_state.lock:
            self.telemetry_state.panel_test_alert_mode = mode
            if mode == 1:
                self.telemetry_state.info_warning_yellow_checked = True
            elif mode == 2:
                self.telemetry_state.info_warning_red_checked = True

    def start(self):

        if not self.telemetry_thread.is_alive():

            self.telemetry_thread.start()

        self.timer.start()


    # =========================
    # Stop runtime
    # =========================

    def stop(self):

        self.timer.stop()

        self.stop_event.set()

        if self.cap is not None:

            self.cap.release()

            self.cap = None


        if self.telemetry_thread.is_alive():

            self.telemetry_thread.join(
                timeout=2.0
            )


    # =========================
    # Update HUD frame
    # =========================

    def update_frame(self):

        current_time = (
            time.monotonic()
        )


        # =========================
        # Camera
        # =========================

        if self.cap is None:

            display_frame = (
                self.no_camera_screen.copy()
            )

            camera_connected = False


            if (
                current_time
                - self.last_camera_connection_attempt
                >= CAMERA_RECONNECT_INTERVAL
            ):

                self.last_camera_connection_attempt = (
                    current_time
                )

                print(
                    "Checking for USB camera..."
                )

                self.cap = (
                    open_usb_camera()
                )


                if self.cap is not None:

                    print(
                        "USB camera detected."
                    )

                    camera_connected = True


        else:

            ret, frame = (
                self.cap.read()
            )


            if (
                ret
                and frame is not None
            ):

                raw_camera_frame = frame.copy()
                display_frame = frame.copy()

                camera_connected = True

                self.raw_camera_frame_ready.emit(
                    raw_camera_frame
                )


            else:

                print(
                    "USB camera disconnected."
                )

                self.cap.release()

                self.cap = None

                camera_connected = False

                display_frame = (
                    self.no_camera_screen.copy()
                )


        # =========================
        # Draw existing HUD
        # =========================

        draw_telemetry(
            display_frame,
            self.telemetry_state,
            test_alert_mode=self.test_alert_mode,
        )


        # =========================
        # Connection state
        # =========================

        with self.telemetry_state.lock:

            self.telemetry_state.camera_connected = (
                camera_connected
            )

            telemetry_connected = (
                self.telemetry_state.connected
            )

            rc_failsafe = (
                self.telemetry_state.rc_failsafe
            )

            rc_percent_available = (
                self.telemetry_state.rc_rssi_percent
                is not None
                and
                self.telemetry_state.rc_rssi_percent
                > 0
            )


            if not telemetry_connected:

                rc_connected = False


            elif rc_failsafe is True:

                rc_connected = False


            elif rc_failsafe is False:

                rc_connected = True


            else:

                rc_connected = (
                    rc_percent_available
                )

            self.telemetry_state.rc_connected = (
                rc_connected
            )


        # =========================
        # Disconnect warnings
        # =========================

        draw_disconnect_messages(
            display_frame,
            camera_connected=(
                camera_connected
            ),
            telemetry_connected=(
                telemetry_connected
            ),
            rc_connected=(
                rc_connected
            ),
        )


        # =========================
        # Send frame to PySide6
        # =========================
                # =========================
        # Map telemetry state
        # =========================

        with self.telemetry_state.lock:

            gps_fix_type = (
                self.telemetry_state
                .gps_fix_type
            )

            latitude = (
                self.telemetry_state
                .latitude_deg
            )

            longitude = (
                self.telemetry_state
                .longitude_deg
            )

            heading = (
                self.telemetry_state
                .heading_deg
            )

            armed = (
                self.telemetry_state
                .armed
            )


        # =========================
        # GPS validity
        #
        # 3 = 3D fix
        # 4/5/6 = better fixes
        # =========================

        gps_valid = (
            telemetry_connected
            and
            latitude is not None
            and
            longitude is not None
        )


        # =========================
        # Send state to map
        # =========================

        self.map_state_ready.emit(
            gps_valid,
            latitude,
            longitude,
            heading,
            armed,
        )

        self.frame_ready.emit(
            display_frame
        )