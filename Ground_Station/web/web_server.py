"""Red Sun public website server.

In production, set REDSUN_R2_PUBLIC_URL and public assets/logs are read from
Cloudflare R2.  Without that variable the existing local assets/public_logs
folders are used for development.  The private logs folder is never read.
"""
from __future__ import annotations

import os
import time
import csv
import hmac
import json
from html import escape
from pathlib import Path
from urllib.parse import quote, unquote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import Flask, abort, jsonify, redirect, request, send_file
from werkzeug.utils import safe_join

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
PUBLIC_LOGS = PROJECT_ROOT / "public_logs"
ASSETS = PROJECT_ROOT / "assets"
R2_PUBLIC_URL = os.getenv("REDSUN_R2_PUBLIC_URL", "").strip().rstrip("/")
TOKEN = (
    os.getenv("REDSUN_LIVE_UPLOAD_KEY", "").strip()
    or os.getenv("REDSUN_WEB_TOKEN", "").strip()
)
OFFLINE_AFTER_SECONDS = 8.0
REMOTE_TIMEOUT_SECONDS = 20
MANIFEST_CACHE_SECONDS = 10.0

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024
live = {"updated": 0.0, "flight_display": None, "hud": None}
manifest_cache = {"updated": 0.0, "folders": []}


def r2_url(key: str) -> str:
    """Build a safely encoded public object URL."""
    return f"{R2_PUBLIC_URL}/{quote(key, safe='/')}"


def fetch_remote_bytes(url: str, no_cache: bool = False) -> bytes:
    headers = {"User-Agent": "RedSunWebsite/1.0"}
    if no_cache:
        headers["Cache-Control"] = "no-cache"
    remote_request = Request(url, headers=headers)
    with urlopen(remote_request, timeout=REMOTE_TIMEOUT_SECONDS) as response:
        return response.read()


def remote_manifest(force: bool = False) -> list[dict]:
    """Read the publisher-generated R2 manifest with a short process cache."""
    if not R2_PUBLIC_URL:
        return []
    now = time.monotonic()
    if (
        not force
        and now - float(manifest_cache["updated"]) < MANIFEST_CACHE_SECONDS
    ):
        return manifest_cache["folders"]
    try:
        payload = json.loads(
            fetch_remote_bytes(
                r2_url("public_logs/index.json"), no_cache=True
            ).decode("utf-8")
        )
        folders = payload.get("folders", [])
        if not isinstance(folders, list):
            raise ValueError("R2 manifest has an invalid folders value")
        normalized = []
        for item in folders:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            files = item.get("files", [])
            if not name or "/" in name or "\\" in name or not isinstance(files, list):
                continue
            normalized.append(
                {"name": name, "files": [str(value) for value in files]}
            )
        manifest_cache["folders"] = normalized
        manifest_cache["updated"] = now
        return normalized
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        if manifest_cache["folders"]:
            return manifest_cache["folders"]
        app.logger.warning("Could not load R2 log manifest: %s", error)
        return []


def remote_folder(folder_name: str) -> dict | None:
    return next(
        (item for item in remote_manifest() if item["name"] == folder_name),
        None,
    )


def safe_remote_log_name(name: str) -> tuple[str, str] | None:
    """Return (folder, relative file) only when the key exists in manifest."""
    decoded = unquote(name).replace("\\", "/").lstrip("/")
    parts = decoded.split("/", 1)
    if len(parts) != 2 or any(part in ("", ".", "..") for part in decoded.split("/")):
        return None
    folder_name, relative = parts
    folder = remote_folder(folder_name)
    if not folder or relative not in folder["files"]:
        return None
    return folder_name, relative


