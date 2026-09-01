import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QPushButton,
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QStackedWidget,
    QScrollArea,
    QSizePolicy,
    QLayout,
)

from config import BASE_LOG_DIRECTORY


GROUND_SESSION_MARKER_FILENAME = ".ground_session.json"


class PhaseChecklistWidget(QWidget):
    """Flight-phase tabs with automatically updated checklist content."""

    PHASE_NAMES = (
        "BEFORE TAKEOFF",
        "CRUISING",
        "AFTER LANDING",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.telemetry_state = None
        self.current_phase = None
        # Set after at least two motor outputs have exceeded 10% during the
        # current flight cycle. This distinguishes a real flight/landing from
        # an idle automatic Disarm.
        self.flight_thrust_detected = False
        # Last confirmed arm state received while telemetry was connected.
        # It is used to detect real Disarmed -> Armed and Armed -> Disarmed
        # transitions instead of treating a telemetry loss as a Disarm.
        self.previous_armed = False
        # Final after-landing acknowledgement. This is intentionally manual:
        # the operator clicks the checklist row after reviewing the flight.
        self.flight_completion_confirmed = False
        self.tab_buttons = []
        self.page_labels = []
        self.page_scroll_areas = []
        self.pages = QStackedWidget()

        # Browser-style tab strip. The active white tab touches the white page
        # below, so both surfaces read as one continuous sheet.
        self.tab_bar = QFrame()
        self.tab_bar.setFixedHeight(46)
        self.tab_bar.setStyleSheet(
            "QFrame {"
            "background-color: #E6E6E6;"
            "border: none;"
            "}"
        )

        tab_layout = QHBoxLayout(self.tab_bar)
        tab_layout.setContentsMargins(4, 4, 4, 0)
        tab_layout.setSpacing(2)

        for index, phase_name in enumerate(self.PHASE_NAMES):
            button = QPushButton(phase_name)
            button.setCheckable(True)
            button.setFixedHeight(36)
            button.clicked.connect(
                lambda checked=False, page=index: self.select_phase(page)
            )
            self.tab_buttons.append(button)
            tab_layout.addWidget(
                button,
                1,
                Qt.AlignBottom,
            )

            page = QWidget()
            page.setStyleSheet("background-color: #FFFFFF; border: none;")
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(10, 10, 10, 10)
            page_layout.setSizeConstraint(QLayout.SetMinAndMaxSize)

            label = QLabel()
            label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
            label.setStyleSheet("font-size: 11px; color: #242424;")
            page_layout.addWidget(label)

            # Keep the phase tabs fixed while allowing the active checklist
            # or plan to be scrolled whenever the Warning panel leaves too
            # little vertical space for all rows.
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            scroll_area.setFrameShape(QFrame.NoFrame)
            scroll_area.setHorizontalScrollBarPolicy(
                Qt.ScrollBarAlwaysOff
            )
            scroll_area.setVerticalScrollBarPolicy(
                Qt.ScrollBarAsNeeded
            )
            scroll_area.setStyleSheet(
                "QScrollArea { background: #FFFFFF; border: none; }"
                "QScrollArea > QWidget > QWidget { background: #FFFFFF; }"
            )
            scroll_area.setWidget(page)

            self.page_labels.append(label)
            self.page_scroll_areas.append(scroll_area)
            self.pages.addWidget(scroll_area)

        # Only the final After Landing row contains an interactive rich-text
        # link. QLabel emits linkActivated without opening an external page.
        self.page_labels[2].setTextInteractionFlags(
            Qt.LinksAccessibleByMouse
        )
        self.page_labels[2].setOpenExternalLinks(False)
        self.page_labels[2].linkActivated.connect(
            self._handle_after_landing_link
        )

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(8, 0, 8, 8)
        self.main_layout.setSpacing(0)
        self.main_layout.addWidget(self.tab_bar)
        self.main_layout.addWidget(self.pages, 1)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(250)
        self.refresh_timer.timeout.connect(self.refresh_from_telemetry)
        self.refresh_timer.start()

        self.select_phase(0)

    def compact_height(self):
        """Exact height required when only the browser-style tabs are shown."""
        return self.tab_bar.height()

    def set_compact_mode(self, compact):
        """At maximum Warning size, hide the checklist without blank space."""
        self.pages.setVisible(not compact)
        self.main_layout.setContentsMargins(
            8,
            0,
            8,
            0 if compact else 8,
        )

    def bind_telemetry_state(self, telemetry_state):
        self.telemetry_state = telemetry_state
        self.refresh_from_telemetry()

    def select_phase(self, index):
        self.pages.setCurrentIndex(index)

        for button_index, button in enumerate(self.tab_buttons):
            active = button_index == index
            button.setChecked(active)
            button.setStyleSheet(
                "QPushButton {"
                f"background-color: {'#FFFFFF' if active else '#D8D8D8'};"
                "color: #161616;"
                "border: none;"
                "border-top-left-radius: 12px;"
                "border-top-right-radius: 12px;"
                "border-bottom-left-radius: 0px;"
                "border-bottom-right-radius: 0px;"
                "padding: 6px 4px;"
                "font-size: 11px;"
                f"font-weight: {'700' if active else '400'};"
                "}"
                "QPushButton:hover {"
                f"background-color: {'#FFFFFF' if active else '#CECECE'};"
                "}"
            )

    @staticmethod
    def status_line(label, passed, pass_text, fail_text):
        """Create a colored row whose status is aligned at the right."""
        passed = bool(passed)
        status = pass_text if passed else fail_text
        color = "#168A3B" if passed else "#D71920"
        return (
            '<tr>'
            f'<td style="color:{color}; font-weight:600; '
            f'white-space:nowrap;">{label}</td>'
            f'<td width="100%" align="center" style="color:{color}; '
            f'white-space:nowrap;">................................................</td>'
            f'<td align="right" style="color:{color}; font-weight:600; '
            f'white-space:nowrap;">{status}</td>'
            '</tr>'
        )

    @classmethod
    def connection_line(cls, label, connected):
        return cls.status_line(
            label,
            connected,
            "Connected",
            "Disconnected",
        )

    def _handle_after_landing_link(self, link):
        """Complete the flight and return to the preflight checklist."""
        if link != "complete-flight":
            return

        # The click closes the completed flight cycle. Reset this manual row
        # to its red/incomplete state ready for the next flight.
        self.flight_completion_confirmed = False
        self.flight_thrust_detected = False
        self.current_phase = 0
        self.select_phase(0)
        self.refresh_from_telemetry()

    def complete_flight_line(self):
        """Create the clickable final row of the after-landing checklist."""
        passed = self.flight_completion_confirmed
        color = "#168A3B" if passed else "#D71920"
        status = "Complete" if passed else "Incomplete"
        return (
            '<tr>'
            f'<td style="color:{color}; font-weight:600; '
            'white-space:nowrap;">Complete Flight</td>'
            '<td width="100%" align="center" style="white-space:nowrap;">'
            '<span style="color:#777777;">....................</span>'
            '<a href="complete-flight" style="color:#1565C0; '
            'font-weight:600; text-decoration:underline;">Click</a>'
            '<span style="color:#777777;">....................</span>'
            '</td>'
            f'<td align="right" style="color:{color}; font-weight:600; '
            f'white-space:nowrap;">{status}</td>'
            '</tr>'
        )

    @staticmethod
    def _find_completed_session_folder(session_name, session_directory):
        """Locate one completed recording before or after CSV-folder merge."""
        if not session_name:
            return None

        candidates = []
        if session_directory:
            candidates.append(Path(session_directory))

        log_root = Path(BASE_LOG_DIRECTORY).resolve()
        candidates.append(log_root / str(session_name))

        for candidate in candidates:
            if candidate.is_dir():
                return candidate

        try:
            folders = (path for path in log_root.iterdir() if path.is_dir())
            for folder in folders:
                marker = folder / GROUND_SESSION_MARKER_FILENAME
                try:
                    payload = json.loads(marker.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    continue
                if payload.get("ground_session_name") == session_name:
                    return folder
        except OSError:
            pass
        return None

    @classmethod
    def _after_landing_file_status(cls, session_name, session_directory):
        folder = cls._find_completed_session_folder(
            session_name,
            session_directory,
        )
        if folder is None:
            return False, False
        try:
            files = [path for path in folder.iterdir() if path.is_file()]
        except OSError:
            return False, False

        def valid_file(path, suffix):
            if path.suffix.lower() != suffix:
                return False
            try:
                return path.stat().st_size > 0
            except OSError:
                return False

        mp4_saved = any(valid_file(path, ".mp4") for path in files)
        csv_received = any(valid_file(path, ".csv") for path in files)
        return mp4_saved, csv_received

    def refresh_from_telemetry(self):
        state = self.telemetry_state
        if state is None:
            return

        with state.lock:
            connected = bool(getattr(state, "connected", False))
            camera_connected = bool(
                getattr(state, "camera_connected", False)
            )
            rc_connected = bool(
                getattr(state, "rc_connected", False)
            )
            ready_to_arm = getattr(state, "ready_to_arm", None)
            pi_load = getattr(state, "pi_load_percent", None)
            pc_battery = getattr(state, "pc_battery_percent", None)
            hud_yellow_checked = bool(
                getattr(state, "hud_warning_yellow_checked", False)
            )
            hud_red_checked = bool(
                getattr(state, "hud_warning_red_checked", False)
            )
            info_yellow_checked = bool(
                getattr(state, "info_warning_yellow_checked", False)
            )
            info_red_checked = bool(
                getattr(state, "info_warning_red_checked", False)
            )
            pi_state = getattr(state, "pi_state", None)
            armed = bool(getattr(state, "armed", False))
            motor_percentages = list(
                getattr(state, "motor_percentages", [])
            )
            battery = getattr(state, "battery_voltage_v", None)
            pi_temp = getattr(state, "pi_temp_c", None)
            outputs_enabled = getattr(state, "motor_outputs_enabled", None)
            recording = bool(getattr(state, "recording", False))
            after_landing_session_name = getattr(
                state, "after_landing_session_name", None
            )
            after_landing_session_directory = getattr(
                state, "after_landing_session_directory", None
            )

        # A new Arm starts a new flight cycle. Clear the thrust history left
        # by the preceding flight exactly once on the rising arm edge.
        new_arm_cycle = (
            connected
            and armed
            and not self.previous_armed
        )
        if new_arm_cycle:
            self.flight_thrust_detected = False
            self.flight_completion_confirmed = False

        motors_above_ten = 0
        for value in motor_percentages[:4]:
            try:
                if value is not None and float(value) > 10.0:
                    motors_above_ten += 1
            except (TypeError, ValueError):
                continue

        if motors_above_ten >= 2:
            self.flight_thrust_detected = True

        # BEFORE TAKEOFF -> CRUISING: aircraft becomes armed.
        # CRUISING -> AFTER LANDING: at least two motors previously exceeded
        # 10%, followed by Disarm.
        confirmed_disarm_edge = (
            connected
            and self.previous_armed
            and not armed
        )

        if not connected:
            # Freeze the last confirmed phase while the link is unavailable.
            # A missing heartbeat is not evidence of either Arm or Disarm.
            pi_state = (
                self.current_phase
                if self.current_phase in (0, 1, 2)
                else 0
            )
        elif armed:
            pi_state = 1
        elif (
            self.current_phase == 1
            and self.flight_thrust_detected
            and confirmed_disarm_edge
        ):
            pi_state = 2
        elif self.current_phase == 2:
            pi_state = 2
        else:
            pi_state = 0

        # Do not turn an absent heartbeat into a false Disarm edge. Keep the
        # last confirmed value until telemetry is available again.
        if connected:
            self.previous_armed = armed

        if pi_state != self.current_phase:
            self.current_phase = pi_state
            self.select_phase(pi_state)

        try:
            pi_started = connected and float(pi_load) > 0.0
        except (TypeError, ValueError):
            pi_started = False

        try:
            pc_charge_value = float(pc_battery)
            pc_charge_ok = pc_charge_value > 10.0
            pc_charge_text = f"{pc_charge_value:.0f}%"
        except (TypeError, ValueError):
            pc_charge_ok = False
            pc_charge_text = "Unavailable"

        hud_warning_checked = (
            hud_yellow_checked and hud_red_checked
        )
        info_warning_checked = (
            info_yellow_checked and info_red_checked
        )

        before_content = "".join([
            '<div style="color:#242424; margin-bottom:10px;">'
            'BEFORE TAKEOFF CHECKLIST</div>',
            '<table width="100%" cellspacing="0" cellpadding="0">',
            self.connection_line("USB Camera", camera_connected),
            self.connection_line("Telemetry", connected),
            self.connection_line("RC Signal", rc_connected),
            self.status_line(
                "Drone Ready to Arm",
                ready_to_arm is True,
                "Ready",
                "Not Ready",
            ),
            self.status_line(
                "Pi Start Up",
                pi_started,
                "Started",
                "Not Started",
            ),
            self.status_line(
                "PC Charge",
                pc_charge_ok,
                pc_charge_text,
                pc_charge_text,
            ),
            self.status_line(
                "HUD Warning Check",
                hud_warning_checked,
                "Checked",
                "Not Checked",
            ),
            self.status_line(
                "Info Warning Check",
                info_warning_checked,
                "Checked",
                "Not Checked",
            ),
            '</table>',
        ])

        cruising_lines = [
            "CRUISING PLAN",
            "",
            "Planning functions will be added in a future stage.",
        ]

        mp4_saved, csv_received = self._after_landing_file_status(
            after_landing_session_name,
            after_landing_session_directory,
        )
        after_content = "".join([
            '<div style="color:#242424; margin-bottom:10px;">'
            'AFTER LANDING CHECKLIST</div>',
            '<table width="100%" cellspacing="0" cellpadding="0">',
            self.status_line(
                "Flight Recording",
                mp4_saved,
                "Complete",
                "Incomplete",
            ),
            self.status_line(
                "CSV Flight Log",
                csv_received,
                "Complete",
                "Incomplete",
            ),
            self.status_line(
                "Aircraft",
                not armed,
                "Disarmed",
                "ARMED",
            ),
            self.complete_flight_line(),
            '</table>',
        ])

        self.page_labels[0].setText(before_content)
        self.page_labels[1].setText("\n".join(cruising_lines))
        self.page_labels[2].setText(after_content)