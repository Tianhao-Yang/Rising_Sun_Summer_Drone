import math
import time

import cv2
import numpy as np

from config import (
    COMPASS_DOWN_OFFSET,
    TEL_WARNING_PERCENT,
    TEL_CRITICAL_PERCENT,
    RC_WARNING_PERCENT,
    RC_CRITICAL_PERCENT,
    BAT_VOLTAGE_WARNING,
    BAT_VOLTAGE_CRITICAL,
    CURRENT_WARNING_A,
    CURRENT_CRITICAL_A,
    GPS_MIN_FIX_TYPE,
    GPS_MIN_SATELLITES_EXCLUSIVE,
    GPS_MAX_HDOP,
    WARNING_BLINK_PERIOD_S,
)

def format_value(value, decimals=1):
    if value is None:
        return "---"

    return f"{value:.{decimals}f}"

def draw_vertical_tape(
    frame,
    value,
    x,
    center_y,
    height,
    major_step,
    minor_step,
    pixels_per_unit,
    label,
    unit,
    ticks_point_right=True,
    fill_negative_region=False,
):  # draw moving HUD line
    """
    Draw a moving vertical HUD tape.

    value:
        Current measured value. If None, zero is used for the scale and the
        value window displays ---.

    x:
        X coordinate of the main vertical scale line.

    ticks_point_right:
        True for the left-side speed tape.
        False for the right-side altitude tape.
    """
    hud_color = (80, 255, 80)
    shadow_color = (0, 0, 0)
    font = cv2.FONT_HERSHEY_SIMPLEX

    top = center_y - height // 2
    bottom = center_y + height // 2
    current_value = 0.0 if value is None else float(value)

    # Main scale line.
    cv2.line(frame, (x, top), (x, bottom), hud_color, 1, cv2.LINE_AA)


    cap_length = max(18, int(frame.shape[1] * 0.05),)                # Horizontal end-cap length.

                                                                        # Make one end of each horizontal line touch the vertical tape.
                                                                        # Left speed tape: caps extend to the left.
                                                                        # Right altitude tape: caps extend to the right.
    if ticks_point_right:
        # Left speed tape: caps extend outward to the left.
        top_cap_start = (x - cap_length, top)
        top_cap_end = (x, top)

        bottom_cap_start = (x - cap_length, bottom)
        bottom_cap_end = (x, bottom)
    else:
        # Right altitude tape: caps extend outward to the right.
        top_cap_start = (x, top)
        top_cap_end = (x + cap_length, top)

        bottom_cap_start = (x, bottom)
        bottom_cap_end = (x + cap_length, bottom)

    cv2.line(
        frame,
        top_cap_start,
        top_cap_end,
        hud_color,
        1,
        cv2.LINE_AA,
    )

    cv2.line(
        frame,
        bottom_cap_start,
        bottom_cap_end,
        hud_color,
        1,
        cv2.LINE_AA,
    )

    # Determine which minor tick values are visible.
    value_at_top = current_value + (center_y - top) / pixels_per_unit
    value_at_bottom = current_value - (bottom - center_y) / pixels_per_unit

    first_tick = math.floor(value_at_bottom / minor_step) * minor_step
    last_tick = math.ceil(value_at_top / minor_step) * minor_step

    # For the altitude tape, replace the visible region below 0 m
    # with one continuous solid bar instead of separate tick marks.
    if fill_negative_region:
        zero_y = int(
            round(
                center_y
                - (0.0 - current_value) * pixels_per_unit
            )
        )

        negative_top = max(top, zero_y)
        negative_bottom = bottom

        if negative_top < negative_bottom:                            
            solid_bar_width = 8  # Same width as a major tick.

            if ticks_point_right:
                bar_left = x - solid_bar_width
                bar_right = x
            else:
                bar_left = x
                bar_right = x + solid_bar_width

            cv2.rectangle(
                frame,
                (bar_left, negative_top),
                (bar_right, negative_bottom),
                hud_color,
                -1,
            )

    tick_value = first_tick
    while tick_value <= last_tick + 1e-9:
        tick_y = int(round(center_y - (tick_value - current_value) * pixels_per_unit))

        if top <= tick_y <= bottom:
            if fill_negative_region and tick_value < 0:
                tick_value += minor_step
                continue

            major_ratio = tick_value / major_step
            is_major = abs(major_ratio - round(major_ratio)) < 1e-6
            tick_length = 18 if is_major else 9

            if ticks_point_right:
                                                                            # Left speed tape: ticks and numbers extend outward to the left.
                tick_start = (x - tick_length, tick_y)
                tick_end = (x, tick_y)
                text_x = x - tick_length - 15
            else:
                                                                            # Right altitude tape: ticks and numbers extend outward to the right.
                tick_start = (x, tick_y)
                tick_end = (x + tick_length, tick_y)
                text_x = x + tick_length + 5

            cv2.line(
                frame,
                tick_start,
                tick_end,
                hud_color,
                1,
                cv2.LINE_AA,
            )

            if is_major:

                box_top = center_y - 15
                box_bottom = center_y + 15

                if not (box_top <= tick_y <= box_bottom):

                    tick_label = f"{tick_value:.0f}"

                    cv2.putText(
                        frame,
                        tick_label,
                        (text_x, tick_y + 5),
                        font,
                        0.4,
                        hud_color,
                        1,
                        cv2.LINE_AA,
                    )

        tick_value += minor_step

    # Current-value pointer and box.
    if ticks_point_right:
        # Left speed tape: pointer and value box extend outward to the left.
        pointer = [
            (x + 2, center_y),
            (x - 11, center_y - 8),
            (x - 11, center_y + 8),
        ]
        box_left = x - 55
        box_right = x - 11
    else:
        # Right altitude tape: pointer and value box extend outward to the right.
        pointer = [
            (x - 2, center_y),
            (x + 11, center_y - 8),
            (x + 11, center_y + 8),
        ]
        box_left = x + 11
        box_right = x + 55

    cv2.polylines(
        frame,
        [np.array(pointer, dtype=np.int32)],
        True,
        hud_color,
        1,
        cv2.LINE_AA,
    )

    # Draw a semi-transparent black background inside the value box.
    overlay = frame.copy()

    cv2.rectangle(
        overlay,
        (box_left, center_y - 15),
        (box_right, center_y + 15),
        shadow_color,
        -1,
    )

    box_alpha = 0.30  # 0.0 = fully transparent, 1.0 = fully black for altitude tape and speed tape

    cv2.addWeighted(
        overlay,
        box_alpha,
        frame,
        1.0 - box_alpha,
        0,
        frame,
    )

    # Draw the green outline after blending so it remains fully visible.
    cv2.rectangle(
        frame,
        (box_left, center_y - 15),
        (box_right, center_y + 15),
        hud_color,
        1,
        cv2.LINE_AA,
    )

    value_text = "---" if value is None else f"{value:.1f}"
    text_size, _ = cv2.getTextSize(value_text, font, 0.62, 1)
    text_x = box_left + (box_right - box_left - text_size[0]) // 2

    cv2.putText(
        frame,
        value_text,
        (text_x, center_y + 7),
        font,
        0.62,
        hud_color,
        1,
        cv2.LINE_AA,
    )

    # Tape title.
    title = f"{label} {unit}"
    title_size, _ = cv2.getTextSize(title, font, 0.45, 1)

    if ticks_point_right:
        # Left title sits outside/left of the speed tape.
        title_x = x - title_size[0] + 3
    else:
        # Right title sits outside/right of the altitude tape.
        title_x = x - 3

    cv2.putText(
        frame,
        title,
        (title_x, top - 10),
        font,
        0.45,
        hud_color,
        1,
        cv2.LINE_AA,
    )

    # Show the live value directly below the SPD/ALT title.
    # When no telemetry value is available, display "--".
    title_value_text = "--" if value is None else f"{value:.1f}"

    title_value_size, _ = cv2.getTextSize(
        title_value_text,
        font,
        0.42,
        1,
    )

    # Center the value beneath the title.
    title_value_x = (
        title_x
        + (title_size[0] - title_value_size[0]) // 2
    )
    title_value_y = top + 250

    cv2.putText(
        frame,
        title_value_text,
        (title_value_x, title_value_y),
        font,
        0.42,
        hud_color,
        1,
        cv2.LINE_AA,
    )

