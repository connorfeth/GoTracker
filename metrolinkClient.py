"""
All communication with the Metrolinx Open Data API lives here.

The rest of the app only calls get_stops(), get_departures(stop_code) and
get_stop_details(stop_code). If no API_KEY is set (or USE_MOCK_DATA=true),
built-in sample data is used so the frontend still works.
"""
import os
import time
from urllib.parse import quote

import requests
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL", "https://api.openmetrolinx.com/OpenDataAPI/api/V1")
API_KEY = os.getenv("API_KEY", "")
TIMEOUT = 10  # seconds
STOPS_CACHE_SECONDS = 3600  # the station list rarely changes

_stops_cache = {"time": 0, "data": []}

DEST_FROM_TIME = os.getenv("DEST_FROM_TIME", "0000")
DEST_TO_TIME = os.getenv("DEST_TO_TIME", "2359")
DEST_CACHE_SECONDS = 3600
_dest_cache = {}


class MetrolinxError(Exception):
    """The API responded, but reported an error in its Metadata block."""

# ---------- Helpers ----------

def _get(path):
    """GET a path under the API base URL. The key is sent as ?key=..."""
    for attempt in range(2):
        resp = requests.get(f"{API_BASE_URL}{path}", params={"key": API_KEY}, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        meta = data.get("Metadata") or {}
        code = str(meta.get("ErrorCode") or "")
        if code == "403" and attempt == 0:
            time.sleep(1)  # the API returns occasional one-off 403s; retry once
            continue
        if code not in ("", "0", "200"):
            raise MetrolinxError(meta.get("ErrorMessage") or f"API error code {code}")
        return data


def _hhmm(value):
    """'2026-10-23 21:35:00' or '21:35:00' -> '21:35' (empty string if missing)."""
    if not value:
        return ""
    s = str(value)
    for sep in ("T", " "):
        if sep in s:
            s = s.split(sep, 1)[1]
            break
    return s[:5]




def get_stops():
    """Return a sorted list of {'id', 'name', 'type'} for every stop/station."""

    if time.time() - _stops_cache["time"] < STOPS_CACHE_SECONDS and _stops_cache["data"]:
        return _stops_cache["data"]

    raw = _get("/Stop/All")
    stations = (raw.get("Stations") or {}).get("Station") or []
    stops = [
        {
            "id": s.get("LocationCode"),
            "name": s.get("LocationName"),
            "type": s.get("LocationType") or "",
        }
        for s in stations
        if s.get("LocationCode")
    ]

    train_stops = [s for s in stops if "train" in s["type"].lower()]
    if train_stops:
        stops = train_stops

    stops.sort(key=lambda s: (s["name"] or "").lower())
    _stops_cache.update(time=time.time(), data=stops)
    return stops


def get_destinations(stop_code):
    """Return the end-of-line destinations of trips leaving this stop.

    The API reports where each trip *terminates* (e.g. "GT - Kitchener GO"),
    not every station along the way. The 'id' matches NextService's DirectionName.
    """

    cached = _dest_cache.get(stop_code)
    if cached and time.time() - cached["time"] < DEST_CACHE_SECONDS:
        return cached["data"]

    path = f"/Stop/Destinations/{quote(stop_code, safe='')}/{DEST_FROM_TIME}/{DEST_TO_TIME}"
    entries = (_get(path).get("Stop") or {}).get("Line") or []

    seen = {}
    for e in entries:
        display = (e.get("Display") or "").strip()  
        if not display or e.get("DestinationStop") == stop_code or display in seen:
            continue
        line, _, terminus = display.partition(" - ")
        label = f"{terminus} ({line})" if terminus else display
        seen[display] = {"id": display, "name": label}

    result = sorted(seen.values(), key=lambda d: d["name"].lower())
    _dest_cache[stop_code] = {"time": time.time(), "data": result}
    return result


def get_departures(stop_code, destination=None):
    """Return upcoming departures for one stop, optionally only trains ending at `destination`."""

    raw = _get(f"/Stop/NextService/{quote(stop_code, safe='')}")
    lines = (raw.get("NextService") or {}).get("Lines") or []
    if destination:
        wanted = destination.strip()
        lines = [l for l in lines if (l.get("DirectionName") or "").strip() == wanted]
    return [
        {
            "line": l.get("LineName"),
            "direction": l.get("DirectionName"),
            "scheduled": _hhmm(l.get("ScheduledDepartureTime")),
            "expected": _hhmm(l.get("ComputedDepartureTime")),
            "platform": l.get("ActualPlatform") or l.get("ScheduledPlatform") or "",
            "status": l.get("DepartureStatus") or l.get("Status") or "",
        }
        for l in lines
    ]


def get_stop_details(stop_code):
    """Return name, address, facilities and parking for one stop."""

    raw = _get(f"/Stop/Details/{quote(stop_code, safe='')}")
    s = raw.get("Stop") or {}
    street = " ".join(p for p in [s.get("StreetNumber"), s.get("StreetName")] if p)
    address = ", ".join(p for p in [street, s.get("City")] if p)
    return {
        "name": s.get("StopName"),
        "address": address,
        "facilities": [f.get("Description") for f in (s.get("Facilities") or []) if f.get("Description")],
        "parking": [
            {"name": p.get("Name"), "spots": p.get("ParkSpots")}
            for p in (s.get("Parkings") or [])
        ],
    }