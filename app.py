"""
Pi Home Dashboard - a Flask dashboard for a small touchscreen.

Pages:  Home (clock, weather, Pi stats, smart-home toggles) | Calendar | Camera
All configuration comes from environment variables (see .env.example).
"""
import asyncio
import hmac
import os
import secrets
import time
from functools import wraps

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

load_dotenv()

import calendar_fetch  # noqa: E402  (after load_dotenv so it can read env too)


def env(name, default=""):
    return os.environ.get(name, default).strip()


def env_list(name):
    return [x.strip() for x in env(name).split(",") if x.strip()]


# ── Configuration ────────────────────────────────────────────────────────────
DASHBOARD_TITLE = env("DASHBOARD_TITLE", "Home Dashboard")
DASHBOARD_USER = env("DASHBOARD_USER")
DASHBOARD_PASS = env("DASHBOARD_PASS")

LOCATION_NAME = env("LOCATION_NAME", "My Location")
WEATHER_LAT = env("WEATHER_LAT", "40.7128")
WEATHER_LON = env("WEATHER_LON", "-74.0060")
WEATHER_TZ = env("WEATHER_TZ", "America/New_York")
UNITS = env("UNITS", "imperial").lower()  # imperial | metric

CAMERA_STATS_URL = env("CAMERA_STATS_URL")      # e.g. http://<camera-pi-ip>:5001/api/stats
CAM_STREAM_URL = env("CAM_STREAM_URL")    # e.g. http://<camera-pi-ip>:8080/?action=stream

TAPO_EMAIL = env("TAPO_EMAIL")
TAPO_PASSWORD = env("TAPO_PASSWORD")

# key -> (tapo device type, list of IPs). Devices with no IP set are skipped.
DEVICES = {
    "bulb":     ("l530", env_list("TAPO_BULB_IP")),
    "plug":     ("p100", env_list("TAPO_PLUG_IP")),
    "group":    ("l530", env_list("TAPO_GROUP_IPS")),     # comma-separated, toggled together
    "lamp":     ("l530", env_list("TAPO_LAMP_IP")),
}

app = Flask(__name__)
_secret = env("SECRET_KEY")
if not _secret:
    _secret = secrets.token_hex(32)
    print("! SECRET_KEY not set - using a random one (logins reset on restart)")
app.secret_key = _secret


@app.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.context_processor
def inject_config():
    metric = UNITS == "metric"
    return {
        "dashboard_title": DASHBOARD_TITLE,
        "location_name": LOCATION_NAME,
        "weather_lat": WEATHER_LAT,
        "weather_lon": WEATHER_LON,
        "weather_tz": WEATHER_TZ,
        "temp_unit": "celsius" if metric else "fahrenheit",
        "temp_symbol": "C" if metric else "F",
        "wind_unit": "kmh" if metric else "mph",
        "wind_label": "km/h" if metric else "mph",
        "camera_stats_url": CAMERA_STATS_URL,
        "cam_stream_url": CAM_STREAM_URL,
        "label_bulb": env("LABEL_BULB", "Light"),
        "label_plug": env("LABEL_PLUG", "Plug"),
        "label_group": env("LABEL_GROUP", "Light Group"),
        "label_lamp": env("LABEL_LAMP", "Lamp"),
    }


# ── Login ────────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


def _same(a, b):
    return hmac.compare_digest(a.encode(), b.encode())


@app.route("/login", methods=["GET", "POST"])
def login_page():
    error = None
    if request.method == "POST":
        u = request.form.get("username", "")
        p = request.form.get("password", "")
        if _same(u, DASHBOARD_USER) and _same(p, DASHBOARD_PASS):
            session["logged_in"] = True
            return redirect(url_for("index"))
        error = "Invalid username or password"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


# ── Tapo smart devices ───────────────────────────────────────────────────────
# Clients are cached between requests; if a call fails (e.g. SESSION_TIMEOUT)
# we reconnect once and retry.
_clients = {}


