"""
Tiny stats server for the camera Pi. The dashboard Pi polls this.

    pip install flask flask-cors psutil
    python3 camera_stats.py          # listens on :5001

CORS is enabled because the dashboard page (served from the other Pi) fetches
this endpoint directly from the browser. Only run it on a trusted LAN.
"""
import time

import psutil
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)


@app.route("/api/stats")
def stats():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            cpu_temp = round(int(f.read().strip()) / 1000, 1)
    except Exception:
        cpu_temp = 0
    h, rem = divmod(int(time.time() - psutil.boot_time()), 3600)
    return jsonify({
        "cpu_temp": cpu_temp,
        "cpu_pct": round(psutil.cpu_percent(interval=0.5)),
        "mem_pct": round(psutil.virtual_memory().percent),
        "disk_pct": round(psutil.disk_usage("/").percent),
        "uptime": f"{h}h {rem // 60}m",
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
