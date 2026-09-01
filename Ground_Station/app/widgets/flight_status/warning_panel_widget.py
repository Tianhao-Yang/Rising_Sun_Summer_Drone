import time
import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QFrame,
    QScrollArea,
    QSizePolicy,
    QHBoxLayout,
    QVBoxLayout,
)

class DroneAlertLineWidget(QWidget):
    """One borderless checklist-style Pixhawk warning/alert line."""

    dismiss_requested = Signal(object)

    def __init__(
        self,
        severity,
        text,
        details="",
        dismiss_id=None,
        parent=None,
    ):
        super().__init__(parent)
        self.dismiss_id = dismiss_id

        severity = str(severity).upper()
        if severity in ("ALERT", "CRITICAL"):
            color = "#D71920"
        elif severity == "NOTICE":
            color = "#168A3B"
        else:
            color = "#D69E00"

        message = QLabel(str(text))
        message.setStyleSheet(
            f"color: {color}; font-size: 10px; font-weight: 600;"
        )
        message.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        dotted_line = QFrame()
        dotted_line.setFixedHeight(1)
        dotted_line.setStyleSheet(
            f"border: none; border-top: 1px dotted {color};"
        )
        dotted_line.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        severity_label = QLabel(
            f"{severity} (click)" if dismiss_id is not None else severity
        )
        severity_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        severity_label.setStyleSheet(
            f"color: {color}; font-size: 10px; font-weight: 700;"
        )
        severity_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(6)
        layout.addWidget(message)
        layout.addWidget(dotted_line, 1)
        layout.addWidget(severity_label)

        if details:
            self.setToolTip(str(details))

        if dismiss_id is not None:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip(
                (self.toolTip() + "\n" if self.toolTip() else "")
                + "Click to acknowledge and remove"
            )

    def mouseReleaseEvent(self, event):
        if (
            self.dismiss_id is not None
            and event.button() == Qt.LeftButton
        ):
            self.dismiss_requested.emit(self.dismiss_id)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class AlertSectionWidget(QFrame):
    """Fixed alert section with an independent vertical scrollbar."""

    alert_dismiss_requested = Signal(object)

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self._signature = None

        title_label = QLabel(title)
        title_label.setStyleSheet(
            "font-size: 11px; font-weight: 700; color: #181818;"
        )

        title_line = QFrame()
        title_line.setFixedHeight(1)
        title_line.setStyleSheet(
            "background-color: #C8C8C8; border: none;"
        )

        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(8)
        title_layout.addWidget(title_label)
        title_layout.addWidget(title_line, 1)

        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background: transparent;")
        self.alert_layout = QVBoxLayout(self.scroll_content)
        self.alert_layout.setContentsMargins(4, 4, 4, 4)
        self.alert_layout.setSpacing(4)
        self.alert_layout.addStretch()

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setStyleSheet("border: none; background: transparent;")
        scroll_area.setWidget(self.scroll_content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 5)
        layout.setSpacing(4)
        layout.addLayout(title_layout)
        layout.addWidget(scroll_area, 1)

        self.setFrameShape(QFrame.NoFrame)

    def set_alerts(self, alerts):
        signature = tuple(tuple(map(str, alert)) for alert in alerts)
        if signature == self._signature:
            return
        self._signature = signature

        while self.alert_layout.count() > 1:
            item = self.alert_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not alerts:
            empty = QLabel("NO ACTIVE WARNINGS")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet("color: #8A8A8A; font-size: 10px;")
            self.alert_layout.insertWidget(0, empty)
            return

        for alert in alerts:
            severity, text, details = alert[:3]
            dismiss_id = alert[3] if len(alert) > 3 else None
            alert_widget = DroneAlertLineWidget(
                severity,
                text,
                details,
                dismiss_id=dismiss_id,
            )
            alert_widget.dismiss_requested.connect(
                self.alert_dismiss_requested.emit
            )
            self.alert_layout.insertWidget(
                self.alert_layout.count() - 1,
                alert_widget,
            )