async def _connect(key):
    from tapo import ApiClient
    kind, ips = DEVICES[key]
    client = ApiClient(TAPO_EMAIL, TAPO_PASSWORD)
    make = getattr(client, kind)
    return [await make(ip) for ip in ips]


async def _devices(key, force=False):
    if force or key not in _clients:
        _clients[key] = await _connect(key)
    return _clients[key]


async def _device_on(key, dev):
    """Return True/False for one device, or None if unreachable."""
    try:
        return (await dev.get_device_info()).device_on
    except Exception:
        return None


async def status(key):
    """True if any device in the group is on; None if none are reachable."""
    if not DEVICES[key][1]:
        return None
    devices = await _devices(key)
    states = [await _device_on(key, d) for d in devices]
    if all(s is None for s in states):
        devices = await _devices(key, force=True)
        states = [await _device_on(key, d) for d in devices]
    reachable = [s for s in states if s is not None]
    return any(reachable) if reachable else None


async def toggle(key):
    devices = await _devices(key)
    states = [(d, await _device_on(key, d)) for d in devices]
    if all(s is None for _, s in states):
        devices = await _devices(key, force=True)
        states = [(d, await _device_on(key, d)) for d in devices]
    is_on = any(s for _, s in states if s is not None)
    for d, s in states:
        if s is None:
            continue
        try:
            await (d.off() if is_on else d.on())
        except Exception:
            pass


# ── Pages ────────────────────────────────────────────────────────────────────
@app.route("/")
@login_required
def index():
    return render_template("home.html")


@app.route("/camera")
@login_required
def camera():
    return render_template("camera.html")


@app.route("/calendar")
@login_required
def calendar():
    return render_template("calendar.html")


@app.route("/favicon.ico")
def favicon():
    return "", 204


# ── API ──────────────────────────────────────────────────────────────────────
@app.route("/api/stats")
@login_required
def api_stats():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            cpu_temp = round(int(f.read().strip()) / 1000, 1)
    except Exception:
        cpu_temp = 0
    try:
        import psutil
        cpu_pct = round(psutil.cpu_percent(interval=0.5))
        mem_pct = round(psutil.virtual_memory().percent)
        disk_pct = round(psutil.disk_usage("/").percent)
        h, rem = divmod(int(time.time() - psutil.boot_time()), 3600)
        uptime = f"{h}h {rem // 60}m"
    except Exception:
        cpu_pct = mem_pct = disk_pct = 0
        uptime = "unknown"
    return jsonify({"cpu_temp": cpu_temp, "cpu_pct": cpu_pct, "mem_pct": mem_pct,
                    "disk_pct": disk_pct, "uptime": uptime})


@app.route("/api/calendar")
@login_required
def api_calendar():
    return jsonify(calendar_fetch.get_cache())


@app.route("/api/smarthome/status")
@login_required
def smarthome_status():
    out = {"error": None}
    errors = []
    for key in DEVICES:
        try:
            out[key] = asyncio.run(status(key))
        except Exception as e:  # one offline device must not break the rest
            out[key] = None
            errors.append(f"{key}: {e}")
    if errors:
        out["error"] = "; ".join(errors)
    return jsonify(out)


@app.route("/api/smarthome/<key>/toggle", methods=["POST"])
@login_required
def smarthome_toggle(key):
    if key not in DEVICES or not DEVICES[key][1]:
        return jsonify({"success": False, "error": "unknown or unconfigured device"}), 404
    try:
        asyncio.run(toggle(key))
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ── Startup ──────────────────────────────────────────────────────────────────
def check_config():
    if not DASHBOARD_USER or not DASHBOARD_PASS:
        raise SystemExit("Set DASHBOARD_USER and DASHBOARD_PASS in .env (see .env.example)")


if __name__ == "__main__":
    check_config()
    calendar_fetch.start()
    app.run(host=env("HOST", "0.0.0.0"), port=int(env("PORT", "5000")), debug=False)
