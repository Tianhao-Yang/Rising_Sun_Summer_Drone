import math
import os
import re
import time
from collections import deque

# Channels 9-16 in SERVO_OUTPUT_RAW are MAVLink 2 extension fields.  Force
# pymavlink to use MAVLink 2 from the first connection so a cold-started link
# does not need one app run to negotiate the protocol before these fields
# become available.
os.environ["MAVLINK20"] = "1"

from pymavlink import mavutil

try:
    import psutil
except ImportError:
    psutil = None

from config import (
    TELEMETRY_PORT,
    TELEMETRY_BAUD,
    TELEMETRY_RECONNECT_INTERVAL,
    HEARTBEAT_TIMEOUT,
    MESSAGE_REQUEST_RETRY_INTERVAL,
    MOTOR_OUTPUT_CHANNELS,
    OUTPUT_MIN,
    OUTPUT_MAX,
)
from core.flight_logging import (
    process_safety_state,
    append_log_sample_if_needed,
    stop_recording,
)


PC_POWER_UPDATE_INTERVAL = 5.0
THRUST_LOSS_WARNING_HOLD_S = 5.0
MOTOR_MESSAGE_REQUEST_INTERVAL = 1.0


def update_pc_power_state(state):
    """Read the ground computer's battery percentage and AC status."""
    battery = None

    if psutil is not None:
        try:
            battery = psutil.sensors_battery()
        except Exception:
            battery = None

    with state.lock:
        if battery is None:
            state.pc_battery_percent = None
            state.pc_power_plugged = None
        else:
            state.pc_battery_percent = float(battery.percent)
            state.pc_power_plugged = bool(battery.power_plugged)


def mavlink_named_value_name(msg):
    """Return a NAMED_VALUE_* name without MAVLink NUL padding."""
    name = getattr(msg, "name", "")

    if isinstance(name, bytes):
        name = name.decode("ascii", errors="ignore")

    return str(name).split("\x00", 1)[0].strip().upper()


def pixhawk_flight_mode_name(msg):
    """Return the actual ArduPilot mode carried by an autopilot heartbeat."""
    try:
        mode_name = mavutil.mode_string_v10(msg)
    except Exception:
        return None

    if mode_name is None:
        return None

    mode_name = str(mode_name).strip().upper().replace(" ", "_")
    if not mode_name or mode_name.startswith("MODE("):
        return None
    return mode_name

def pwm_equivalent_to_percent(output_value):
    """
    Convert ArduPilot's 1000-2000 motor-output representation to 0-100%.

    This is the commanded output percentage, not actual mechanical RPM.
    """
    if output_value is None or output_value == 0:
        return None

    percentage = (
        (output_value - OUTPUT_MIN)
        / (OUTPUT_MAX - OUTPUT_MIN)
        * 100.0
    )
    

    return max(0.0, min(100.0, percentage))

def request_message_interval(master, message_id, frequency_hz):
    """
    Ask ArduPilot to send a MAVLink message at the requested frequency.
    """
    interval_us = int(1_000_000 / frequency_hz)

    master.mav.command_long_send(
        master.target_system,
        master.target_component,
        mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
        0,
        message_id,
        interval_us,
        0,
        0,
        0,
        0,
        0,
    )

def request_required_messages(master):
    # SYS_STATUS:
    # battery voltage/current and safety-switch state.
    request_message_interval(
        master,
        mavutil.mavlink.MAVLINK_MSG_ID_SYS_STATUS,
        10,
    )

    # BATTERY_STATUS: another source for battery voltage/current.
    request_message_interval(
        master,
        mavutil.mavlink.MAVLINK_MSG_ID_BATTERY_STATUS,
        5,
    )

    # SERVO_OUTPUT_RAW: motor output commands for channels 9-12.
    request_message_interval(
        master,
        mavutil.mavlink.MAVLINK_MSG_ID_SERVO_OUTPUT_RAW,
        10,
    )

    # ArduPilot groups SERVO_OUTPUT_RAW under the RC_CHANNELS data stream.
    # Some telemetry links acknowledge MAV_CMD_SET_MESSAGE_INTERVAL but do
    # not actually start this particular stream.  The standalone motor probe
    # proved that this explicit request makes channels 9-12 arrive, so keep
    # both requests for compatibility with different ArduPilot/MAVLink links.
    master.mav.request_data_stream_send(
        master.target_system,
        master.target_component,
        mavutil.mavlink.MAV_DATA_STREAM_RC_CHANNELS,
        10,
        1,
    )

    # ACTUATOR_OUTPUT_STATUS is a normalized-output fallback for systems
    # where SERVO_OUTPUT_RAW does not carry MAVLink2 servo9..servo16 fields.
    actuator_message_id = getattr(
        mavutil.mavlink,
        "MAVLINK_MSG_ID_ACTUATOR_OUTPUT_STATUS",
        None,
    )
    if actuator_message_id is not None:
        request_message_interval(
            master,
            actuator_message_id,
            10,
        )

    # VFR_HUD: ground speed and heading.
    request_message_interval(
        master,
        mavutil.mavlink.MAVLINK_MSG_ID_VFR_HUD,
        10,
    )

    # GLOBAL_POSITION_INT: altitude relative to home in millimetres.
    request_message_interval(
        master,
        mavutil.mavlink.MAVLINK_MSG_ID_GLOBAL_POSITION_INT,
        10,
    )

    # GPS_RAW_INT: GPS receiver fix status.
    request_message_interval(
        master,
        mavutil.mavlink.MAVLINK_MSG_ID_GPS_RAW_INT,
        5,
    )

    # ATTITUDE: pitch/roll/yaw. We use pitch for the HUD pitch ladder.
    request_message_interval(
        master,
        mavutil.mavlink.MAVLINK_MSG_ID_ATTITUDE,
        20,
    )

    # RC_CHANNELS: receiver RSSI.
    request_message_interval(
        master,
        mavutil.mavlink.MAVLINK_MSG_ID_RC_CHANNELS,
        5,
    )


