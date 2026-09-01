import math

from PySide6.QtCore import (
    Qt,
    QPointF,
    QTimer,
)

from PySide6.QtGui import (
    QPainter,
    QPainterPath,
    QPen,
    QBrush,
    QColor,
    QFont,
)

from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
)


# ============================================================
# Common colors
# ============================================================

PANEL_BACKGROUND = QColor(65, 65, 65)

DIAL_BACKGROUND = QColor(18, 18, 18)

DIAL_BORDER = QColor(25, 25, 25)

MARKING_COLOR = QColor(245, 245, 245)

POINTER_COLOR = QColor(220, 25, 25)

SKY_COLOR = QColor(70, 135, 190)

GROUND_COLOR = QColor(125, 82, 45)


# ============================================================
# 1. ATTITUDE INDICATOR
# ============================================================

class AttitudeIndicator(QWidget):

    def __init__(self):
        super().__init__()

        self.pitch = 0.0
        self.roll = 0.0

        self.setMinimumSize(
            120,
            120,
        )


    def set_attitude(
        self,
        pitch,
        roll,
    ):

        self.pitch = float(pitch)
        self.roll = float(roll)

        self.update()


    def paintEvent(self, event):

        painter = QPainter(self)

        painter.setRenderHint(
            QPainter.Antialiasing
        )

        painter.fillRect(
            self.rect(),
            PANEL_BACKGROUND
        )


        w = self.width()
        h = self.height()

        size = min(
            w,
            h,
        )

        cx = w / 2
        cy = h / 2


        # ====================================================
        # Instrument geometry
        # ====================================================

        outer_radius = (
            size * 0.44
        )

        ball_radius = (
            outer_radius * 0.76
        )


        # ====================================================
        # Black outer instrument
        # ====================================================

        painter.setBrush(
            DIAL_BACKGROUND
        )

        painter.setPen(
            QPen(
                DIAL_BORDER,
                3,
            )
        )

        painter.drawEllipse(
            QPointF(
                cx,
                cy,
            ),
            outer_radius,
            outer_radius,
        )


        # ====================================================
        # Attitude ball clipping
        # ====================================================

        ball_path = QPainterPath()

        ball_path.addEllipse(
            QPointF(
                cx,
                cy,
            ),
            ball_radius,
            ball_radius,
        )


        painter.save()

        painter.setClipPath(
            ball_path
        )

        painter.translate(
            cx,
            cy,
        )


        # ====================================================
        # Roll
        #
        # Horizon rotates opposite aircraft roll.
        # ====================================================

        painter.rotate(
            -self.roll
        )


        # ====================================================
        # Pitch
        # ====================================================

        pixels_per_degree = (
            ball_radius / 15.0
        )

        pitch_offset = (
            self.pitch
            * pixels_per_degree
        )


        # ====================================================
        # Sky
        # ====================================================

        painter.fillRect(
            int(-ball_radius * 4),
            int(-ball_radius * 4 + pitch_offset),
            int(ball_radius * 8),
            int(ball_radius * 4),
            SKY_COLOR,
        )


        # ====================================================
        # Ground
        # ====================================================

        painter.fillRect(
            int(-ball_radius * 4),
            int(pitch_offset),
            int(ball_radius * 8),
            int(ball_radius * 4),
            GROUND_COLOR,
        )


        # ====================================================
        # Horizon
        # ====================================================

        painter.setPen(
            QPen(
                MARKING_COLOR,
                2,
            )
        )

        painter.drawLine(
            QPointF(
                -ball_radius * 2,
                pitch_offset,
            ),
            QPointF(
                ball_radius * 2,
                pitch_offset,
            ),
        )


        # ====================================================
        # Pitch ladder
        #
        # Thin mark every 2.5 degrees
        # Long mark every 5 degrees
        #
        # Labels every 5 degrees
        # ====================================================

        pitch_mark = -60.0

        while pitch_mark <= 60.0:

            if abs(pitch_mark) < 0.001:

                pitch_mark += 2.5
                continue


            y = (
                pitch_offset
                - pitch_mark
                * pixels_per_degree
            )


            # Outside visible attitude ball
            if abs(y) > ball_radius:

                pitch_mark += 2.5
                continue


            is_five_degree = (
                abs(
                    pitch_mark % 5.0
                )
                < 0.001
            )


            if is_five_degree:

                line_length = (
                    ball_radius * 0.34
                )

                line_width = 2

            else:

                line_length = (
                    ball_radius * 0.20
                )

                line_width = 1


            painter.setPen(
                QPen(
                    MARKING_COLOR,
                    line_width,
                )
            )


            painter.drawLine(
                QPointF(
                    -line_length,
                    y,
                ),
                QPointF(
                    line_length,
                    y,
                ),
            )


            # =================================================
            # Pitch numbers
            # =================================================

            if is_five_degree:

                painter.setFont(
                    QFont(
                        "Arial",
                        max(
                            5,
                            int(
                                size
                                * 0.020
                            ),
                        ),
                    )
                )


                pitch_text = (
                    f"{int(pitch_mark)}°"
                )


                number_width = (
                    ball_radius * 0.24
                )

                number_height = 14

                number_gap = (
                    ball_radius * 0.035
                )


                # Left
                painter.drawText(
                    int(
                        -line_length
                        - number_gap
                        - number_width
                    ),
                    int(
                        y
                        - number_height / 2
                    ),
                    int(number_width),
                    number_height,
                    Qt.AlignRight
                    | Qt.AlignVCenter,
                    pitch_text,
                )


                # Right
                painter.drawText(
                    int(
                        line_length
                        + number_gap
                    ),
                    int(
                        y
                        - number_height / 2
                    ),
                    int(number_width),
                    number_height,
                    Qt.AlignLeft
                    | Qt.AlignVCenter,
                    pitch_text,
                )


            pitch_mark += 2.5


        painter.restore()


        # ====================================================
        # Attitude ball border
        # ====================================================

        painter.setBrush(
            Qt.NoBrush
        )

        painter.setPen(
            QPen(
                DIAL_BORDER,
                max(
                    2,
                    int(
                        size
                        * 0.012
                    ),
                ),
            )
        )


        painter.drawEllipse(
            QPointF(
                cx,
                cy,
            ),
            ball_radius,
            ball_radius,
        )


        # ====================================================
        # Roll scale
        #
        # -60 ... +60 degrees
        # ====================================================

        scale_outer_radius = (
            outer_radius * 0.91
        )


        for roll_mark in range(
            -60,
            61,
            5,
        ):

            angle_deg = (
                -90
                + roll_mark
            )

            angle = math.radians(
                angle_deg
            )


            if roll_mark % 30 == 0:

                tick_length = (
                    outer_radius * 0.16
                )

                line_width = 2

            elif roll_mark % 10 == 0:

                tick_length = (
                    outer_radius * 0.11
                )

                line_width = 2

            else:

                tick_length = (
                    outer_radius * 0.065
                )

                line_width = 1


            outer = (
                scale_outer_radius
            )

            inner = (
                outer
                - tick_length
            )


            x1 = (
                cx
                + outer
                * math.cos(angle)
            )

            y1 = (
                cy
                + outer
                * math.sin(angle)
            )


            x2 = (
                cx
                + inner
                * math.cos(angle)
            )

            y2 = (
                cy
                + inner
                * math.sin(angle)
            )


            painter.setPen(
                QPen(
                    MARKING_COLOR,
                    line_width,
                )
            )


            painter.drawLine(
                QPointF(
                    x1,
                    y1,
                ),
                QPointF(
                    x2,
                    y2,
                ),
            )


        # ====================================================
        # Roll pointer
        # ====================================================

        displayed_roll = max(
            -60.0,
            min(
                60.0,
                self.roll,
            ),
        )


        pointer_angle = math.radians(
            -90
            + displayed_roll
        )


        pointer_radius = (
            outer_radius * 0.99
        )


        px = (
            cx
            + pointer_radius
            * math.cos(pointer_angle)
        )

        py = (
            cy
            + pointer_radius
            * math.sin(pointer_angle)
        )


        dx = cx - px
        dy = cy - py


        vector_length = math.hypot(
            dx,
            dy,
        )


        if vector_length > 0:

            dx /= vector_length
            dy /= vector_length


        sx = -dy
        sy = dx


        triangle_length = (
            outer_radius * 0.12
        )

        triangle_width = (
            outer_radius * 0.055
        )


        tip = QPointF(
            px
            + dx
            * triangle_length,

            py
            + dy
            * triangle_length,
        )


        left = QPointF(
            px
            + sx
            * triangle_width,

            py
            + sy
            * triangle_width,
        )


        right = QPointF(
            px
            - sx
            * triangle_width,

            py
            - sy
            * triangle_width,
        )


        triangle = QPainterPath()

        triangle.moveTo(
            tip
        )

        triangle.lineTo(
            left
        )

        triangle.lineTo(
            right
        )

        triangle.closeSubpath()


        painter.setPen(
            Qt.NoPen
        )

        painter.setBrush(
            POINTER_COLOR
        )

        painter.drawPath(
            triangle
        )


        # ====================================================
        # Fixed aircraft reference
        #
        #       --- ● ---
        # ====================================================

        painter.setPen(
            QPen(
                POINTER_COLOR,
                max(
                    3,
                    int(
                        size
                        * 0.015
                    ),
                ),
            )
        )


        wing_length = (
            ball_radius * 0.34
        )

        center_gap = (
            ball_radius * 0.09
        )


        painter.drawLine(
            QPointF(
                cx - wing_length,
                cy,
            ),
            QPointF(
                cx - center_gap,
                cy,
            ),
        )


        painter.drawLine(
            QPointF(
                cx + center_gap,
                cy,
            ),
            QPointF(
                cx + wing_length,
                cy,
            ),
        )


        painter.setBrush(
            POINTER_COLOR
        )

        painter.setPen(
            Qt.NoPen
        )


        dot_radius = max(
            3,
            size * 0.020,
        )


        painter.drawEllipse(
            QPointF(
                cx,
                cy,
            ),
            dot_radius,
            dot_radius,
        )