def page(title: str, content: str) -> str:
    return f"""<!doctype html><html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{title} · Rising Sun No. 1</title><link rel='icon' href='/assets/RisingSun.ico'>
<script type='module' src='https://ajax.googleapis.com/ajax/libs/model-viewer/4.1.0/model-viewer.min.js'></script>
<link rel='stylesheet' href='/site.css'><link rel='stylesheet' href='/log-browser.css'><link rel='stylesheet' href='/log-viewer.css'></head><body>
<header><img src='/assets/RisingSun.png'><nav><a href='/'>Home</a><a href='/flight-display'>Flight Display</a><a href='/hud'>HUD</a></nav></header>
{content}</body></html>"""


@app.get("/")
def home():
    return page("Home", """
<main class='home'><h1>Rising Sun No. 1 (红太阳一号)</h1>
<section class='model'><model-viewer src='/assets/Whole_Assembly_1.glb' camera-controls auto-rotate shadow-intensity='1' environment-image='neutral'></model-viewer></section>
<section class='overview'><h2>Project Overview</h2><p><b>Rising Sun No. 1 (红太阳一号)</b> is a self-developed unmanned aerial vehicle (UAV) project. Its primary objective is to create a complete and integrated flight system including a drone that performs flight missions, a ground control station that monitors and visualizes flight status, and an onboard computer that manages high-level flight tasks. The main goal of this project is to successfully develop each subsystem and integrate them into a coordinated and functional system. Through this process, the project improves systems-thinking and problem-solving abilities while also developing the specialized engineering skills required to design, build, and test each subsystem.</p></section>
<section class='systems'>
  <article>
    <h2>01&nbsp;&nbsp;Drone Subsystem</h2>
    <p>The drone provides a stable, controllable, and flyable aerial platform by integrating electrical, propulsion, and flight-control systems.</p>
    <p><b>Electrical system.</b> A 4S LiPo battery powers the aircraft. The power module supplies and monitors the flight controller, while the power distribution board (PDB) distributes power to the propulsion, onboard computer, and video transmission (VTX) systems.</p>
    <p><b>Propulsion system.</b> Four Tarot 2814 700 KV motors with 12 × 3.8-inch propellers are driven by four Talon 40A Slim ESCs running AM32 firmware. The system can theoretically produce 7,200 g of total thrust—approximately twice the aircraft's weight—with a maximum current draw of 100 A and a hovering current of about 25 A.</p>
    <p><b>Flight-control system.</b> A Pixhawk 6C Pro flight controller and an M10 GPS module provide flight stabilization, navigation, and aircraft-state estimation. Mission Planner 1.3.83 is used to configure the controller, calibrate its sensors and radio inputs, adjust flight parameters, and monitor the aircraft during testing.</p>
    <p><a href='/assets/Drone FDCR (1).xlsx'>Whole Product View List</a><br><a href='/assets/Electrical Wiring.drawio.png'>Electrical Wiring</a></p>
  </article>
  <article>
    <h2>02&nbsp;&nbsp;Ground Control Station</h2>
    <p>A custom ground control station was developed so the complete system could be designed around the project's own requirements rather than relying on Mission Planner as the primary flight interface. It combines the live VTX video feed with visualized telemetry, helping the pilot assess aircraft status and make decisions intuitively. It also records, organizes, and visualizes flight logs for post-flight analysis.</p>
    <p>The Flight Display is inspired by commercial-aircraft cockpit displays. It includes a head-up display (HUD), a GPS-based map, flight instruments, and Information Panels that present system status, operating information, and active warnings. Future versions may also support waypoint and high-level flight-task entry directly through the interface.</p>
    <h2>03&nbsp;&nbsp;Onboard Computer</h2>
    <p>A Raspberry Pi 4 provides the high-level computing layer. The Pixhawk handles real-time attitude stabilization and motion control, while the Raspberry Pi manages system coordination, data processing, communication, and higher-level tasks. This layered architecture provides a foundation for autonomous navigation, computer vision, obstacle avoidance, and advanced mission planning.</p>
    <p>The Raspberry Pi monitors the aircraft through a three-stage finite-state machine: <b>Before Takeoff</b>, <b>Cruising</b>, and <b>After Landing</b>. It controls the navigation, strobe, and beacon lights; performs and reports the preflight checklist through MAVLink; records flight data; and transfers the completed CSV log to the corresponding ground-station folder via Bluetooth after landing.</p>
  </article>
</section>
<section class='overview'><h2>Future Aircraft Improvements</h2><p>In the future, several aspects of the aircraft can be improved. First, the entire power system could be redesigned around a 6S battery. This would allow the use of lower-KV motors with greater torque, enabling the drone to carry heavier payloads. The current ESCs could also be replaced with models that use plug-in connectors, reducing the number of solder joints and making assembly, maintenance, and component replacement easier. The current Pixhawk flight controller could also be replaced with a smaller bare-board flight controller. This would provide more hardware options while reducing the aircraft's size and weight, resulting in a design closer to modern commercial drones. However, a bare-board controller would require more soldering and a more complicated wiring process.</p></section>
<section class='overview'><h2>Future Project Development</h2><p>This project has established a functional and flyable aerial platform, providing a foundation for further development. Future work can proceed in two main directions. First, a preliminary flight-control program could be independently developed to explore the fundamental principles of robot dynamics, flight stabilization, and motion control. Second, the Raspberry Pi's high-level task-management system could be extended to perform more complex autonomous tasks, such as obstacle detection and avoidance using trained machine-learning models.</p></section>
<p class='center'><a class='button' href='/flight-display'>Enter Flight Display</a></p>
<section><h2>Public Flight Logs</h2><div id='logs' class='flight-folders'>Loading…</div></section>
<section><h2>Certificates</h2><div class='cards'><a href='/assets/Pilot Certificate Basic.pdf'>Pilot Certificate Basic</a><a href='/assets/Registration.pdf'>Aircraft Registration</a></div></section></main>
<script>fetch('/api/logs').then(r=>r.json()).then(x=>{logs.innerHTML=x.folders.length?x.folders.map(f=>`<a class="flight-folder" href="/flight-log/${encodeURIComponent(f.name)}"><b>${f.name}</b><span>${f.file_count} files</span></a>`).join(''):'No public logs selected.'})</script>""")


