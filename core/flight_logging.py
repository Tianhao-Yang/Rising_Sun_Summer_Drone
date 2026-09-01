"""Ground-station recording of Flight Display, HUD and raw USB camera."""

from __future__ import annotations

import json
import os
import shutil
import time
import re
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QCoreApplication, QObject, QTimer, Slot
from PySide6.QtGui import QImage

from config import BASE_LOG_DIRECTORY


VIDEO_FPS = 10.0
VIDEO_TIMER_INTERVAL_MS = int(round(1000.0 / VIDEO_FPS))
VIDEO_CODEC = "mp4v"
PENDING_SESSION_FILENAME = ".pending_session.json"
GROUND_SESSION_MARKER_FILENAME = ".ground_session.json"
FLIGHT_COUNTER_FILENAME = ".flight_counter.json"
DISARM_PHASE_SETTLE_SECONDS = 5.0
DISARM_MINIMUM_WAIT_SECONDS = 2.5


def _new_session_name():
    log_root = Path(BASE_LOG_DIRECTORY).resolve()
    log_root.mkdir(parents=True, exist_ok=True)
    counter_path = log_root / FLIGHT_COUNTER_FILENAME
    last_sequence = 0
    try:
        payload = json.loads(counter_path.read_text(encoding="utf-8"))
        last_sequence = max(0, int(payload.get("last_flight_sequence", 0)))
    except (OSError, ValueError, TypeError, AttributeError):
        pattern = re.compile(r"^flight_(\d{6})_")
        for path in log_root.iterdir():
            match = pattern.match(path.name)
            if match:
                last_sequence = max(last_sequence, int(match.group(1)))

    sequence = last_sequence + 1
    temporary = counter_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"last_flight_sequence": sequence}, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, counter_path)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return f"flight_{sequence:06d}_{stamp}"


def start_recording(state, now):
    """Telemetry-thread request to begin a three-video session."""
    with state.lock:
        if state.recording:
            return
        # Allocate a counter only after this ARM transition has been accepted.
        # Repeated callbacks while recording must not silently consume numbers.
        session_name = _new_session_name()
        state.recording = True
        state.recording_start_time = now
        state.recording_session_name = session_name
        state.records = []
        state.last_log_sample_time = 0.0
    print(f"Aircraft armed: video recording requested ({session_name}).")


def stop_recording(state):
    """Telemetry-thread request to finish the active video session."""
    with state.lock:
        if not state.recording:
            return
        state.recording = False
        state.recording_start_time = None
    print("Aircraft disarmed: video recording stop requested.")


def process_safety_state(state, outputs_enabled, now):
    """Compatibility hook used by telemetry.py; recording follows ARM state."""
    with state.lock:
        state.motor_outputs_enabled = outputs_enabled
        armed = bool(getattr(state, "armed", False))
        previous_armed = getattr(state, "video_logging_armed", None)
        state.video_logging_armed = armed
        currently_recording = bool(getattr(state, "recording", False))

    if previous_armed is None:
        if armed and not currently_recording:
            start_recording(state, now)
        return
    if not previous_armed and armed:
        start_recording(state, now)
    elif previous_armed and not armed:
        stop_recording(state)


def append_log_sample_if_needed(state, now):
    """Legacy hook: Windows logging is video-only, so no data samples."""
    return


