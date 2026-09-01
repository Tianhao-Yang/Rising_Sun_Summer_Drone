"""Explicitly publish one selected flight folder to Cloudflare R2.

Private ``logs`` are never scanned. The caller must pass one folder selected
by the user. Public copies are created under ``public_logs`` before upload.
Cloudflare credentials are read only from environment variables.
"""
from __future__ import annotations

import json
import mimetypes
import os
import shutil
import subprocess
from pathlib import Path

from config import BASE_LOG_DIRECTORY


VIDEO_NAMES = ("Flight_Display.mp4", "HUD.mp4", "USB_Camera.mp4")


def _project_root() -> Path:
    # Installed at 红太阳App/core/public_log_publisher.py
    return Path(__file__).resolve().parents[1]


def _require_ffmpeg() -> str:
    executable = shutil.which("ffmpeg")
    if not executable:
        raise RuntimeError(
            "FFmpeg was not found. Install FFmpeg and reopen the App before publishing."
        )
    return executable


def _make_web_video(source: Path, destination: Path) -> None:
    ffmpeg = _require_ffmpeg()
    command = [
        ffmpeg, "-y", "-i", str(source), "-c:v", "libx264",
        "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", "-an", str(destination),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        creationflags=0x08000000 if os.name == "nt" else 0,
    )
    if completed.returncode != 0:
        destination.unlink(missing_ok=True)
        detail = completed.stderr.strip().splitlines()[-1:] or ["Unknown FFmpeg error"]
        raise RuntimeError(f"Could not convert {source.name}: {detail[0]}")


def _prepare_public_copy(source_folder: Path) -> tuple[Path, list[str]]:
    public_root = _project_root() / "public_logs"
    destination = public_root / source_folder.name
    destination.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    for source in source_folder.iterdir():
        if not source.is_file():
            continue
        suffix = source.suffix.lower()
        if suffix == ".csv" or source.name == "session.json":
            shutil.copy2(source, destination / source.name)
        elif suffix == ".mp4" and source.stem.endswith("_web"):
            shutil.copy2(source, destination / source.name)

    for video_name in VIDEO_NAMES:
        source = source_folder / video_name
        web_name = f"{source.stem}_web.mp4"
        output = destination / web_name
        existing_web = source_folder / web_name
        if existing_web.is_file():
            shutil.copy2(existing_web, output)
        elif source.is_file() and not output.is_file():
            try:
                _make_web_video(source, output)
            except RuntimeError as error:
                warnings.append(str(error))

    if not any(destination.glob("*.csv")):
        raise RuntimeError("This flight folder contains no CSV file.")
    return destination, warnings


def _r2_client():
    try:
        import boto3
    except ImportError as error:
        raise RuntimeError(
            "Missing boto3. Run: python -m pip install boto3"
        ) from error

    account_id = os.getenv("REDSUN_R2_ACCOUNT_ID", "").strip()
    access_key = os.getenv("REDSUN_R2_ACCESS_KEY_ID", "").strip()
    secret_key = os.getenv("REDSUN_R2_SECRET_ACCESS_KEY", "").strip()
    bucket = os.getenv("REDSUN_R2_BUCKET", "red-sun-public").strip()
    if not account_id or not access_key or not secret_key:
        raise RuntimeError(
            "R2 credentials are not configured. Set REDSUN_R2_ACCOUNT_ID, "
            "REDSUN_R2_ACCESS_KEY_ID, and REDSUN_R2_SECRET_ACCESS_KEY."
        )

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
    )
    return client, bucket


def _content_type(path: Path) -> str:
    overrides = {
        ".csv": "text/csv; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".mp4": "video/mp4",
    }
    return overrides.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _upload_folder(client, bucket: str, folder: Path) -> None:
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        key = f"public_logs/{folder.name}/{path.relative_to(folder).as_posix()}"
        client.upload_file(
            str(path), bucket, key,
            ExtraArgs={"ContentType": _content_type(path), "CacheControl": "public, max-age=3600"},
        )


def _upload_index(client, bucket: str) -> None:
    paginator = client.get_paginator("list_objects_v2")
    objects = []
    for page in paginator.paginate(Bucket=bucket, Prefix="public_logs/"):
        objects.extend(
            item["Key"] for item in page.get("Contents", [])
            if item["Key"] != "public_logs/index.json"
        )

    folders = {}
    for key in objects:
        parts = key.split("/")
        if len(parts) < 3:
            continue
        folders.setdefault(parts[1], []).append("/".join(parts[2:]))
    manifest = {
        "folders": [
            {"name": name, "files": sorted(files)}
            for name, files in sorted(folders.items(), reverse=True)
        ]
    }
    payload = json.dumps(manifest, indent=2).encode("utf-8")
    client.put_object(
        Bucket=bucket,
        Key="public_logs/index.json",
        Body=payload,
        ContentType="application/json; charset=utf-8",
        CacheControl="no-cache",
    )


def publish_flight_folder(source_folder) -> str:
    source = Path(source_folder).resolve()
    private_root = Path(BASE_LOG_DIRECTORY).resolve()
    if not source.is_dir() or source.parent != private_root:
        raise RuntimeError("Only a flight folder directly inside logs can be published.")

    public_folder, warnings = _prepare_public_copy(source)
    client, bucket = _r2_client()
    _upload_folder(client, bucket, public_folder)
    _upload_index(client, bucket)
    count = sum(1 for path in public_folder.rglob("*") if path.is_file())
    message = f"{source.name} published successfully ({count} public files)."
    if warnings:
        message += " Skipped damaged video(s): " + "; ".join(warnings)
    return message