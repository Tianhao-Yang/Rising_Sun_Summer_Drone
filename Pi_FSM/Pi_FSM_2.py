from enum import Enum, auto
from threading import Thread, Event, Lock
from time import sleep, monotonic
import signal
import os
import subprocess
import psutil
import csv
import math
import json
import hashlib
import socket
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from gpiozero import LED
from pymavlink import mavutil


# ==================================================
# Pixhawk connection
# ==================================================

PIXHAWK_PORT = "/dev/serial0"
PIXHAWK_BAUD = 57600

HEARTBEAT_TIMEOUT = 3.0
RECONNECT_DELAY = 2.0

# Raspberry Pi -> Pixhawk -> telemetry-radio MAVLink reporting
PI_HEARTBEAT_INTERVAL = 1.0
PI_HEALTH_INTERVAL = 2.0

# MAVLink component ID 191 = onboard/companion computer
PI_COMPONENT_ID = mavutil.mavlink.MAV_COMP_ID_ONBOARD_COMPUTER

# PI_STATE values sent to the ground side
PI_STATE_BEFORE_TAKEOFF = 0
PI_STATE_CRUISING = 1
PI_STATE_AFTER_LANDING = 2

# Flight-start detection: Pixhawk motor outputs are channels 9-12.
MOTOR_OUTPUT_CHANNELS = (9, 10, 11, 12)
OUTPUT_MIN = 1000
OUTPUT_MAX = 2000
MOTOR_START_THRESHOLD = 10.0
MOTOR_COUNT_REQUIRED = 2

# Flight log configuration
LOG_DIR = Path("/home/danielyang/Drone/logs")
LOG_SAMPLE_INTERVAL = 0.1  # 10 Hz
FLIGHT_COUNTER_FILE = LOG_DIR / ".flight_counter.json"
TORONTO_TIMEZONE = ZoneInfo("America/Toronto")
MIN_VALID_UNIX_USEC = 1_600_000_000_000_000
TIME_SOURCE_DISAGREEMENT_SECONDS = 2.0
GPS_TIME_MAX_AGE_SECONDS = 5.0

# Raspberry Pi -> Windows Bluetooth flight-log transfer.
# Windows ground station:
#   Bluetooth MAC: F0:20:FF:D2:13:AA
#   Incoming COM:  COM3
#
# COM3 is only the Windows-side local port used by bluetooth_log_receiver.py.
# The Pi connects to the Windows Bluetooth Serial Port Profile service by
# MAC address + RFCOMM channel. The channel is not guaranteed to equal COM3,
# so the Pi discovers it first and falls back to BT_RFCOMM_CHANNEL if needed.
BT_PC_ADDRESS = "F0:20:FF:D2:13:AA"
BT_RFCOMM_CHANNEL = 4
BT_PROTOCOL_VERSION = 1
BT_CONNECT_TIMEOUT = 15.0
BT_IO_TIMEOUT = 30.0
BT_RETRY_INTERVAL = 10.0
BT_CHUNK_SIZE = 64 * 1024


# ==================================================
# GPIO assignment
# ==================================================

# Navigation lights - constant ON while Pi program is running
navi1 = LED(12)
navi2 = LED(16)
navi3 = LED(6)
navi4 = LED(13)
navigation_lights = [navi1, navi2, navi3, navi4]

# Strobe lights
strobe1 = LED(24)
strobe2 = LED(25)
strobe3 = LED(5)
strobe4 = LED(4)
strobes = [strobe1, strobe2, strobe3, strobe4]

# Beacon lights
beacon1 = LED(20)
beacon2 = LED(19)
beacons = [beacon1, beacon2]


# ==================================================
# Light timing
# ==================================================

FLASH_TIME = 0.05
DOUBLE_GAP = 0.07
CYCLE_GAP = 0.9

BEACON_ON_TIME = 0.15
BEACON_CYCLE = 1.0


# ==================================================
# FSM states
# ==================================================

class FlightState(Enum):
    BEFORE_TAKEOFF = auto()
    CRUISING = auto()
    AFTER_LANDING = auto()


# ==================================================
# Shared state
# ==================================================

stop_program = Event()
strobe_enabled = Event()
beacon_enabled = Event()
log_transfer_requested = Event()

state_lock = Lock()
flight_state = FlightState.BEFORE_TAKEOFF

# Becomes True once >=2 motors exceed 10% during an armed period.
flight_started = False
motor_outputs = [0.0, 0.0, 0.0, 0.0]

# Latest Pixhawk state
pixhawk_connected = False
safety_released = False
armed = False
last_heartbeat_time = 0.0

# Latest values cached for the flight logger
flight_mode = 0
pixhawk_system_status = 0

roll_deg = float("nan")
pitch_deg = float("nan")
yaw_deg = float("nan")
roll_rate_dps = float("nan")
pitch_rate_dps = float("nan")
yaw_rate_dps = float("nan")

battery_voltage_v = float("nan")
battery_current_a = float("nan")

latitude_deg = float("nan")
longitude_deg = float("nan")
relative_alt_m = float("nan")
gps_alt_m = float("nan")
velocity_north_mps = float("nan")
velocity_east_mps = float("nan")
velocity_down_mps = float("nan")
groundspeed_mps = float("nan")
climb_mps = float("nan")

gps_fix_type = 0
gps_satellites = 0
gps_hdop = float("nan")
latest_gps_unix_usec = 0
latest_gps_time_received_monotonic = 0.0

rc_channels = [float("nan")] * 18
rc_rssi = float("nan")