def mission_page(channel: str, title: str):
    return page(title, f"""<main class='mission'><div class='mission-title'><div><small>LIVE GROUND STATION</small><h1>{title}</h1></div><b id='state'>OFFLINE</b></div><div class='screen'><img id='feed'><div id='offline'><i></i><small>GROUND STATION OFFLINE</small><h2>NO FLIGHT MISSION</h2></div></div></main>
<script>const channel='{channel}',feed=document.querySelector('#feed'),off=document.querySelector('#offline'),state=document.querySelector('#state');async function tick(){{try{{let s=await fetch('/api/live/status',{{cache:'no-store'}}).then(r=>r.json());if(s.online){{feed.src='/api/live/frame/'+channel+'?t='+Date.now();feed.style.display='block';off.style.display='none';state.textContent='LIVE';state.className='on'}}else{{feed.style.display='none';off.style.display='flex';state.textContent='OFFLINE';state.className=''}}}}catch(e){{state.textContent='OFFLINE'}}}}tick();setInterval(tick,2000)</script>""")


@app.get("/flight-display")
def flight_display(): return mission_page("flight-display", "Flight Display")


@app.get("/hud")
def hud(): return mission_page("hud", "HUD")


@app.get("/site.css")
def css(): return send_file(ROOT / "site.css", mimetype="text/css")


@app.get("/log-browser.css")
def log_browser_css(): return send_file(ROOT / "log-browser.css", mimetype="text/css")


@app.get("/log-viewer.css")
def log_viewer_css(): return send_file(ROOT / "log-viewer.css", mimetype="text/css")


@app.get("/log-viewer.js")
def log_viewer_js(): return send_file(ROOT / "log-viewer.js", mimetype="text/javascript")


