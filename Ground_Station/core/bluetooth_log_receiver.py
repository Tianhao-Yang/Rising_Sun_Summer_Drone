"""Ground-station receiver for the Raspberry Pi flight-log protocol.

Place this file at ``red_sun_app/core/bluetooth_log_receiver.py`` or run it
standalone from the project root.  The Raspberry Pi is the RFCOMM client and
this Windows computer is the RFCOMM server.

The receiver never acknowledges a file until it has:
  * received exactly the advertised byte count,
  * flushed the file to disk,
  * verified SHA-256,
  * atomically installed the final CSV in logs/<flight-name>/.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
import argparse
from datetime import datetime
from pathlib import Path
from typing import Callable


BT_PROTOCOL_VERSION = 1
BT_IO_TIMEOUT = 30.0
BT_CHUNK_SIZE = 64 * 1024
BT_SERIAL_BAUD = 115200

PROJECT_ROOT = Path(__file__).resolve().parent
if PROJECT_ROOT.name.lower() == "core":
    PROJECT_ROOT = PROJECT_ROOT.parent

LOG_ROOT = PROJECT_ROOT / "logs"
PENDING_SESSION_FILE = LOG_ROOT / ".pending_session.json"
PENDING_SESSIONS_FILE = LOG_ROOT / ".pending_sessions.json"
MATCH_ANCHOR_FILE = LOG_ROOT / ".match_anchor.json"
PENDING_SESSION_MATCH_TOLERANCE_SECONDS = 5.0
RECONCILE_INTERVAL_SECONDS = 1.0
_RECONCILE_LOCK = threading.RLock()

LOG_NAME_PATTERN = re.compile(
    r"^flight_(?:\d{6}_)?(?:\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}|TIME_UNKNOWN)\.csv$"
)
NEW_SESSION_PATTERN = re.compile(
    r"^flight_(?P<sequence>\d{6})_(?P<stamp>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}|TIME_UNKNOWN)$"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while True:
            chunk = file.read(BT_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def send_control(sock, message: dict) -> None:
    payload = (json.dumps(message, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    sock.sendall(payload)


def recv_control(sock, max_bytes: int = 1024 * 1024) -> dict:
    data = bytearray()
    while len(data) < max_bytes:
        byte = sock.recv(1)
        if not byte:
            raise ConnectionError("Connection closed while reading control data")
        if byte == b"\n":
            return json.loads(data.decode("utf-8"))
        data.extend(byte)
    raise ValueError("Bluetooth control message is too large")


def safe_log_name(name: object) -> str:
    name = str(name)
    if not LOG_NAME_PATTERN.fullmatch(name):
        raise ValueError(f"Rejected unsafe or unexpected log filename: {name!r}")
    return name


def session_folder_for_log(name: str) -> Path:
    return LOG_ROOT / Path(name).stem


def read_pending_session() -> dict | None:
    try:
        value = json.loads(PENDING_SESSION_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def clear_pending_session() -> None:
    try:
        PENDING_SESSION_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def parse_session_identity(value: str) -> tuple[int | None, datetime | None]:
    value = Path(str(value)).stem
    match = NEW_SESSION_PATTERN.fullmatch(value)
    if match:
        sequence = int(match.group("sequence"))
        stamp = match.group("stamp")
        if stamp == "TIME_UNKNOWN":
            return sequence, None
        return sequence, datetime.strptime(stamp, "%Y-%m-%d_%H-%M-%S")

    value = value.removeprefix("flight_")
    try:
        return None, datetime.strptime(value, "%Y-%m-%d_%H-%M-%S")
    except (TypeError, ValueError):
        return None, None


def parse_session_timestamp(value: str) -> datetime | None:
    return parse_session_identity(value)[1]


def session_names_match(folder_name: str, log_name: str) -> bool:
    folder_timestamp = Path(folder_name).name.removeprefix("flight_")
    log_timestamp = Path(log_name).stem.removeprefix("flight_")

    if folder_timestamp == log_timestamp:
        return True

    folder_time = parse_session_timestamp(folder_timestamp)
    log_time = parse_session_timestamp(log_timestamp)
    if folder_time is None or log_time is None:
        return False

    delta_seconds = abs((folder_time - log_time).total_seconds())
    return delta_seconds <= PENDING_SESSION_MATCH_TOLERANCE_SECONDS


def _read_pending_sessions() -> list[dict]:
    """Read the queue and import the old single-pending-file format."""
    sessions: list[dict] = []
    try:
        value = json.loads(PENDING_SESSIONS_FILE.read_text(encoding="utf-8"))
        if isinstance(value, list):
            sessions.extend(item for item in value if isinstance(item, dict))
    except (OSError, ValueError, TypeError):
        pass

    legacy = read_pending_session()
    if legacy and legacy.get("status") == "awaiting_pi_log":
        sessions.append(legacy)
        clear_pending_session()

    # De-duplicate without losing older unmatched sessions.
    result: list[dict] = []
    seen: set[str] = set()
    for item in sessions:
        folder_name = item.get("folder_name")
        if not isinstance(folder_name, str) or not folder_name:
            continue
        safe_name = Path(folder_name).name
        sequence, timestamp = parse_session_identity(safe_name)
        if safe_name in seen or (sequence is None and timestamp is None):
            continue
        source = LOG_ROOT / safe_name
        if source.is_dir():
            seen.add(safe_name)
            result.append({"folder_name": safe_name, "status": "awaiting_pi_log"})

    # Recover every ground-first recording, including folders created while
    # the Bluetooth receiver was stopped.  The legacy single pending file can
    # only remember the newest flight, so relying on it alone loses older
    # unmatched sessions.  A directory without a verified Pi CSV is pending.
    try:
        folders = sorted(LOG_ROOT.iterdir(), key=lambda path: path.name)
    except OSError:
        folders = []
    for source in folders:
        if not source.is_dir() or source.name in seen:
            continue
        sequence, timestamp = parse_session_identity(source.name)
        if sequence is None and timestamp is None:
            continue
        try:
            has_pi_csv = any(
                child.is_file() and LOG_NAME_PATTERN.fullmatch(child.name)
                for child in source.iterdir()
            )
        except OSError:
            continue
        if has_pi_csv:
            continue
        seen.add(source.name)
        result.append(
            {"folder_name": source.name, "status": "awaiting_pi_log"}
        )
    return result


def _write_pending_sessions(sessions: list[dict]) -> None:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = PENDING_SESSIONS_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(sessions, indent=2), encoding="utf-8")
    os.replace(temporary, PENDING_SESSIONS_FILE)


def register_ground_session(folder_name: str | Path) -> None:
    """Register a completed ground recording, then match it immediately.

    The ground recorder must call this only after it has closed its MP4 file.
    Keeping one queue entry per recording prevents a later flight from
    overwriting an older unmatched recording.
    """
    safe_name = Path(folder_name).name
    sequence, timestamp = parse_session_identity(safe_name)
    if sequence is None and timestamp is None:
        raise ValueError(f"Invalid ground-session folder name: {folder_name!r}")
    source = LOG_ROOT / safe_name
    if not source.is_dir():
        raise FileNotFoundError(source)

    with _RECONCILE_LOCK:
        sessions = _read_pending_sessions()
        if not any(item.get("folder_name") == safe_name for item in sessions):
            sessions.append(
                {"folder_name": safe_name, "status": "awaiting_pi_log"}
            )
            _write_pending_sessions(sessions)
        reconcile_all_sessions()


def _move_without_overwrite(source: Path, target_folder: Path) -> None:
    """Move one item without silently discarding a same-named file."""
    destination = target_folder / source.name
    if not destination.exists():
        shutil.move(str(source), str(destination))
        return
    if source.is_file() and destination.is_file():
        try:
            if source.stat().st_size == destination.stat().st_size:
                if sha256_file(source) == sha256_file(destination):
                    source.unlink()
                    return
        except OSError:
            pass
    counter = 1
    while True:
        candidate = target_folder / f"{source.stem}.ground-{counter}{source.suffix}"
        if not candidate.exists():
            shutil.move(str(source), str(candidate))
            return
        counter += 1


def _merge_ground_folder(source_folder: Path, target_folder: Path) -> None:
    target_folder.mkdir(parents=True, exist_ok=True)
    if source_folder == target_folder or not source_folder.is_dir():
        return
    for item in list(source_folder.iterdir()):
        _move_without_overwrite(item, target_folder)
    source_folder.rmdir()


def _read_match_anchor() -> tuple[int, int] | None:
    try:
        value = json.loads(MATCH_ANCHOR_FILE.read_text(encoding="utf-8"))
        return int(value["pi_sequence"]), int(value["ground_sequence"])
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _write_match_anchor(pi_sequence: int, ground_sequence: int) -> None:
    value = {
        "pi_sequence": pi_sequence,
        "ground_sequence": ground_sequence,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    temporary = MATCH_ANCHOR_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    os.replace(temporary, MATCH_ANCHOR_FILE)


def reconcile_all_sessions() -> int:
    """Match every waiting ground recording to existing Pi CSVs one-to-one.

    Reliable Pi times match within five seconds.  A successful time match also
    anchors both counters.  TIME_UNKNOWN logs then match by equal counter
    distance from that anchor (or by equal absolute counter before any anchor).
    A ground recording and a Pi CSV can each be consumed at most once.
    Unmatched ground recordings remain queued for later Pi transfers.
    """
    with _RECONCILE_LOCK:
        sessions = _read_pending_sessions()
        csv_paths = [
            path
            for path in LOG_ROOT.glob("flight_*/flight_*.csv")
            if path.is_file() and LOG_NAME_PATTERN.fullmatch(path.name)
        ]
        anchor = _read_match_anchor()
        candidates: list[
            tuple[int, float, datetime, str, Path, int | None, int | None]
        ] = []
        for item in sessions:
            folder_name = str(item["folder_name"])
            ground_sequence, ground_time = parse_session_identity(folder_name)
            if ground_time is None and ground_sequence is None:
                continue
            for csv_path in csv_paths:
                pi_sequence, pi_time = parse_session_identity(csv_path.name)
                if ground_time is not None and pi_time is not None:
                    delta = abs((ground_time - pi_time).total_seconds())
                    if delta <= PENDING_SESSION_MATCH_TOLERANCE_SECONDS:
                        candidates.append(
                            (0, delta, ground_time, folder_name, csv_path,
                             ground_sequence, pi_sequence)
                        )
                    # A reliable but wrong timestamp must never fall back to count.
                    continue
                if pi_time is not None or pi_sequence is None or ground_sequence is None:
                    continue
                if anchor is not None:
                    count_match = (
                        pi_sequence - anchor[0]
                        == ground_sequence - anchor[1]
                    )
                else:
                    count_match = pi_sequence == ground_sequence
                if count_match:
                    candidates.append(
                        (1, 0.0, ground_time or datetime.min, folder_name,
                         csv_path, ground_sequence, pi_sequence)
                    )

        candidates.sort(
            key=lambda value: (value[0], value[1], value[2], value[3], str(value[4]))
        )
        used_ground: set[str] = set()
        used_csv: set[Path] = set()
        time_anchors: list[tuple[datetime, int, int]] = []
        for mode, _, ground_time, folder_name, csv_path, ground_sequence, pi_sequence in candidates:
            if folder_name in used_ground or csv_path in used_csv:
                continue
            _merge_ground_folder(LOG_ROOT / folder_name, csv_path.parent)
            used_ground.add(folder_name)
            used_csv.add(csv_path)
            if mode == 0 and ground_sequence is not None and pi_sequence is not None:
                time_anchors.append((ground_time, pi_sequence, ground_sequence))

        if time_anchors:
            _, pi_sequence, ground_sequence = max(time_anchors)
            _write_match_anchor(pi_sequence, ground_sequence)

        remaining = [
            item for item in sessions if str(item.get("folder_name")) not in used_ground
        ]
        _write_pending_sessions(remaining)
        return len(used_ground)


def merge_or_rename_pending_session(target_folder: Path, log_name: str) -> Path:
    """Compatibility wrapper; matching occurs after the CSV is verified."""
    target_folder.mkdir(parents=True, exist_ok=True)
    return target_folder


def reconcile_pending_session_with_existing_logs() -> None:
    """Backward-compatible name for the all-session reconciler."""
    reconcile_all_sessions()


def ground_manifest_by_name() -> dict[str, dict]:
    """Index every verified CSV currently stored by the ground station."""
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    reconcile_pending_session_with_existing_logs()
    result: dict[str, dict] = {}

    for path in LOG_ROOT.glob("flight_*/flight_*.csv"):
        if not path.is_file() or not LOG_NAME_PATTERN.fullmatch(path.name):
            continue
        try:
            result[path.name] = {
                "name": path.name,
                "size": int(path.stat().st_size),
                "sha256": sha256_file(path),
            }
        except OSError:
            continue

    return result


def compare_manifest(pi_logs: object) -> tuple[list[str], list[str]]:
    ground = ground_manifest_by_name()
    missing: list[str] = []
    mismatched: list[str] = []

    if not isinstance(pi_logs, list):
        raise ValueError("Manifest logs must be a list")

    for entry in pi_logs:
        if not isinstance(entry, dict):
            continue
        name = safe_log_name(entry.get("name"))
        local = ground.get(name)
        if local is None:
            missing.append(name)
            continue
        if (
            int(local["size"]) != int(entry.get("size", -1))
            or local["sha256"] != str(entry.get("sha256", ""))
        ):
            mismatched.append(name)

    return missing, mismatched


def receive_exact_file(sock, destination: Path, byte_count: int) -> None:
    remaining = byte_count
    destination.parent.mkdir(parents=True, exist_ok=True)

    with destination.open("wb") as file:
        while remaining:
            chunk = sock.recv(min(BT_CHUNK_SIZE, remaining))
            if not chunk:
                raise ConnectionError("Connection closed during file transfer")
            file.write(chunk)
            remaining -= len(chunk)
        file.flush()
        os.fsync(file.fileno())


class BluetoothLogReceiver:
    """Background receiver using a Windows incoming Bluetooth COM port."""

    def __init__(
        self,
        log_root: Path | str = LOG_ROOT,
        serial_port: str = "COM12",
        status_callback: Callable[[str], None] | None = None,
    ):
        global LOG_ROOT, PENDING_SESSION_FILE, PENDING_SESSIONS_FILE, MATCH_ANCHOR_FILE

        LOG_ROOT = Path(log_root).resolve()
        PENDING_SESSION_FILE = LOG_ROOT / ".pending_session.json"
        PENDING_SESSIONS_FILE = LOG_ROOT / ".pending_sessions.json"
        MATCH_ANCHOR_FILE = LOG_ROOT / ".match_anchor.json"
        self.serial_port = str(serial_port)
        self.status_callback = status_callback
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.reconcile_thread: threading.Thread | None = None
        self.server_sock = None

    def report(self, text: str) -> None:
        print(f"[BT LOG RECEIVER] {text}", flush=True)
        if self.status_callback is not None:
            try:
                self.status_callback(text)
            except Exception:
                pass

    def start(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    def _reconcile_forever(self) -> None:
        while not self.stop_event.is_set():
            try:
                reconcile_all_sessions()
            except Exception as exc:
                self.report(f"Session reconciliation failed: {exc}")
            self.stop_event.wait(RECONCILE_INTERVAL_SECONDS)

    def stop(self) -> None:
        self.stop_event.set()
        if self.server_sock is not None:
            try:
                self.server_sock.close()
            except Exception:
                pass

    def serve_forever(self) -> None:
        try:
            import serial
        except ImportError as exc:
            self.report(
                "pyserial is missing. Install it with: python -m pip install pyserial"
            )
            raise RuntimeError("pyserial is not installed") from exc

        LOG_ROOT.mkdir(parents=True, exist_ok=True)
        if self.reconcile_thread is None or not self.reconcile_thread.is_alive():
            self.reconcile_thread = threading.Thread(
                target=self._reconcile_forever,
                daemon=True,
            )
            self.reconcile_thread.start()
        self.report(
            f"Waiting on Windows Bluetooth incoming port {self.serial_port}"
        )

        while not self.stop_event.is_set():
            stream = None
            try:
                serial_connection = serial.Serial(
                    port=self.serial_port,
                    baudrate=BT_SERIAL_BAUD,
                    timeout=1.0,
                    write_timeout=BT_IO_TIMEOUT,
                )
                stream = SerialStream(serial_connection, self.stop_event)
                self.server_sock = stream
                self.report(f"Port opened: {self.serial_port}; waiting for Pi HELLO")
                self.handle_client(stream)
            except Exception as exc:
                if not self.stop_event.is_set():
                    self.report(f"Connection/session failed: {exc}")
                    self.stop_event.wait(2.0)
            finally:
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass

    def handle_client(self, sock) -> None:
        hello = recv_control(sock)
        if (
            hello.get("type") != "HELLO"
            or int(hello.get("protocol", -1)) != BT_PROTOCOL_VERSION
        ):
            raise RuntimeError(f"Unexpected HELLO: {hello}")

        send_control(
            sock,
            {"type": "HELLO_ACK", "protocol": BT_PROTOCOL_VERSION},
        )
        self.report("Pi HELLO accepted; protocol handshake complete")

        while not self.stop_event.is_set():
            message = recv_control(sock)
            message_type = message.get("type")

            if message_type == "MANIFEST":
                missing, mismatched = compare_manifest(message.get("logs"))
                send_control(
                    sock,
                    {
                        "type": "MANIFEST_ACK",
                        "missing": missing,
                        "mismatched": mismatched,
                    },
                )
                self.report(
                    f"Manifest: missing={len(missing)}, mismatched={len(mismatched)}"
                )

            elif message_type == "FILE_META":
                self.receive_one_file(sock, message)

            elif message_type == "VERIFY_MANIFEST":
                missing, mismatched = compare_manifest(message.get("logs"))
                send_control(
                    sock,
                    {
                        "type": "VERIFY_RESULT",
                        "missing": missing,
                        "mismatched": mismatched,
                    },
                )
                self.report(
                    f"Final verification: missing={len(missing)}, "
                    f"mismatched={len(mismatched)}"
                )
                return

            else:
                raise RuntimeError(f"Unexpected protocol message: {message}")

    def receive_one_file(self, sock, meta: dict) -> None:
        name = safe_log_name(meta.get("name"))
        expected_size = int(meta.get("size", -1))
        expected_sha = str(meta.get("sha256", ""))

        if expected_size < 0 or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha):
            raise ValueError(f"Invalid FILE_META for {name}")

        target_folder = merge_or_rename_pending_session(
            session_folder_for_log(name),
            name,
        )
        final_path = target_folder / name
        partial_path = target_folder / f".{name}.part"

        try:
            partial_path.unlink(missing_ok=True)
            send_control(sock, {"type": "FILE_READY", "name": name})
            receive_exact_file(sock, partial_path, expected_size)

            received_size = int(partial_path.stat().st_size)
            received_sha = sha256_file(partial_path)
            if received_size != expected_size or received_sha != expected_sha:
                partial_path.unlink(missing_ok=True)
                raise RuntimeError(
                    f"Verification failed for {name}: size={received_size}, "
                    f"sha256={received_sha}"
                )

            os.replace(partial_path, final_path)

            # The verified CSV now exists, so a ground-first recording can be
            # matched immediately. Pi-first recordings are matched by
            # register_ground_session() or the background reconciler.
            reconcile_all_sessions()

            session_info = {
                "flight_name": Path(name).stem,
                "pi_log": name,
                "size": expected_size,
                "sha256": expected_sha,
                "status": "verified",
            }
            (target_folder / "session.json").write_text(
                json.dumps(session_info, indent=2),
                encoding="utf-8",
            )

            send_control(
                sock,
                {
                    "type": "FILE_ACK",
                    "status": "OK",
                    "name": name,
                    "size": expected_size,
                    "sha256": expected_sha,
                },
            )
            self.report(f"Verified and stored: {final_path}")

        except Exception:
            try:
                partial_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise


class SerialStream:
    """Give pyserial the recv/sendall interface used by the Pi protocol."""

    def __init__(self, serial_connection, stop_event: threading.Event):
        self.serial = serial_connection
        self.stop_event = stop_event

    def recv(self, size: int) -> bytes:
        while not self.stop_event.is_set():
            data = self.serial.read(size)
            if data:
                return data
        return b""

    def sendall(self, data: bytes) -> None:
        view = memoryview(data)
        while view and not self.stop_event.is_set():
            written = self.serial.write(view)
            if written is None or written <= 0:
                raise ConnectionError("Bluetooth COM write failed")
            view = view[written:]
        self.serial.flush()

    def close(self) -> None:
        self.serial.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Receive Raspberry Pi flight logs over a Bluetooth COM port."
    )
    parser.add_argument(
        "--serial-port",
        required=True,
        help="Windows incoming Bluetooth serial port, for example COM12.",
    )
    parser.add_argument(
        "--log-root",
        default=str(LOG_ROOT),
        help="Destination logs directory (default: project logs directory).",
    )
    args = parser.parse_args()

    receiver = BluetoothLogReceiver(
        log_root=args.log_root,
        serial_port=args.serial_port,
    )
    try:
        receiver.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        receiver.stop()


if __name__ == "__main__":
    main()