sensor_present = 0
sensor_enabled = 0
sensor_health = 0

# Latest Pi health snapshot
pi_temp_c = float("nan")
pi_cpu_pct = float("nan")
pi_mem_pct = float("nan")
pi_throttled = -1
pi_uptime_s = 0.0

# Logger state
log_active = False
log_file = None
log_writer = None
log_path = None
log_start_monotonic = 0.0
last_log_sample_time = 0.0


# ==================================================
# Light helpers
# ==================================================

def lights_on(lights):
    for light in lights:
        light.on()


def lights_off(lights):
    for light in lights:
        light.off()


def navigation_on():
    lights_on(navigation_lights)


def navigation_off():
    lights_off(navigation_lights)


def strobes_on():
    lights_on(strobes)


def strobes_off():
    lights_off(strobes)


def beacons_on():
    lights_on(beacons)


def beacons_off():
    lights_off(beacons)


# ==================================================
# Light worker threads
# ==================================================

def strobe_worker():
    """Double-flash strobe while strobe_enabled is set."""

    while not stop_program.is_set():

        if not strobe_enabled.is_set():
            strobes_off()
            sleep(0.05)
            continue

        # First flash
        strobes_on()
        sleep(FLASH_TIME)
        strobes_off()

        if not strobe_enabled.is_set() or stop_program.is_set():
            continue

        sleep(DOUBLE_GAP)

        # Second flash
        strobes_on()
        sleep(FLASH_TIME)
        strobes_off()

        # Wait between double-flash cycles,
        # but remain responsive to disable / shutdown.
        end_time = monotonic() + CYCLE_GAP

        while monotonic() < end_time:
            if not strobe_enabled.is_set() or stop_program.is_set():
                break
            sleep(0.03)

    strobes_off()


def beacon_worker():
    """Single beacon flash once per BEACON_CYCLE while enabled."""

    while not stop_program.is_set():

        if not beacon_enabled.is_set():
            beacons_off()
            sleep(0.05)
            continue

        beacons_on()
        sleep(BEACON_ON_TIME)
        beacons_off()

        end_time = monotonic() + max(
            0.0,
            BEACON_CYCLE - BEACON_ON_TIME
        )

        while monotonic() < end_time:
            if not beacon_enabled.is_set() or stop_program.is_set():
                break
            sleep(0.03)

    beacons_off()


# ==================================================
# FSM logic
# ==================================================

def set_flight_state(new_state):
    global flight_state

    with state_lock:

        if new_state == flight_state:
            return

        old_state = flight_state
        flight_state = new_state

    print(f"FSM: {old_state.name} -> {new_state.name}", flush=True)


def pwm_to_percent(pwm):
    """Convert 1000-2000 us output to 0-100%."""
    if pwm is None or pwm <= 0:
        return 0.0
    value = (float(pwm) - OUTPUT_MIN) / (OUTPUT_MAX - OUTPUT_MIN) * 100.0
    return max(0.0, min(100.0, value))


def check_flight_started():
    """Latch a real-flight indication while the aircraft is armed."""
    global flight_started

    if not armed or flight_started:
        return

    count = sum(v > MOTOR_START_THRESHOLD for v in motor_outputs)
    if count >= MOTOR_COUNT_REQUIRED:
        flight_started = True
        print(
            f"FLIGHT START DETECTED: {count} motors > "
            f"{MOTOR_START_THRESHOLD:.0f}%",
            flush=True
        )


def update_fsm(current_armed):
    """
    Pi start -> BEFORE_TAKEOFF.

    ARM -> start a temporary flight log and enter CRUISING.

    While armed, >=2 motors >10% latches flight_started=True.

    DISARM:
      - no real flight -> BEFORE_TAKEOFF and delete the temporary log
      - real flight    -> AFTER_LANDING and keep the completed log

    AFTER_LANDING stays latched while disarmed.
    """
    global flight_started

    if current_armed:
        # New arm cycle after a completed flight.
        if flight_state == FlightState.AFTER_LANDING:
            flight_started = False

        if not log_active:
            start_flight_log()

        set_flight_state(FlightState.CRUISING)
        return

    # DISARMED
    if flight_state == FlightState.AFTER_LANDING:
        return

    if flight_started:
        set_flight_state(FlightState.AFTER_LANDING)
        stop_flight_log(keep_file=True)
        return

    # Arm/disarm without a real flight.
    set_flight_state(FlightState.BEFORE_TAKEOFF)
    stop_flight_log(keep_file=False)


# ==================================================
# Flight logging
# ==================================================

LOG_FIELDS = [
    "timestamp", "elapsed_s", "fsm_state", "armed", "safety_released",
    "flight_mode", "pixhawk_system_status",
    "roll_deg", "pitch_deg", "yaw_deg",
    "roll_rate_dps", "pitch_rate_dps", "yaw_rate_dps",
    "motor1_pct", "motor2_pct", "motor3_pct", "motor4_pct",
    "battery_voltage_v", "battery_current_a",
    "latitude_deg", "longitude_deg", "relative_alt_m", "gps_alt_m",
    "velocity_north_mps", "velocity_east_mps", "velocity_down_mps",
    "groundspeed_mps", "climb_mps",
    "gps_fix_type", "gps_satellites", "gps_hdop",
    *[f"rc{i}" for i in range(1, 19)], "rc_rssi",
    "sensor_present", "sensor_enabled", "sensor_health",
    "pi_temp_c", "pi_cpu_pct", "pi_mem_pct", "pi_throttled",
    "pi_uptime_s", "pi_heartbeat"
]