def draw_vertical_speed_readout(frame, altitude_tape_x, tape_bottom, vertical_speed_m_s):
    """
    Draw vertical speed below the altitude tape.

    No signal:
        VS: --

    Ascending:
        VS: 1.2 plus a graphical upward arrow

    Descending:
        VS: -0.8 plus a graphical downward arrow
    """
    hud_color = (80, 255, 80)
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.42
    thickness = 1

    # Place the readout below the ALT tape, aligned with its vertical line.
    text_x = altitude_tape_x
    text_y = min(frame.shape[0] - 12, tape_bottom + 28)

    if vertical_speed_m_s is None:
        text = "VS: --"
        cv2.putText(
            frame,
            text,
            (text_x, text_y),
            font,
            font_scale,
            hud_color,
            thickness,
            cv2.LINE_AA,
        )
        return

    vertical_speed = float(vertical_speed_m_s)
    text = f"VS: {vertical_speed:.1f}"

    cv2.putText(
        frame,
        text,
        (text_x, text_y),
        font,
        font_scale,
        hud_color,
        thickness,
        cv2.LINE_AA,
    )

    # OpenCV's Hershey font does not reliably support Unicode arrows,
    # so draw the arrow as lines.
    text_size, _ = cv2.getTextSize(
        text,
        font,
        font_scale,
        thickness,
    )

    arrow_x = text_x + text_size[0] + 10
    arrow_center_y = text_y - 5
    arrow_length = 14
    arrow_head = 5

    # Small deadband: near-zero climb shows the number without an arrow.
    if vertical_speed > 0.05:
        arrow_top = arrow_center_y - arrow_length // 2
        arrow_bottom = arrow_center_y + arrow_length // 2

        cv2.line(
            frame,
            (arrow_x, arrow_bottom),
            (arrow_x, arrow_top),
            hud_color,
            thickness,
            cv2.LINE_AA,
        )
        cv2.line(
            frame,
            (arrow_x, arrow_top),
            (arrow_x - arrow_head, arrow_top + arrow_head),
            hud_color,
            thickness,
            cv2.LINE_AA,
        )
        cv2.line(
            frame,
            (arrow_x, arrow_top),
            (arrow_x + arrow_head, arrow_top + arrow_head),
            hud_color,
            thickness,
            cv2.LINE_AA,
        )

    elif vertical_speed < -0.05:
        arrow_top = arrow_center_y - arrow_length // 2
        arrow_bottom = arrow_center_y + arrow_length // 2

        cv2.line(
            frame,
            (arrow_x, arrow_top),
            (arrow_x, arrow_bottom),
            hud_color,
            thickness,
            cv2.LINE_AA,
        )
        cv2.line(
            frame,
            (arrow_x, arrow_bottom),
            (arrow_x - arrow_head, arrow_bottom - arrow_head),
            hud_color,
            thickness,
            cv2.LINE_AA,
        )
        cv2.line(
            frame,
            (arrow_x, arrow_bottom),
            (arrow_x + arrow_head, arrow_bottom - arrow_head),
            hud_color,
            thickness,
            cv2.LINE_AA,
        )

def draw_primary_hud_tapes(frame, speed_m_s, altitude_m, vertical_speed_m_s):
    """
    Draw the two main HUD tapes requested by the user:
    left = horizontal/ground speed, right = relative altitude.
    """
    frame_height, frame_width = frame.shape[:2]

    center_y = int(frame_height*0.4)
    tape_height = max(180, int(frame_height * 0.5))               # airspeed tap height and altitude tap height

    
    left_x = int(frame_width * 0.28)                               # left side 20% from the edge
    right_x = int(frame_width * 0.72)                              # right side 80% from the edge

    draw_vertical_tape(                                            # draw speed tape
        frame=frame,
        value=speed_m_s,
        x=left_x,
        center_y=center_y,
        height=tape_height,
        major_step=5.0,
        minor_step=1.0,
        pixels_per_unit=14.0,
        label="SPD",
        unit="m/s",
        ticks_point_right=True,
    )

    draw_vertical_tape(                                            # draw altitude tape
        frame=frame,
        value=altitude_m,
        x=right_x,
        center_y=center_y,
        height=tape_height,
        major_step=1,
        minor_step=0.2,
        pixels_per_unit=70,
        label="ALT",
        unit="m",
        ticks_point_right=False,
        fill_negative_region=True,
    )

    altitude_tape_bottom = center_y + tape_height // 2

    draw_vertical_speed_readout(
        frame=frame,
        altitude_tape_x=right_x,
        tape_bottom=altitude_tape_bottom,
        vertical_speed_m_s=vertical_speed_m_s,
    )