def request_motor_output_messages(master):
    """Keep Pixhawk motor outputs active independently of other streams."""
    request_message_interval(
        master,
        mavutil.mavlink.MAVLINK_MSG_ID_SERVO_OUTPUT_RAW,
        10,
    )

    # The standalone probe succeeds because it explicitly enables this
    # stream. Repeating it is harmless and fixes the first-app-start case.
    master.mav.request_data_stream_send(
        master.target_system,
        master.target_component,
        mavutil.mavlink.MAV_DATA_STREAM_RC_CHANNELS,
        10,
        1,
    )

    actuator_message_id = getattr(
        mavutil.mavlink,
        "MAVLINK_MSG_ID_ACTUATOR_OUTPUT_STATUS",
        None,
    )
    if actuator_message_id is not None:
        request_message_interval(master, actuator_message_id, 10)

def close_master(master):
    if master is not None:
        try:
            master.close()
        except Exception:
            pass

def update_mavlink_packet_quality(
    msg,
    now,
    last_seq_by_source,
    quality_events,
    window_seconds=5.0,
):
    """
    Estimate telemetry link quality from MAVLink packet sequence continuity.

    MAVLink packets from each source contain an 8-bit sequence number.
    If the sequence jumps forward, the missing sequence numbers are counted
    as lost packets.

    A rolling time window is used so the displayed percentage responds to
    recent link quality instead of being an all-time average.

    Returns:
        int 0..100 when enough information is available, otherwise None.
    """
    try:
        seq = int(msg.get_seq()) & 0xFF
        src_system = int(msg.get_srcSystem())
        src_component = int(msg.get_srcComponent())
    except Exception:
        return None

    source_key = (
        src_system,
        src_component,
    )

    previous_seq = last_seq_by_source.get(source_key)
    last_seq_by_source[source_key] = seq

    # First packet from a source establishes the baseline.
    if previous_seq is None:
        quality_events.append(
            (
                now,
                1,  # received
                0,  # lost
            )
        )
    else:
        delta = (seq - previous_seq) & 0xFF

        # delta == 0 can be a duplicate packet.
        # Very large deltas usually indicate a reset/out-of-order stream rather
        # than hundreds of genuinely lost packets, so re-baseline instead.
        if delta == 0:
            pass
        elif 1 <= delta <= 127:
            lost_packets = max(
                0,
                delta - 1,
            )

            quality_events.append(
                (
                    now,
                    1,
                    lost_packets,
                )
            )
        else:
            # Sequence moved backwards/reset; do not treat it as massive loss.
            quality_events.append(
                (
                    now,
                    1,
                    0,
                )
            )

    cutoff = now - window_seconds

    while (
        quality_events
        and quality_events[0][0] < cutoff
    ):
        quality_events.popleft()

    received_total = sum(
        event[1]
        for event in quality_events
    )

    lost_total = sum(
        event[2]
        for event in quality_events
    )

    expected_total = (
        received_total
        + lost_total
    )

    if expected_total <= 0:
        return None

    quality = (
        received_total
        / expected_total
        * 100.0
    )

    return int(round(
        max(
            0.0,
            min(
                100.0,
                quality,
            ),
        )
    ))