def next_flight_sequence():
    """Permanently consume one sequence number for this ARM/log cycle."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    last_sequence = 0
    try:
        payload = json.loads(FLIGHT_COUNTER_FILE.read_text(encoding="utf-8"))
        last_sequence = max(0, int(payload.get("last_flight_sequence", 0)))
    except (OSError, ValueError, TypeError, AttributeError):
        # First deployment: continue after any already-numbered Pi logs.
        pattern = re.compile(r"^flight_(\d{6})_")
        for path in LOG_DIR.glob("flight_*.csv"):
            match = pattern.match(path.name)
            if match:
                last_sequence = max(last_sequence, int(match.group(1)))

    sequence = last_sequence + 1
    temporary = FLIGHT_COUNTER_FILE.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"last_flight_sequence": sequence}, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, FLIGHT_COUNTER_FILE)
    return sequence


def network_time_is_synchronized():
    """True only when Linux reports that NTP has actually synchronized."""
    try:
        result = subprocess.run(
            ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        return result.returncode == 0 and result.stdout.strip().lower() == "yes"
    except Exception:
        return False


def reliable_log_datetime():
    """Return (Toronto datetime, source), preferring synchronized NTP."""
    network_time = None
    if network_time_is_synchronized():
        network_time = datetime.now(timezone.utc)

    gps_time = None
    gps_time_age = (
        monotonic() - latest_gps_time_received_monotonic
        if latest_gps_time_received_monotonic > 0.0
        else float("inf")
    )
    if (
        latest_gps_unix_usec >= MIN_VALID_UNIX_USEC
        and gps_time_age <= GPS_TIME_MAX_AGE_SECONDS
    ):
        try:
            gps_time = datetime.fromtimestamp(
                latest_gps_unix_usec / 1_000_000.0,
                tz=timezone.utc,
            )
        except (OverflowError, OSError, ValueError):
            gps_time = None

    if network_time is not None and gps_time is not None:
        difference = abs((network_time - gps_time).total_seconds())
        if difference > TIME_SOURCE_DISAGREEMENT_SECONDS:
            print(
                f"TIME WARNING: network and GPS differ by {difference:.1f}s; "
                "using network time",
                flush=True,
            )
        return network_time.astimezone(TORONTO_TIMEZONE), "NETWORK"
    if network_time is not None:
        return network_time.astimezone(TORONTO_TIMEZONE), "NETWORK"
    if gps_time is not None:
        return gps_time.astimezone(TORONTO_TIMEZONE), "GPS"
    return None, "UNKNOWN"

def start_flight_log():
    global log_active, log_file, log_writer, log_path
    global log_start_monotonic, last_log_sample_time

    if log_active:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    sequence = next_flight_sequence()
    reliable_time, time_source = reliable_log_datetime()
    stamp = (
        reliable_time.strftime("%Y-%m-%d_%H-%M-%S")
        if reliable_time is not None
        else "TIME_UNKNOWN"
    )
    log_path = LOG_DIR / f"flight_{sequence:06d}_{stamp}.csv"

    log_file = open(log_path, "w", newline="", encoding="utf-8")
    log_writer = csv.DictWriter(log_file, fieldnames=LOG_FIELDS)
    log_writer.writeheader()
    log_file.flush()

    log_start_monotonic = monotonic()
    last_log_sample_time = 0.0
    log_active = True
    print(
        f"LOG STARTED: {log_path} (time_source={time_source})",
        flush=True,
    )

def stop_flight_log(keep_file):
    global log_active, log_file, log_writer, log_path

    if not log_active:
        return

    path = log_path

    try:
        if log_file is not None:
            log_file.flush()
            log_file.close()
    except Exception:
        pass

    log_active = False
    log_file = None
    log_writer = None
    log_path = None

    if keep_file:
        print(f"LOG SAVED: {path}", flush=True)
        # File is closed and flushed before the Bluetooth worker sees it.
        log_transfer_requested.set()
    else:
        try:
            if path is not None and path.exists():
                path.unlink()
            print(f"LOG DELETED (no real flight): {path}", flush=True)
        except Exception as exc:
            print(f"LOG DELETE FAILED: {exc}", flush=True)


# ==================================================
# Bluetooth log transfer
# ==================================================

def log_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while True:
            chunk = file.read(BT_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def build_log_manifest():
    """Snapshot all completed Pi CSV logs; never include the active log."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    active_path = log_path if log_active else None
    manifest = []

    for path in sorted(LOG_DIR.glob("flight_*.csv")):
        if not path.is_file() or path == active_path:
            continue
        try:
            manifest.append({
                "name": path.name,
                "size": int(path.stat().st_size),
                "sha256": log_sha256(path),
            })
        except OSError as exc:
            print(f"[BT LOG] Cannot inspect {path}: {exc}", flush=True)

    return manifest


