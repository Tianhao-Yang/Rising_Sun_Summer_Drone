import threading
from dataclasses import dataclass, field


@dataclass
class TelemetryState:

    connected: bool = False
    status: str = "Telemetry disconnected"

    battery_voltage_v: float | None = None
    battery_remaining_percent: int | None = None
    total_current_a: float | None = None

    # =========================
    # Link quality
    # =========================

    telemetry_link_quality_percent: int | None = None
    rc_rssi_percent: int | None = None

    # Local ground-station connection states used by the checklist.
    camera_connected: bool = False
    rc_connected: bool = False

    # Pixhawk pre-arm result from SYS_STATUS/MAV_SYS_STATUS_PREARM_CHECK.
    # None means that no valid pre-arm status is currently available.
    ready_to_arm: bool | None = None

    # Latched HUD warning-test results for the current application run.
    hud_warning_yellow_checked: bool = False
    hud_warning_red_checked: bool = False

    # Latched Information Panel warning tests for the preflight checklist.
    info_warning_yellow_checked: bool = False
    info_warning_red_checked: bool = False

    # 0 = live indicators, 1 = yellow test, 2 = red test.
    panel_test_alert_mode: int = 0

    # Motor number -> monotonic expiry time for ArduPilot
    # "Potential Thrust Loss (n)" STATUSTEXT warnings.
    potential_thrust_loss_until: dict[int, float] = field(
        default_factory=dict
    )

    # Warning/alert STATUSTEXT messages received directly from Pixhawk.
    drone_alerts: list[dict] = field(default_factory=list)
    next_drone_alert_id: int = 1


    # =========================
    # Main flight HUD values
    # =========================

    altitude_m: float | None = None
    ground_speed_m_s: float | None = None
    vertical_speed_m_s: float | None = None
    heading_deg: float | None = None


    # =========================
    # GPS
    # =========================

    # MAVLink fix_type >= 3:
    # valid 3D GPS fix
    gps_fix_type: int | None = None

    gps_satellites_visible: int | None = None
    gps_hdop: float | None = None

    # GLOBAL_POSITION_INT
    #
    # Stored in normal degrees:
    #
    # Toronto example:
    # latitude_deg  = 43.65
    # longitude_deg = -79.38
    latitude_deg: float | None = None
    longitude_deg: float | None = None


    # =========================
    # Attitude
    # =========================

    pitch_deg: float | None = None
    roll_deg: float | None = None
    yaw_deg: float | None = None


    # =========================
    # Motor outputs
    # =========================

    motor_percentages: list[float | None] = field(
        default_factory=lambda: [
            None,
            None,
            None,
            None,
        ]
    )


    # =========================
    # Raspberry Pi health
    #
    # Received as MAVLink NAMED_VALUE messages from
    # companion-computer component ID 191.
    # =========================

    pi_thr: int | None = None
    pi_temp_c: float | None = None
    pi_load_percent: float | None = None
    # 0 = BEFORE_TAKEOFF, 1 = CRUISING, 2 = AFTER_LANDING.
    pi_state: int | None = None


    # =========================
    # Ground-computer power
    # =========================

    pc_battery_percent: float | None = None
    pc_power_plugged: bool | None = None


    # =========================
    # Actual ArduPilot ARM state
    #
    # Updated from HEARTBEAT:
    #
    # MAV_MODE_FLAG_SAFETY_ARMED
    # =========================

    armed: bool = False

    # Current flight mode reported by the Pixhawk autopilot HEARTBEAT.
    # Examples: STABILIZE, ALT_HOLD, LOITER, RTL, LAND.
    flight_mode: str | None = None

    # Retained when telemetry is lost so the HUD can label it explicitly as
    # the last confirmed mode rather than pretending it is still live.
    last_confirmed_flight_mode: str | None = None

    # Failsafe state is driven only by Pixhawk STATUSTEXT trigger/clear
    # messages. The actual response is always taken from flight_mode.
    failsafe_active: bool = False
    failsafe_reason: str | None = None


    # =========================
    # Safety-switch/logging state
    # =========================

    motor_outputs_enabled: bool | None = None

    recording: bool = False
    recording_start_time: float | None = None
    recording_session_name: str | None = None

    # Identity of the most recently completed ground-side flight recording.
    # The checklist uses this value to follow the same session even after the
    # Bluetooth receiver merges/renames its folder around the verified CSV.
    after_landing_session_name: str | None = None
    after_landing_session_directory: str | None = None

    records: list[dict] = field(
        default_factory=list
    )

    last_log_sample_time: float = 0.0


    # =========================
    # Connection timing
    # =========================

    last_heartbeat_time: float = 0.0
    last_rc_message_time: float = 0.0


    # =========================
    # RC receiver state
    # =========================

    # True  = Radio/RC failsafe
    # False = RC healthy
    # None  = not determined
    rc_failsafe: bool | None = None


    # =========================
    # Thread lock
    # =========================

    lock: threading.Lock = field(
        default_factory=threading.Lock,
        repr=False,
    )