def telemetry_worker(state, stop_event):
    master = None
    last_message_request_time = 0.0
    last_motor_message_request_time = 0.0
    last_pc_power_update_time = 0.0
    last_gcs_heartbeat_time = 0.0
    last_valid_servo_output_time = 0.0
    last_motor_debug_time = 0.0

    # Ensure the information panel always has these fields, even before the
    # first matching MAVLink packet or PC battery reading arrives.
    with state.lock:
        state.pi_thr = None
        state.pi_temp_c = None
        state.pi_load_percent = None
        state.ready_to_arm = None
        state.potential_thrust_loss_until.clear()
        state.pc_battery_percent = None
        state.pc_power_plugged = None
        state.drone_alerts.clear()
        state.next_drone_alert_id = 1
        state.motor_percentages = [None, None, None, None]
        state.flight_mode = None
        state.last_confirmed_flight_mode = None
        state.failsafe_active = False
        state.failsafe_reason = None

    # Packet-loss tracker used for the TEL percentage.
    # Keep sequence history separately for each MAVLink source component.
    last_seq_by_source = {}
    quality_events = deque()

    while not stop_event.is_set():
        now = time.monotonic()

        # PC power monitoring is local and remains available even while the
        # Pixhawk/telemetry radio is disconnected.
        if (
            now - last_pc_power_update_time
            >= PC_POWER_UPDATE_INTERVAL
        ):
            update_pc_power_state(state)
            last_pc_power_update_time = now

        if master is None:
            with state.lock:
                state.connected = False
                state.flight_mode = None
                state.status = f"Connecting to {TELEMETRY_PORT}..."
                state.telemetry_link_quality_percent = None
                state.ready_to_arm = None
                state.potential_thrust_loss_until.clear()

            last_seq_by_source.clear()
            quality_events.clear()

            try:
                master = mavutil.mavlink_connection(
                    TELEMETRY_PORT,
                    baud=TELEMETRY_BAUD,
                    autoreconnect=True,
                    source_system=255,
                )

                # Activate this telemetry channel as an independent GCS link
                # before waiting for Pixhawk. This must not depend on Pi
                # heartbeats or Pi telemetry traffic.
                master.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_GCS,
                    mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                    0,
                    0,
                    mavutil.mavlink.MAV_STATE_ACTIVE,
                )
                last_gcs_heartbeat_time = time.monotonic()

                heartbeat = master.wait_heartbeat(
                    timeout=5
                )

                if heartbeat is None:
                    raise TimeoutError(
                        "No heartbeat received"
                    )


                # =========================
                # One-time startup stream
                #
                # This helps ArduPilot start
                # sending telemetry immediately,
                # especially when the aircraft
                # was powered after the app.
                #
                # IMPORTANT:
                # Only do this ONCE after connect.
                # Do NOT repeat this every few seconds.
                # =========================

                master.mav.request_data_stream_send(
                    master.target_system,
                    master.target_component,
                    mavutil.mavlink.MAV_DATA_STREAM_ALL,
                    5,
                    1,
                )

                # The broad stream request must come first. Exact rates sent
                # before it can be overwritten during the first cold start.
                request_required_messages(master)
                request_motor_output_messages(master)


                now = time.monotonic()

                last_message_request_time = (
                    now
                )
                last_motor_message_request_time = now


                with state.lock:

                    state.connected = True

                    state.status = (
                        "Telemetry connected"
                    )

                    state.last_heartbeat_time = (
                        now
                    )


                print(
                    "Telemetry connected."
                )



            except Exception as error:
                print(f"Telemetry connection failed: {error}")

                close_master(master)
                master = None

                with state.lock:
                    state.connected = False
                    state.flight_mode = None
                    state.status = "Telemetry disconnected"
                    state.telemetry_link_quality_percent = None
                    state.rc_rssi_percent = None
                    state.last_rc_message_time = 0.0
                    state.rc_failsafe = None
                    state.ready_to_arm = None
                    state.potential_thrust_loss_until.clear()

                stop_event.wait(TELEMETRY_RECONNECT_INTERVAL)
                continue

        try:
            # Keep the PC registered as an active GCS on the Pixhawk MAVLink
            # channel even when Raspberry Pi is powered off.
            if now - last_gcs_heartbeat_time >= 1.0:
                master.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_GCS,
                    mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                    0,
                    0,
                    mavutil.mavlink.MAV_STATE_ACTIVE,
                )
                last_gcs_heartbeat_time = now

            # A short timeout prevents this thread from blocking forever.
            msg = master.recv_match(
                blocking=True,
                timeout=0.2,
            )

            now = time.monotonic()

            # Motor outputs get their own short retry. This does not wait for
            # the 15-second general retry and does not depend on restarting
            # the application a second time.
            if (
                now - last_motor_message_request_time
                >= MOTOR_MESSAGE_REQUEST_INTERVAL
            ):
                request_motor_output_messages(master)
                last_motor_message_request_time = now

            # Re-send the requested message rates every few seconds.
            # This makes startup order robust:
            #   Python first -> Pixhawk later
            #   Pixhawk first -> Python later
            # both recover automatically without restarting this program.
            if (
                now - last_message_request_time
                >= MESSAGE_REQUEST_RETRY_INTERVAL
            ):
                # Re-assert only the exact message rates we need.
                # Do NOT send MAV_DATA_STREAM_ALL again here.
                # Only a real autopilot HEARTBEAT refreshes the heartbeat timer.
                request_required_messages(master)

                last_message_request_time = now

            if msg is not None:
                message_type = msg.get_type()

                telemetry_quality = update_mavlink_packet_quality(
                    msg=msg,
                    now=now,
                    last_seq_by_source=last_seq_by_source,
                    quality_events=quality_events,
                    window_seconds=5.0,
                )

                if telemetry_quality is not None:
                    with state.lock:
                        state.telemetry_link_quality_percent = telemetry_quality

                if message_type == "HEARTBEAT":

                    # =========================
                    # Identify autopilot HEARTBEAT
                    # =========================

                    src_system = int(
                        msg.get_srcSystem()
                    )


                    autopilot_type = int(
                        getattr(
                            msg,
                            "autopilot",
                            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                        )
                    )


                    # Do not depend on target_component here.
                    #
                    # We want the heartbeat belonging to the
                    # aircraft system and actually identifying
                    # itself as an autopilot.
                    is_autopilot_heartbeat = (
                        src_system
                        == master.target_system
                        and
                        autopilot_type
                        != mavutil.mavlink.MAV_AUTOPILOT_INVALID
                    )


                    if is_autopilot_heartbeat:

                        # =========================
                        # ARM state
                        # =========================

                        armed = bool(
                            int(msg.base_mode)
                            &
                            mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
                        )

                        flight_mode = pixhawk_flight_mode_name(msg)


                        # =========================
                        # Connection state
                        # =========================

                        with state.lock:

                            state.connected = True

                            state.status = (
                                "Telemetry connected"
                            )

                            state.last_heartbeat_time = (
                                now
                            )

                            state.armed = armed

                            state.flight_mode = flight_mode

                            if flight_mode is not None:
                                state.last_confirmed_flight_mode = flight_mode

                elif message_type == "STATUSTEXT":
                    # ArduPilot sends explicit text when Radio Failsafe
                    # becomes active or clears. Use this as an additional
                    # source so the HUD follows the same state that Mission
                    # Planner displays.
                    status_text = str(
                        getattr(msg, "text", "")
                    ).strip()

                    # Only the Pixhawk autopilot component is allowed to feed
                    # the DRONE warning list. Pi/component STATUSTEXT is not a
                    # Drone warning, even when MAVLink routes it through the
                    # same telemetry radio.
                    if int(msg.get_srcComponent()) != int(
                        mavutil.mavlink.MAV_COMP_ID_AUTOPILOT1
                    ):
                        continue

                    status_text_lower = status_text.lower()

                    # Drone warnings come only from Pixhawk STATUSTEXT.
                    # MAV_SEVERITY 0..3 is displayed as ALERT (red), while
                    # MAV_SEVERITY_WARNING (4) is WARNING (yellow).
                    try:
                        status_severity = int(getattr(msg, "severity", 6))
                    except (TypeError, ValueError):
                        status_severity = 6

                    clear_words = (
                        " clear",
                        "cleared",
                        "recovered",
                        "resolved",
                    )
                    is_failsafe = "failsafe" in status_text_lower

                    is_prearm_text = (
                        status_text_lower.startswith("prearm:")
                        or status_text_lower.startswith("pre-arm:")
                    )

                    def failsafe_family(text):
                        for name, words in (
                            ("RADIO", ("radio", "rc ", "rc_")),
                            ("GCS", ("gcs", "ground station")),
                            ("EKF", ("ekf",)),
                            ("BATTERY", ("battery", "batt")),
                            ("TERRAIN", ("terrain",)),
                            ("FENCE", ("fence",)),
                        ):
                            if any(word in text for word in words):
                                return name
                        return "GENERIC"

                    with state.lock:
                        vehicle_armed = bool(state.armed)

                    event_family = failsafe_family(status_text_lower)
                    if event_family == "RADIO":
                        failsafe_reason_code = "RC"
                    elif event_family == "BATTERY":
                        if "critical" in status_text_lower:
                            failsafe_reason_code = "BAT CRIT"
                        elif "low" in status_text_lower:
                            failsafe_reason_code = "BAT LOW"
                        else:
                            failsafe_reason_code = "BAT"
                    elif event_family == "EKF":
                        failsafe_reason_code = "EKF"
                    elif event_family == "GCS":
                        failsafe_reason_code = "GCS"
                    elif event_family == "TERRAIN":
                        failsafe_reason_code = "TERRAIN"
                    elif event_family == "FENCE":
                        failsafe_reason_code = "FENCE"
                    else:
                        failsafe_reason_code = "OTHER"
                    battery_failsafe_event = (
                        vehicle_armed
                        and event_family == "BATTERY"
                        and (
                            " is low" in status_text_lower
                            or " is critical" in status_text_lower
                            or "battery low" in status_text_lower
                            or "battery critical" in status_text_lower
                        )
                    )
                    ekf_failsafe_event = (
                        vehicle_armed
                        and event_family == "EKF"
                        and "variance" in status_text_lower
                    )
                    is_failsafe_event = (
                        is_failsafe
                        or battery_failsafe_event
                        or ekf_failsafe_event
                    )
                    is_failsafe_clear = (
                        event_family != "GENERIC"
                        and any(
                            word in status_text_lower
                            for word in clear_words
                        )
                        and (
                            is_failsafe
                            or event_family in ("RADIO", "EKF", "BATTERY")
                        )
                    )

                    # A Pixhawk clear/recovery message removes the matching
                    # active failsafe. The recovery line itself is not added
                    # as a new warning.
                    if status_text and is_failsafe_clear:
                        cleared_family = failsafe_family(status_text_lower)
                        with state.lock:
                            state.drone_alerts = [
                                alert
                                for alert in state.drone_alerts
                                if not (
                                    alert.get("category") == "FAILSAFE"
                                    and alert.get("family") == cleared_family
                                )
                            ]
                            remaining_failsafes = [
                                alert
                                for alert in state.drone_alerts
                                if alert.get("category") == "FAILSAFE"
                            ]
                            state.failsafe_active = bool(remaining_failsafes)
                            state.failsafe_reason = (
                                str(
                                    remaining_failsafes[-1].get(
                                        "reason",
                                        remaining_failsafes[-1].get("family"),
                                    )
                                )
                                if remaining_failsafes
                                else None
                            )

                    elif status_text and status_severity <= 5:
                        if (
                            is_prearm_text
                        ):
                            alert_category = "PREARM"
                        elif is_failsafe_event:
                            alert_category = "FAILSAFE"
                        else:
                            alert_category = "MANUAL"

                        with state.lock:
                            alerts = list(state.drone_alerts)
                            matching_alert = None
                            for existing in reversed(alerts):
                                if (
                                    existing.get("text") == status_text
                                    and int(existing.get("severity", 6))
                                    == status_severity
                                    and existing.get("category")
                                    == alert_category
                                ):
                                    matching_alert = existing
                                    break

                            if matching_alert is None:
                                alert_id = state.next_drone_alert_id
                                state.next_drone_alert_id += 1
                                alerts.append({
                                    "id": alert_id,
                                    "severity": status_severity,
                                    "text": status_text,
                                    "count": 1,
                                    "received_at": now,
                                    "category": alert_category,
                                    "family": (
                                        failsafe_family(status_text_lower)
                                        if alert_category == "FAILSAFE"
                                        else None
                                    ),
                                    "reason": (
                                        failsafe_reason_code
                                        if alert_category == "FAILSAFE"
                                        else None
                                    ),
                                })
                            else:
                                matching_alert["count"] = (
                                    int(matching_alert.get("count", 1)) + 1
                                )
                                matching_alert["received_at"] = now

                            # Bound memory while retaining recent Pixhawk
                            # warning history for the scrollable Drone area.
                            state.drone_alerts = alerts[-50:]

                            # A pre-arm complaint can contain the word
                            # "failsafe", but the aircraft is not executing a
                            # flight failsafe. Only a live Pixhawk failsafe
                            # event drives the HUD FAILSAFE label.
                            if is_failsafe_event and not is_prearm_text:
                                state.failsafe_active = True
                                state.failsafe_reason = failsafe_reason_code

                    thrust_loss_match = re.search(
                        r"potential\s+thrust\s+loss\s*\(\s*(\d+)\s*\)",
                        status_text,
                        re.IGNORECASE,
                    )

                    if thrust_loss_match is not None:
                        motor_number = int(thrust_loss_match.group(1))
                        if 1 <= motor_number <= 4:
                            with state.lock:
                                state.potential_thrust_loss_until[
                                    motor_number
                                ] = float("inf")

                    if "radio failsafe" in status_text_lower:
                        failsafe_cleared = (
                            "clear" in status_text_lower
                            or "off" in status_text_lower
                            or "recovered" in status_text_lower
                        )

                        failsafe_active = not failsafe_cleared

                        # "PreArm: Radio failsafe on" is explicitly active.
                        if "failsafe on" in status_text_lower:
                            failsafe_active = True

                        with state.lock:
                            state.rc_failsafe = failsafe_active

                            if failsafe_active:
                                state.rc_rssi_percent = None

                        print(
                            "RC failsafe state:",
                            "ACTIVE" if failsafe_active else "CLEARED",
                            f"({status_text})",
                        )

                elif message_type == "SYS_STATUS":
                    voltage = None
                    current = None

                    # voltage_battery is in millivolts.
                    if msg.voltage_battery not in (0, 65535):
                        voltage = msg.voltage_battery / 1000.0

                    # current_battery is in centiamps; -1 means unavailable.
                    if msg.current_battery != -1:
                        current = msg.current_battery / 100.0

                    outputs_enabled = bool(
                        msg.onboard_control_sensors_enabled
                        & mavutil.mavlink.MAV_SYS_STATUS_SENSOR_MOTOR_OUTPUTS
                    )

                    # RC receiver health.
                    #
                    # ArduPilot exposes the RC receiver in SYS_STATUS.
                    # When the receiver is enabled but its health bit drops,
                    # treat that as Radio Failsafe / RC disconnected.
                    rc_receiver_mask = getattr(
                        mavutil.mavlink,
                        "MAV_SYS_STATUS_SENSOR_RC_RECEIVER",
                        65536,  # MAVLink common enum fallback: 1 << 16
                    )

                    rc_receiver_present = bool(
                        msg.onboard_control_sensors_present
                        & rc_receiver_mask
                    )
                    rc_receiver_enabled = bool(
                        msg.onboard_control_sensors_enabled
                        & rc_receiver_mask
                    )
                    rc_receiver_healthy = bool(
                        msg.onboard_control_sensors_health
                        & rc_receiver_mask
                    )

                    # ArduPilot sets this SYS_STATUS bit healthy while all
                    # enabled pre-arm checks are passing. Do not infer this
                    # from the vehicle merely being disarmed.
                    prearm_mask = getattr(
                        mavutil.mavlink,
                        "MAV_SYS_STATUS_PREARM_CHECK",
                        0x10000000,
                    )
                    prearm_present = bool(
                        msg.onboard_control_sensors_present
                        & prearm_mask
                    )
                    prearm_enabled = bool(
                        msg.onboard_control_sensors_enabled
                        & prearm_mask
                    )
                    prearm_healthy = bool(
                        msg.onboard_control_sensors_health
                        & prearm_mask
                    )

                    with state.lock:
                        if voltage is not None:
                            state.battery_voltage_v = voltage

                        if current is not None:
                            state.total_current_a = current

                        if prearm_present and prearm_enabled:
                            state.ready_to_arm = prearm_healthy
                        else:
                            state.ready_to_arm = None

                        # Only update from SYS_STATUS if ArduPilot says the
                        # RC receiver sensor exists / is enabled.
                        if rc_receiver_present or rc_receiver_enabled:
                            state.rc_failsafe = not rc_receiver_healthy

                            if state.rc_failsafe:
                                # Do not keep displaying the last LQ value
                                # after the transmitter has been lost.
                                state.rc_rssi_percent = None

                    process_safety_state(
                        state,
                        outputs_enabled,
                        now,
                    )

                elif message_type == "BATTERY_STATUS":
                    voltage = None
                    current = None

                    valid_voltages_mv = [
                        value
                        for value in msg.voltages
                        if value not in (0, 65535)
                    ]

                    if valid_voltages_mv:
                        voltage = sum(valid_voltages_mv) / 1000.0

                    if msg.current_battery != -1:
                        current = msg.current_battery / 100.0

                    battery_remaining = getattr(msg, "battery_remaining", -1)
                    if battery_remaining is not None and battery_remaining >= 0:
                        battery_remaining = int(
                            max(0, min(100, battery_remaining))
                        )
                    else:
                        battery_remaining = None

                    with state.lock:
                        if voltage is not None:
                            state.battery_voltage_v = voltage

                        if current is not None:
                            state.total_current_a = current

                        if battery_remaining is not None:
                            state.battery_remaining_percent = battery_remaining

                elif message_type == "VFR_HUD":
                    # groundspeed and climb are metres per second.
                    # Positive climb means ascending; negative means descending.
                    with state.lock:
                        state.ground_speed_m_s = float(msg.groundspeed)
                        state.vertical_speed_m_s = float(msg.climb)

                        heading = float(msg.heading)
                        if heading >= 0:
                            state.heading_deg = heading % 360.0

                elif message_type == "ATTITUDE":
                    # MAVLink ATTITUDE roll/pitch/yaw are in radians.
                    pitch_deg = math.degrees(float(msg.pitch))
                    roll_deg = math.degrees(float(msg.roll))
                    yaw_deg = math.degrees(float(msg.yaw)) % 360.0

                    with state.lock:
                        state.pitch_deg = pitch_deg
                        state.roll_deg = roll_deg
                        state.yaw_deg = yaw_deg

                elif message_type == "GPS_RAW_INT":

                    # =========================
                    # GPS fix state
                    # =========================

                    fix_type = int(
                        msg.fix_type
                    )


                    # =========================
                    # Satellites
                    # =========================

                    satellites_visible = getattr(
                        msg,
                        "satellites_visible",
                        None,
                    )

                    if satellites_visible in (
                        None,
                        255,
                    ):

                        satellites_visible = None

                    else:

                        satellites_visible = int(
                            satellites_visible
                        )


                    # =========================
                    # HDOP
                    # =========================

                    eph = getattr(
                        msg,
                        "eph",
                        None,
                    )

                    if eph in (
                        None,
                        65535,
                    ):

                        hdop = None

                    else:

                        hdop = (
                            float(eph)
                            / 100.0
                        )


                    # =========================
                    # GPS latitude / longitude
                    #
                    # GPS_RAW_INT also contains
                    # lat / lon in degrees * 1E7.
                    #
                    # This is important because
                    # GLOBAL_POSITION_INT may not
                    # become available immediately
                    # when GPS first obtains a fix.
                    # =========================

                    latitude_deg = None
                    longitude_deg = None


                    raw_lat = getattr(
                        msg,
                        "lat",
                        None,
                    )

                    raw_lon = getattr(
                        msg,
                        "lon",
                        None,
                    )


                    # Only trust GPS coordinates
                    # when we actually have a 3D fix
                    # or better.
                    if (
                        fix_type >= 3
                        and
                        raw_lat is not None
                        and
                        raw_lon is not None
                    ):

                        latitude_deg = (
                            float(raw_lat)
                            / 1e7
                        )

                        longitude_deg = (
                            float(raw_lon)
                            / 1e7
                        )


                        # Reject invalid 0,0 position
                        if (
                            abs(latitude_deg) < 0.000001
                            and
                            abs(longitude_deg) < 0.000001
                        ):

                            latitude_deg = None
                            longitude_deg = None


                    # =========================
                    # Save GPS state
                    # =========================

                    with state.lock:

                        state.gps_fix_type = (
                            fix_type
                        )

                        state.gps_satellites_visible = (
                            satellites_visible
                        )

                        state.gps_hdop = (
                            hdop
                        )


                        if latitude_deg is not None:

                            state.latitude_deg = (
                                latitude_deg
                            )


                        if longitude_deg is not None:

                            state.longitude_deg = (
                                longitude_deg
                            )

                elif message_type == "GLOBAL_POSITION_INT":

                    # =========================
                    # Latitude / Longitude
                    #
                    # MAVLink sends degrees * 1E7
                    # =========================

                    raw_lat = getattr(
                        msg,
                        "lat",
                        None,
                    )

                    raw_lon = getattr(
                        msg,
                        "lon",
                        None,
                    )


                    latitude_deg = None
                    longitude_deg = None


                    if (
                        raw_lat is not None
                        and
                        raw_lon is not None
                    ):

                        latitude_deg = (
                            float(raw_lat)
                            / 1e7
                        )

                        longitude_deg = (
                            float(raw_lon)
                            / 1e7
                        )


                        # 0,0 normally means we do not
                        # have a useful global position.
                        if (
                            abs(latitude_deg) < 0.000001
                            and
                            abs(longitude_deg) < 0.000001
                        ):

                            latitude_deg = None
                            longitude_deg = None


                    # =========================
                    # Relative altitude
                    # =========================

                    relative_alt_mm = getattr(
                        msg,
                        "relative_alt",
                        None,
                    )


                    altitude_m = None


                    if relative_alt_mm is not None:

                        altitude_m = (
                            float(relative_alt_mm)
                            / 1000.0
                        )


                        # Altitude deadband
                        if (
                            -0.2
                            <= altitude_m
                            <= 0.2
                        ):

                            altitude_m = 0.0


                    # =========================
                    # Save state
                    # =========================

                    with state.lock:

                        if latitude_deg is not None:

                            state.latitude_deg = (
                                latitude_deg
                            )


                        if longitude_deg is not None:

                            state.longitude_deg = (
                                longitude_deg
                            )


                        if altitude_m is not None:

                            state.altitude_m = (
                                altitude_m
                            )

                elif message_type == "RC_CHANNELS":
                    rc_rssi = getattr(msg, "rssi", None)

                    if rc_rssi in (None, 255):
                        rc_percent = None
                    else:
                        rc_percent = int(round(
                            max(
                                0.0,
                                min(
                                    100.0,
                                    float(rc_rssi) / 254.0 * 100.0,
                                ),
                            )
                        ))

                    with state.lock:
                        state.last_rc_message_time = now

                        # RC_CHANNELS can continue to be transmitted by
                        # ArduPilot even after the physical RC link is lost,
                        # and its RSSI/LQ can retain the last valid value.
                        # Therefore never use it to clear a Radio Failsafe.
                        if (
                            state.rc_failsafe is True
                            or rc_percent is None
                            or rc_percent <= 0
                        ):
                            state.rc_rssi_percent = None
                        else:
                            state.rc_rssi_percent = rc_percent

                elif message_type == "SERVO_OUTPUT_RAW":
                    # Do not reject a valid packet solely because its source
                    # system or output-port metadata differs.  Radio/router
                    # links can rewrite that metadata even though the MAVLink2
                    # servo9_raw..servo12_raw extension fields are intact.
                    # The fields themselves are the reliable discriminator.
                    raw_values = [
                        getattr(msg, f"servo{channel}_raw", None)
                        for channel in MOTOR_OUTPUT_CHANNELS
                    ]
                    percentages = [
                        pwm_equivalent_to_percent(output_value)
                        for output_value in raw_values
                    ]

                    if any(value is not None for value in percentages):
                        with state.lock:
                            state.motor_percentages = percentages
                        last_valid_servo_output_time = now

                        # Temporary, rate-limited proof of the complete
                        # Pixhawk -> parser -> percentage conversion path.
                        if now - last_motor_debug_time >= 1.0:
                            print(
                                "[MOTOR OUTPUT] "
                                f"raw={raw_values} "
                                f"percent={[round(value, 1) if value is not None else None for value in percentages]}"
                            )
                            last_motor_debug_time = now
                    else:
                        # Missing servo9_raw..servo12_raw means this packet did
                        # not carry the MAVLink 2 extension fields; it does NOT
                        # prove that the motor output is zero.  Keep the values
                        # unknown so ACTUATOR_OUTPUT_STATUS can provide the
                        # fallback and so a cold-start protocol problem is not
                        # shown to the pilot as four real 0% readings.
                        with state.lock:
                            state.motor_percentages = [None] * 4

                elif message_type == "ACTUATOR_OUTPUT_STATUS":
                    # Prefer valid SERVO_OUTPUT_RAW data whenever it exists.
                    # Use normalized actuator values only when servo9..12 have
                    # not produced usable values recently.
                    if now - last_valid_servo_output_time >= 1.0:
                        actuator_values = list(
                            getattr(msg, "actuator", []) or []
                        )
                        active_mask = int(getattr(msg, "active", 0) or 0)
                        percentages = []

                        for channel in MOTOR_OUTPUT_CHANNELS:
                            index = int(channel) - 1
                            value = None

                            if 0 <= index < len(actuator_values):
                                try:
                                    normalized = float(actuator_values[index])
                                    is_active = (
                                        active_mask == 0
                                        or bool(active_mask & (1 << index))
                                    )
                                    if math.isfinite(normalized) and is_active:
                                        value = max(
                                            0.0,
                                            min(100.0, normalized * 100.0),
                                        )
                                except (TypeError, ValueError):
                                    value = None

                            percentages.append(value)

                        if any(value is not None for value in percentages):
                            with state.lock:
                                state.motor_percentages = percentages

                elif message_type in (
                    "NAMED_VALUE_FLOAT",
                    "NAMED_VALUE_INT",
                ):
                    # The companion Pi publishes these values through Pixhawk's
                    # MAVLink router using component ID 191.
                    value_name = mavlink_named_value_name(msg)
                    value = getattr(msg, "value", None)
                    source_component = int(msg.get_srcComponent())

                    if (
                        value is not None
                        and source_component
                        == mavutil.mavlink.MAV_COMP_ID_ONBOARD_COMPUTER
                    ):
                        with state.lock:
                            if value_name == "PI_THR":
                                state.pi_thr = int(value)
                            elif value_name == "PI_TEMP":
                                state.pi_temp_c = float(value)
                            elif value_name == "PI_LOAD":
                                state.pi_load_percent = float(value)
                            elif value_name == "PI_STATE":
                                phase = int(value)
                                if phase in (0, 1, 2):
                                    state.pi_state = phase

            append_log_sample_if_needed(state, now)

            with state.lock:
                heartbeat_age = now - state.last_heartbeat_time

            if heartbeat_age > HEARTBEAT_TIMEOUT:
                print("Heartbeat lost. Telemetry disconnected.")

                with state.lock:
                    state.connected = False
                    state.status = "Telemetry disconnected"
                    state.flight_mode = None
                    state.telemetry_link_quality_percent = None
                    state.rc_rssi_percent = None
                    state.last_rc_message_time = 0.0
                    state.rc_failsafe = None
                    state.ready_to_arm = None
                    state.potential_thrust_loss_until.clear()

                close_master(master)
                master = None
                last_message_request_time = 0.0
                last_motor_message_request_time = 0.0

        except Exception as error:
            print(f"Telemetry error: {error}")

            with state.lock:
                state.connected = False
                state.status = "Telemetry disconnected"
                state.flight_mode = None
                state.rc_rssi_percent = None
                state.last_rc_message_time = 0.0
                state.rc_failsafe = None
                state.ready_to_arm = None
                state.potential_thrust_loss_until.clear()

            close_master(master)
            master = None
            last_message_request_time = 0.0
            last_motor_message_request_time = 0.0

    # Save an unfinished recording when the program closes.
    with state.lock:
        unfinished_recording = state.recording

    if unfinished_recording:
        stop_recording(state)

    close_master(master)