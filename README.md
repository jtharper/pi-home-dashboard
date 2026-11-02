# Pi Home Dashboard

A small Flask dashboard built for a 7" Raspberry Pi touchscreen (800×480), running in a kiosk browser.

- **Home** – 12-hour clock, local weather ([Open-Meteo](https://open-meteo.com), no API key), CPU/memory/disk/uptime for the dashboard Pi *and* a second Pi, and toggles for TP-Link Tapo bulbs and plugs
- **Calendar** – 7-day Google Calendar view (read-only)
- **Camera** – live MJPEG stream from a USB webcam on a second Pi (a pet tank, front door, 3D printer...)
- Login page so only people on your network who know the password can use it

```
 Dashboard Pi + screen            Camera Pi + USB webcam
 ┌────────────────────────┐        ┌────────────────────────────────┐
 │ app.py (Flask)  :5000  │ ─────► │ mjpg_streamer :8080  (video)   │
 │ kiosk browser -> :5000 │ ─────► │ camera_stats.py :5001  (stats) │
 └────────────────────────┘        └────────────────────────────────┘
```

The second Pi is optional. Every section degrades gracefully if its settings are left blank.

## Setup (dashboard Pi)

```bash
git clone https://github.com/<you>/pi-home-dashboard.git
cd pi-home-dashboard
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env        # set DASHBOARD_USER / DASHBOARD_PASS / SECRET_KEY, location, devices
python app.py    # then open http://<pi-ip>:5000
```

`.env` is git-ignored. **Never commit it.**

### Google Calendar (optional)
1. In [Google Cloud Console](https://console.cloud.google.com) create a project, enable the **Google Calendar API**, configure the OAuth consent screen (add yourself as a test user), and create an **OAuth client ID → Desktop app**.
2. Download the JSON and save it as `client_secret.json` in the project folder (see `client_secret.example.json` for the shape). It is git-ignored.
3. Run `python app.py` once on the Pi's desktop – a browser opens to authorise. A `token.pickle` is saved (also git-ignored) and refreshes automatically.

The Calendar API is free at this usage level.

### Tapo smart devices (optional)
1. In the Tapo app enable **Third-Party Compatibility** (Me → Third-Party Services), including for any device you add later.
2. Give each device a DHCP reservation / static IP in your router.
3. Put the email, password and IPs in `.env`. Leave an IP blank to skip a device; an unreachable one just shows "unavailable".

The four rows are a single bulb, a plug, a group of bulbs toggled together, and a second bulb. Rename them with the `LABEL_*` settings in `.env`.

## Setup (camera Pi, optional)

```bash
# stats server
cd camera-pi && pip install -r requirements.txt --break-system-packages && python3 camera_stats.py

# video: build https://github.com/jacksonliam/mjpg-streamer, then
./mjpg_streamer -i "input_uvc.so -d /dev/video0 -r 640x480 -f 10 -q 50" \
                -o "output_http.so -p 8080 -w ./www"
```

Use `v4l2-ctl --list-devices` to find the right `/dev/videoN`. Lower the frame rate/resolution if the stream lags on a Pi 3. A **powered USB hub** avoids low-voltage problems.

Then set `CAMERA_STATS_URL` and `CAM_STREAM_URL` in the dashboard's `.env`.

## Run on boot

Copy the examples in `deploy/`, replace the `<PLACEHOLDERS>`, then:

```bash
sudo cp deploy/dashboard.service /etc/systemd/system/pi-dashboard.service
sudo systemctl daemon-reload && sudo systemctl enable --now pi-dashboard
journalctl -u pi-dashboard -f      # logs
```

`deploy/swayidle-autostart.txt` shows how to blank the screen after 30 minutes idle on Wayland.

## Security notes

- This is meant for a **trusted home LAN**. Don't port-forward it to the internet.
- The login is a single shared username/password over plain HTTP. Fine on your LAN, not a substitute for real auth.
- `camera_stats.py` has open CORS and no auth for the same reason.
- If a credential ever lands in git history, rotate it – deleting the file isn't enough.