@app.get("/assets/<path:name>")
def asset(name):
    if R2_PUBLIC_URL:
        return redirect(r2_url(f"assets/{name}"), code=302)
    path = safe_join(str(ASSETS), name)
    return send_file(path) if path and Path(path).is_file() else abort(404)


@app.get("/api/logs")
def log_index():
    if R2_PUBLIC_URL:
        folders = [
            {"name": item["name"], "file_count": len(item["files"])}
            for item in remote_manifest()
        ]
        return jsonify(folders=folders)
    PUBLIC_LOGS.mkdir(exist_ok=True)
    folders = []
    for folder in sorted((p for p in PUBLIC_LOGS.iterdir() if p.is_dir()), key=lambda p: p.name.lower()):
        folders.append({"name": folder.name, "file_count": sum(1 for p in folder.rglob("*") if p.is_file())})
    return jsonify(folders=folders)


@app.get("/flight-log/<folder_name>")
def flight_log_folder(folder_name):
    if R2_PUBLIC_URL:
        remote = remote_folder(folder_name)
        if not remote:
            abort(404)
        file_entries = [
            (relative, Path(relative).name, Path(relative).suffix.lower())
            for relative in sorted(remote["files"], key=str.lower)
        ]
        display_name = folder_name
    else:
        folder_path = safe_join(str(PUBLIC_LOGS), folder_name)
        folder = Path(folder_path) if folder_path else None
        if not folder or not folder.is_dir() or folder.parent.resolve() != PUBLIC_LOGS.resolve():
            abort(404)
        file_entries = [
            (
                file_path.relative_to(folder).as_posix(),
                file_path.name,
                file_path.suffix.lower(),
            )
            for file_path in sorted(
                (p for p in folder.rglob("*") if p.is_file()),
                key=lambda p: p.name.lower(),
            )
        ]
        display_name = folder.name
    items = []
    for relative_in_folder, raw_name, suffix in file_entries:
        relative = f"{folder_name}/{relative_in_folder}"
        url = "/public-logs/" + quote(relative, safe="/")
        name = escape(raw_name)
        if suffix == ".mp4":
            items.append(f"<article class='log-file video-file'><h3>{name}</h3><video controls preload='metadata' src='{url}'></video></article>")
        elif suffix == ".csv":
            viewer_url = "/csv-viewer/" + quote(relative, safe="/")
            items.append(f"<a class='log-file data-file' href='{viewer_url}'><b>{name}</b><span>Open Log Viewer</span></a>")
        else:
            items.append(f"<a class='log-file data-file' href='{url}'><b>{name}</b><span>{escape(suffix.lstrip('.').upper() or 'FILE')}</span></a>")
    content = "".join(items) or "<p>No files in this flight folder.</p>"
    return page("Flight Log", f"""<main class='home log-detail'><p><a class='back-link' href='/#logs'>&larr; Back to Public Flight Logs</a></p><h1>{escape(display_name)}</h1><section class='log-files'>{content}</section></main>""")


def resolve_public_csv(name):
    if R2_PUBLIC_URL:
        resolved = safe_remote_log_name(name)
        if not resolved or not resolved[1].lower().endswith(".csv"):
            abort(404)
        return resolved
    path = safe_join(str(PUBLIC_LOGS), name)
    csv_path = Path(path) if path else None
    if not csv_path or not csv_path.is_file() or csv_path.suffix.lower() != ".csv":
        abort(404)
    return csv_path