def _qwidget_frame(widget):
    if widget is None or widget.width() <= 0 or widget.height() <= 0:
        return None
    pixmap = widget.grab()
    if pixmap.isNull():
        return None
    image = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
    width, height = image.width(), image.height()
    if width <= 0 or height <= 0:
        return None
    rgba = np.frombuffer(
        image.constBits(), dtype=np.uint8, count=image.sizeInBytes()
    ).reshape((height, image.bytesPerLine() // 4, 4))[:, :width]
    return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)


def _normalize_bgr_frame(frame):
    if frame is None:
        return None
    try:
        value = np.asarray(frame)
    except Exception:
        return None
    if value.ndim != 3 or value.shape[0] <= 0 or value.shape[1] <= 0:
        return None
    if value.shape[2] == 4:
        value = cv2.cvtColor(value, cv2.COLOR_BGRA2BGR)
    elif value.shape[2] != 3:
        return None
    if value.dtype != np.uint8:
        value = np.clip(value, 0, 255).astype(np.uint8)
    return np.ascontiguousarray(value)


class _VideoSink:
    def __init__(self, path, fps):
        self.path = Path(path)
        # Never expose an unfinished MP4 under its final filename. MP4 writes
        # its index during release(); a crash before then leaves invalid data.
        # Keep the working file outside the flight folder as well. The
        # Bluetooth receiver may merge that folder immediately after DISARM;
        # it must never see or move an MP4 that VideoWriter still has open.
        self.recording_path = (
            self.path.parent.parent
            / ".recording_video_tmp"
            / self.path.parent.name
            / self.path.name
        )
        self.fps = float(fps)
        self.writer = None
        self.frame_size = None
        self.frame_count = 0

    def write(self, frame):
        frame = _normalize_bgr_frame(frame)
        if frame is None:
            return False
        height, width = frame.shape[:2]
        if self.writer is None:
            width -= width % 2
            height -= height % 2
            if width < 2 or height < 2:
                return False
            self.frame_size = (width, height)
            self.recording_path.parent.mkdir(parents=True, exist_ok=True)
            self.recording_path.unlink(missing_ok=True)
            fourcc = cv2.VideoWriter_fourcc(*VIDEO_CODEC)
            self.writer = cv2.VideoWriter(
                str(self.recording_path), fourcc, self.fps, self.frame_size
            )
            if not self.writer.isOpened():
                self.writer.release()
                self.writer = None
                self.recording_path.unlink(missing_ok=True)
                raise RuntimeError(f"Cannot open video writer: {self.path}")
        if (frame.shape[1], frame.shape[0]) != self.frame_size:
            frame = cv2.resize(frame, self.frame_size, interpolation=cv2.INTER_AREA)
        self.writer.write(frame)
        self.frame_count += 1
        return True

    def close(self):
        if self.writer is not None:
            self.writer.release()
            self.writer = None
        if (
            self.frame_count > 0
            and self.recording_path.is_file()
            and self.recording_path.stat().st_size > 0
        ):
            os.replace(self.recording_path, self.path)
        else:
            self.recording_path.unlink(missing_ok=True)
        try:
            self.recording_path.parent.rmdir()
            self.recording_path.parent.parent.rmdir()
        except OSError:
            pass
        self.frame_size = None
        self.frame_count = 0


class VideoRecordingController(QObject):
    """GUI-thread controller for all three Windows-side MP4 files."""

    def __init__(self, state, dashboard_page, hud_page, parent=None):
        super().__init__(parent)
        self.state = state
        self.dashboard_page = dashboard_page
        self.hud_page = hud_page
        self.log_root = Path(BASE_LOG_DIRECTORY).resolve()
        self.log_root.mkdir(parents=True, exist_ok=True)
        print(f"Video log root: {self.log_root}")
        self.active = False
        self.session_name = None
        self.session_directory = None
        self.sinks = {}
        self.latest_camera_frame = None
        self.last_observed_armed = None
        self.disarm_detected_at = None
        self.timer = QTimer(self)
        self.timer.setInterval(VIDEO_TIMER_INTERVAL_MS)
        self.timer.timeout.connect(self.poll_and_capture)
        self.timer.start()
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    @Slot(object)
    def submit_camera_frame(self, frame):
        frame = _normalize_bgr_frame(frame)
        if frame is not None:
            self.latest_camera_frame = frame.copy()

    def _read_state(self):
        with self.state.lock:
            return (
                # The Pixhawk HEARTBEAT is the authoritative recording
                # trigger.  HUD and video recorder now read the same flag.
                bool(getattr(self.state, "armed", False)),
                getattr(self.state, "recording_session_name", None),
                getattr(self.state, "pi_state", None),
            )

    def _start_session(self, requested_name):
        if self.active:
            return
        self.session_name = str(requested_name or _new_session_name())
        self.session_directory = self.log_root / self.session_name
        if self.session_directory.exists():
            suffix = 2
            while (self.log_root / f"{self.session_name}_{suffix}").exists():
                suffix += 1
            self.session_name = f"{self.session_name}_{suffix}"
            self.session_directory = self.log_root / self.session_name
        self.session_directory.mkdir(parents=True, exist_ok=False)
        with self.state.lock:
            self.state.recording = True
            self.state.recording_session_name = self.session_name
            # A new flight invalidates the preceding after-landing checklist.
            self.state.after_landing_session_name = None
            self.state.after_landing_session_directory = None
        self.sinks = {
            "flight_display": _VideoSink(
                self.session_directory / "Flight_Display.mp4", VIDEO_FPS
            ),
            "hud": _VideoSink(self.session_directory / "HUD.mp4", VIDEO_FPS),
            "camera": _VideoSink(
                self.session_directory / "USB_Camera.mp4", VIDEO_FPS
            ),
        }
        self.active = True
        print(f"Video session started: {self.session_directory}")

    def _write_pending_session(self):
        pending_path = self.log_root / PENDING_SESSION_FILENAME
        temporary_path = self.log_root / f"{PENDING_SESSION_FILENAME}.tmp"
        payload = {
            "status": "awaiting_pi_log",
            "folder_name": self.session_directory.name,
            "started_at": self.session_name,
            "videos": ["Flight_Display.mp4", "HUD.mp4", "USB_Camera.mp4"],
        }
        temporary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temporary_path, pending_path)

        # This marker travels with the MP4 files if the Bluetooth receiver
        # later merges this ground folder into the Pi CSV folder.
        marker_path = self.session_directory / GROUND_SESSION_MARKER_FILENAME
        marker_temporary = marker_path.with_suffix(".json.tmp")
        marker_temporary.write_text(
            json.dumps(
                {
                    "ground_session_name": self.session_directory.name,
                    "status": "recording_complete",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        os.replace(marker_temporary, marker_path)

    def _stop_session(self, keep=True):
        if not self.active:
            return
        for sink in self.sinks.values():
            sink.close()
        directory = self.session_directory
        self.sinks = {}
        self.active = False
        if keep:
            self._write_pending_session()
            print(f"Video session saved; awaiting Pi log: {directory}")
        else:
            shutil.rmtree(directory, ignore_errors=True)
            print(f"Video session discarded: {directory}")
        with self.state.lock:
            self.state.recording = False
            self.state.recording_start_time = None
            self.state.recording_session_name = None
            if keep:
                self.state.after_landing_session_name = directory.name
                self.state.after_landing_session_directory = str(directory)
            else:
                self.state.after_landing_session_name = None
                self.state.after_landing_session_directory = None
        self.session_name = None
        self.session_directory = None

    @Slot()
    def poll_and_capture(self):
        aircraft_armed, requested_name, pi_state = self._read_state()

        if aircraft_armed != self.last_observed_armed:
            print(f"Video recorder observed Pixhawk armed={aircraft_armed}")
            self.last_observed_armed = aircraft_armed

        if aircraft_armed:
            self.disarm_detected_at = None
            if not self.active:
                self._start_session(requested_name)
        elif self.active:
            # Pi publishes PI_STATE periodically.  Give it time to replace
            # CRUISING (1) with the final disarmed state before deciding
            # whether this was a real flight or only an aborted ARM test.
            if self.disarm_detected_at is None:
                self.disarm_detected_at = time.monotonic()

            disarm_age = time.monotonic() - self.disarm_detected_at

            if disarm_age >= DISARM_MINIMUM_WAIT_SECONDS and pi_state == 0:
                # Delete only this session directory, never the logs root.
                self._stop_session(keep=False)
                self.disarm_detected_at = None
            elif disarm_age >= DISARM_MINIMUM_WAIT_SECONDS and pi_state == 2:
                self._stop_session(keep=True)
                self.disarm_detected_at = None
            elif (
                disarm_age >= DISARM_PHASE_SETTLE_SECONDS
            ):
                # Unknown/stale phase: preserve data rather than risk
                # deleting a real flight log.
                print(
                    "PI_STATE did not settle after DISARM; "
                    "preserving this video session."
                )
                self._stop_session(keep=True)
                self.disarm_detected_at = None
        if not self.active:
            return
        try:
            self.sinks["flight_display"].write(
                _qwidget_frame(self.dashboard_page)
            )
            self.sinks["hud"].write(_qwidget_frame(self.hud_page))
            self.sinks["camera"].write(self.latest_camera_frame)
        except Exception as error:
            print(f"Video recording error: {error}")

    def shutdown(self):
        self.timer.stop()
        if self.active:
            self._stop_session(keep=True)


def configure_video_recording(state, dashboard_page, hud_page, parent=None):
    return VideoRecordingController(
        state=state,
        dashboard_page=dashboard_page,
        hud_page=hud_page,
        parent=parent,
    )