class WarningPanelWidget(QWidget):
    """Scrollable Drone/Pi/PC warning groups in a 55:30:15 ratio."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.telemetry_state = None

        self.drone_section = AlertSectionWidget("DRONE")
        self.drone_section.alert_dismiss_requested.connect(
            self.dismiss_drone_alert
        )
        self.pi_section = AlertSectionWidget("R-PI")
        self.pi_section.alert_dismiss_requested.connect(
            self.dismiss_pi_alert
        )
        self.pc_section = AlertSectionWidget("PC")
        self.dismissed_pi_thr_value = None

        for section in (
            self.drone_section,
            self.pi_section,
            self.pc_section,
        ):
            section.setMinimumHeight(0)
            section.setSizePolicy(
                QSizePolicy.Expanding,
                QSizePolicy.Ignored,
            )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(5)
        layout.addWidget(self.drone_section, 3)
        layout.addWidget(self.pi_section, 2)
        layout.addWidget(self.pc_section, 1)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(250)
        self.refresh_timer.timeout.connect(self.refresh_from_telemetry)
        self.refresh_timer.start()

    def bind_telemetry_state(self, telemetry_state):
        self.telemetry_state = telemetry_state
        self.refresh_from_telemetry()

    def dismiss_drone_alert(self, alert_id):
        """Acknowledge one MANUAL alert and remove its motor indication."""
        state = self.telemetry_state
        if state is None:
            return

        with state.lock:
            removed_text = ""
            remaining = []
            for alert in state.drone_alerts:
                if alert.get("id") == alert_id:
                    removed_text = str(alert.get("text", ""))
                else:
                    remaining.append(alert)
            state.drone_alerts = remaining

            thrust_match = re.search(
                r"potential\s+thrust\s+loss\s*\(\s*(\d+)\s*\)",
                removed_text,
                re.IGNORECASE,
            )
            if thrust_match is not None:
                state.potential_thrust_loss_until.pop(
                    int(thrust_match.group(1)),
                    None,
                )

        self.refresh_from_telemetry()

    def dismiss_pi_alert(self, dismiss_id):
        """Acknowledge the current PI_THR flag value until it changes."""
        if (
            isinstance(dismiss_id, tuple)
            and len(dismiss_id) == 2
            and dismiss_id[0] == "PI_THR"
        ):
            self.dismissed_pi_thr_value = int(dismiss_id[1])
            self.refresh_from_telemetry()

    @staticmethod
    def normalize_drone_alert(alert):
        if isinstance(alert, dict):
            severity = alert.get("severity", "WARNING")
            text = alert.get("text", "Pixhawk warning")
            count = alert.get("count", 1)
        else:
            severity = getattr(alert, "severity", "WARNING")
            text = getattr(alert, "text", str(alert))
            count = getattr(alert, "count", 1)

        try:
            severity_number = int(severity)
        except (TypeError, ValueError):
            severity_number = None

        if severity_number is not None:
            if severity_number <= 3:
                severity = "ALERT"
            elif severity_number == 4:
                severity = "WARNING"
            elif severity_number == 5:
                severity = "NOTICE"
            else:
                return None
        else:
            severity = str(severity).upper()
            if severity in ("EMERGENCY", "CRITICAL", "ERROR"):
                severity = "ALERT"
            if severity not in ("WARNING", "ALERT", "NOTICE"):
                return None

        try:
            repeat_count = int(count)
        except (TypeError, ValueError):
            repeat_count = 1

        details = f"Repeated ×{repeat_count}" if repeat_count > 1 else ""
        return severity, str(text), details

    def refresh_from_telemetry(self):
        state = self.telemetry_state
        if state is None:
            return

        with state.lock:
            connected = bool(getattr(state, "connected", False))
            drone_source = list(getattr(state, "drone_alerts", []) or [])
            pi_load = getattr(state, "pi_load_percent", None)
            pi_temp = getattr(state, "pi_temp_c", None)
            pi_thr = getattr(state, "pi_thr", None)
            pc_battery = getattr(state, "pc_battery_percent", None)
            pc_plugged = getattr(state, "pc_power_plugged", None)
            ready_to_arm = getattr(state, "ready_to_arm", None)
            armed = bool(getattr(state, "armed", False))

        drone_alerts = []
        if connected:
            now = time.monotonic()
            for alert in drone_source:
                category = str(alert.get("category", "MANUAL")).upper()

                if category == "PREARM":
                    if ready_to_arm is True or armed:
                        continue
                    try:
                        age = now - float(alert["received_at"])
                    except (KeyError, TypeError, ValueError):
                        age = 36.0
                    if age >= 35.0:
                        continue

                normalized = self.normalize_drone_alert(alert)
                if normalized is not None:
                    dismiss_id = (
                        alert.get("id") if category == "MANUAL" else None
                    )
                    drone_alerts.append((*normalized, dismiss_id))

        pi_alerts = []
        if connected:
            if pi_load is not None and pi_load >= 95.0:
                pi_alerts.append(("ALERT", "PI CPU OVERLOAD", f"{pi_load:.1f}%"))
            elif pi_load is not None and pi_load >= 80.0:
                pi_alerts.append(("WARNING", "PI CPU LOAD HIGH", f"{pi_load:.1f}%"))

            if pi_temp is not None and pi_temp >= 80.0:
                pi_alerts.append(("ALERT", "PI OVERHEATING", f"{pi_temp:.1f} C"))
            elif pi_temp is not None and pi_temp >= 70.0:
                pi_alerts.append(("WARNING", "PI TEMPERATURE HIGH", f"{pi_temp:.1f} C"))

            if pi_thr is not None and pi_thr >= 0:
                pi_thr_value = int(pi_thr)
                current_flags = pi_thr_value & 0xF
                historical_flags = pi_thr_value & 0xF0000
                has_thr_alert = bool(current_flags or historical_flags)

                if not has_thr_alert:
                    self.dismissed_pi_thr_value = None

                show_thr_alert = (
                    has_thr_alert
                    and self.dismissed_pi_thr_value != pi_thr_value
                )

                if show_thr_alert and current_flags & 0x4:
                    pi_alerts.append((
                        "ALERT",
                        "PI THROTTLING",
                        hex(pi_thr_value),
                        ("PI_THR", pi_thr_value),
                    ))
                elif show_thr_alert and current_flags:
                    pi_alerts.append((
                        "WARNING",
                        "PI POWER/THERMAL LIMIT",
                        hex(pi_thr_value),
                        ("PI_THR", pi_thr_value),
                    ))
                elif show_thr_alert and historical_flags:
                    pi_alerts.append((
                        "WARNING",
                        "PI THROTTLING OCCURRED",
                        hex(pi_thr_value),
                        ("PI_THR", pi_thr_value),
                    ))

        pc_alerts = []
        if pc_battery is not None and pc_plugged is not True:
            if pc_battery < 10.0:
                pc_alerts.append(("ALERT", "PC BATTERY CRITICAL", f"{pc_battery:.0f}%"))
            elif pc_battery < 15.0:
                pc_alerts.append(("WARNING", "PC BATTERY LOW", f"{pc_battery:.0f}%"))

        self.drone_section.set_alerts(drone_alerts)
        self.pi_section.set_alerts(pi_alerts)
        self.pc_section.set_alerts(pc_alerts)