# ============================================================
# 2. SPEED INDICATOR
# ============================================================

class SpeedIndicator(QWidget):

    def __init__(self):
        super().__init__()

        self.speed = 0.0

        self.setMinimumSize(
            120,
            120,
        )


    def set_speed(
        self,
        speed,
    ):

        self.speed = max(
            0.0,
            min(
                60.0,
                float(speed),
            ),
        )

        self.update()


    def paintEvent(self, event):

        painter = QPainter(self)

        painter.setRenderHint(
            QPainter.Antialiasing
        )


        painter.fillRect(
            self.rect(),
            PANEL_BACKGROUND
        )


        w = self.width()
        h = self.height()

        size = min(
            w,
            h,
        )

        cx = w / 2
        cy = h / 2

        radius = (
            size * 0.43
        )


        # ====================================================
        # Black dial
        # ====================================================

        painter.setBrush(
            QBrush(
                DIAL_BACKGROUND
            )
        )

        painter.setPen(
            QPen(
                DIAL_BORDER,
                3,
            )
        )

        painter.drawEllipse(
            QPointF(
                cx,
                cy,
            ),
            radius,
            radius,
        )


        # ====================================================
        # Speed scale
        #
        # 0 - 60 m/s
        # ====================================================

        start_angle = 135.0
        sweep_angle = 270.0


        painter.setFont(
            QFont(
                "Arial",
                max(
                    7,
                    int(
                        size
                        * 0.045
                    ),
                ),
            )
        )


        for value in range(
            0,
            61,
            2,
        ):

            ratio = (
                value / 60.0
            )


            angle_deg = (
                start_angle
                + ratio
                * sweep_angle
            )


            angle = math.radians(
                angle_deg
            )


            major = (
                value % 10 == 0
            )


            outer_radius = (
                radius * 0.92
            )


            if major:

                inner_radius = (
                    radius * 0.75
                )

            else:

                inner_radius = (
                    radius * 0.83
                )


            x1 = (
                cx
                + outer_radius
                * math.cos(angle)
            )

            y1 = (
                cy
                + outer_radius
                * math.sin(angle)
            )


            x2 = (
                cx
                + inner_radius
                * math.cos(angle)
            )

            y2 = (
                cy
                + inner_radius
                * math.sin(angle)
            )


            painter.setPen(
                QPen(
                    MARKING_COLOR,
                    2
                    if major
                    else 1,
                )
            )


            painter.drawLine(
                QPointF(
                    x1,
                    y1,
                ),
                QPointF(
                    x2,
                    y2,
                ),
            )


            if major:

                text_radius = (
                    radius * 0.61
                )


                tx = (
                    cx
                    + text_radius
                    * math.cos(angle)
                )

                ty = (
                    cy
                    + text_radius
                    * math.sin(angle)
                )


                painter.drawText(
                    int(tx - 16),
                    int(ty - 10),
                    32,
                    20,
                    Qt.AlignCenter,
                    str(value),
                )


        # ====================================================
        # SPD labels
        # ====================================================

        painter.setPen(
            MARKING_COLOR
        )


        painter.drawText(
            int(
                cx
                - radius * 0.4
            ),
            int(
                cy
                + radius * 0.28
            ),
            int(
                radius * 0.8
            ),
            20,
            Qt.AlignCenter,
            "SPD",
        )


        painter.drawText(
            int(
                cx
                - radius * 0.4
            ),
            int(
                cy
                + radius * 0.45
            ),
            int(
                radius * 0.8
            ),
            20,
            Qt.AlignCenter,
            "m/s",
        )


        # ====================================================
        # Speed needle
        # ====================================================

        ratio = (
            self.speed / 60.0
        )


        angle = math.radians(
            start_angle
            + ratio
            * sweep_angle
        )


        needle_length = (
            radius * 0.70
        )


        nx = (
            cx
            + needle_length
            * math.cos(angle)
        )

        ny = (
            cy
            + needle_length
            * math.sin(angle)
        )


        painter.setPen(
            QPen(
                POINTER_COLOR,
                max(
                    2,
                    int(
                        size
                        * 0.015
                    ),
                ),
            )
        )


        painter.drawLine(
            QPointF(
                cx,
                cy,
            ),
            QPointF(
                nx,
                ny,
            ),
        )


        painter.setBrush(
            POINTER_COLOR
        )

        painter.setPen(
            Qt.NoPen
        )


        painter.drawEllipse(
            QPointF(
                cx,
                cy,
            ),
            max(
                3,
                size * 0.025,
            ),
            max(
                3,
                size * 0.025,
            ),
        )