def send_bt_control(sock, message):
    payload = (json.dumps(message, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    sock.sendall(payload)


def recv_bt_control(sock, max_bytes=1024 * 1024):
    data = bytearray()
    while len(data) < max_bytes:
        byte = sock.recv(1)
        if not byte:
            raise ConnectionError("Ground station closed the Bluetooth connection")
        if byte == b"\n":
            message = json.loads(data.decode("utf-8"))
            if not isinstance(message, dict):
                raise ValueError("Bluetooth control message is not an object")
            return message
        data.extend(byte)
    raise ValueError("Bluetooth control message is too large")


def discover_ground_station_rfcomm_channel():
    """
    Return the Windows Serial Port Profile RFCOMM channel if BlueZ can see it.
    Fall back to BT_RFCOMM_CHANNEL when service discovery is unavailable.
    """
    try:
        result = subprocess.run(
            ["sdptool", "browse", BT_PC_ADDRESS],
            capture_output=True,
            text=True,
            timeout=12.0,
            check=False,
        )
    except Exception as exc:
        print(
            f"[BT LOG] RFCOMM service discovery unavailable: {exc}; "
            f"using channel {BT_RFCOMM_CHANNEL}",
            flush=True,
        )
        return BT_RFCOMM_CHANNEL

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        print(
            f"[BT LOG] RFCOMM service discovery failed: {detail}; "
            f"using channel {BT_RFCOMM_CHANNEL}",
            flush=True,
        )
        return BT_RFCOMM_CHANNEL

    in_serial_service = False
    for line in result.stdout.splitlines():
        text = line.strip()
        lower = text.lower()

        if lower.startswith("service name:"):
            in_serial_service = "serial port" in lower
            continue

        if in_serial_service and lower.startswith("channel:"):
            try:
                channel = int(text.split(":", 1)[1].strip())
            except ValueError:
                continue
            if channel > 0:
                print(
                    f"[BT LOG] Discovered Windows RFCOMM channel {channel}",
                    flush=True,
                )
                return channel

    print(
        f"[BT LOG] Serial Port service channel not found; "
        f"using channel {BT_RFCOMM_CHANNEL}",
        flush=True,
    )
    return BT_RFCOMM_CHANNEL


def connect_ground_station():
    channel = discover_ground_station_rfcomm_channel()
    sock = socket.socket(
        socket.AF_BLUETOOTH,
        socket.SOCK_STREAM,
        socket.BTPROTO_RFCOMM,
    )
    sock.settimeout(BT_CONNECT_TIMEOUT)
    try:
        sock.connect((BT_PC_ADDRESS, channel))
        sock.settimeout(BT_IO_TIMEOUT)
        return sock
    except Exception:
        sock.close()
        raise


def transfer_logs_once():
    """Synchronize completed logs and return only after final verification."""
    manifest = build_log_manifest()
    if not manifest:
        print("[BT LOG] No completed logs waiting for transfer", flush=True)
        return True

    by_name = {entry["name"]: entry for entry in manifest}
    sock = None

    try:
        print(
            f"[BT LOG] Connecting to {BT_PC_ADDRESS}, "
            "RFCOMM Serial Port service",
            flush=True,
        )
        sock = connect_ground_station()

        send_bt_control(sock, {
            "type": "HELLO",
            "protocol": BT_PROTOCOL_VERSION,
        })
        hello_ack = recv_bt_control(sock)
        if (
            hello_ack.get("type") != "HELLO_ACK"
            or int(hello_ack.get("protocol", -1)) != BT_PROTOCOL_VERSION
        ):
            raise RuntimeError(f"Unexpected HELLO_ACK: {hello_ack}")

        send_bt_control(sock, {"type": "MANIFEST", "logs": manifest})
        manifest_ack = recv_bt_control(sock)
        if manifest_ack.get("type") != "MANIFEST_ACK":
            raise RuntimeError(f"Unexpected MANIFEST_ACK: {manifest_ack}")

        requested_names = []
        for key in ("missing", "mismatched"):
            values = manifest_ack.get(key, [])
            if not isinstance(values, list):
                raise RuntimeError(f"Invalid {key} list in MANIFEST_ACK")
            for name in values:
                if name in by_name and name not in requested_names:
                    requested_names.append(name)

        for name in requested_names:
            entry = by_name[name]
            path = LOG_DIR / name
            send_bt_control(sock, {
                "type": "FILE_META",
                "name": name,
                "size": entry["size"],
                "sha256": entry["sha256"],
            })

            ready = recv_bt_control(sock)
            if ready.get("type") != "FILE_READY" or ready.get("name") != name:
                raise RuntimeError(f"Unexpected FILE_READY: {ready}")

            with path.open("rb") as file:
                while True:
                    chunk = file.read(BT_CHUNK_SIZE)
                    if not chunk:
                        break
                    sock.sendall(chunk)

            file_ack = recv_bt_control(sock)
            if (
                file_ack.get("type") != "FILE_ACK"
                or file_ack.get("status") != "OK"
                or file_ack.get("name") != name
                or int(file_ack.get("size", -1)) != entry["size"]
                or file_ack.get("sha256") != entry["sha256"]
            ):
                raise RuntimeError(f"File was not verified by Windows: {file_ack}")

            print(f"[BT LOG] Windows verified {name}", flush=True)

        send_bt_control(sock, {
            "type": "VERIFY_MANIFEST",
            "logs": manifest,
        })
        verify = recv_bt_control(sock)
        if (
            verify.get("type") != "VERIFY_RESULT"
            or verify.get("missing")
            or verify.get("mismatched")
        ):
            raise RuntimeError(f"Final verification failed: {verify}")

        print(
            f"[BT LOG] Synchronization complete: {len(manifest)} log(s) verified",
            flush=True,
        )
        # Deliberately retain Pi CSV files. They can be cleaned up manually later.
        return True

    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def bluetooth_log_worker():
    """Retry pending transfers without blocking MAVLink or the flight FSM."""
    while not stop_program.is_set():
        if not log_transfer_requested.wait(timeout=1.0):
            continue
        if stop_program.is_set():
            break

        try:
            if transfer_logs_once():
                log_transfer_requested.clear()
        except Exception as exc:
            print(
                f"[BT LOG] Transfer failed: {exc}; "
                f"retrying in {BT_RETRY_INTERVAL:.0f}s",
                flush=True,
            )
            stop_program.wait(BT_RETRY_INTERVAL)

def write_log_sample():
    global last_log_sample_time

    if not log_active or log_writer is None:
        return

    now = monotonic()
    if last_log_sample_time and now - last_log_sample_time < LOG_SAMPLE_INTERVAL:
        return
    last_log_sample_time = now

    with state_lock:
        state_name = flight_state.name

    row = {
        "timestamp": datetime.now().isoformat(timespec="milliseconds"),
        "elapsed_s": round(now - log_start_monotonic, 3),
        "fsm_state": state_name,
        "armed": int(bool(armed)),
        "safety_released": int(bool(safety_released)),
        "flight_mode": flight_mode,
        "pixhawk_system_status": pixhawk_system_status,
        "roll_deg": roll_deg, "pitch_deg": pitch_deg, "yaw_deg": yaw_deg,
        "roll_rate_dps": roll_rate_dps,
        "pitch_rate_dps": pitch_rate_dps,
        "yaw_rate_dps": yaw_rate_dps,
        "motor1_pct": motor_outputs[0], "motor2_pct": motor_outputs[1],
        "motor3_pct": motor_outputs[2], "motor4_pct": motor_outputs[3],
        "battery_voltage_v": battery_voltage_v,
        "battery_current_a": battery_current_a,
        "latitude_deg": latitude_deg, "longitude_deg": longitude_deg,
        "relative_alt_m": relative_alt_m, "gps_alt_m": gps_alt_m,
        "velocity_north_mps": velocity_north_mps,
        "velocity_east_mps": velocity_east_mps,
        "velocity_down_mps": velocity_down_mps,
        "groundspeed_mps": groundspeed_mps, "climb_mps": climb_mps,
        "gps_fix_type": gps_fix_type, "gps_satellites": gps_satellites,
        "gps_hdop": gps_hdop, "rc_rssi": rc_rssi,
        "sensor_present": sensor_present, "sensor_enabled": sensor_enabled,
        "sensor_health": sensor_health,
        "pi_temp_c": pi_temp_c, "pi_cpu_pct": pi_cpu_pct,
        "pi_mem_pct": pi_mem_pct, "pi_throttled": pi_throttled,
        "pi_uptime_s": pi_uptime_s, "pi_heartbeat": 1,
    }
    for i in range(18):
        row[f"rc{i+1}"] = rc_channels[i]

    log_writer.writerow(row)
    try:
        log_file.flush()
    except Exception:
        pass

# ==================================================
# Output logic
# ==================================================

def update_lights():
    """
    Navigation:
        ON whenever this program is running.

    Strobe:
        Flash when the Pixhawk physical safety is released.

    Beacon:
        Flash when the aircraft is ARMED.
    """

    navigation_on()

    if safety_released:
        strobe_enabled.set()
    else:
        strobe_enabled.clear()

    if armed:
        beacon_enabled.set()
    else:
        beacon_enabled.clear()


# ==================================================
# Pixhawk / MAVLink
# ==================================================

def connect_pixhawk():

    print(
        f"Connecting to Pixhawk on "
        f"{PIXHAWK_PORT} @ {PIXHAWK_BAUD}...",
        flush=True
    )

    master = mavutil.mavlink_connection(
        PIXHAWK_PORT,
        baud=PIXHAWK_BAUD,
        autoreconnect=True
    )

    master.wait_heartbeat(timeout=10)

    print(
        f"Pixhawk connected: "
        f"system={master.target_system}, "
        f"component={master.target_component}",
        flush=True
    )

    # Identify Pi packets as a companion-computer component
    # on the same MAVLink vehicle system.
    master.mav.srcSystem = master.target_system
    master.mav.srcComponent = PI_COMPONENT_ID

    print(
        f"Pi MAVLink identity: "
        f"system={master.target_system}, "
        f"component={PI_COMPONENT_ID}",
        flush=True
    )

    # Request SYS_STATUS at 2 Hz so we can read
    # the Pixhawk physical safety state.
    master.mav.command_long_send(
        master.target_system,
        master.target_component,
        mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
        0,
        mavutil.mavlink.MAVLINK_MSG_ID_SYS_STATUS,
        500000,   # 0.5 sec = 2 Hz
        0, 0, 0, 0, 0
    )

    print(
        "Requested SYS_STATUS at 2 Hz",
        flush=True
    )

    # Request motor outputs at 10 Hz for flight-start detection.
    master.mav.command_long_send(
        master.target_system,
        master.target_component,
        mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
        0,
        mavutil.mavlink.MAVLINK_MSG_ID_SERVO_OUTPUT_RAW,
        100000,
        0, 0, 0, 0, 0
    )

    print("Requested SERVO_OUTPUT_RAW at 10 Hz", flush=True)

    logger_streams = [
        (mavutil.mavlink.MAVLINK_MSG_ID_ATTITUDE, 100000),
        (mavutil.mavlink.MAVLINK_MSG_ID_GLOBAL_POSITION_INT, 100000),
        (mavutil.mavlink.MAVLINK_MSG_ID_VFR_HUD, 200000),
        (mavutil.mavlink.MAVLINK_MSG_ID_GPS_RAW_INT, 500000),
        (mavutil.mavlink.MAVLINK_MSG_ID_RC_CHANNELS, 100000),
        (mavutil.mavlink.MAVLINK_MSG_ID_BATTERY_STATUS, 500000),
    ]

    for message_id, interval_us in logger_streams:
        master.mav.command_long_send(
            master.target_system, master.target_component,
            mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
            message_id, interval_us, 0, 0, 0, 0, 0
        )

    print("Requested logger MAVLink streams", flush=True)

    return master


def process_mavlink_message(msg):

    global armed, safety_released, last_heartbeat_time
    global flight_mode, pixhawk_system_status
    global roll_deg, pitch_deg, yaw_deg
    global roll_rate_dps, pitch_rate_dps, yaw_rate_dps
    global battery_voltage_v, battery_current_a
    global latitude_deg, longitude_deg, relative_alt_m, gps_alt_m
    global velocity_north_mps, velocity_east_mps, velocity_down_mps
    global groundspeed_mps, climb_mps
    global gps_fix_type, gps_satellites, gps_hdop, rc_rssi
    global latest_gps_unix_usec, latest_gps_time_received_monotonic
    global sensor_present, sensor_enabled, sensor_health

    msg_type = msg.get_type()

    # --------------------------------------------------
    # ARM / DISARM
    # --------------------------------------------------

    if msg_type == "HEARTBEAT":

        # Ignore companion-computer/GCS heartbeats; only Pixhawk/autopilot
        # heartbeat is allowed to drive ARM/DISARM and the FSM.
        if getattr(msg, "autopilot", mavutil.mavlink.MAV_AUTOPILOT_INVALID) == mavutil.mavlink.MAV_AUTOPILOT_INVALID:
            return

        last_heartbeat_time = monotonic()
        flight_mode = getattr(msg, "custom_mode", 0)
        pixhawk_system_status = getattr(msg, "system_status", 0)

        new_armed = bool(
            msg.base_mode
            & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
        )

        if new_armed != armed:

            armed = new_armed

            print(
                f"ARMED: {armed}",
                flush=True
            )

        update_fsm(armed)

    # --------------------------------------------------
    # Physical Pixhawk safety switch
    # --------------------------------------------------

    elif msg_type == "SYS_STATUS":

        motor_outputs_bit = (
            mavutil.mavlink.MAV_SYS_STATUS_SENSOR_MOTOR_OUTPUTS
        )

        new_safety_released = bool(
            msg.onboard_control_sensors_enabled
            & motor_outputs_bit
        )

        sensor_present = getattr(msg, "onboard_control_sensors_present", 0)
        sensor_enabled = getattr(msg, "onboard_control_sensors_enabled", 0)
        sensor_health = getattr(msg, "onboard_control_sensors_health", 0)

        voltage = getattr(msg, "voltage_battery", 65535)
        if voltage not in (0, 65535):
            battery_voltage_v = voltage / 1000.0

        current = getattr(msg, "current_battery", -1)
        if current is not None and current >= 0:
            battery_current_a = current / 100.0

        if new_safety_released != safety_released:

            safety_released = new_safety_released

            print(
                f"SAFETY RELEASED: {safety_released}",
                flush=True
            )

    # Motor outputs 1-4: Pixhawk output channels 9-12
    elif msg_type == "SERVO_OUTPUT_RAW":
        for index, channel in enumerate(MOTOR_OUTPUT_CHANNELS):
            pwm = getattr(msg, f"servo{channel}_raw", 0)
            motor_outputs[index] = pwm_to_percent(pwm)
        check_flight_started()

    elif msg_type == "ATTITUDE":
        roll_deg = math.degrees(getattr(msg, "roll", float("nan")))
        pitch_deg = math.degrees(getattr(msg, "pitch", float("nan")))
        yaw_deg = math.degrees(getattr(msg, "yaw", float("nan")))
        roll_rate_dps = math.degrees(getattr(msg, "rollspeed", float("nan")))
        pitch_rate_dps = math.degrees(getattr(msg, "pitchspeed", float("nan")))
        yaw_rate_dps = math.degrees(getattr(msg, "yawspeed", float("nan")))

    elif msg_type == "GLOBAL_POSITION_INT":
        latitude_deg = getattr(msg, "lat", 0) / 1e7
        longitude_deg = getattr(msg, "lon", 0) / 1e7
        gps_alt_m = getattr(msg, "alt", 0) / 1000.0
        relative_alt_m = getattr(msg, "relative_alt", 0) / 1000.0
        velocity_north_mps = getattr(msg, "vx", 0) / 100.0
        velocity_east_mps = getattr(msg, "vy", 0) / 100.0
        velocity_down_mps = getattr(msg, "vz", 0) / 100.0

    elif msg_type == "VFR_HUD":
        groundspeed_mps = float(getattr(msg, "groundspeed", float("nan")))
        climb_mps = float(getattr(msg, "climb", float("nan")))

    elif msg_type == "GPS_RAW_INT":
        gps_fix_type = int(getattr(msg, "fix_type", 0))
        gps_satellites = int(getattr(msg, "satellites_visible", 0))
        eph = getattr(msg, "eph", 65535)
        gps_hdop = eph / 100.0 if eph not in (0, 65535) else float("nan")
        gps_unix_usec = int(getattr(msg, "time_usec", 0) or 0)
        if gps_fix_type >= 2 and gps_unix_usec >= MIN_VALID_UNIX_USEC:
            latest_gps_unix_usec = gps_unix_usec
            latest_gps_time_received_monotonic = monotonic()

    elif msg_type == "RC_CHANNELS":
        for idx in range(18):
            rc_channels[idx] = getattr(msg, f"chan{idx+1}_raw", float("nan"))
        rc_rssi = float(getattr(msg, "rssi", float("nan")))

    elif msg_type == "BATTERY_STATUS":
        voltages = getattr(msg, "voltages", None)
        if voltages:
            valid = [v for v in voltages if v not in (0, 65535)]
            if valid:
                battery_voltage_v = sum(valid) / 1000.0
        current = getattr(msg, "current_battery", -1)
        if current is not None and current >= 0:
            battery_current_a = current / 100.0

    update_lights()



# ==================================================
# Raspberry Pi health + outbound MAVLink telemetry
# ==================================================

def get_pi_state_code():
    """
    PI_STATE:
        0 = BEFORE_TAKEOFF
        1 = CRUISING
        2 = AFTER_LANDING
    """
    with state_lock:
        state = flight_state

    if state == FlightState.CRUISING:
        return PI_STATE_CRUISING

    if state == FlightState.AFTER_LANDING:
        return PI_STATE_AFTER_LANDING

    return PI_STATE_BEFORE_TAKEOFF


def get_pi_temperature_c():
    """Return Raspberry Pi CPU temperature in degrees C."""
    try:
        with open(
            "/sys/class/thermal/thermal_zone0/temp",
            "r",
            encoding="utf-8"
        ) as file:
            return float(file.read().strip()) / 1000.0
    except Exception:
        return float("nan")


def get_pi_load_percent():
    """Return current Raspberry Pi CPU utilization percentage."""
    try:
        return psutil.cpu_percent(interval=0.1)
    except Exception:
        return float("nan")


def get_pi_memory_percent():
    """Return percentage of RAM currently in use."""
    try:
        values = {}

        with open("/proc/meminfo", "r", encoding="utf-8") as file:
            for line in file:
                key, value = line.split(":", 1)
                values[key] = float(value.strip().split()[0])

        total = values["MemTotal"]
        available = values["MemAvailable"]

        return ((total - available) / total) * 100.0

    except Exception:
        return float("nan")


def get_pi_uptime_seconds():
    """Return Linux uptime in seconds."""
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as file:
            return float(file.read().split()[0])
    except Exception:
        return 0.0


def get_pi_throttled_flags():
    """
    Return Raspberry Pi get_throttled flags as an integer.

    Healthy example:
        throttled=0x0  -> PI_THR = 0
    """
    try:
        result = subprocess.run(
            ["vcgencmd", "get_throttled"],
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False
        )

        output = result.stdout.strip()

        if "=" not in output:
            return -1

        return int(output.split("=", 1)[1], 16)

    except Exception:
        return -1


def send_named_float(master, name, value, time_boot_ms):
    """Send a compact MAVLink NAMED_VALUE_FLOAT."""
    master.mav.named_value_float_send(
        time_boot_ms,
        name.encode("ascii"),
        float(value)
    )


def send_named_int(master, name, value, time_boot_ms):
    """Send a compact MAVLink NAMED_VALUE_INT."""
    master.mav.named_value_int_send(
        time_boot_ms,
        name.encode("ascii"),
        int(value)
    )


def send_pi_heartbeat(master):
    """
    Send a heartbeat identifying the Raspberry Pi as an onboard
    companion controller.
    """
    master.mav.heartbeat_send(
        mavutil.mavlink.MAV_TYPE_ONBOARD_CONTROLLER,
        mavutil.mavlink.MAV_AUTOPILOT_INVALID,
        0,
        0,
        mavutil.mavlink.MAV_STATE_ACTIVE
    )


def send_pi_health(master):
    global pi_temp_c, pi_cpu_pct, pi_mem_pct, pi_throttled, pi_uptime_s
    """
    Send Raspberry Pi / FSM information to Pixhawk.

    Values:
        PI_STATE : 0 before takeoff, 1 cruising, 2 after landing
        PI_TEMP  : CPU temperature in C
        PI_LOAD  : normalized 1-minute CPU load %
        PI_MEM   : RAM used %
        PI_UP    : Linux uptime in seconds
        PI_THR   : get_throttled bitmask as integer
                   (0 means 0x0)
    """
    uptime = get_pi_uptime_seconds()
    time_boot_ms = int(uptime * 1000) & 0xFFFFFFFF

    state_code = get_pi_state_code()
    temperature = get_pi_temperature_c()
    cpu_load = get_pi_load_percent()
    memory_used = get_pi_memory_percent()
    throttled = get_pi_throttled_flags()

    pi_temp_c = temperature
    pi_cpu_pct = cpu_load
    pi_mem_pct = memory_used
    pi_throttled = throttled
    pi_uptime_s = uptime

    send_named_int(master, "PI_STATE", state_code, time_boot_ms)
    send_named_float(master, "PI_TEMP", temperature, time_boot_ms)
    send_named_float(master, "PI_LOAD", cpu_load, time_boot_ms)
    send_named_float(master, "PI_MEM", memory_used, time_boot_ms)
    send_named_float(master, "PI_UP", uptime, time_boot_ms)
    send_named_int(master, "PI_THR", throttled, time_boot_ms)

    with state_lock:
        state_name = flight_state.name

    throttled_text = hex(throttled) if throttled >= 0 else "UNKNOWN"

    print(
        "[PI STATUS] "
        f"FSM={state_name} | "
        f"TEMP={temperature:.1f}C | "
        f"LOAD={cpu_load:.1f}% | "
        f"MEM={memory_used:.1f}% | "
        f"UPTIME={uptime:.0f}s | "
        f"THROTTLED={throttled_text}",
        flush=True
    )


# ==================================================
# Safe fallback when telemetry is lost
# ==================================================

def telemetry_lost_fallback():
    """
    If the Pi loses Pixhawk heartbeat:

        Navigation stays ON.
        Strobe OFF.
        Beacon OFF.

    This avoids leaving flight-status lights showing an old state.
    """

    global armed
    global safety_released

    armed = False
    safety_released = False

    strobe_enabled.clear()
    beacon_enabled.clear()

    navigation_on()


# ==================================================
# Graceful shutdown
# ==================================================

def request_shutdown(signum=None, frame=None):
    """
    Called by:
        Ctrl+C               -> SIGINT
        systemctl stop       -> SIGTERM

    Do not directly close GPIO here.
    We only request shutdown.
    main() performs the final cleanup.
    """

    print(
        "Shutdown signal received",
        flush=True
    )

    stop_program.set()
    strobe_enabled.clear()
    beacon_enabled.clear()
    log_transfer_requested.set()


def cleanup(master=None):
    """
    Force every light OFF and release GPIO resources.
    """

    stop_program.set()
    strobe_enabled.clear()
    beacon_enabled.clear()

    # Give worker threads a moment to leave.
    sleep(0.15)

    # Force all lights LOW.
    navigation_off()
    strobes_off()
    beacons_off()

    # Close MAVLink serial connection.
    if master is not None:
        try:
            master.close()
        except Exception:
            pass

    # Preserve a partial log if the service/program stops unexpectedly
    # during an active flight/arm cycle.
    if log_active:
        stop_flight_log(keep_file=True)

    # Release gpiozero resources.
    for light in navigation_lights + strobes + beacons:
        try:
            light.off()
            light.close()
        except Exception:
            pass

    print(
        "All lights OFF. GPIO released. Program stopped.",
        flush=True
    )


# ==================================================
# Main
# ==================================================

def main():

    global pixhawk_connected
    global last_heartbeat_time

    # Navigation lights come on immediately.
    navigation_on()
    strobes_off()
    beacons_off()

    print(
        "========================================",
        flush=True
    )

    print(
        "Drone FSM light controller started",
        flush=True
    )

    print(
        f"FSM state: {flight_state.name}",
        flush=True
    )

    print(
        "Navigation lights: ON",
        flush=True
    )

    print(
        "========================================",
        flush=True
    )

    # Independent flashing workers.
    strobe_thread = Thread(
        target=strobe_worker,
        daemon=True
    )

    beacon_thread = Thread(
        target=beacon_worker,
        daemon=True
    )

    bluetooth_thread = Thread(
        target=bluetooth_log_worker,
        daemon=True
    )

    strobe_thread.start()
    beacon_thread.start()
    bluetooth_thread.start()

    # Retry logs retained from an earlier flight or interrupted transfer.
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    retained_logs = sorted(LOG_DIR.glob("flight_*.csv"))
    if retained_logs:
        print(
            f"[BT LOG] Found {len(retained_logs)} retained log(s); "
            "requesting Bluetooth sync",
            flush=True,
        )
        log_transfer_requested.set()
    else:
        print("[BT LOG] No retained logs found at startup", flush=True)

    master = None

    last_pi_heartbeat_sent = 0.0
    last_pi_health_sent = 0.0

    try:

        while not stop_program.is_set():

            # ------------------------------------------
            # Connect / reconnect Pixhawk
            # ------------------------------------------

            if master is None:

                try:

                    master = connect_pixhawk()

                    pixhawk_connected = True

                    last_heartbeat_time = monotonic()

                    # Announce Pi immediately after every reconnect.
                    last_pi_heartbeat_sent = 0.0
                    last_pi_health_sent = 0.0

                except Exception as exc:

                    pixhawk_connected = False

                    telemetry_lost_fallback()

                    print(
                        f"Pixhawk connection failed: {exc}",
                        flush=True
                    )

                    # Responsive reconnect wait.
                    stop_program.wait(RECONNECT_DELAY)

                    continue

            # ------------------------------------------
            # Receive MAVLink
            # ------------------------------------------

            try:

                msg = master.recv_match(
                    blocking=False
                )

                if msg is not None:
                    process_mavlink_message(msg)

                write_log_sample()

                # Raspberry Pi -> Pixhawk -> telemetry radio
                now = monotonic()

                if (
                    now - last_pi_heartbeat_sent
                    >= PI_HEARTBEAT_INTERVAL
                ):
                    send_pi_heartbeat(master)
                    last_pi_heartbeat_sent = now

                if (
                    now - last_pi_health_sent
                    >= PI_HEALTH_INTERVAL
                ):
                    send_pi_health(master)
                    last_pi_health_sent = now

                # Detect a dead MAVLink connection even
                # when the serial device still exists.
                if (
                    last_heartbeat_time > 0
                    and monotonic() - last_heartbeat_time
                    > HEARTBEAT_TIMEOUT
                ):
                    raise ConnectionError(
                        "Pixhawk heartbeat timeout"
                    )

                sleep(0.01)

            except Exception as exc:

                if stop_program.is_set():
                    break

                print(
                    f"Pixhawk disconnected: {exc}",
                    flush=True
                )

                pixhawk_connected = False

                telemetry_lost_fallback()

                try:
                    master.close()
                except Exception:
                    pass

                master = None

                stop_program.wait(RECONNECT_DELAY)

    finally:

        cleanup(master)


# ==================================================
# Program entry
# ==================================================

if __name__ == "__main__":

    # Ctrl+C
    signal.signal(
        signal.SIGINT,
        request_shutdown
    )

    # systemctl stop Pi_FSM.service
    signal.signal(
        signal.SIGTERM,
        request_shutdown
    )
    main()