def draw_roll_indicator(frame, roll_deg):
    """
    Draw a continuous 360-degree roll indicator.

    Full roll range:
        -180 deg ... 0 deg ... +180 deg

    Visible window:
        120 degrees total
        = 60 degrees left
        + 60 degrees right

    Behaviour:
        - Fixed triangle does NOT move.
        - Scale moves continuously underneath it.
        - One degree leaves the visible region while one degree
          enters from the opposite side.
        - +180 and -180 wrap continuously.
    """

    frame_height, frame_width = frame.shape[:2]

    hud_color = (80, 255, 80)
    font = cv2.FONT_HERSHEY_SIMPLEX

    center_x = frame_width // 2


    # =========================
    # Roll scale geometry
    # =========================

    # Move entire roll arc up / down here.
    arc_center_y = int(
        frame_height * 0.33
    )

    # Size of the roll arc.
    radius = max(
        90,
        int(
            min(
                frame_width,
                frame_height,
            )
            * 0.24
        ),
    )


    # =========================
    # Current roll
    # =========================

    current_roll = (
        0.0
        if roll_deg is None
        else float(roll_deg)
    )


    # Convert roll into:
    #
    # -180 <= roll < 180
    #
    current_roll = (
        (current_roll + 180.0)
        % 360.0
        - 180.0
    )


    # =========================
    # Visible roll window
    # =========================

    # Total visible range = 120 deg
    #
    # -60 deg relative to pointer
    # +60 deg relative to pointer
    visible_half_range = 60.0


    # =========================
    # Fixed pointer
    # =========================

    pointer_tip_y = (
        arc_center_y
        - radius
        + 6
    )

    triangle_half_width = max(
        7,
        int(radius * 0.055),
    )

    triangle_height = max(
        9,
        int(radius * 0.075),
    )


    pointer_points = np.array(
        [
            (
                center_x,
                pointer_tip_y,
            ),

            (
                center_x
                - triangle_half_width,

                pointer_tip_y
                - triangle_height,
            ),

            (
                center_x
                + triangle_half_width,

                pointer_tip_y
                - triangle_height,
            ),
        ],
        dtype=np.int32,
    )


    cv2.polylines(
        frame,
        [pointer_points],
        True,
        hud_color,
        1,
        cv2.LINE_AA,
    )


    # =========================
    # Helper:
    # shortest angular distance
    # =========================

    def angular_difference(
        angle,
        reference,
    ):

        return (
            (
                angle
                - reference
                + 180.0
            )
            % 360.0
            - 180.0
        )


    # =========================
    # Draw all roll ticks
    # =========================

    # IMPORTANT:
    #
    # The scale itself contains the complete
    # -180 ... +180 range.
    #
    # We draw one tick EVERY degree.
    #
    for mark_deg in range(
        -180,
        181,
        5
    ):

        # Where should this world roll mark appear
        # relative to the current aircraft roll?
        screen_deg = angular_difference(
            mark_deg,
            current_roll,
        )


        # Only show a 120-degree window.
        if (
            screen_deg < -visible_half_range
            or
            screen_deg > visible_half_range
        ):
            continue


        # 0 deg on screen = straight upward.
        angle_rad = math.radians(
            screen_deg
        )


        # =========================
        # Tick hierarchy
        # =========================

        absolute_mark = abs(
            mark_deg
        )


        # 180-degree mark
        if absolute_mark == 180:

            tick_length = max(
                17,
                int(radius * 0.13),
            )

            thickness = 2


        # Every 30 degrees
        elif mark_deg % 30 == 0:

            tick_length = max(
                15,
                int(radius * 0.11),
            )

            thickness = 2


        # Every 10 degrees
        elif mark_deg % 10 == 0:

            tick_length = max(
                12,
                int(radius * 0.085),
            )

            thickness = 1


        # Every 5 degrees
        elif mark_deg % 5 == 0:

            tick_length = max(
                8,
                int(radius * 0.055),
            )

            thickness = 1


        # Every single degree
        else:

            tick_length = max(
                4,
                int(radius * 0.028),
            )

            thickness = 1


        # =========================
        # Tick coordinates
        # =========================

        outer_x = int(
            round(
                center_x
                + radius
                * math.sin(angle_rad)
            )
        )

        outer_y = int(
            round(
                arc_center_y
                - radius
                * math.cos(angle_rad)
            )
        )


        inner_radius = (
            radius
            - tick_length
        )


        inner_x = int(
            round(
                center_x
                + inner_radius
                * math.sin(angle_rad)
            )
        )

        inner_y = int(
            round(
                arc_center_y
                - inner_radius
                * math.cos(angle_rad)
            )
        )


        cv2.line(
            frame,
            (
                inner_x,
                inner_y,
            ),
            (
                outer_x,
                outer_y,
            ),
            hud_color,
            thickness,
            cv2.LINE_AA,
        )


        # =========================
        # Number labels
        # =========================

        # Show number every 10 degrees.
        if mark_deg % 10 == 0:

            label_radius = (
                radius
                + max(
                    15,
                    int(radius * 0.09),
                )
            )


            label_x = int(
                round(
                    center_x
                    + label_radius
                    * math.sin(angle_rad)
                )
            )

            label_y = int(
                round(
                    arc_center_y
                    - label_radius
                    * math.cos(angle_rad)
                )
            )


            # Actual roll angle label:
            #
            # -170
            # -160
            # ...
            # 0
            # ...
            # 160
            # 170
            # 180
            #
            label_text = str(
                int(mark_deg)
            )


            text_size, _ = cv2.getTextSize(
                label_text,
                font,
                0.34,
                1,
            )


            cv2.putText(
                frame,
                label_text,
                (
                    label_x
                    - text_size[0] // 2,

                    label_y
                    + text_size[1] // 2,
                ),
                font,
                0.34,
                hud_color,
                1,
                cv2.LINE_AA,
            )