# ============================================================
# 3. ALTITUDE + VSI INDICATOR
# ============================================================

class AltitudeVsiIndicator(QWidget):

    def __init__(self):
        super().__init__()

        self.altitude = 0.0
        self.vertical_speed = 0.0

        self.setMinimumSize(
            120,
            120,
        )


    def set_altitude(
        self,
        altitude,
    ):

        self.altitude = max(
            0.0,
            float(altitude),
        )

        self.update()


    def set_vertical_speed(
        self,
        vertical_speed,
    ):

        # Current visual scale:
        # -6 ... +6 m/s
        self.vertical_speed = max(
            -6.0,
            min(
                6.0,
                float(vertical_speed),
            ),
        )

        self.update()


    def paintEvent(self, event):

        painter = QPainter(self)

        painter.setRenderHint(
            QPainter.Antialiasing
        )

        painter.fillRect(
            self.rect(),
            PANEL_BACKGROUND
        )


        w = self.width()
        h = self.height()

        size = min(
            w,
            h,
        )

        cx = w / 2
        cy = h / 2

        radius = (
            size * 0.43
        )


        # ====================================================
        # Black dial
        # ====================================================

        painter.setBrush(
            DIAL_BACKGROUND
        )

        painter.setPen(
            QPen(
                DIAL_BORDER,
                3,
            )
        )


        painter.drawEllipse(
            QPointF(
                cx,
                cy,
            ),
            radius,
            radius,
        )


        # ====================================================
        # Outer altitude scale
        #
        # 0 - 9
        # ====================================================

        painter.setFont(
            QFont(
                "Arial",
                max(
                    7,
                    int(
                        size
                        * 0.043
                    ),
                ),
            )
        )


        for value in range(10):

            angle_deg = (
                -90
                + value * 36
            )

            angle = math.radians(
                angle_deg
            )


            outer_radius = (
                radius * 0.94
            )

            inner_radius = (
                radius * 0.80
            )


            x1 = (
                cx
                + outer_radius
                * math.cos(angle)
            )

            y1 = (
                cy
                + outer_radius
                * math.sin(angle)
            )


            x2 = (
                cx
                + inner_radius
                * math.cos(angle)
            )

            y2 = (
                cy
                + inner_radius
                * math.sin(angle)
            )


            painter.setPen(
                QPen(
                    MARKING_COLOR,
                    2,
                )
            )


            painter.drawLine(
                QPointF(
                    x1,
                    y1,
                ),
                QPointF(
                    x2,
                    y2,
                ),
            )


            text_radius = (
                radius * 0.68
            )


            tx = (
                cx
                + text_radius
                * math.cos(angle)
            )

            ty = (
                cy
                + text_radius
                * math.sin(angle)
            )


            painter.drawText(
                int(tx - 10),
                int(ty - 9),
                20,
                18,
                Qt.AlignCenter,
                str(value),
            )


        # ====================================================
        # Digital altitude
        #
        # 3 digits
        # ====================================================

        altitude_integer = int(
            round(
                self.altitude
            )
        )


        altitude_integer = max(
            0,
            min(
                999,
                altitude_integer,
            ),
        )


        altitude_text = (
            f"{altitude_integer:03d}"
        )


        box_width = (
            radius * 0.27
        )

        box_height = (
            radius * 0.21
        )


        total_width = (
            box_width * 3
        )


        start_x = (
            cx
            - total_width / 2
        )


        box_y = (
            cy
            - radius * 0.52
        )


        painter.setFont(
            QFont(
                "Arial",
                max(
                    7,
                    int(
                        size
                        * 0.043
                    ),
                ),
            )
        )


        for index, digit in enumerate(
            altitude_text
        ):

            x = (
                start_x
                + index
                * box_width
            )


            painter.setBrush(
                QColor(
                    5,
                    5,
                    5,
                )
            )

            painter.setPen(
                QPen(
                    MARKING_COLOR,
                    1,
                )
            )


            painter.drawRect(
                int(x),
                int(box_y),
                int(box_width),
                int(box_height),
            )


            painter.drawText(
                int(x),
                int(box_y),
                int(box_width),
                int(box_height),
                Qt.AlignCenter,
                digit,
            )


        # ====================================================
        # Altitude needle
        #
        # One revolution = 10 m
        # ====================================================

        altitude_digit = (
            self.altitude
            % 10.0
        )


        altitude_angle = math.radians(
            -90
            + altitude_digit
            * 36
        )


        altitude_needle_length = (
            radius * 0.66
        )


        alt_x = (
            cx
            + altitude_needle_length
            * math.cos(
                altitude_angle
            )
        )

        alt_y = (
            cy
            + altitude_needle_length
            * math.sin(
                altitude_angle
            )
        )


        painter.setPen(
            QPen(
                POINTER_COLOR,
                max(
                    2,
                    int(
                        size
                        * 0.014
                    ),
                ),
            )
        )


        painter.drawLine(
            QPointF(
                cx,
                cy,
            ),
            QPointF(
                alt_x,
                alt_y,
            ),
        )


        # ====================================================
        # ALT label
        # ====================================================

        painter.setPen(
            MARKING_COLOR
        )

        painter.setFont(
            QFont(
                "Arial",
                max(
                    6,
                    int(
                        size
                        * 0.028
                    ),
                ),
            )
        )


        painter.drawText(
            int(cx - 25),
            int(
                cy
                - radius * 0.31
            ),
            50,
            16,
            Qt.AlignCenter,
            "ALT",
        )


        # ====================================================
        # VSI scale
        #
        # -6 ... +6 m/s
        # ====================================================

        vsi_radius = (
            radius * 0.50
        )


        vsi_start_angle = 150.0
        vsi_end_angle = 30.0


        # ====================================================
        # VSI ticks
        # ====================================================

        for value in range(
            -6,
            7,
        ):

            ratio = (
                value + 6.0
            ) / 12.0


            angle_deg = (
                vsi_start_angle
                + ratio
                * (
                    vsi_end_angle
                    - vsi_start_angle
                )
            )


            angle = math.radians(
                angle_deg
            )


            major = (
                value % 2 == 0
            )


            outer = (
                vsi_radius
            )


            if major:

                inner = (
                    vsi_radius
                    - radius
                    * 0.055
                )

                line_width = 2

            else:

                inner = (
                    vsi_radius
                    - radius
                    * 0.030
                )

                line_width = 1


            x1 = (
                cx
                + outer
                * math.cos(angle)
            )

            y1 = (
                cy
                + outer
                * math.sin(angle)
            )


            x2 = (
                cx
                + inner
                * math.cos(angle)
            )

            y2 = (
                cy
                + inner
                * math.sin(angle)
            )


            painter.setPen(
                QPen(
                    MARKING_COLOR,
                    line_width,
                )
            )


            painter.drawLine(
                QPointF(
                    x1,
                    y1,
                ),
                QPointF(
                    x2,
                    y2,
                ),
            )


        # ====================================================
        # VSI numbers
        # ====================================================

        painter.setFont(
            QFont(
                "Arial",
                max(
                    5,
                    int(
                        size
                        * 0.022
                    ),
                ),
            )
        )


        vsi_number_values = (
            -6,
            -4,
            -2,
            0,
            2,
            4,
            6,
        )


        for value in vsi_number_values:

            ratio = (
                value + 6.0
            ) / 12.0


            angle_deg = (
                vsi_start_angle
                + ratio
                * (
                    vsi_end_angle
                    - vsi_start_angle
                )
            )


            angle = math.radians(
                angle_deg
            )


            text_radius = (
                vsi_radius * 0.70
            )


            tx = (
                cx
                + text_radius
                * math.cos(angle)
            )

            ty = (
                cy
                + text_radius
                * math.sin(angle)
            )


            if value > 0:

                text = (
                    f"+{value}"
                )

            else:

                text = str(value)


            painter.setPen(
                MARKING_COLOR
            )


            painter.drawText(
                int(tx - 12),
                int(ty - 7),
                24,
                14,
                Qt.AlignCenter,
                text,
            )


        # ====================================================
        # VSI needle
        # ====================================================

        vsi_ratio = (
            self.vertical_speed
            + 6.0
        ) / 12.0


        vsi_angle_deg = (
            vsi_start_angle
            + vsi_ratio
            * (
                vsi_end_angle
                - vsi_start_angle
            )
        )


        vsi_angle = math.radians(
            vsi_angle_deg
        )


        vsi_needle_length = (
            vsi_radius * 0.72
        )


        vsi_x = (
            cx
            + vsi_needle_length
            * math.cos(
                vsi_angle
            )
        )

        vsi_y = (
            cy
            + vsi_needle_length
            * math.sin(
                vsi_angle
            )
        )


        painter.setPen(
            QPen(
                POINTER_COLOR,
                2,
            )
        )


        painter.drawLine(
            QPointF(
                cx,
                cy,
            ),
            QPointF(
                vsi_x,
                vsi_y,
            ),
        )


        # ====================================================
        # VSI label
        # ====================================================

        painter.setPen(
            MARKING_COLOR
        )


        painter.setFont(
            QFont(
                "Arial",
                max(
                    6,
                    int(
                        size
                        * 0.027
                    ),
                ),
            )
        )


        painter.drawText(
            int(cx - 30),
            int(
                cy
                + radius * 0.10
            ),
            60,
            16,
            Qt.AlignCenter,
            "VSI",
        )


        # ====================================================
        # Center hub
        # ====================================================

        painter.setBrush(
            POINTER_COLOR
        )

        painter.setPen(
            Qt.NoPen
        )


        hub_radius = max(
            3,
            size * 0.020,
        )


        painter.drawEllipse(
            QPointF(
                cx,
                cy,
            ),
            hub_radius,
            hub_radius,
        )


