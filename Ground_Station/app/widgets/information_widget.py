import math
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import QWidget

from app.widgets.flight_status import FlightStatusWidget


class InformationWidget(QWidget):

    def __init__(self, parent=None, telemetry_state=None):
        super().__init__(parent)

        self.telemetry_state = telemetry_state

        # =====================================================
        # DATA
        # Values remain unavailable until real telemetry is received.
        # =====================================================

        # Data order:
        # [M1, M2, M3, M4]
        self.motor_values = [
            None,
            None,
            None,
            None,
        ]

        # Drone
        self.battery_voltage = None
        self.output_current = None
        self.thrust_loss_motors = set()

        # R-Pi
        self.pi_thr = None
        self.pi_temp = None
        self.pi_load = None

        # PC
        self.pc_battery = None
        self.pc_power_plugged = None
        self.panel_test_alert_mode = 0

        # Independent flight-stage/checklist and warning panel displayed in
        # the right half.  paintEvent() deliberately reserves this area.
        self.flight_status_widget = FlightStatusWidget(self)

        if telemetry_state is not None:
            self.flight_status_widget.bind_telemetry_state(telemetry_state)

        # Qt widgets must be updated on the GUI thread. The timer copies a
        # locked snapshot from the telemetry worker's shared state.
        self.telemetry_timer = QTimer(self)
        self.telemetry_timer.setInterval(200)
        self.telemetry_timer.timeout.connect(self.refresh_from_telemetry)
        self.telemetry_timer.start()

        # =====================================================
        # PANEL SIZE
        # Designed around 400 : 500 minimum
        # =====================================================

        self.setMinimumSize(
            400,
            500,
        )


    # =========================================================
    # DATA UPDATE
    # =========================================================

    def set_telemetry_state(self, telemetry_state):
        """Attach the shared state used by telemetry_worker()."""
        self.telemetry_state = telemetry_state
        self.flight_status_widget.bind_telemetry_state(telemetry_state)
        self.refresh_from_telemetry()


    def bind_telemetry_state(self, telemetry_state):
        """Compatibility entry point used by MainWindow/InstrumentPanel."""
        self.set_telemetry_state(telemetry_state)


    def refresh_from_telemetry(self):
        """Copy all information-panel values from the shared telemetry state."""
        state = self.telemetry_state

        if state is None:
            return

        with state.lock:
            telemetry_connected = bool(getattr(state, "connected", False))
            motor_values = list(getattr(state, "motor_percentages", []))
            battery_voltage = getattr(state, "battery_voltage_v", None)
            output_current = getattr(state, "total_current_a", None)
            pi_thr = getattr(state, "pi_thr", None)
            pi_temp = getattr(state, "pi_temp_c", None)
            pi_load = getattr(state, "pi_load_percent", None)
            pc_battery = getattr(state, "pc_battery_percent", None)
            pc_power_plugged = getattr(state, "pc_power_plugged", None)
            panel_test_alert_mode = int(
                getattr(state, "panel_test_alert_mode", 0)
            )
            thrust_loss_until = dict(
                getattr(state, "potential_thrust_loss_until", {}) or {}
            )

        if telemetry_connected:
            self.motor_values = [
                (
                    None
                    if index >= len(motor_values)
                    or motor_values[index] is None
                    else float(motor_values[index])
                )
                for index in range(4)
            ]
            self.battery_voltage = (
                None
                if battery_voltage is None
                else float(battery_voltage)
            )
            self.output_current = (
                None
                if output_current is None
                else float(output_current)
            )
            self.pi_thr = None if pi_thr is None else int(pi_thr)
            self.pi_temp = None if pi_temp is None else float(pi_temp)
            self.pi_load = None if pi_load is None else float(pi_load)
            now = time.monotonic()
            self.thrust_loss_motors = {
                int(motor_number)
                for motor_number, expiry_time in thrust_loss_until.items()
                if float(expiry_time) >= now
            }
        else:
            # Never leave stale aircraft/Pi values on screen after heartbeat
            # loss. PC power remains local and continues updating separately.
            self.motor_values = [None, None, None, None]
            self.battery_voltage = None
            self.output_current = None
            self.pi_thr = None
            self.pi_temp = None
            self.pi_load = None
            self.thrust_loss_motors = set()

        self.pc_battery = (
            None if pc_battery is None else float(pc_battery)
        )
        self.pc_power_plugged = pc_power_plugged
        self.panel_test_alert_mode = max(
            0,
            min(2, panel_test_alert_mode),
        )

        self.update()

    def set_drone_data(
        self,
        motor_values,
        battery_voltage,
        output_current,
    ):

        self.motor_values = list(
            motor_values
        )

        self.battery_voltage = (
            battery_voltage
        )

        self.output_current = (
            output_current
        )

        self.update()


    def set_pi_data(
        self,
        pi_thr,
        pi_temp,
        pi_load,
    ):

        self.pi_thr = None if pi_thr is None else int(pi_thr)
        self.pi_temp = None if pi_temp is None else float(pi_temp)
        self.pi_load = None if pi_load is None else float(pi_load)

        self.update()


    def set_pc_battery(
        self,
        battery_percent,
    ):

        self.pc_battery = (
            None
            if battery_percent is None
            else float(battery_percent)
        )

        self.update()


    # =========================================================
    # MOTOR GAUGE
    # =========================================================

    def draw_motor_gauge(
        self,
        painter,
        center_x,
        center_y,
        radius,
        value,
        label,
        warning=False,
    ):

        value_available = value is not None

        numeric_value = max(
            0.0,
            min(
                100.0,
                0.0 if value is None else float(value),
            ),
        )

        # Feed the keyboard test into the same motor-alert severity path used
        # by a real Potential Thrust Loss warning.  Do not recolor the panel.
        alert_level = 1 if warning else 0
        alert_level = max(alert_level, self.panel_test_alert_mode)
        warning = alert_level > 0
        warning_color = (
            QColor(210, 25, 35)
            if alert_level >= 2
            else QColor(220, 170, 0)
        )

        label_color = warning_color if warning else QColor(20, 20, 20)
        background_arc_color = (
            warning_color if warning else QColor(215, 215, 215)
        )
        active_arc_color = (
            warning_color if warning else QColor(20, 20, 20)
        )
        tick_color = warning_color if warning else QColor(70, 70, 70)
        value_color = warning_color if warning else QColor(10, 10, 10)

        # =====================================================
        # MOTOR LABEL
        # =====================================================

        painter.setPen(
            label_color
        )

        painter.setFont(
            QFont(
                "Arial",
                8,
                QFont.Bold,
            )
        )

        painter.drawText(
            center_x - radius,
            center_y - radius - 18,
            radius * 2,
            16,
            Qt.AlignCenter,
            label,
        )


        # =====================================================
        # BACKGROUND ARC
        # =====================================================

        diameter = (
            radius * 2
        )

        rect_x = (
            center_x - radius
        )

        rect_y = (
            center_y - radius
        )

        start_angle = (
            225 * 16
        )

        total_angle = (
            -270 * 16
        )

        painter.setPen(
            QPen(
                background_arc_color,
                4,
            )
        )

        painter.drawArc(
            rect_x,
            rect_y,
            diameter,
            diameter,
            start_angle,
            total_angle,
        )


        # =====================================================
        # ACTIVE ARC
        # =====================================================

        active_angle = int(
            total_angle
            * numeric_value
            / 100.0
        )

        painter.setPen(
            QPen(
                active_arc_color,
                4,
            )
        )

        painter.drawArc(
            rect_x,
            rect_y,
            diameter,
            diameter,
            start_angle,
            active_angle,
        )


        # =====================================================
        # TICKS
        # =====================================================

        painter.setPen(
            QPen(
                tick_color,
                1,
            )
        )

        for i in range(11):

            percentage = (
                i / 10.0
            )

            angle_deg = (
                225
                - percentage * 270
            )

            angle = math.radians(
                angle_deg
            )

            outer_r = (
                radius - 6
            )

            if i in (
                0,
                5,
                10,
            ):
                inner_r = (
                    radius - 14
                )
            else:
                inner_r = (
                    radius - 10
                )

            x1 = (
                center_x
                + math.cos(angle)
                * outer_r
            )

            y1 = (
                center_y
                - math.sin(angle)
                * outer_r
            )

            x2 = (
                center_x
                + math.cos(angle)
                * inner_r
            )

            y2 = (
                center_y
                - math.sin(angle)
                * inner_r
            )

            painter.drawLine(
                int(x1),
                int(y1),
                int(x2),
                int(y2),
            )


        # =====================================================
        # VALUE
        # =====================================================

        painter.setPen(
            value_color
        )

        painter.setFont(
            QFont(
                "Arial",
                12,
                QFont.Bold,
            )
        )

        painter.drawText(
            center_x - radius,
            center_y - 9,
            radius * 2,
            22,
            Qt.AlignCenter,
            f"{numeric_value:.0f}" if value_available else "--",
        )

        painter.setFont(
            QFont(
                "Arial",
                7,
            )
        )

        painter.drawText(
            center_x - radius,
            center_y + 12,
            radius * 2,
            15,
            Qt.AlignCenter,
            "%" if value_available else "",
        )


    # =========================================================
    # PAINT
    # =========================================================

    def resizeEvent(self, event):
        """Keep FlightStatusWidget fitted to the reserved right half."""
        super().resizeEvent(event)

        right_x = self.width() // 2
        self.flight_status_widget.setGeometry(
            right_x + 1,
            0,
            max(0, self.width() - right_x - 1),
            self.height(),
        )

    def paintEvent(
        self,
        event,
    ):

        painter = QPainter(
            self
        )

        painter.setRenderHint(
            QPainter.Antialiasing,
            True,
        )

        width = (
            self.width()
        )

        height = (
            self.height()
        )

        # =====================================================
        # BACKGROUND
        # =====================================================

        painter.fillRect(
            self.rect(),
            QColor(
                255,
                255,
                255,
            ),
        )

        # =====================================================
        # SPLIT PANEL INTO TWO HALVES
        # =====================================================

        left_width = int(
            width * 0.50
        )

        painter.setPen(
            QPen(
                QColor(
                    215,
                    215,
                    215,
                ),
                1,
            )
        )

        painter.drawLine(
            left_width,
            0,
            left_width,
            height,
        )

        # Right half intentionally left empty.

        margin = 14

        test_alert_level = self.panel_test_alert_mode

        # Test mode must not recolor the whole panel. General headings,
        # battery voltage/current, dividers, and ordinary text keep their
        # normal color; dedicated alert indicators choose their own color.
        panel_content_color = QColor(20, 20, 20)


        # =====================================================
        # DRONE SECTION
        # =====================================================

        painter.setPen(
            panel_content_color
        )

        painter.setFont(
            QFont(
                "Arial",
                10,
                QFont.Bold,
            )
        )

        painter.drawText(
            margin,
            12,
            left_width - margin * 2,
            22,
            Qt.AlignLeft
            | Qt.AlignVCenter,
            "DRONE",
        )


        # =====================================================
        # MOTOR POSITIONS
        #
        # M3             M1
        #
        #      BAT/CUR
        #
        # M2             M4
        #
        # Clockwise:
        # M1 -> M4 -> M2 -> M3
        # =====================================================

        gauge_radius = 30

        motor_left_x = int(
            left_width * 0.22
        )

        motor_right_x = int(
            left_width * 0.78
        )

        motor_top_y = 90
        motor_bottom_y = 205


        # M3
        self.draw_motor_gauge(
            painter,
            motor_left_x,
            motor_top_y,
            gauge_radius,
            self.motor_values[2],
            "M3",
            warning=3 in self.thrust_loss_motors,
        )


        # M1
        self.draw_motor_gauge(
            painter,
            motor_right_x,
            motor_top_y,
            gauge_radius,
            self.motor_values[0],
            "M1",
            warning=1 in self.thrust_loss_motors,
        )


        # M2
        self.draw_motor_gauge(
            painter,
            motor_left_x,
            motor_bottom_y,
            gauge_radius,
            self.motor_values[1],
            "M2",
            warning=2 in self.thrust_loss_motors,
        )


        # M4
        self.draw_motor_gauge(
            painter,
            motor_right_x,
            motor_bottom_y,
            gauge_radius,
            self.motor_values[3],
            "M4",
            warning=4 in self.thrust_loss_motors,
        )


        # =====================================================
        # DRONE CENTER
        # =====================================================

        center_x = (
            left_width // 2
        )


        # Battery voltage label
        painter.setPen(
            panel_content_color
        )

        painter.setFont(
            QFont(
                "Arial",
                6,
            )
        )

        painter.drawText(
            center_x - 55,
            85,
            110,
            16,
            Qt.AlignCenter,
            "BATTERY VOLTAGE",
        )


        painter.setFont(
            QFont(
                "Arial",
                11,
                QFont.Bold,
            )
        )

        painter.drawText(
            center_x - 55,
            102,
            110,
            22,
            Qt.AlignCenter,
            (
                f"{self.battery_voltage:.1f} V"
                if self.battery_voltage is not None
                else "--"
            ),
        )


        # Center separator
        painter.setPen(
            QPen(
                QColor(
                    210,
                    210,
                    210,
                ),
                1,
            )
        )

        painter.drawLine(
            center_x - 32,
            137,
            center_x + 32,
            137,
        )


        # Output current
        painter.setPen(
            panel_content_color
        )

        painter.setFont(
            QFont(
                "Arial",
                6,
            )
        )

        painter.drawText(
            center_x - 55,
            145,
            110,
            16,
            Qt.AlignCenter,
            "OUTPUT CURRENT",
        )


        painter.setFont(
            QFont(
                "Arial",
                11,
                QFont.Bold,
            )
        )

        painter.drawText(
            center_x - 55,
            162,
            110,
            22,
            Qt.AlignCenter,
            (
                f"{self.output_current:.1f} A"
                if self.output_current is not None
                else "--"
            ),
        )


        # =====================================================
        # DRONE / R-PI DIVIDER
        # =====================================================

        drone_bottom = 260

        painter.setPen(
            QPen(
                QColor(
                    215,
                    215,
                    215,
                ),
                1,
            )
        )

        painter.drawLine(
            margin,
            drone_bottom,
            left_width - margin,
            drone_bottom,
        )


        # =====================================================
        # R-PI
        # =====================================================

        pi_top = 272

        painter.setPen(
            panel_content_color
        )

        painter.setFont(
            QFont(
                "Arial",
                9,
                QFont.Bold,
            )
        )

        painter.drawText(
            margin,
            pi_top,
            left_width - margin * 2,
            20,
            Qt.AlignLeft
            | Qt.AlignVCenter,
            "R-PI",
        )


        # =====================================================
        # PI DATA
        # =====================================================

        column_width = (
            left_width
            - margin * 2
        ) / 3.0

        normal_color = panel_content_color
        warning_color = QColor(220, 170, 0)
        critical_color = QColor(210, 25, 35)

        thr_alert_level = 0
        if self.pi_thr is not None:
            thr_value = int(self.pi_thr)
            current_flags = thr_value & 0xF
            historical_flags = thr_value & 0xF0000
            if current_flags & 0x4:
                thr_alert_level = 2
            elif current_flags or historical_flags:
                thr_alert_level = 1
        pi_thr_color = (
            critical_color if thr_alert_level >= 2
            else warning_color if thr_alert_level == 1
            else normal_color
        )

        temp_alert_level = 0
        if self.pi_temp is not None and self.pi_temp >= 80.0:
            temp_alert_level = 2
        elif self.pi_temp is not None and self.pi_temp >= 70.0:
            temp_alert_level = 1
        temp_alert_level = max(temp_alert_level, test_alert_level)
        pi_temp_color = (
            critical_color if temp_alert_level >= 2
            else warning_color if temp_alert_level == 1
            else normal_color
        )

        load_alert_level = 0
        if self.pi_load is not None and self.pi_load >= 95.0:
            load_alert_level = 2
        elif self.pi_load is not None and self.pi_load >= 80.0:
            load_alert_level = 1
        load_alert_level = max(load_alert_level, test_alert_level)
        pi_load_color = (
            critical_color if load_alert_level >= 2
            else warning_color if load_alert_level == 1
            else normal_color
        )

        pi_data = [
            (
                "PI_THR",
                (
                    hex(self.pi_thr)
                    if self.pi_thr is not None and self.pi_thr >= 0
                    else "--"
                ),
                pi_thr_color,
            ),
            (
                "PI_TEMP",
                (
                    f"{self.pi_temp:.1f} C"
                    if self.pi_temp is not None
                    else "--"
                ),
                pi_temp_color,
            ),
            (
                "PI_LOAD",
                (
                    f"{self.pi_load:.0f} %"
                    if self.pi_load is not None
                    else "--"
                ),
                pi_load_color,
            ),
        ]

        for i, (
            label,
            value,
            value_color,
        ) in enumerate(
            pi_data
        ):

            x = int(
                margin
                + i * column_width
            )

            painter.setPen(value_color)

            painter.setFont(
                QFont(
                    "Arial",
                    6,
                )
            )

            painter.drawText(
                x,
                pi_top + 34,
                int(column_width),
                15,
                Qt.AlignCenter,
                label,
            )


            painter.setFont(
                QFont(
                    "Arial",
                    10,
                    QFont.Bold,
                )
            )

            painter.drawText(
                x,
                pi_top + 52,
                int(column_width),
                22,
                Qt.AlignCenter,
                value,
            )


        # =====================================================
        # R-PI / PC DIVIDER
        # =====================================================

        pc_divider = 365

        painter.setPen(
            QPen(
                QColor(
                    215,
                    215,
                    215,
                ),
                1,
            )
        )

        painter.drawLine(
            margin,
            pc_divider,
            left_width - margin,
            pc_divider,
        )


        # =====================================================
        # PC
        # =====================================================

        pc_top = 378

        painter.setPen(
            panel_content_color
        )

        painter.setFont(
            QFont(
                "Arial",
                9,
                QFont.Bold,
            )
        )

        painter.drawText(
            margin,
            pc_top,
            left_width - margin * 2,
            20,
            Qt.AlignLeft
            | Qt.AlignVCenter,
            "PC",
        )


        # =====================================================
        # PC BATTERY
        # =====================================================

        pc_alert_level = 0
        if self.pc_battery is not None and self.pc_battery < 10.0:
            pc_alert_level = 2
        elif self.pc_battery is not None and self.pc_battery < 15.0:
            pc_alert_level = 1
        pc_alert_level = max(pc_alert_level, test_alert_level)
        pc_battery_color = (
            QColor(210, 25, 35) if pc_alert_level >= 2
            else QColor(220, 170, 0) if pc_alert_level == 1
            else QColor(20, 20, 20)
        )

        painter.setPen(pc_battery_color)

        painter.setFont(
            QFont(
                "Arial",
                6,
            )
        )

        painter.drawText(
            margin,
            pc_top + 30,
            125,
            16,
            Qt.AlignLeft
            | Qt.AlignVCenter,
            (
                "AC POWER CONNECTED"
                if self.pc_power_plugged is True
                else "BATTERY REMAINING"
            ),
        )


        painter.setFont(
            QFont(
                "Arial",
                10,
                QFont.Bold,
            )
        )

        painter.drawText(
            left_width - 80,
            pc_top + 28,
            60,
            18,
            Qt.AlignRight
            | Qt.AlignVCenter,
            (
                f"{self.pc_battery:.0f} %"
                if self.pc_battery is not None
                else "--"
            ),
        )


        # =====================================================
        # PC BATTERY BAR
        # =====================================================

        bar_x = margin
        bar_y = pc_top + 58

        bar_width = (
            left_width
            - margin * 2
        )

        bar_height = 6

        painter.setPen(QPen(pc_battery_color, 1))

        painter.setBrush(
            Qt.NoBrush
        )

        painter.drawRoundedRect(
            bar_x,
            bar_y,
            bar_width,
            bar_height,
            3,
            3,
        )


        fill_width = int(
            bar_width
            * max(
                0.0,
                min(
                    100.0,
                    0.0 if self.pc_battery is None else self.pc_battery,
                ),
            )
            / 100.0
        )


        painter.setPen(
            Qt.NoPen
        )

        painter.setBrush(
            pc_battery_color
        )

        painter.drawRoundedRect(
            bar_x,
            bar_y,
            fill_width,
            bar_height,
            3,
            3,
        )

        painter.end()


# =============================================================
# STANDALONE TEST
# =============================================================

if __name__ == "__main__":

    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication(
        sys.argv
    )

    window = InformationWidget()

    window.resize(
        800,
        500,
    )

    window.show()

    sys.exit(
        app.exec()
    )