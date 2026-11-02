"""
Google Calendar fetcher using official Google Calendar API.
Free, no Anthropic API needed.
"""

import os
import time
import threading
from datetime import datetime, timezone, timedelta

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pickle

SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), 'client_secret.json')
TOKEN_FILE = os.path.join(os.path.dirname(__file__), 'token.pickle')
REFRESH_INTERVAL = 900  # 15 minutes

_cal_cache = {
    "days": [],
    "last_updated": None,
    "error": None,
}
_cal_lock = threading.Lock()

DAYS   = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday']
MONTHS = ['January','February','March','April','May','June',
          'July','August','September','October','November','December']


def get_credentials():
    """Load saved token or run OAuth flow to get credentials."""
    creds = None

    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            # Run local server flow — opens browser on Pi for one-time auth
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, 'wb') as f:
            pickle.dump(creds, f)
        print("✓ Google Calendar token saved")

    return creds


def day_label(date_obj, index):
    """Return Today / Tomorrow / Weekday Month Day."""
    if index == 0:
        return "Today"
    if index == 1:
        return "Tomorrow"
    return f"{DAYS[date_obj.weekday()]} {MONTHS[date_obj.month - 1]} {date_obj.day}"


def fetch_calendar():
    """Fetch next 7 days of events from Google Calendar."""
    try:
        creds = get_credentials()
        service = build('calendar', 'v3', credentials=creds)

        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7)

        events_result = service.events().list(
            calendarId='primary',
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy='startTime',
            maxResults=100,
        ).execute()

        events = events_result.get('items', [])

        # Group into 7 day buckets
        days_map = {}
        for i in range(7):
            day = (start + timedelta(days=i)).date()
            days_map[day] = {
                "date": day.strftime("%Y-%m-%d"),
                "label": day_label(day, i),
                "events": []
            }

        for event in events:
            start_raw = event['start'].get('dateTime', event['start'].get('date'))
            if 'T' in start_raw:
                event_dt = datetime.fromisoformat(start_raw.replace('Z', '+00:00'))
                event_date = event_dt.date()
                time_str = event_dt.strftime("%I:%M %p").lstrip('0')
                time_sort = event_dt.strftime("%H:%M")
            else:
                from datetime import date
                event_date = date.fromisoformat(start_raw)
                time_str = "All day"
                time_sort = "00:00"

            if event_date in days_map:
                days_map[event_date]["events"].append({
                    "title": event.get('summary', 'Untitled'),
                    "time": time_str,
                    "time_sort": time_sort,
                })

        days = list(days_map.values())
        for day in days:
            day["events"].sort(key=lambda e: e["time_sort"])

        with _cal_lock:
            _cal_cache["days"] = days
            _cal_cache["last_updated"] = time.strftime("%H:%M:%S")
            _cal_cache["error"] = None

        total = sum(len(d["events"]) for d in days)
        print(f"✓ Calendar refreshed at {_cal_cache['last_updated']} — {total} events over 7 days")

    except Exception as e:
        print(f"✗ Calendar fetch error: {e}")
        with _cal_lock:
            _cal_cache["error"] = str(e)


def get_cache():
    with _cal_lock:
        return dict(_cal_cache)


def background_refresh():
    while True:
        fetch_calendar()
        time.sleep(REFRESH_INTERVAL)


def start():
    fetch_calendar()
    t = threading.Thread(target=background_refresh, daemon=True)
    t.start()