# ============================================================
# 4. HEADING INDICATOR
# ============================================================

class HeadingIndicator(QWidget):

    def __init__(self):
        super().__init__()

        self.heading = 0.0

        self.setMinimumSize(
            120,
            120,
        )


    def set_heading(
        self,
        heading,
    ):

        self.heading = (
            float(heading)
            % 360.0
        )

        self.update()


    def paintEvent(self, event):

        painter = QPainter(self)

        painter.setRenderHint(
            QPainter.Antialiasing
        )


        painter.fillRect(
            self.rect(),
            PANEL_BACKGROUND
        )


        w = self.width()
        h = self.height()

        size = min(
            w,
            h,
        )

        cx = w / 2
        cy = h / 2

        radius = (
            size * 0.43
        )


        # ====================================================
        # Black dial
        # ====================================================

        painter.setBrush(
            DIAL_BACKGROUND
        )

        painter.setPen(
            QPen(
                DIAL_BORDER,
                3,
            )
        )


        painter.drawEllipse(
            QPointF(
                cx,
                cy,
            ),
            radius,
            radius,
        )


        # ====================================================
        # Rotating compass card
        # ====================================================

        painter.save()

        painter.translate(
            cx,
            cy,
        )


        painter.rotate(
            -self.heading
        )


        painter.setFont(
            QFont(
                "Arial",
                max(
                    7,
                    int(
                        size
                        * 0.04
                    ),
                ),
            )
        )


        for deg in range(
            0,
            360,
            5,
        ):

            angle = math.radians(
                deg - 90
            )


            major = (
                deg % 30 == 0
            )


            outer_radius = (
                radius * 0.92
            )


            if major:

                inner_radius = (
                    radius * 0.75
                )

            else:

                inner_radius = (
                    radius * 0.84
                )


            x1 = (
                outer_radius
                * math.cos(angle)
            )

            y1 = (
                outer_radius
                * math.sin(angle)
            )


            x2 = (
                inner_radius
                * math.cos(angle)
            )

            y2 = (
                inner_radius
                * math.sin(angle)
            )


            painter.setPen(
                QPen(
                    MARKING_COLOR,
                    2
                    if major
                    else 1,
                )
            )


            painter.drawLine(
                QPointF(
                    x1,
                    y1,
                ),
                QPointF(
                    x2,
                    y2,
                ),
            )


            if (
                major
                and deg not in (
                    0,
                    90,
                    180,
                    270,
                )
            ):

                text_radius = (
                    radius * 0.63
                )


                tx = (
                    text_radius
                    * math.cos(angle)
                )

                ty = (
                    text_radius
                    * math.sin(angle)
                )


                painter.drawText(
                    int(tx - 14),
                    int(ty - 9),
                    28,
                    18,
                    Qt.AlignCenter,
                    str(deg),
                )


        # ====================================================
        # N E S W
        # ====================================================

        labels = {
            0: "N",
            90: "E",
            180: "S",
            270: "W",
        }


        painter.setFont(
            QFont(
                "Arial",
                max(
                    9,
                    int(
                        size
                        * 0.06
                    ),
                ),
            )
        )


        for deg, label in labels.items():

            angle = math.radians(
                deg - 90
            )


            text_radius = (
                radius * 0.62
            )


            x = (
                text_radius
                * math.cos(angle)
            )

            y = (
                text_radius
                * math.sin(angle)
            )


            painter.setPen(
                MARKING_COLOR
            )


            painter.drawText(
                int(x - 12),
                int(y - 10),
                24,
                20,
                Qt.AlignCenter,
                label,
            )


        painter.restore()


        # ====================================================
        # Fixed red heading pointer
        # ====================================================

        painter.setPen(
            QPen(
                POINTER_COLOR,
                3,
            )
        )


        painter.drawLine(
            QPointF(
                cx,
                cy
                - radius * 0.98,
            ),
            QPointF(
                cx,
                cy
                - radius * 0.75,
            ),
        )


        # ====================================================
        # Aircraft cross
        # ====================================================

        painter.setPen(
            QPen(
                MARKING_COLOR,
                2,
            )
        )


        wing = (
            radius * 0.27
        )


        painter.drawLine(
            QPointF(
                cx - wing,
                cy,
            ),
            QPointF(
                cx + wing,
                cy,
            ),
        )


        painter.drawLine(
            QPointF(
                cx,
                cy
                - radius * 0.22,
            ),
            QPointF(
                cx,
                cy
                + radius * 0.22,
            ),
        )


        # ====================================================
        # Current heading
        # ====================================================

        painter.setFont(
            QFont(
                "Arial",
                max(
                    7,
                    int(
                        size
                        * 0.04
                    ),
                ),
            )
        )


        painter.setPen(
            MARKING_COLOR
        )


        painter.drawText(
            int(cx - 30),
            int(
                cy
                + radius * 0.25
            ),
            60,
            20,
            Qt.AlignCenter,
            f"{self.heading:03.0f}°",
        )