def draw_pitch_ladder(frame, pitch_deg, roll_deg):
    """
    Draw pitch ladder with opposite roll compensation.

    If aircraft rolls right +10 deg, the pitch ladder rotates left -10 deg.
    Rotation center is the fixed aircraft reference symbol.
    """
    frame_height, frame_width = frame.shape[:2]

    hud_color = (80, 255, 80)
    font = cv2.FONT_HERSHEY_SIMPLEX

    center_x = frame_width // 2
    reference_y = int(frame_height * 0.39)

    current_pitch = 0.0 if pitch_deg is None else float(pitch_deg)
    current_roll = 0.0 if roll_deg is None else float(roll_deg)

    # Opposite direction to aircraft roll.
    ladder_roll_rad = math.radians(-current_roll)
    cos_r = math.cos(ladder_roll_rad)
    sin_r = math.sin(ladder_roll_rad)

    def rotate_point(x, y):
        dx = x - center_x
        dy = y - reference_y

        rx = center_x + dx * cos_r - dy * sin_r
        ry = reference_y + dx * sin_r + dy * cos_r

        return int(round(rx)), int(round(ry))

    pixels_per_degree = max(3.5, frame_height * 0.018)
    pitch_step = 5.0

    tape_center_y = int(frame_height * 0.4)
    tape_height = max(180, int(frame_height * 0.5))
    tape_top = tape_center_y - tape_height // 2

    distance_to_top = reference_y - tape_top
    visible_top = max(0, tape_top)
    visible_bottom = min(
        frame_height - 1,
        reference_y + distance_to_top,
    )

    normal_half_width = max(55, int(frame_width * 0.095))
    horizon_half_width = max(85, int(frame_width * 0.2))
    center_gap = max(24, int(frame_width * 0.035))

    left_limit = int(frame_width * 0.34)
    right_limit = int(frame_width * 0.66)

    pitch_at_top = (
        current_pitch
        + (reference_y - visible_top) / pixels_per_degree
    )

    pitch_at_bottom = (
        current_pitch
        + (reference_y - visible_bottom) / pixels_per_degree
    )

    lowest_visible_pitch = min(pitch_at_top, pitch_at_bottom)
    highest_visible_pitch = max(pitch_at_top, pitch_at_bottom)

    first_mark = (
        math.ceil(lowest_visible_pitch / pitch_step)
        * pitch_step
    )

    last_mark = (
        math.floor(highest_visible_pitch / pitch_step)
        * pitch_step
    )

    mark_deg = first_mark

    while mark_deg <= last_mark + 1e-9:
        base_y = int(round(
            reference_y
            + (current_pitch - mark_deg) * pixels_per_degree
        ))

        if visible_top <= base_y <= visible_bottom:
            if abs(mark_deg) < 1e-9:
                half_width = horizon_half_width
            else:
                half_width = normal_half_width

            left_x = max(left_limit, center_x - half_width)
            right_x = min(right_limit, center_x + half_width)

            left_outer = rotate_point(left_x, base_y)
            left_inner = rotate_point(center_x - center_gap, base_y)
            right_inner = rotate_point(center_x + center_gap, base_y)
            right_outer = rotate_point(right_x, base_y)

            cv2.line(
                frame,
                left_outer,
                left_inner,
                hud_color,
                1,
                cv2.LINE_AA,
            )

            cv2.line(
                frame,
                right_inner,
                right_outer,
                hud_color,
                1,
                cv2.LINE_AA,
            )

            hook_height = max(4, int(frame_height * 0.010))

            if mark_deg > 0:
                left_hook_end = rotate_point(
                    left_x,
                    min(base_y + hook_height, visible_bottom),
                )
                right_hook_end = rotate_point(
                    right_x,
                    min(base_y + hook_height, visible_bottom),
                )

                cv2.line(
                    frame,
                    left_outer,
                    left_hook_end,
                    hud_color,
                    1,
                    cv2.LINE_AA,
                )

                cv2.line(
                    frame,
                    right_outer,
                    right_hook_end,
                    hud_color,
                    1,
                    cv2.LINE_AA,
                )

            elif mark_deg < 0:
                left_hook_end = rotate_point(
                    left_x,
                    max(base_y - hook_height, visible_top),
                )
                right_hook_end = rotate_point(
                    right_x,
                    max(base_y - hook_height, visible_top),
                )

                cv2.line(
                    frame,
                    left_outer,
                    left_hook_end,
                    hud_color,
                    1,
                    cv2.LINE_AA,
                )

                cv2.line(
                    frame,
                    right_outer,
                    right_hook_end,
                    hud_color,
                    1,
                    cv2.LINE_AA,
                )

            # Labels move with the ladder, but stay upright.
            if abs(mark_deg) >= 1e-9:
                label = f"{int(round(mark_deg)):+d}"
                text_size, _ = cv2.getTextSize(
                    label,
                    font,
                    0.38,
                    1,
                )

                left_label = rotate_point(left_x - 8, base_y)
                right_label = rotate_point(right_x + 8, base_y)

                cv2.putText(
                    frame,
                    label,
                    (left_label[0] - text_size[0], left_label[1] + 5),
                    font,
                    0.38,
                    hud_color,
                    1,
                    cv2.LINE_AA,
                )

                cv2.putText(
                    frame,
                    label,
                    (right_label[0], right_label[1] + 5),
                    font,
                    0.38,
                    hud_color,
                    1,
                    cv2.LINE_AA,
                )

        mark_deg += pitch_step

def draw_lower_center_symbol(frame):
    """
    Draw a sharp green reference symbol in the lower half of the screen.

    The symbol stays horizontally centered and scales with the frame size.
    A thin dark outline plus a bright center line keeps the symbol clear
    without the blurry glow produced by a thick anti-aliased line.
    """
    frame_height, frame_width = frame.shape[:2]

    outline_color = (0, 110, 0)
    hud_color = (80, 255, 80)

    
    center_x = frame_width // 2
    center_y = int(frame_height * 0.39)                                      # aircraft position

    # Scale the symbol with the video resolution.
    symbol_width = max(80, int(frame_width * 0.16))
    notch_width = max(24, int(symbol_width * 0.28))
    notch_depth = max(7, int(frame_height * 0.022))

    # Short sloped transitions make the corners smoother and clearer.
    slope_width = max(8, int(symbol_width * 0.06))

    left_x = center_x - symbol_width // 2
    right_x = center_x + symbol_width // 2

    notch_left_x = center_x - notch_width // 2
    notch_right_x = center_x + notch_width // 2

    points = np.array(
        [
            (left_x, center_y),
            (notch_left_x - slope_width, center_y),
            (notch_left_x, center_y + notch_depth),
            (notch_right_x, center_y + notch_depth),
            (notch_right_x + slope_width, center_y),
            (right_x, center_y),
        ],
        dtype=np.int32,
    )

    # Dark outline: LINE_8 prevents a wide blurry anti-aliased glow.
    cv2.polylines(
        frame,
        [points],
        False,
        outline_color,
        3,
        cv2.LINE_8,
    )

    # Bright one-pixel center line.
    cv2.polylines(
        frame,
        [points],
        False,
        hud_color,
        1,
        cv2.LINE_AA,
    )

