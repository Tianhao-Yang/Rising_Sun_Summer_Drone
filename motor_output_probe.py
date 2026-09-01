"""Inspect the motor-output MAVLink messages emitted by a Pixhawk.

Close the ground-station application and Mission Planner before running this
script because a Windows COM port normally has only one owner.
"""

import time

from pymavlink import mavutil


PORT = "COM8"
BAUD = 57600
TEST_SECONDS = 20


def request_message(master, message_id, frequency_hz=10):
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


def compact_servo_message(message):
    values = {}
    for index in range(1, 17):
        name = f"servo{index}_raw"
        value = getattr(message, name, None)
        if value not in (None, 0, 65535):
            values[name] = value

    return {
        "port": getattr(message, "port", None),
        "values": values,
    }


def main():
    print(f"Opening {PORT} at {BAUD} baud...")
    master = mavutil.mavlink_connection(PORT, baud=BAUD)
    heartbeat = master.wait_heartbeat(timeout=10)
    if heartbeat is None:
        raise RuntimeError("No heartbeat received within 10 seconds")

    protocol_magic = getattr(getattr(heartbeat, "_header", None), "magic", None)
    protocol = {
        0xFD: "MAVLink 2",
        0xFE: "MAVLink 1",
    }.get(protocol_magic, f"unknown (magic={protocol_magic!r})")

    print(
        "Heartbeat received: "
        f"system={master.target_system}, component={master.target_component}, "
        f"protocol={protocol}"
    )

    request_message(master, mavutil.mavlink.MAVLINK_MSG_ID_SERVO_OUTPUT_RAW)

    actuator_id = getattr(
        mavutil.mavlink,
        "MAVLINK_MSG_ID_ACTUATOR_OUTPUT_STATUS",
        None,
    )
    if actuator_id is not None:
        request_message(master, actuator_id)

    # This request is retained as a fallback for firmware that does not accept
    # MAV_CMD_SET_MESSAGE_INTERVAL for SERVO_OUTPUT_RAW.
    master.mav.request_data_stream_send(
        master.target_system,
        master.target_component,
        mavutil.mavlink.MAV_DATA_STREAM_RC_CHANNELS,
        10,
        1,
    )

    print(
        f"Listening for {TEST_SECONDS} seconds. Arm only if it is safe to do so; "
        "changing throttle briefly makes the active outputs easier to identify."
    )

    deadline = time.monotonic() + TEST_SECONDS
    servo_count = 0
    actuator_count = 0
    last_servo = None
    last_actuator = None

    while time.monotonic() < deadline:
        message = master.recv_match(
            type=["SERVO_OUTPUT_RAW", "ACTUATOR_OUTPUT_STATUS"],
            blocking=True,
            timeout=1,
        )
        if message is None:
            continue

        message_type = message.get_type()
        if message_type == "SERVO_OUTPUT_RAW":
            servo_count += 1
            current = compact_servo_message(message)
            if current != last_servo:
                print("SERVO_OUTPUT_RAW:", current)
                last_servo = current

        elif message_type == "ACTUATOR_OUTPUT_STATUS":
            actuator_count += 1
            actuator = list(getattr(message, "actuator", []) or [])
            current = {
                "active": getattr(message, "active", None),
                "actuator": [round(float(value), 4) for value in actuator],
            }
            if current != last_actuator:
                print("ACTUATOR_OUTPUT_STATUS:", current)
                last_actuator = current

    print()
    print(
        f"Result: SERVO_OUTPUT_RAW={servo_count} messages, "
        f"ACTUATOR_OUTPUT_STATUS={actuator_count} messages"
    )

    if servo_count == 0 and actuator_count == 0:
        print(
            "No motor-output messages arrived. This is a Pixhawk stream/config "
            "problem, not an InformationWidget display problem."
        )
    elif servo_count:
        print(
            "Copy every SERVO_OUTPUT_RAW line above. Its port and field names "
            "identify the exact channel mapping needed by telemetry.py."
        )


if __name__ == "__main__":
    main()