# ============================================================
# COMPLETE INSTRUMENT PANEL
# ============================================================

class InstrumentPanel(QWidget):

    def __init__(
        self,
        telemetry_state=None,
        update_interval_ms=50,
    ):

        super().__init__()


        # ====================================================
        # Telemetry
        #
        # IMPORTANT:
        #
        # This must be the SAME state object used by
        # renderer.py / telemetry receiver.
        #
        # This class does NOT open COM8.
        # ====================================================

        self.telemetry_state = (
            telemetry_state
        )


        # ====================================================
        # Create instruments
        # ====================================================

        self.attitude_indicator = (
            AttitudeIndicator()
        )

        self.speed_indicator = (
            SpeedIndicator()
        )

        self.altitude_vsi_indicator = (
            AltitudeVsiIndicator()
        )

        self.heading_indicator = (
            HeadingIndicator()
        )


        # ====================================================
        # Horizontal layout
        # ====================================================

        layout = QHBoxLayout(
            self
        )


        layout.setContentsMargins(
            4,
            4,
            4,
            4,
        )


        layout.setSpacing(
            4
        )


        layout.addWidget(
            self.attitude_indicator,
            1,
        )

        layout.addWidget(
            self.speed_indicator,
            1,
        )

        layout.addWidget(
            self.altitude_vsi_indicator,
            1,
        )

        layout.addWidget(
            self.heading_indicator,
            1,
        )


        self.setStyleSheet(
            "background-color: rgb(65, 65, 65);"
        )


        # ====================================================
        # Telemetry update timer
        #
        # 50 ms = 20 Hz
        # ====================================================

        self.telemetry_timer = (
            QTimer(self)
        )


        self.telemetry_timer.setInterval(
            int(update_interval_ms)
        )


        self.telemetry_timer.timeout.connect(
            self.update_from_telemetry
        )


        # Only start if a telemetry state
        # has already been supplied.
        if self.telemetry_state is not None:

            self.telemetry_timer.start()


    # ========================================================
    # Bind shared telemetry state
    # ========================================================

    def bind_telemetry_state(
        self,
        telemetry_state,
    ):

        """
        Connect this panel to the SAME TelemetryState object
        already used by the HUD renderer.

        This does NOT create another serial connection.
        """

        self.telemetry_state = (
            telemetry_state
        )


        if (
            self.telemetry_state
            is not None
        ):

            if (
                not self.telemetry_timer.isActive()
            ):

                self.telemetry_timer.start()

        else:

            self.telemetry_timer.stop()


    # ========================================================
    # Stop telemetry binding
    # ========================================================

    def unbind_telemetry_state(self):

        self.telemetry_timer.stop()

        self.telemetry_state = None


    # ========================================================
    # Read live telemetry
    # ========================================================

    def update_from_telemetry(self):

        state = (
            self.telemetry_state
        )


        if state is None:
            return


        # ====================================================
        # Copy telemetry under state lock
        #
        # Do NOT paint while holding the lock.
        # ====================================================

        try:

            with state.lock:

                connected = getattr(
                    state,
                    "connected",
                    False,
                )


                pitch = getattr(
                    state,
                    "pitch_deg",
                    None,
                )


                roll = getattr(
                    state,
                    "roll_deg",
                    None,
                )


                speed = getattr(
                    state,
                    "ground_speed_m_s",
                    None,
                )


                altitude = getattr(
                    state,
                    "altitude_m",
                    None,
                )


                vertical_speed = getattr(
                    state,
                    "vertical_speed_m_s",
                    None,
                )


                # renderer.py uses yaw_deg for
                # the rotating compass.
                heading = getattr(
                    state,
                    "yaw_deg",
                    None,
                )


                # Fallback if yaw_deg is unavailable.
                if heading is None:

                    heading = getattr(
                        state,
                        "heading_deg",
                        None,
                    )


        except Exception:

            return


        # ====================================================
        # Telemetry disconnected
        #
        # Keep last displayed values.
        # ====================================================

        if not connected:
            return


        # ====================================================
        # Update only values actually received.
        #
        # If one MAVLink message is temporarily missing,
        # other instruments can continue updating.
        # ====================================================

        if (
            pitch is not None
            and roll is not None
        ):

            self.set_attitude(
                pitch,
                roll,
            )


        if speed is not None:

            self.set_speed(
                speed
            )


        if altitude is not None:

            self.set_altitude(
                altitude
            )


        if vertical_speed is not None:

            self.set_vertical_speed(
                vertical_speed
            )


        if heading is not None:

            self.set_heading(
                heading
            )


    # ========================================================
    # Individual update functions
    # ========================================================

    def set_attitude(
        self,
        pitch,
        roll,
    ):

        self.attitude_indicator.set_attitude(
            pitch,
            roll,
        )


    def set_speed(
        self,
        speed,
    ):

        self.speed_indicator.set_speed(
            speed
        )


    def set_altitude(
        self,
        altitude,
    ):

        self.altitude_vsi_indicator.set_altitude(
            altitude
        )


    def set_vertical_speed(
        self,
        vertical_speed,
    ):

        self.altitude_vsi_indicator.set_vertical_speed(
            vertical_speed
        )


    def set_heading(
        self,
        heading,
    ):

        self.heading_indicator.set_heading(
            heading
        )


    # ========================================================
    # Manual / combined update
    #
    # Still useful for testing.
    # ========================================================

    def set_flight_data(
        self,
        pitch,
        roll,
        speed,
        altitude,
        vertical_speed,
        heading,
    ):

        self.set_attitude(
            pitch,
            roll,
        )

        self.set_speed(
            speed
        )

        self.set_altitude(
            altitude
        )

        self.set_vertical_speed(
            vertical_speed
        )

        self.set_heading(
            heading
        )