@app.get("/csv-viewer/<path:name>")
def csv_viewer(name):
    csv_source = resolve_public_csv(name)
    if R2_PUBLIC_URL:
        folder_name, relative = csv_source
        encoded = quote(f"{folder_name}/{relative}", safe="/")
        csv_name = Path(relative).name
    else:
        csv_path = csv_source
        encoded = quote(csv_path.relative_to(PUBLIC_LOGS).as_posix(), safe="/")
        folder_name = csv_path.parent.name
        csv_name = csv_path.name
    folder_url = "/flight-log/" + quote(folder_name)
    return page("Log Viewer", f"""<main class='viewer' data-csv='{encoded}'>
<div class='viewer-head'><a class='back-link' href='{folder_url}'>&larr; Back to Flight Folder</a><h1>{escape(csv_name)}</h1></div>
<div class='viewer-tabs'><button class='active' data-tab='visual'>Visualized Data</button><button data-tab='raw'>Raw CSV</button></div>
<section id='visual' class='viewer-panel active'><aside><h3>Displayed values</h3><div id='series-list'></div></aside><div class='chart-area'><canvas id='log-chart'></canvas><label>Current sample <input id='time-cursor' type='range' min='0' value='0'></label><div id='mode-timeline'></div><div id='sample-status'>Loading log…</div></div><aside class='rc-panel'><h3>RC Channels</h3><div id='rc-list'></div></aside></section>
<section id='raw' class='viewer-panel'><div class='raw-wrap'><table id='raw-table'></table></div></section>
</main><script src='/log-viewer.js'></script>""")


@app.get("/api/csv/<path:name>")
def csv_data(name):
    csv_source = resolve_public_csv(name)
    if R2_PUBLIC_URL:
        folder_name, relative = csv_source
        try:
            content = fetch_remote_bytes(
                r2_url(f"public_logs/{folder_name}/{relative}")
            )
        except (HTTPError, URLError, TimeoutError):
            abort(502)
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(text.splitlines())
        csv_name = Path(relative).name
        headers = reader.fieldnames or []
        rows = list(reader)
        return jsonify(name=csv_name, headers=headers, rows=rows)
    csv_path = csv_source
    with csv_path.open("r", encoding="utf-8-sig", newline="", errors="replace") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        rows = list(reader)
    return jsonify(name=csv_path.name, headers=headers, rows=rows)


@app.get("/public-logs/<path:name>")
def public_log(name):
    if R2_PUBLIC_URL:
        resolved = safe_remote_log_name(name)
        if not resolved:
            abort(404)
        folder_name, relative = resolved
        return redirect(
            r2_url(f"public_logs/{folder_name}/{relative}"), code=302
        )
    path = safe_join(str(PUBLIC_LOGS), name)
    return send_file(path, as_attachment=False) if path and Path(path).is_file() else abort(404)


def authorized():
    supplied = request.headers.get("Authorization", "")
    expected = f"Bearer {TOKEN}"
    return bool(TOKEN) and hmac.compare_digest(supplied, expected)


@app.post("/api/live/frames")
def receive_frames():
    if not TOKEN:
        return jsonify(error="Live upload is not configured."), 503
    if not authorized(): abort(401)
    for form_name, key in (("flight_display", "flight_display"), ("hud", "hud")):
        upload = request.files.get(form_name)
        if upload: live[key] = upload.read()
    live["updated"] = time.monotonic()
    return jsonify(ok=True)


@app.post("/api/live/offline")
def receive_offline():
    if not TOKEN:
        return jsonify(error="Live upload is not configured."), 503
    if not authorized(): abort(401)
    live["updated"] = 0.0
    return jsonify(ok=True)


@app.get("/api/live/status")
def live_status():
    online = time.monotonic() - float(live["updated"]) < OFFLINE_AFTER_SECONDS
    return jsonify(online=online)


@app.get("/api/live/frame/<channel>")
def live_frame(channel):
    key = {"flight-display": "flight_display", "hud": "hud"}.get(channel)
    if not key or not live[key]: abort(404)
    from io import BytesIO
    return send_file(BytesIO(live[key]), mimetype="image/jpeg", max_age=0)


if __name__ == "__main__":
    PUBLIC_LOGS.mkdir(exist_ok=True)
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        threaded=True,
    )