def draw_rotating_compass(
    frame,
    heading_deg,
    speed_m_s,
    gps_fix_type,
    gps_satellites_visible,
    gps_hdop,
):
    """
    Draw a rotating 360-degree compass rose at the bottom of the HUD.

    Design:
        - The aircraft itself is fixed relative to the screen.
        - A fixed inverted triangle at the top of the compass represents
          the aircraft's current heading reference.
        - The compass rose rotates with respect to the real world.
        - North = 000 deg, East = 090 deg, South = 180 deg, West = 270 deg.
        - One tick is drawn for every 1 degree.
        - Longer ticks are used every 5, 10, 30 and 90 degrees.

    Rotation logic:
        If aircraft heading = 0 deg:
            N is directly beneath the fixed triangle.

        If aircraft heading = 90 deg:
            E is directly beneath the fixed triangle.

        Therefore the compass rose is rotated by:
            world_angle - aircraft_heading
    """
    frame_height, frame_width = frame.shape[:2]

    hud_color = (80, 255, 80)
    shadow_color = (0, 0, 0)
    font = cv2.FONT_HERSHEY_SIMPLEX

    # Use zero only as a visual fallback before telemetry becomes available.
    heading = 0.0 if heading_deg is None else float(heading_deg) % 360.0

    # ---------------------------------------------------------
    # Compass geometry
    # ---------------------------------------------------------
    center_x = frame_width // 2

    # Compass size.
    radius = max(55, int(min(frame_width, frame_height) * 0.15))

    # Compass vertical position.
    #
    # The compass is intentionally allowed to extend below the image.
    # COMPASS_DOWN_OFFSET controls how far it moves downward.
    #
    # Example:
    #   0  -> bottom of compass just touches bottom of frame
    #   40 -> bottom 40 px of compass is outside the frame
    center_y = (
        frame_height
        - radius
        + COMPASS_DOWN_OFFSET
    )


    # ---------------------------------------------------------
    # Draw all 360 one-degree ticks.
    #
    # Screen-angle convention:
    #     0 deg is straight up on the screen.
    #     positive angle rotates clockwise.
    #
    # For a world direction d:
    #     screen_angle = d - heading
    #
    # Example:
    #     heading = 90
    #     East = 90
    #     screen_angle = 0
    # Therefore E appears at the top under the aircraft pointer.
    # ---------------------------------------------------------
    for world_deg in range(0,360,10):
        screen_deg = (world_deg - heading) % 360.0
        angle_rad = math.radians(screen_deg)

        # Tick length hierarchy.
        if world_deg % 90 == 0:
            tick_length = max(12, int(radius * 0.16))
            thickness = 2
        elif world_deg % 30 == 0:
            tick_length = max(10, int(radius * 0.13))
            thickness = 1
        elif world_deg % 10 == 0:
            tick_length = max(8, int(radius * 0.10))
            thickness = 1
        elif world_deg % 5 == 0:
            tick_length = max(6, int(radius * 0.075))
            thickness = 1
        else:
            tick_length = max(3, int(radius * 0.045))
            thickness = 1

        outer_radius = radius
        inner_radius = radius - tick_length

        outer_x = int(round(
            center_x + outer_radius * math.sin(angle_rad)
        ))
        outer_y = int(round(
            center_y - outer_radius * math.cos(angle_rad)
        ))

        inner_x = int(round(
            center_x + inner_radius * math.sin(angle_rad)
        ))
        inner_y = int(round(
            center_y - inner_radius * math.cos(angle_rad)
        ))

        cv2.line(
            frame,
            (inner_x, inner_y),
            (outer_x, outer_y),
            hud_color,
            thickness,
            cv2.LINE_AA,
        )

    # ---------------------------------------------------------
    # Cardinal labels: N, E, S, W.
    # These labels rotate with the real-world compass rose.
    # ---------------------------------------------------------
    cardinal_directions = {
        0: "N",
        90: "E",
        180: "S",
        270: "W",
    }

    label_radius = radius - max(24, int(radius * 0.25))

    for world_deg, label in cardinal_directions.items():
        screen_deg = (world_deg - heading) % 360.0
        angle_rad = math.radians(screen_deg)

        label_center_x = int(round(
            center_x + label_radius * math.sin(angle_rad)
        ))
        label_center_y = int(round(
            center_y - label_radius * math.cos(angle_rad)
        ))

        text_size, _ = cv2.getTextSize(
            label,
            font,
            0.52,
            1,
        )

        cv2.putText(
            frame,
            label,
            (
                label_center_x - text_size[0] // 2,
                label_center_y + text_size[1] // 2,
            ),
            font,
            0.52,
            hud_color,
            1,
            cv2.LINE_AA,
        )

    # ---------------------------------------------------------
    # Numerical labels every 30 degrees.
    #
    # Cardinal points keep N/E/S/W instead of numbers.
    # Other labels use aviation-style tens:
    #     030 -> 3
    #     060 -> 6
    #     120 -> 12
    # etc.
    # ---------------------------------------------------------
    number_radius = int(radius * 0.75)

    for world_deg in range(0, 360, 30):
        if world_deg in cardinal_directions:
            continue

        screen_deg = (world_deg - heading) % 360.0
        angle_rad = math.radians(screen_deg)

        number_center_x = int(round(
            center_x + number_radius * math.sin(angle_rad)
        ))
        number_center_y = int(round(
            center_y - number_radius * math.cos(angle_rad)
        ))

        number_text = str(world_deg // 10)

        text_size, _ = cv2.getTextSize(
            number_text,
            font,
            0.34,
            1,
        )

        cv2.putText(
            frame,
            number_text,
            (
                number_center_x - text_size[0] // 2,
                number_center_y + text_size[1] // 2,
            ),
            font,
            0.34,
            hud_color,
            1,
            cv2.LINE_AA,
        )

    # ---------------------------------------------------------
    # Fixed inverted triangle at the top center.
    #
    # This DOES NOT rotate. It represents the aircraft heading line.
    # The compass rose moves underneath it.
    # ---------------------------------------------------------
    triangle_top_y = center_y - radius - 10
    triangle_half_width = max(6, int(radius * 0.07))
    triangle_height = max(8, int(radius * 0.09))

    pointer_points = np.array(
        [
            (center_x - triangle_half_width, triangle_top_y),
            (center_x + triangle_half_width, triangle_top_y),
            (center_x, triangle_top_y + triangle_height),
        ],
        dtype=np.int32,
    )

    cv2.polylines(
        frame,
        [pointer_points],
        True,
        hud_color,
        1,
        cv2.LINE_AA,
    )

    # ---------------------------------------------------------
    # Left-side SPD and HDG readouts.
    # ---------------------------------------------------------
    if heading_deg is None:
        heading_text = "HDG ---"
    else:
        heading_text = f"HDG {int(round(heading)) % 360:03d}"

    if speed_m_s is None:
        speed_text = "SPD ---"
    else:
        speed_text = f"SPD {float(speed_m_s):.1f}"

    heading_size, _ = cv2.getTextSize(
        heading_text,
        font,
        0.42,
        1,
    )

    speed_size, _ = cv2.getTextSize(
        speed_text,
        font,
        0.42,
        1,
    )

    max_text_width = max(
        heading_size[0],
        speed_size[0],
    )

    # Put both labels on the LEFT side of the compass.
    text_x = center_x - radius - max_text_width - max(
        15,
        int(frame_width * 0.02),
    )
    text_x = max(5, text_x)

    # HDG remains vertically centered beside the compass.
    text_up_offset = 30
    heading_text_y = center_y + heading_size[1] // 2 - text_up_offset

    # SPD is directly above HDG.
    line_spacing = max(
        22,
        int(frame_height * 0.045),
    )
    speed_text_y = heading_text_y - line_spacing

    cv2.putText(
        frame,
        speed_text,
        (
            text_x,
            speed_text_y,
        ),
        font,
        0.42,
        hud_color,
        1,
        cv2.LINE_AA,
    )

    cv2.putText(
        frame,
        heading_text,
        (
            text_x,
            heading_text_y,
        ),
        font,
        0.42,
        hud_color,
        1,
        cv2.LINE_AA,
    )

    # ---------------------------------------------------------
    # Right-side GPS readouts, symmetrical to SPD / HDG.
    #
    # GPS is binary GREEN / RED:
    # GREEN only when:
    #   fix_type >= 3
    #   satellites > 3
    #   HDOP <= 2.0
    # Otherwise RED.
    # ---------------------------------------------------------
    fix_text = gps_fix_type_to_text(gps_fix_type)

    if gps_fix_type is None:
        gps_text = "GPS: NO GPS"
    else:
        gps_text = f"GPS: {fix_text}"

    satellites_text = (
        "--"
        if gps_satellites_visible is None
        else str(gps_satellites_visible)
    )

    hdop_text = (
        "--"
        if gps_hdop is None
        else f"{gps_hdop:.1f}"
    )

    sat_text = f"SAT: {satellites_text}  HDOP {hdop_text}"

    gps_good = (
        gps_fix_type is not None
        and gps_fix_type >= GPS_MIN_FIX_TYPE
        and gps_satellites_visible is not None
        and gps_satellites_visible > GPS_MIN_SATELLITES_EXCLUSIVE
        and gps_hdop is not None
        and gps_hdop <= GPS_MAX_HDOP
    )

    gps_color = (
        (80, 255, 80) if gps_good
        else (0, 0, 255)
    )

    gps_size, _ = cv2.getTextSize(
        gps_text,
        font,
        0.42,
        1,
    )

    sat_size, _ = cv2.getTextSize(
        sat_text,
        font,
        0.42,
        1,
    )

    right_text_width = max(
        gps_size[0],
        sat_size[0],
    )

    right_text_x = center_x + radius + max(
        15,
        int(frame_width * 0.02),
    )

    right_text_x = min(
        right_text_x,
        frame_width - right_text_width - 5,
    )

    cv2.putText(
        frame,
        gps_text,
        (right_text_x, speed_text_y),
        font,
        0.42,
        gps_color,
        1,
        cv2.LINE_AA,
    )

    cv2.putText(
        frame,
        sat_text,
        (right_text_x, heading_text_y),
        font,
        0.42,
        gps_color,
        1,
        cv2.LINE_AA,
    )

     # ---------------------------------------------------------
    # Copter symbol at compass center
    # Small circle + X
    # ---------------------------------------------------------
    copter_radius = max(5, int(radius * 0.045))

    # Small center circle
    diamond_size = max(6, int(radius * 0.03))

    diamond_points = np.array(
        [
            (center_x, center_y - diamond_size),      # top
            (center_x + diamond_size, center_y),      # right
            (center_x, center_y + diamond_size),      # bottom
            (center_x - diamond_size, center_y),      # left
        ],
        dtype=np.int32,
    )

    cv2.polylines(
        frame,
        [diamond_points],
        True,
        hud_color,
        1,
        cv2.LINE_AA,
    )
    # X inside the circle
    x_size = max(12, int(copter_radius * 1))

    cv2.line(
        frame,
        (center_x - x_size, center_y - x_size),
        (center_x + x_size, center_y + x_size),
        hud_color,
        1,
        cv2.LINE_AA,
    )

    cv2.line(
        frame,
        (center_x + x_size, center_y - x_size),
        (center_x - x_size, center_y + x_size),
        hud_color,
        1,
        cv2.LINE_AA,
    )

    # ---------------------------------------------------------
    # GPS warning at the compass center.
    #
    # GPS_RAW_INT fix_type:
    #   0 = no GPS
    #   1 = no fix
    #   2 = 2D fix
    #   3+ = valid 3D (or better) fix
    #
    # Missing GPS data and anything below 3D fix are treated as NOT FIX.
    #
    # The warning is split into TWO lines so the existing center copter
    # symbol (diamond + X) remains visible and is NOT covered.
    # ---------------------------------------------------------
    if gps_fix_type is None or gps_fix_type < 3:
        warning_color = (0, 0, 255)
        warning_font_scale = 0.48
        warning_thickness = 1

        top_text = " GPS NOT FIX"
        

        top_size, _ = cv2.getTextSize(
            top_text,
            font,
            warning_font_scale,
            warning_thickness,
        )



        # Leave a clear gap around the existing copter symbol.
        # Increase this value if you want the red text farther away
        # from the diamond/X.
        symbol_clearance = max(
            18,
            x_size + diamond_size + 6,
        )

        # "GPS" above the center symbol.
        top_x = center_x - top_size[0] // 2
        top_y = center_y - symbol_clearance

        cv2.putText(
            frame,
            top_text,
            (top_x, top_y),
            font,
            warning_font_scale,
            warning_color,
            warning_thickness,
            cv2.LINE_AA,
        )

def gps_fix_type_to_text(fix_type):
    if fix_type is None:
        return "--"

    fix_names = {
        0: "NO GPS",
        1: "NO FIX",
        2: "2D",
        3: "3D",
        4: "DGPS",
        5: "RTK FLOAT",
        6: "RTK FIX",
    }

    return fix_names.get(
        int(fix_type),
        str(int(fix_type)),
    )

def draw_lower_left_status_panel(
    frame,
    connected,
    telemetry_link_quality_percent,
    rc_rssi_percent,
    rc_failsafe,
    total_current_a,
    battery_voltage_v,
    battery_remaining_percent,
    test_alert_mode=0,
):
    """
    Lower-left panel with three-level colors:

    TEL / RC:
        GREEN  >= 40%
        YELLOW 20% .. <40%
        RED    <20%

    CUR:
        GREEN  <=60 A
        YELLOW >60 A .. <=90 A
        RED    >90 A

    BAT:
        GREEN  >=14.0 V
        YELLOW 13.2 V .. <14.0 V
        RED    <13.2 V
    """
    frame_height, frame_width = frame.shape[:2]

    green = (80, 255, 80)
    yellow = (0, 255, 255)
    red = (0, 0, 255)

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.42
    thickness = 1

    text_x = (
        max(10, int(frame_width * 0.015))
        + 40
    )

    line_spacing = max(
        22,
        int(frame_height * 0.045),
    )

    fourth_line_y = (
        frame_height
        - 12
        - 90
    )

    first_line_y = fourth_line_y - 3 * line_spacing

    # TEL
    if connected and telemetry_link_quality_percent is not None:
        tel_text = f"TEL: {telemetry_link_quality_percent}%"

        if telemetry_link_quality_percent < TEL_CRITICAL_PERCENT:
            tel_color = red
        elif telemetry_link_quality_percent < TEL_WARNING_PERCENT:
            tel_color = yellow
        else:
            tel_color = green
    else:
        tel_text = "TEL: --"
        tel_color = green

    # RC
    # When ArduPilot reports Radio Failsafe, or the reported receiver
    # signal value has dropped to 0, treat the RC link as disconnected.
    if (
        connected
        and rc_failsafe is not True
        and rc_rssi_percent is not None
        and rc_rssi_percent > 0
    ):
        rc_text = f"RC : {rc_rssi_percent}%"

        if rc_rssi_percent < RC_CRITICAL_PERCENT:
            rc_color = red
        elif rc_rssi_percent < RC_WARNING_PERCENT:
            rc_color = yellow
        else:
            rc_color = green
    else:
        rc_text = "RC : --"
        rc_color = green

    # CUR
    if connected and total_current_a is not None:
        current_text = f"CUR: {total_current_a:.1f}A"

        if total_current_a > CURRENT_CRITICAL_A:
            current_color = red
        elif total_current_a > CURRENT_WARNING_A:
            current_color = yellow
        else:
            current_color = green
    else:
        current_text = "CUR: --A"
        current_color = green

    # BAT
    if connected and battery_voltage_v is not None:
        voltage_text = f"{battery_voltage_v:.1f}V"

        if battery_voltage_v < BAT_VOLTAGE_CRITICAL:
            battery_color = red
        elif battery_voltage_v < BAT_VOLTAGE_WARNING:
            battery_color = yellow
        else:
            battery_color = green
    else:
        voltage_text = "--V"
        battery_color = green

    if connected and battery_remaining_percent is not None:
        battery_percent_text = f"{battery_remaining_percent}%"
    else:
        battery_percent_text = "--%"

    battery_text = f"BAT: {voltage_text}  {battery_percent_text}"

    # Manual alert-test override.
    # Keep the real displayed values; only force the alert state/color.
    if test_alert_mode == 1:
        tel_color = yellow
        rc_color = yellow
        current_color = yellow
        battery_color = yellow

    elif test_alert_mode == 2:
        tel_color = red
        rc_color = red
        current_color = red
        battery_color = red

    lines = (
        (tel_text, tel_color),
        (rc_text, rc_color),
        (current_text, current_color),
        (battery_text, battery_color),
    )

    for line_index, (text, color) in enumerate(lines):
        text_y = first_line_y + line_index * line_spacing

        cv2.putText(
            frame,
            text,
            (text_x, text_y),
            font,
            font_scale,
            color,
            thickness,
            cv2.LINE_AA,
        )

def draw_system_warnings(
    frame,
    connected,
    telemetry_link_quality_percent,
    rc_rssi_percent,
    total_current_a,
    battery_voltage_v,
    test_alert_mode=0,
):
    """
    Upper-right warning messages.

    Warning range:
        steady YELLOW

    Critical range:
        flashing RED
    """
    # In normal mode, warnings require a live telemetry connection.
    # In manual test modes 1/2, warnings must still be visible even when
    # telemetry is disconnected.
    if not connected and test_alert_mode == 0:
        return

    yellow = (0, 255, 255)
    red = (0, 0, 255)

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.52
    thickness = 1

    warnings = []

    # Manual test mode overrides the live threshold logic.
    if test_alert_mode == 1:
        warnings = [
            ("Telemetry is low", "warning"),
            ("RC is low", "warning"),
            ("Current is high", "warning"),
            ("Battery is low", "warning"),
        ]

    elif test_alert_mode == 2:
        warnings = [
            ("Telemetry is low", "critical"),
            ("RC is low", "critical"),
            ("Current is high", "critical"),
            ("Battery is low", "critical"),
        ]

    # Normal live threshold logic.
    elif test_alert_mode == 0 and telemetry_link_quality_percent is not None:
        if telemetry_link_quality_percent < TEL_CRITICAL_PERCENT:
            warnings.append(("Telemetry is low", "critical"))
        elif telemetry_link_quality_percent < TEL_WARNING_PERCENT:
            warnings.append(("Telemetry is low", "warning"))

    # RC
    if test_alert_mode == 0 and rc_rssi_percent is not None:
        if rc_rssi_percent < RC_CRITICAL_PERCENT:
            warnings.append(("RC is low", "critical"))
        elif rc_rssi_percent < RC_WARNING_PERCENT:
            warnings.append(("RC is low", "warning"))

    # CUR
    if test_alert_mode == 0 and total_current_a is not None:
        if total_current_a > CURRENT_CRITICAL_A:
            warnings.append(("Current is high", "critical"))
        elif total_current_a > CURRENT_WARNING_A:
            warnings.append(("Current is high", "warning"))

    # BAT
    if test_alert_mode == 0 and battery_voltage_v is not None:
        if battery_voltage_v < BAT_VOLTAGE_CRITICAL:
            warnings.append(("Battery is low", "critical"))
        elif battery_voltage_v < BAT_VOLTAGE_WARNING:
            warnings.append(("Battery is low", "warning"))

    if not warnings:
        return

    blink_on = (
        time.monotonic() % WARNING_BLINK_PERIOD_S
    ) < (WARNING_BLINK_PERIOD_S / 2.0)

    right_margin = 10
    first_y = 20
    line_spacing = max(
        24,
        int(frame.shape[0] * 0.045),
    )

    visible_index = 0

    for text, severity in warnings:
        if severity == "critical":
            if not blink_on:
                continue
            color = red
        else:
            color = yellow

        text_y = first_y + visible_index * line_spacing
        text_size, _ = cv2.getTextSize(
            text,
            font,
            font_scale,
            thickness,
        )
        text_x = max(
            0,
            frame.shape[1] - right_margin - text_size[0],
        )

        cv2.putText(
            frame,
            text,
            (text_x, text_y),
            font,
            font_scale,
            color,
            thickness,
            cv2.LINE_AA,
        )

        visible_index += 1

def draw_disconnect_messages(
    frame,
    camera_connected,
    telemetry_connected,
    rc_connected,
):
    """
    Draw connection-loss messages over the middle of the pitch ladder.

    Each message is shown only while that connection is missing:
        USB Camera Disconnect
        Telemetry Disconnect
        RC Signal Disconnect
    """
    frame_height, frame_width = frame.shape[:2]

    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.5
    thickness = 1
    warning_color = (0, 0, 255)  # red
    shadow_color = (0, 0, 0)

    # Keep the three rows at fixed locations, so each warning has its own
    # position and simply disappears when that connection becomes available.
    messages = [
        ("USB Camera Disconnect", not camera_connected, -1),
        ("Telemetry Disconnect", not telemetry_connected, 0),
        ("RC Signal Disconnect", not rc_connected, 1),
    ]

    center_x = frame_width // 2
    center_y = int(frame_height * 0.39)
    line_spacing = max(30, int(frame_height * 0.1))

    for message, visible, row_offset in messages:
        if not visible:
            continue

        text_size, _ = cv2.getTextSize(
            message,
            font,
            font_scale,
            thickness,
        )

        text_x = center_x - text_size[0] // 2
        text_y = center_y + row_offset * line_spacing


        cv2.putText(
            frame,
            message,
            (text_x, text_y),
            font,
            font_scale,
            warning_color,
            thickness,
            cv2.LINE_AA,
        )

def heading_to_cardinal(heading_deg):
    if heading_deg is None:
        return "---"

    directions = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
    index = int((heading_deg + 22.5) // 45) % 8
    return directions[index]
def draw_top_mode_bar(
    frame,
    armed=None,
    telemetry_connected=False,
    flight_mode=None,
    last_confirmed_flight_mode=None,
    failsafe_active=False,
):
    """
    Top HUD status bar.

    Left:
        ARM / NO ARM

    Center (priority order):
        TEL LOST / FAILSAFE / A/P / FREE FLIGHT

    Right:
        The action Pixhawk is actually executing, derived from its current
        HEARTBEAT mode. This is never inferred from the RC switch position.
    """

    frame_height, frame_width = frame.shape[:2]

    # =========================================================
    # COLORS / FONT
    # =========================================================

    hud_color = (80, 255, 80)
    warning_color = (0, 0, 255)

    font = cv2.FONT_HERSHEY_SIMPLEX

    font_scale = 0.42
    thickness = 1


    # =========================================================
    # BAR WIDTH
    #
    # Do NOT use the whole screen.
    #
    # Approximately spans from the left speed tape
    # to the right altitude tape.
    # =========================================================

    bar_left = int(
        frame_width * 0.21
    )

    bar_right = int(
        frame_width * 0.79
    )


    # =========================================================
    # BAR HEIGHT
    #
    # Smaller than previous version.
    # =========================================================

    bar_top = 3

    bar_height = max(
        22,
        int(frame_height * 0.038),
    )

    bar_bottom = (
        bar_top
        + bar_height
    )


    # =========================================================
    # THREE SECTIONS
    # =========================================================

    bar_width = (
        bar_right
        - bar_left
    )

    section_width = (
        bar_width / 3.0
    )

    x1 = int(
        bar_left
        + section_width
    )

    x2 = int(
        bar_left
        + section_width * 2
    )


    # =========================================================
    # DIVIDER LINES
    #
    # Only two vertical lines.
    # No horizontal line underneath.
    # =========================================================

    cv2.line(
        frame,
        (x1, bar_top),
        (x1, bar_bottom),
        hud_color,
        1,
        cv2.LINE_AA,
    )

    cv2.line(
        frame,
        (x2, bar_top),
        (x2, bar_bottom),
        hud_color,
        1,
        cv2.LINE_AA,
    )


    # =========================================================
    # LEFT — ARM STATUS
    # =========================================================

    if armed is True:

        left_text = "ARM"
        left_color = hud_color

    else:

        left_text = "NO ARM"
        left_color = warning_color


    # =========================================================
    # CENTER / RIGHT — PIXHAWK ACTUAL FLIGHT CONTROL
    # =========================================================

    def mode_display_name(mode):
        if not mode:
            return "---"

        normalized = str(mode).strip().upper().replace(" ", "_")
        aliases = {
            "ALT_HOLD": "ALT HOLD",
            "ALTHOLD": "ALT HOLD",
            "RTL": "RETURN",
            "SMART_RTL": "RETURN",
            "LAND": "LAND",
            "LOITER": "LOITER",
        }
        return aliases.get(normalized, normalized.replace("_", " "))

    normalized_mode = (
        str(flight_mode).strip().upper().replace(" ", "_")
        if flight_mode
        else None
    )
    free_flight_modes = {
        "STABILIZE",
        "ACRO",
    }

    if not telemetry_connected:
        center_text = "TEL LOST"
        right_text = mode_display_name(last_confirmed_flight_mode)
        center_color = warning_color
        right_color = warning_color
    elif failsafe_active:
        center_text = "FAILSAFE"
        right_text = (
            "NO ACTION"
            if normalized_mode in free_flight_modes
            else mode_display_name(normalized_mode)
        )
        center_color = warning_color
        right_color = warning_color
    elif normalized_mode in free_flight_modes:
        center_text = "FREE FLIGHT"
        right_text = "---"
        center_color = hud_color
        right_color = hud_color
    elif normalized_mode:
        center_text = "A/P"
        right_text = mode_display_name(normalized_mode)
        center_color = hud_color
        right_color = hud_color
    else:
        center_text = "MODE"
        right_text = "---"
        center_color = warning_color
        right_color = warning_color


    # =========================================================
    # SECTION DEFINITIONS
    # =========================================================

    sections = [

        (
            left_text,
            left_color,
            bar_left,
            x1,
        ),

        (
            center_text,
            center_color,
            x1,
            x2,
        ),

        (
            right_text,
            right_color,
            x2,
            bar_right,
        ),

    ]


    # =========================================================
    # DRAW CENTERED TEXT
    # =========================================================

    for (
        text,
        color,
        section_left,
        section_right,
    ) in sections:

        text_size, baseline = (
            cv2.getTextSize(
                text,
                font,
                font_scale,
                thickness,
            )
        )

        text_width = (
            text_size[0]
        )

        text_height = (
            text_size[1]
        )


        # Horizontal center.
        text_x = int(
            section_left
            +
            (
                section_right
                - section_left
                - text_width
            )
            / 2
        )


        # Vertical center.
        text_y = int(
            bar_top
            +
            (
                bar_height
                + text_height
            )
            / 2
        )


        cv2.putText(
            frame,
            text,
            (
                text_x,
                text_y,
            ),
            font,
            font_scale,
            color,
            thickness,
            cv2.LINE_AA,
        )

def draw_telemetry(frame, state, test_alert_mode=0):
    with state.lock:
        connected = state.connected
        status = state.status
        voltage = state.battery_voltage_v
        battery_remaining = state.battery_remaining_percent
        current = state.total_current_a
        telemetry_link_quality = state.telemetry_link_quality_percent
        rc_rssi = state.rc_rssi_percent
        rc_failsafe = state.rc_failsafe
        altitude = state.altitude_m
        ground_speed = state.ground_speed_m_s
        vertical_speed = state.vertical_speed_m_s
        heading = state.heading_deg
        gps_fix_type = state.gps_fix_type
        gps_satellites_visible = state.gps_satellites_visible
        gps_hdop = state.gps_hdop
        yaw = state.yaw_deg
        pitch = state.pitch_deg
        roll = state.roll_deg

        # =========================
        # Actual Pixhawk ARM state
        # =========================
        armed = state.armed
        flight_mode = getattr(state, "flight_mode", None)
        last_confirmed_flight_mode = getattr(
            state,
            "last_confirmed_flight_mode",
            None,
        )
        failsafe_active = bool(
            getattr(state, "failsafe_active", False)
        )

        motor_percentages = list(state.motor_percentages)
        recording = state.recording
        record_count = len(state.records)

    # =========================================================
    # DRAW ALL HUD GRAPHICS ON A TEMPORARY FRAME
    #
    # frame:
    #     original analog video
    #
    # hud_frame:
    #     analog video + ALL green HUD graphics
    #
    # Nothing is drawn directly onto frame until the safe margin
    # has been applied.
    # =========================================================
    hud_frame = frame.copy()
        # =========================================================
    # TOP MODE / AUTOPILOT STATUS BAR
    # =========================================================

    draw_top_mode_bar(
        hud_frame,
        armed=armed,
        telemetry_connected=connected,
        flight_mode=flight_mode,
        last_confirmed_flight_mode=last_confirmed_flight_mode,
        failsafe_active=failsafe_active,
    )

    # Main speed / altitude tapes.
    draw_primary_hud_tapes(
        hud_frame,
        speed_m_s=ground_speed if connected else None,
        altitude_m=altitude if connected else None,
        vertical_speed_m_s=vertical_speed if connected else None,
    )

    # Central pitch ladder.
    draw_pitch_ladder(
        hud_frame,
        pitch_deg=pitch if connected else None,
        roll_deg=roll if connected else None,
    )


    # Top-center roll / bank indicator.
    draw_roll_indicator(
        hud_frame,
        roll_deg=roll if connected else None,
    )

    # Aircraft reference / attitude symbol.
    draw_lower_center_symbol(
        hud_frame
    )

    # Rotating compass + SPD + HDG.
    # HUD graphics may use the complete video frame.
    draw_rotating_compass(
        hud_frame,
        heading_deg=yaw if connected else None,
        speed_m_s=ground_speed if connected else None,
        gps_fix_type=gps_fix_type if connected else None,
        gps_satellites_visible=(
            gps_satellites_visible if connected else None
        ),
        gps_hdop=gps_hdop if connected else None,
    )

    # Lower-left telemetry / RC / GPS / battery status.
    draw_lower_left_status_panel(
    hud_frame,
    connected=connected,
    telemetry_link_quality_percent=telemetry_link_quality,
    rc_rssi_percent=rc_rssi,
    rc_failsafe=rc_failsafe,
    total_current_a=current,
    battery_voltage_v=voltage,
    battery_remaining_percent=battery_remaining,
    test_alert_mode=test_alert_mode,
    )

    frame[:, :] = hud_frame

    # Upper-right TEL / RC / CUR / BAT alerts.
    draw_system_warnings(
        frame,
        connected=connected,
        telemetry_link_quality_percent=telemetry_link_quality,
        rc_rssi_percent=rc_rssi,
        total_current_a=current,
        battery_voltage_v=voltage,
        test_alert_mode=test_alert_mode,
    )