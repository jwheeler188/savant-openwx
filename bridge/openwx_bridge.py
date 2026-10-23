#!/usr/bin/env python3
"""
Savant OpenWx - weather bridge
==============================
Weather, forecast and NWS watches/warnings for Savant, as plain states.

Every few minutes the bridge pulls the forecast (free: National Weather Service +
EPA / MET Norway UV + US Naval Observatory sun times; or Open-Meteo with an API key)
and active NWS alerts, boils it all down into flat KEY=value states, and serves them
to the Savant host over a plain TCP line protocol, so the Blueprint profile needs no
HTTPS or JSON parsing. Also serves a touch-friendly HTML dashboard.

Python 3.6+, standard library only. Runs on a Savant Mac mini Pro host or any Linux box.
MIT License. Not affiliated with or endorsed by Savant Systems, Inc.

TCP protocol (port 2350 by default):
  Bridge -> Savant :  KEY=value<LF>      (full dump on connect, then changes only)
  Savant -> Bridge :  PING               -> PONG
                      REFRESH            -> fetch now
                      DUMP               -> resend every state
                      SITE <lat>,<lon>   -> site coordinates from Blueprint
                      OVERRIDE <text>    -> zip / "lat,lon" / "City, ST"; empty or CLEAR removes it
                      SET <key> <number> -> threshold override (wind_protect_gust, ...); empty = config.json value
                      APIKEY <key>       -> Open-Meteo API key, the word private, or empty
                      CONTACT <email>    -> contact email sent to the data providers; empty = config.json
"""

import argparse
import asyncio
import json
import logging
import logging.handlers
import os
import re
import shutil
import signal
import sys
import subprocess
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

VERSION = "2.0.0"
log = logging.getLogger("wxbridge")

# --------------------------------------------------------------------------
# State definitions (single source of truth -- the profile generator imports this)
# (key, savant_type, description)
# --------------------------------------------------------------------------
STATE_DEFS = []


def _s(key, typ, desc):
    STATE_DEFS.append((key, typ, desc))


# System
_s("SYS_ONLINE", "integer", "1 = bridge has fresh data, 0 = stale/failed")
_s("SYS_LAST_UPDATE", "string", "Time of last successful update (e.g. 10:35 PM)")
_s("SYS_LAST_UPDATE_EPOCH", "integer", "Unix time of last successful update")
_s("SYS_LOCATION_NAME", "string", "Resolved location name")
_s("SYS_LOCATION_SOURCE", "string", "override / site / default")
_s("SYS_LAT", "string", "Latitude in use")
_s("SYS_LON", "string", "Longitude in use")
_s("SYS_UNITS", "string", "imperial / metric")
_s("SYS_ERROR", "string", "Last error message, blank when healthy")
_s("SYS_CURRENT_SOURCE", "string", "Where current conditions came from: Station KDWH / Forecast hour (station report too old) / Open-Meteo model")
_s("SYS_STATION_ID", "string", "NWS observation station used for current conditions, e.g. KDWH")
_s("SYS_STATION_NAME", "string", "Station name, e.g. Houston, David Wayne Hooks Memorial Airport")
_s("SYS_STATION_DISTANCE", "string", "Distance and direction from the site to the station, e.g. 11 mi NW")
_s("SYS_STATION_OBS_TIME", "string", "Time of the station report in use, e.g. 6:15 PM")
_s("SYS_CONTACT_SET", "integer", "1 = a real contact email is set (Blueprint Contact Email or config.json); 0 = still a placeholder")
_s("SYS_FORECAST_SOURCE", "string", "Where the forecast came from: NWS (free) / Open-Meteo (API key) / Open-Meteo free (private...) / NWS (Open-Meteo unavailable)")
_s("SYS_MEMORY_MB", "integer", "Bridge process memory (MB); it restarts itself above max_memory_mb")

# Current conditions
for k, t, d in [
    ("TEMP", "integer", "Temperature"),
    ("FEELS", "integer", "Feels-like temperature"),
    ("HUMIDITY", "integer", "Relative humidity %"),
    ("DEWPOINT", "integer", "Dew point"),
    ("WIND", "integer", "Wind speed"),
    ("GUST", "integer", "Wind gust"),
    ("WIND_DIR", "string", "Wind direction (N, NE, ...)"),
    ("WIND_DEG", "integer", "Wind direction degrees"),
    ("UV", "integer", "UV index"),
    ("UV_LEVEL", "string", "Low / Moderate / High / Very High / Extreme"),
    ("CLOUD", "integer", "Cloud cover %"),
    ("PRECIP", "string", "Precipitation this hour"),
    ("PRESSURE", "integer", "Sea-level pressure (hPa)"),
    ("IS_DAY", "integer", "1 = daytime"),
    ("SKY", "string", "Sunny / Clear / Mostly Sunny / Partly Cloudy / Mostly Cloudy / Overcast"),
    ("WEATHER", "string", "Sunny / Clear / Partly Cloudy / Cloudy / Rainy / Stormy / Snowy / Icy / Foggy"),
    ("COMFORT", "string", "Hot / Warm / Pleasant / Cool / Cold / Freezing"),
    ("SUMMARY", "string", "e.g. Warm & Sunny"),
    ("ICON", "string", "Icon key: clear-day, clear-night, partly-day, partly-night, cloudy, fog, drizzle, rain, thunder, snow, sleet, wind"),
]:
    _s("CUR_" + k, t, "Now: " + d)

# Look-ahead windows
WINDOWS = {"H3": 3, "H12": 12, "H24": 24}
for w, hrs in WINDOWS.items():
    for k, t, d in [
        ("TEMP_HIGH", "integer", "High temperature"),
        ("TEMP_LOW", "integer", "Low temperature"),
        ("FEELS_HIGH", "integer", "Highest feels-like"),
        ("FEELS_LOW", "integer", "Lowest feels-like"),
        ("RAIN_CHANCE", "integer", "Max precipitation chance %"),
        ("RAIN_TOTAL", "string", "Total expected precipitation"),
        ("WIND_MAX", "integer", "Max sustained wind"),
        ("GUST_MAX", "integer", "Max wind gust"),
        ("GUST_MAX_TIME", "string", "Hour of max gust"),
        ("UV_MAX", "integer", "Max UV index"),
        ("SKY", "string", "Most common sky condition"),
        ("WEATHER", "string", "Most significant weather"),
        ("COMFORT", "string", "Comfort"),
        ("SUMMARY", "string", "Plain-language summary"),
        ("ICON", "string", "Icon key"),
        ("RAIN_EXPECTED", "integer", "1 = rain chance at/above threshold"),
        ("FREEZE_EXPECTED", "integer", "1 = temp at/below freezing"),
    ]:
        _s(f"{w}_{k}", t, f"Next {hrs}h: {d}")

# Hourly strip for UI (every 3 hours for 24h)
for i in range(1, 9):
    for k, t, d in [("TIME", "string", "Hour label"), ("TEMP", "integer", "Temperature"),
                    ("RAIN", "integer", "Rain chance %"), ("GUST", "integer", "Gust"),
                    ("ICON", "string", "Icon key")]:
        _s(f"HR{i}_{k}", t, f"Hourly slot {i} (+{(i - 1) * 3}h): {d}")

# Daily
for i in range(5):
    for k, t, d in [("NAME", "string", "Day name (Today, Thu, ...)"), ("HIGH", "integer", "High"),
                    ("LOW", "integer", "Low"), ("RAIN_CHANCE", "integer", "Rain chance %"),
                    ("GUST_MAX", "integer", "Max gust"), ("UV_MAX", "integer", "Max UV"),
                    ("WEATHER", "string", "Weather"), ("SUMMARY", "string", "Summary"),
                    ("ICON", "string", "Icon key")]:
        _s(f"D{i}_{k}", t, f"Day {i}: {d}")
_s("SUN_RISE", "string", "Sunrise today")
_s("SUN_SET", "string", "Sunset today")
_s("SUN_DAWN", "string", "Civil dawn today (sky getting light, about 25 min before sunrise)")
_s("SUN_DUSK", "string", "Civil dusk today (sky dark, about 25 min after sunset)")
_s("SYS_SUN_SOURCE", "string", "Sunrise/sunset source: US Naval Observatory, or Calculated if USNO is unreachable")
_s("SYS_UV_SOURCE", "string", "UV source: EPA (today) + MET Norway clear-sky (later days) / Open-Meteo / blank if none")

# NWS alerts
_s("ALERT_ACTIVE", "integer", "1 = any NWS watch/warning/advisory active")
_s("ALERT_COUNT", "integer", "Number of different active alerts (duplicates of the same alert counted once)")
_s("ALERT_HIGHEST_SEVERITY", "string", "Extreme / Severe / Moderate / Minor / None")
_s("ALERT_HEADLINE", "string", "Headline of most severe alert")
_s("ALERT_EVENTS", "string", "Comma-separated active event names")
_s("ALERTS_LIST", "string", "Every active alert with its end time, most severe first, e.g. Wind Advisory until Fri 6:00 PM · Air Quality Alert until Fri 9:30 PM; or No active alerts")
ALERT_CATEGORIES = {
    "FREEZE": ["freeze", "frost", "hard freeze"],
    "WIND": ["wind", "gale", "extreme wind"],
    "TORNADO": ["tornado"],
    "TSTORM": ["severe thunderstorm"],
    "FLOOD": ["flood", "flash flood", "coastal flood", "storm surge"],
    "HEAT": ["heat"],
    "WINTER": ["winter", "ice storm", "snow", "blizzard", "wind chill", "cold"],
    "TROPICAL": ["hurricane", "tropical storm", "typhoon"],
    "FIRE": ["fire weather", "red flag"],
    "FOG": ["fog"],
}
for cat in ALERT_CATEGORIES:
    _s(f"ALERT_{cat}", "integer", f"1 = active {cat.lower()}-related alert")
for i in range(1, 4):
    for k, t, d in [("EVENT", "string", "Event name"), ("SEVERITY", "string", "Severity"),
                    ("EXPIRES", "string", "Ends/expires"), ("HEADLINE", "string", "Headline")]:
        _s(f"ALERT{i}_{k}", t, f"Alert {i}: {d}")

# Convenience action flags (thresholds in config)
_s("ACT_WIND_PROTECT", "integer", "1 = gust now or within next 3h >= wind_protect_gust")
_s("ACT_RAIN_SOON", "integer", "1 = rain chance within next 3h >= rain_soon_chance")
_s("ACT_FREEZE_TONIGHT", "integer", "1 = next 12h low <= freeze_temp or freeze alert active")
_s("ACT_HIGH_UV", "integer", "1 = UV now >= high_uv")
_s("ACT_HEAT", "integer", "1 = feels-like now >= heat_feels or heat alert active")

# Thresholds in use (set from the Savant profile, else config.json)
THRESHOLD_KEYS = ["wind_protect_gust", "rain_soon_chance", "rain_expected_chance", "freeze_temp",
                  "high_uv", "heat_feels", "wind_icon_gust"]
for _t in THRESHOLD_KEYS:
    _s("TH_" + _t.upper(), "integer", f"Threshold in use: {_t}")
_s("TH_SOURCE", "string", "Which thresholds were set from Savant (blank = all from config.json)")

# Display-ready text for Savant labels.
# Savant decodes text from profiles as Mac Roman, so the bridge sends Mac Roman:
# the degree sign and accented letters work, emoji can't be represented.
SAVANT_ENCODING = "mac_roman"
_s("CUR_TEMP_TEXT", "string", "Now: temperature as text, e.g. 67°")
_s("CUR_FEELS_TEXT", "string", "Now: e.g. Feels like 70°")
_s("CUR_WIND_TEXT", "string", "Now: e.g. 12 mph SSE, gusts 19 (Calm when still)")
_s("CUR_LINE", "string", "Now: one line, e.g. 67° Pleasant & Partly Cloudy")
for _w, _h in WINDOWS.items():
    _s(f"{_w}_HILO_TEXT", "string", f"{_w}: e.g. 84° / 68°")
    _s(f"{_w}_LINE", "string", f"Next {_h}h: one line matching D*_LINE, e.g. Next {_h}h 67° / 56° Clear")
for _i in range(1, 9):
    _s(f"HR{_i}_TEMP_TEXT", "string", f"Hourly slot {_i}: e.g. 67°")
for _i in range(5):
    _s(f"D{_i}_HILO_TEXT", "string", f"Day {_i}: e.g. 84° / 68°")
    _s(f"D{_i}_LINE", "string", f"Day {_i}: one line, e.g. Thu 84° / 68° Stormy 70%")
_s("ALERT_TEXT", "string", "e.g. ALERT: Wind Advisory until Wed 9:00 PM, or No active alerts")

STATE_KEYS = [k for k, _, _ in STATE_DEFS]

# --------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "tcp_port": 2350,
    "http_port": 8642,
    "max_memory_mb": 150,
    "refresh_seconds": 300,
    "units": "imperial",
    "default_location": "77002",
    "contact_email": "service@example.com",
    "openmeteo_api_key": "",
    "forecast_source": "auto",
    "thresholds": {
        "wind_protect_gust": 25,
        "rain_soon_chance": 50,
        "rain_expected_chance": 40,
        "freeze_temp": 32,
        "high_uv": 8,
        "heat_feels": 100,
        "wind_icon_gust": 30,
    },
}

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
    "PR": "Puerto Rico",
}

SEVERITY_RANK = {"Extreme": 4, "Severe": 3, "Moderate": 2, "Minor": 1, "Unknown": 0}

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


CURL = shutil.which("curl") or ("/usr/bin/curl" if Path("/usr/bin/curl").exists() else None)
USE_CURL = True  # set from config "fetcher": "auto" | "curl" | "python"


def http_json(url, ua, timeout=20):
    """GET a URL and parse JSON.

    Prefers the system curl: on macOS it uses Apple's TLS stack and system
    certificates, which avoids the certificate errors python.org Pythons hit
    until "Install Certificates.command" is run.
    """
    accept = "application/geo+json, application/json"
    if USE_CURL and CURL:
        p = subprocess.run([CURL, "-sS", "-L", "--fail", "--max-time", str(timeout),
                            "-A", ua, "-H", "Accept: " + accept, url],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode != 0:
            raise IOError("curl {}: {}".format(p.returncode, p.stderr.decode(errors="ignore").strip()[:150]))
        return json.loads(p.stdout.decode("utf-8"))
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": accept})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def parse_iso(s):
    """datetime from '2026-10-14T15:00', '2026-10-14' or '2026-10-14T21:00:00-05:00' (offset ignored).
    datetime.fromisoformat needs 3.7+, so parse by hand."""
    s = s.strip()
    s = re.sub(r"(Z|[+-]\d{2}:?\d{2})$", "", s)
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    raise ValueError("bad date " + s)


def rnd(v):
    return "" if v is None else int(round(v))


def cardinal(deg):
    if deg is None:
        return ""
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return dirs[int((deg % 360) / 22.5 + 0.5) % 16]


def uv_level(uv):
    if uv is None:
        return ""
    if uv < 3:
        return "Low"
    if uv < 6:
        return "Moderate"
    if uv < 8:
        return "High"
    if uv < 11:
        return "Very High"
    return "Extreme"


def hour_label(iso):
    try:
        dt = parse_iso(iso)
        return dt.strftime("%I %p").lstrip("0")
    except Exception:
        return ""


def time_label(iso):
    try:
        dt = parse_iso(iso)
        return dt.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return ""


def code_kind(code):
    """Classify a WMO weather code."""
    if code is None:
        return "none"
    if code in (95, 96, 99):
        return "thunder"
    if code in (56, 57, 66, 67):
        return "sleet"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (61, 63, 65, 80, 81, 82):
        return "rain"
    if code in (51, 53, 55):
        return "drizzle"
    if code in (45, 48):
        return "fog"
    return "none"


def sky_label(cloud, is_day):
    if cloud is None:
        return ""
    if cloud <= 10:
        return "Sunny" if is_day else "Clear"
    if cloud <= 30:
        return "Mostly Sunny" if is_day else "Mostly Clear"
    if cloud <= 60:
        return "Partly Cloudy"
    if cloud <= 85:
        return "Mostly Cloudy"
    return "Overcast"


WEATHER_FROM_KIND = {"thunder": "Stormy", "sleet": "Icy", "snow": "Snowy", "rain": "Rainy",
                     "drizzle": "Rainy", "fog": "Foggy"}
SIGNIFICANCE = ["Stormy", "Icy", "Snowy", "Rainy", "Foggy", "Cloudy", "Partly Cloudy", "Sunny", "Clear"]


def weather_label(code, cloud, is_day):
    kind = code_kind(code)
    if kind in WEATHER_FROM_KIND:
        return WEATHER_FROM_KIND[kind]
    sky = sky_label(cloud, is_day)
    if sky in ("Sunny", "Mostly Sunny"):
        return "Sunny"
    if sky in ("Clear", "Mostly Clear"):
        return "Clear"
    if sky == "Partly Cloudy":
        return "Partly Cloudy"
    return "Cloudy" if sky else ""


def icon_key(code, cloud, is_day, gust, wind_icon_gust):
    kind = code_kind(code)
    if kind in ("thunder", "sleet", "snow", "rain", "drizzle", "fog"):
        return kind
    if gust is not None and gust >= wind_icon_gust:
        return "wind"
    if cloud is None:
        return ""
    if cloud <= 30:
        return "clear-day" if is_day else "clear-night"
    if cloud <= 70:
        return "partly-day" if is_day else "partly-night"
    return "cloudy"


def comfort_label(feels, metric):
    if feels is None:
        return ""
    f = feels * 9 / 5 + 32 if metric else feels
    if f >= 95:
        return "Hot"
    if f >= 82:
        return "Warm"
    if f >= 65:
        return "Pleasant"
    if f >= 50:
        return "Cool"
    if f > 32:
        return "Cold"
    return "Freezing"


# --------------------------------------------------------------------------
# Bridge
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Free forecast source: National Weather Service gridpoint data (+ EPA UV)
# Converted into the same shape as an Open-Meteo response, so compute() and
# every Savant state work the same whichever source is used.
# --------------------------------------------------------------------------
import math
from datetime import timedelta, timezone

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except ImportError:  # older Python: fall back to the host's local time zone
    ZoneInfo = None


def parse_utc(s):
    """'2026-10-22T18:00:00+00:00' -> aware UTC datetime."""
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)(?::(\d\d))?(Z|[+-]\d\d:?\d\d)?", s)
    if not m:
        raise ValueError("bad time " + s)
    y, mo, d, hh, mi, ss, tz = m.groups()
    dt = datetime(int(y), int(mo), int(d), int(hh), int(mi), int(ss or 0))
    off = 0
    if tz and tz != "Z":
        sign = -1 if tz[0] == "-" else 1
        tz = tz[1:].replace(":", "")
        off = sign * (int(tz[:2]) * 60 + int(tz[2:]))
    return (dt - timedelta(minutes=off)).replace(tzinfo=timezone.utc)


def parse_duration_hours(s):
    """ISO 8601 duration ('PT1H', 'P1DT6H', 'PT30M') -> hours (at least 1)."""
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", s or "")
    if not m:
        return 1
    d, h, mi = (int(x or 0) for x in m.groups())
    return max(1, d * 24 + h + (1 if mi else 0))


def expand_layer(layer, hours_utc, spread=False):
    """NWS layer {'values':[{'validTime':'<start>/<dur>','value':x}]} -> one value per hour in hours_utc.
    spread=True divides an amount over its duration (precipitation totals)."""
    index = {t: i for i, t in enumerate(hours_utc)}
    out = [None] * len(hours_utc)
    for item in (layer or {}).get("values", []):
        vt = item.get("validTime", "")
        start_s, _, dur = vt.partition("/")
        try:
            start = parse_utc(start_s).replace(minute=0, second=0)
        except ValueError:
            continue
        n = parse_duration_hours(dur)
        val = item.get("value")
        if spread and isinstance(val, (int, float)):
            val = val / n
        for k in range(n):
            i = index.get(start + timedelta(hours=k))
            if i is not None:
                out[i] = val
    return out


def unit_of(layer):
    return ((layer or {}).get("uom") or (layer or {}).get("unitCode") or "").split(":")[-1]


def to_temp(v, unit, metric):
    if v is None:
        return None
    c = (v - 32) * 5 / 9 if unit == "degF" else v
    return c if metric else c * 9 / 5 + 32


def to_speed(v, unit, metric):
    if v is None:
        return None
    kmh = v * 3.6 if unit == "m_s-1" else (v * 1.852 if unit == "kn" else v)
    return kmh if metric else kmh * 0.621371


def to_precip(v, unit, metric):
    if v is None:
        return None
    mm = v * 25.4 if unit == "in" else v
    return mm if metric else mm / 25.4


# NWS weather words -> WMO code used by the rest of the bridge (most significant first)
NWS_WX_CODES = [
    ("thunderstorms", 95), ("freezing_rain", 66), ("freezing_drizzle", 56), ("sleet", 67), ("ice_pellets", 67),
    ("blowing_snow", 75), ("snow_showers", 85), ("snow", 73), ("rain_showers", 80), ("rain", 61),
    ("drizzle", 51), ("freezing_fog", 48), ("fog", 45),
]


def metar_values(raw):
    """Values from a raw METAR report, in the API's units: degC, km/h, degrees, Pa.
    e.g. 'KDWH 222353Z 09003KT 10SM CLR 19/10 A3010 RMK AO2 SLP192 T01940100' ->
    temperature 19.4, dewpoint 10.0, windSpeed 5.6, windDirection 90, seaLevelPressure 101920."""
    out = {}
    if not raw:
        return out
    body, _, rmk = raw.partition(" RMK ")
    m = re.search(r"\bT([01])(\d{3})(?:([01])(\d{3}))?\b", rmk)       # precise: tenths of a degree
    if m:
        out["temperature"] = (-1 if m.group(1) == "1" else 1) * int(m.group(2)) / 10
        if m.group(3):
            out["dewpoint"] = (-1 if m.group(3) == "1" else 1) * int(m.group(4)) / 10
    m = re.search(r"\s(M?\d{2})/(M?\d{2})?(?=\s|$)", " " + body)          # whole degrees
    if m:
        conv = lambda x: -int(x[1:]) if x.startswith("M") else int(x)
        out.setdefault("temperature", conv(m.group(1)))
        if m.group(2):
            out.setdefault("dewpoint", conv(m.group(2)))
    m = re.search(r"\b(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?(KT|MPS)\b", body)
    if m:
        k = 1.852 if m.group(4) == "KT" else 3.6
        out["windSpeed"] = int(m.group(2)) * k
        if m.group(3):
            out["windGust"] = int(m.group(3)) * k
        if m.group(1) != "VRB":
            out["windDirection"] = int(m.group(1))
    m = re.search(r"\bSLP(\d{3})\b", rmk)
    if m:
        v = int(m.group(1)) / 10
        out["seaLevelPressure"] = (v + (900 if v >= 50 else 1000)) * 100
    else:
        m = re.search(r"\bA(\d{4})\b", body)
        if m:
            out["seaLevelPressure"] = int(m.group(1)) / 100 * 3386.39
    return out


METAR_UNITS = {"temperature": "wmoUnit:degC", "dewpoint": "wmoUnit:degC", "windSpeed": "wmoUnit:km_h-1",
               "windGust": "wmoUnit:km_h-1", "windDirection": "wmoUnit:degree_(angle)", "seaLevelPressure": "wmoUnit:Pa"}


def fill_from_metar(o):
    """Fill values the API left null from the report's raw METAR text. Returns the names filled."""
    filled = []
    for k, v in metar_values(o.get("rawMessage") or "").items():
        cur = o.get(k)
        if not isinstance(cur, dict) or cur.get("value") is None:
            o[k] = {"unitCode": METAR_UNITS[k], "value": v}
            filled.append(k)
    t, d = (o.get("temperature") or {}).get("value"), (o.get("dewpoint") or {}).get("value")
    if "temperature" in filled or "dewpoint" in filled:
        if t is not None and d is not None and (o.get("relativeHumidity") or {}).get("value") is None:
            rh = 100 * math.exp(17.625 * d / (243.04 + d)) / math.exp(17.625 * t / (243.04 + t))
            o["relativeHumidity"] = {"unitCode": "wmoUnit:percent", "value": round(rh, 1)}
            filled.append("relativeHumidity")
    return filled


def nws_weather_code(conditions):
    """List of NWS weather condition dicts for one hour -> WMO code or None."""
    words = {(c or {}).get("weather") for c in (conditions or [])}
    for word, code in NWS_WX_CODES:
        if word in words:
            return code
    return None


def sun_times(day, lat, lon, zenith=90.833):
    """Sunrise/sunset (UTC datetimes) for a date, NOAA approximation (within ~1-2 min).
    zenith 90.833 = sunrise/sunset, 96 = civil twilight. Returns (None, None) during polar day/night."""
    n = day.timetuple().tm_yday
    lng_hour = lon / 15.0
    out = []
    for rising in (True, False):
        t = n + ((6 if rising else 18) - lng_hour) / 24
        m = 0.9856 * t - 3.289
        l_ = (m + 1.916 * math.sin(math.radians(m)) + 0.020 * math.sin(math.radians(2 * m)) + 282.634) % 360
        ra = math.degrees(math.atan(0.91764 * math.tan(math.radians(l_)))) % 360
        ra = (ra + (math.floor(l_ / 90) * 90 - math.floor(ra / 90) * 90)) / 15
        sin_dec = 0.39782 * math.sin(math.radians(l_))
        cos_dec = math.cos(math.asin(sin_dec))
        cos_h = (math.cos(math.radians(zenith)) - sin_dec * math.sin(math.radians(lat))) / (cos_dec * math.cos(math.radians(lat)))
        if not -1 <= cos_h <= 1:
            return None, None
        h = (360 - math.degrees(math.acos(cos_h)) if rising else math.degrees(math.acos(cos_h))) / 15
        ut = (h + ra - 0.06571 * t - 6.622 - lng_hour) % 24
        out.append(datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(hours=ut))
    return out[0], out[1]


def epa_time(s):
    """EPA UV DATE_TIME (local) e.g. 'Oct/22/2026 06 AM' -> naive local datetime, or None."""
    s = (s or "").strip()
    for fmt in ("%b/%d/%Y %I %p", "%b/%d/%Y %I:%M %p", "%m/%d/%Y %I %p", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s.title() if "%b" in fmt else s, fmt)
        except ValueError:
            pass
    return None


def ci_get(rec, *names):
    """Case-insensitive field lookup for EPA records."""
    low = {k.lower(): v for k, v in rec.items()}
    for n in names:
        if n.lower() in low:
            return low[n.lower()]
    return None


class Bridge:
    def __init__(self, cfg, data_dir):
        self.cfg = cfg
        self.metric = cfg.get("units", "imperial").lower() == "metric"

        self.data_dir = Path(data_dir)
        self.persist_path = self.data_dir / "wx_state.json"
        self.persist = {"override": "", "site": "", "thresholds": {}, "apikey": "", "contact": ""}
        try:
            self.persist.update(json.loads(self.persist_path.read_text()))
        except Exception:
            pass
        self.values = {k: "" for k in STATE_KEYS}
        self.values["SYS_ONLINE"] = 0
        self.values["SYS_UNITS"] = "metric" if self.metric else "imperial"
        self.clients = set()
        self.refresh_event = asyncio.Event()
        self.loc = None  # (lat, lon, name, source, candidates-key)
        self.loc_warning = ""
        self.geo_failed = set()  # (text, source) pairs that definitely don't resolve
        self.nws_cache = {}  # per-location NWS /points lookups
        self.meta = {}       # station / current-conditions details from the last forecast fetch
        self.uv_cache = {}   # per-city EPA UV forecasts
        self.met_cache = {}  # per-location MET Norway UV forecasts
        self.sun_cache = {}  # per-date USNO sun times
        self.uv_peak = dict(self.persist.get("uv_peak") or {})  # today's highest UV seen, survives restarts
        self.usno_pause_until = 0  # after a USNO failure, use calculated times for an hour
        self.last_ok = 0
        self.fail_count = 0

    @property
    def th(self):
        """Thresholds in use: config.json defaults, overridden by values sent from Savant."""
        t = dict(self.cfg["thresholds"])
        t.update(self.persist.get("thresholds") or {})
        return t

    def threshold_states(self):
        t = self.th
        v = {"TH_" + k.upper(): int(round(t[k])) for k in THRESHOLD_KEYS if k in t}
        v["TH_SOURCE"] = ", ".join(sorted(self.persist.get("thresholds") or {}))
        return v

    # ---------------- persistence ----------------
    def save_persist(self):
        try:
            self.persist_path.write_text(json.dumps(self.persist))
            os.chmod(self.persist_path, 0o600)  # may hold an API key
        except Exception as e:
            log.warning("could not save state: %s", e)

    # ---------------- location ----------------
    def location_candidates(self):
        """Configured locations in priority order: override, site, default."""
        out = []
        for text, source in ((self.persist.get("override", ""), "override"),
                             (self.persist.get("site", ""), "site"),
                             (str(self.cfg.get("default_location", "")), "default")):
            if text.strip():
                out.append((text.strip(), source))
        return out

    def geocode(self, text):
        """Return (lat, lon, name) for zip, 'lat,lon' or 'City, ST'."""
        m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*", text)
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
            if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
                raise ValueError(f"invalid coordinates '{text}'")
            return lat, lon, self.nws_place_name(lat, lon) or f"{lat:.3f}, {lon:.3f}"
        m = re.fullmatch(r"\s*(\d{5})(?:-\d{4})?\s*", text)
        if m:
            zip5 = m.group(1)
            try:
                d = http_json(f"https://api.zippopotam.us/us/{zip5}", self.ua)
                p = d["places"][0]
                return float(p["latitude"]), float(p["longitude"]), f"{p['place name']}, {p['state abbreviation']}"
            except Exception as e:
                log.info("zippopotam has no %s (%s), trying Open-Meteo postal search", zip5, e)
            q = urllib.parse.urlencode({"name": zip5, "count": 10, "language": "en", "format": "json"})
            d = http_json(f"https://geocoding-api.open-meteo.com/v1/search?{q}", self.ua)
            hits = [r for r in (d.get("results") or [])
                    if r.get("country_code") == "US" and zip5 in (r.get("postcodes") or [])]
            if not hits:
                raise ValueError(f"zip {zip5} not found")
            r = hits[0]
            abbr = next((a for a, n in US_STATES.items() if n == r.get("admin1")), r.get("admin1", ""))
            return float(r["latitude"]), float(r["longitude"]), f"{r['name']}, {abbr}".strip(", ")
        parts = [x.strip() for x in text.split(",")]
        city = parts[0]
        state = parts[1] if len(parts) > 1 else ""
        q = urllib.parse.urlencode({"name": city, "count": 20, "language": "en", "format": "json"})
        d = http_json(f"https://geocoding-api.open-meteo.com/v1/search?{q}", self.ua)
        results = d.get("results") or []
        if state:
            st = state.upper()
            full = US_STATES.get(st, state).lower()
            results = [r for r in results if (r.get("admin1") or "").lower() == full
                       or (r.get("admin1") or "").lower() == state.lower()] or results
        else:
            us = [r for r in results if r.get("country_code") == "US"]
            results = us or results
        if not results:
            raise ValueError(f"location '{text}' not found")
        r = results[0]
        abbr = next((a for a, n in US_STATES.items() if n == r.get("admin1")), r.get("admin1", ""))
        return float(r["latitude"]), float(r["longitude"]), f"{r['name']}, {abbr}".strip(", ")

    def nws_place_name(self, lat, lon):
        try:
            d = http_json(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}", self.ua)
            rl = d["properties"]["relativeLocation"]["properties"]
            return f"{rl['city']}, {rl['state']}"
        except Exception:
            return None

    def ensure_location(self):
        """Use the highest-priority location that resolves. A bad override or site
        falls back to the next one instead of stopping weather updates; the problem
        is reported in SYS_ERROR. Returns that warning ('' when none)."""
        cands = self.location_candidates()
        if not cands:
            raise ValueError("no location configured")
        want = tuple(cands)
        if self.loc and self.loc[4] == want:
            return self.loc_warning
        problems = []
        for text, source in cands:
            if (text, source) in self.geo_failed:
                problems.append(f"{source} '{text}' not found")
                continue
            try:
                lat, lon, name = self.geocode(text)
            except Exception as e:
                log.warning("could not resolve %s location '%s': %s", source, text, e)
                if isinstance(e, ValueError) or "404" in str(e):
                    self.geo_failed.add((text, source))  # definitely bad: don't retry until it changes
                problems.append(f"{source} '{text}' not found")
                continue
            self.loc = (lat, lon, name, source, want)
            self.loc_warning = "; ".join(problems) + (f", using {name} ({source})" if problems else "")
            log.info("location: %s (%s) -> %.4f, %.4f [%s]", text, name, lat, lon, source)
            if self.loc_warning:
                log.warning(self.loc_warning)
            return self.loc_warning
        raise ValueError("; ".join(problems) or "no usable location")

    # ---------------- fetch ----------------
    def fetch_forecast(self, lat, lon):
        cur = ("temperature_2m,apparent_temperature,relative_humidity_2m,dew_point_2m,is_day,precipitation,"
               "weather_code,cloud_cover,pressure_msl,wind_speed_10m,wind_direction_10m,wind_gusts_10m")
        hourly = ("temperature_2m,apparent_temperature,precipitation_probability,precipitation,weather_code,"
                  "cloud_cover,wind_speed_10m,wind_gusts_10m,uv_index,is_day")
        daily = ("weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
                 "wind_gusts_10m_max,uv_index_max,sunrise,sunset,apparent_temperature_max")
        p = {"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "current": cur, "hourly": hourly,
             "daily": daily, "timezone": "auto", "forecast_days": 7}
        if not self.metric:
            p.update(temperature_unit="fahrenheit", wind_speed_unit="mph", precipitation_unit="inch")
        host = "api.open-meteo.com"
        if self.api_key():
            host = "customer-api.open-meteo.com"
            p["apikey"] = self.api_key()
        return http_json(f"https://{host}/v1/forecast?{urllib.parse.urlencode(p)}", self.ua)

    # ---------------- free source: NWS + EPA UV ----------------
    def nws_point(self, lat, lon):
        """/points lookup (grid URLs, station list, time zone, city), cached for 12 h per location."""
        key = (round(lat, 4), round(lon, 4))
        hit = self.nws_cache.get(key)
        if hit and time.time() - hit["at"] < 12 * 3600:
            return hit
        try:
            p = http_json(f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}", self.ua)["properties"]
        except Exception as e:
            if "404" in str(e):
                raise ValueError("the free NWS forecast covers the US only; set an Open-Meteo API key for this location")
            raise
        rl = (p.get("relativeLocation") or {}).get("properties") or {}
        info = {"at": time.time(), "grid": p["forecastGridData"], "stations": p.get("observationStations"),
                "tz": p.get("timeZone"), "city": rl.get("city"), "state": rl.get("state"), "station": None}
        info.update(station_name="", station_where="")
        if info["stations"]:
            try:
                feats = http_json(info["stations"], self.ua).get("features") or []
                info["station_list"] = []
                for f in feats[:3]:  # NWS lists stations nearest the forecast point first
                    coords = (f.get("geometry") or {}).get("coordinates")
                    info["station_list"].append({
                        "id": f["properties"]["stationIdentifier"], "name": f["properties"].get("name") or "",
                        "where": self.distance_text(lat, lon, coords[1], coords[0]) if coords and len(coords) >= 2 else ""})
                if info["station_list"]:
                    first = info["station_list"][0]
                    info.update(station=first["id"], station_name=first["name"], station_where=first["where"])
            except Exception as e:
                log.info("NWS station list unavailable: %s", e)
        self.nws_cache[key] = info
        return info

    def distance_text(self, lat1, lon1, lat2, lon2):
        """'11 mi NW' from the site to a point (km when metric)."""
        r = 6371.0
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp, dl = p2 - p1, math.radians(lon2 - lon1)
        km = 2 * r * math.asin(math.sqrt(math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))
        brg = math.degrees(math.atan2(math.sin(dl) * math.cos(p2),
                                      math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl))) % 360
        dist = f"{round(km)} km" if self.metric else f"{round(km * 0.621371)} mi"
        return f"{dist} {cardinal(brg)}" if km >= 0.5 else "at the site"

    def sun_for(self, day, lat, lon, utc_offset_h):
        """Sunrise/sunset/civil twilight for one local date as aware UTC datetimes.
        US Naval Observatory first (cached per date), the built-in calculation if USNO is unreachable."""
        key = (day.isoformat(), round(lat, 3), round(lon, 3), utc_offset_h)
        if key in self.sun_cache:
            return self.sun_cache[key]
        res = None
        try:
            if time.time() < self.usno_pause_until:
                raise IOError("paused after an earlier failure")
            q = urllib.parse.urlencode({"date": day.isoformat(), "coords": f"{lat:.4f},{lon:.4f}", "tz": f"{utc_offset_h:g}"})
            data = http_json(f"https://aa.usno.navy.mil/api/rstt/oneday?{q}", self.ua, timeout=10)
            phen = {}
            for e in ((data.get("properties") or {}).get("data") or {}).get("sundata") or []:
                m = re.match(r"(\d{1,2}):(\d{2})", str(e.get("time") or ""))
                if m:
                    local_dt = datetime(day.year, day.month, day.day, int(m.group(1)), int(m.group(2)))
                    phen[e.get("phen")] = (local_dt - timedelta(hours=utc_offset_h)).replace(tzinfo=timezone.utc)
            if "Rise" in phen and "Set" in phen:
                res = {"rise": phen["Rise"], "set": phen["Set"], "dawn": phen.get("Begin Civil Twilight"),
                       "dusk": phen.get("End Civil Twilight"), "source": "US Naval Observatory"}
        except Exception as e:
            if time.time() >= self.usno_pause_until:
                log.info("USNO sun times unavailable (%s); using calculated times, retrying in 1 h", e)
                self.usno_pause_until = time.time() + 3600
        if res is None:
            rise, sset = sun_times(day, lat, lon)
            dawn, dusk = sun_times(day, lat, lon, zenith=96)
            res = {"rise": rise, "set": sset, "dawn": dawn, "dusk": dusk, "source": "Calculated"}
            return res  # not cached: retry USNO next refresh
        if len(self.sun_cache) > 60:
            self.sun_cache.clear()
        self.sun_cache[key] = res
        return res

    def met_uv(self, lat, lon):
        """MET Norway clear-sky UV forecast {aware UTC hour: uv} (hourly ~2-3 days, then 6-hourly), cached 1 h.
        Clear-sky = the UV with no clouds, so it overstates UV on cloudy days."""
        key = (round(lat, 2), round(lon, 2))
        hit = self.met_cache.get(key)
        if hit and time.time() - hit[0] < 3600:
            return hit[1]
        out = {}
        try:
            # MET Norway terms: at most 4 decimals, identifying User-Agent with contact info
            d = http_json(f"https://api.met.no/weatherapi/locationforecast/2.0/complete?lat={lat:.4f}&lon={lon:.4f}", self.ua)
            for ts in (d.get("properties") or {}).get("timeseries") or []:
                det = ((ts.get("data") or {}).get("instant") or {}).get("details") or {}
                v = det.get("ultraviolet_index_clear_sky")
                if v is not None:
                    out[parse_utc(ts["time"]).replace(minute=0, second=0)] = float(v)
        except Exception as e:
            log.info("MET Norway UV unavailable: %s", e)  # cached empty for 1 h, so not retried every refresh
        self.met_cache[key] = (time.time(), out)
        return out

    def epa_uv(self, city, state, zip5=None):
        """EPA hourly UV forecast {naive local datetime: uv}, cached 1 h. Empty dict if unavailable.
        Tries the ZIP code first (EPA covers far more ZIPs than city names), then city/state."""
        tries = []
        if zip5:
            tries.append((("ZIP", zip5), f"ZIP/{zip5}"))
        if city and state:
            tries.append((("CITY", city.upper(), state.upper()),
                          f"CITY/{urllib.parse.quote(city.upper())}/STATE/{state.upper()}"))
        for key, path in tries:
            hit = self.uv_cache.get(key)
            if hit and time.time() - hit[0] < 3600:
                if hit[1]:
                    return hit[1]
                continue
            out = {}
            try:
                for rec in http_json(f"https://data.epa.gov/dmapservice/getEnvirofactsUVHOURLY/{path}/JSON", self.ua) or []:
                    t = epa_time(str(ci_get(rec, "DATE_TIME") or ""))
                    v = ci_get(rec, "UV_VALUE", "UV_INDEX")
                    if t is not None and v not in (None, ""):
                        out[t.replace(minute=0)] = float(v)
            except Exception as e:
                log.info("EPA UV unavailable for %s: %s", path, e)
            self.uv_cache[key] = (time.time(), out)
            if out:
                return out
        return {}

    def location_zip(self):
        """The 5-digit ZIP of the location in use, if it was entered as a ZIP."""
        if not self.loc:
            return None
        source = self.loc[3]
        for text, src in self.loc[4]:
            if src == source:
                m = re.fullmatch(r"\s*(\d{5})(?:-\d{4})?\s*", text)
                return m.group(1) if m else None
        return None

    def fetch_nws_forecast(self, lat, lon):
        """Build an Open-Meteo-shaped forecast dict from NWS gridpoint data."""
        metric = self.metric
        pt = self.nws_point(lat, lon)
        grid = None
        for attempt in range(2):  # NWS gridpoints occasionally answer 5xx; one retry
            try:
                grid = http_json(pt["grid"], self.ua)["properties"]
                break
            except Exception:
                if attempt:
                    raise
                time.sleep(2)
        tz = None
        if ZoneInfo and pt.get("tz"):
            try:
                tz = ZoneInfo(pt["tz"])
            except Exception:
                tz = None
        local = (lambda dt: dt.astimezone(tz)) if tz else (lambda dt: dt.astimezone())

        # hourly timeline (UTC): from the start of the current local day to 7 days out
        now_utc = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        now_local = local(now_utc)
        day_start = now_utc - timedelta(hours=now_local.hour)
        hours = [day_start + timedelta(hours=i) for i in range(24 * 7)]

        def layer(name, conv=None, spread=False):
            lay = grid.get(name) or {}
            vals = expand_layer(lay, hours, spread)
            if conv:
                u = unit_of(lay)
                vals = [conv(v, u, metric) for v in vals]
            return vals

        temp = layer("temperature", to_temp)
        feels = layer("apparentTemperature", to_temp)
        dew = layer("dewpoint", to_temp)
        rh = layer("relativeHumidity")
        sky = layer("skyCover")
        wdir = layer("windDirection")
        wind = layer("windSpeed", to_speed)
        gust = layer("windGust", to_speed)
        pop = layer("probabilityOfPrecipitation")
        qpf = layer("quantitativePrecipitation", to_precip, spread=True)
        wx = [nws_weather_code(c) for c in expand_layer(grid.get("weather"), hours)]
        feels = [f if f is not None else t for f, t in zip(feels, temp)]
        gust = [max(g, w) if g is not None and w is not None else (g if g is not None else w) for g, w in zip(gust, wind)]

        # sun and day/night
        days = sorted({local(h).date() for h in hours})
        def offset_h(d):
            noon = datetime(d.year, d.month, d.day, 12)
            off = noon.replace(tzinfo=tz).utcoffset() if tz else noon.astimezone().utcoffset()
            return off.total_seconds() / 3600
        suns = {d: self.sun_for(d, lat, lon, offset_h(d)) for d in days[:7]}
        sun = {d: (suns[d]["rise"], suns[d]["set"]) if d in suns else sun_times(d, lat, lon) for d in days}
        self.set_sun_meta(suns.get(days[0]), local)
        def is_day(h):
            rise, sset = sun[local(h).date()]
            if rise is None:
                return 1 if 3 <= local(h).month <= 9 and lat > 0 else 0
            return 1 if rise <= h + timedelta(minutes=30) < sset + timedelta(minutes=30) else 0
        isday = [is_day(h) for h in hours]

        # UV (EPA, US, today only); unknown hours stay None
        uv_map = self.epa_uv(pt.get("city"), pt.get("state"), self.location_zip())
        uv = [uv_map.get(local(h).replace(tzinfo=None)) for h in hours]
        if uv_map:  # night hours are 0, but only on days EPA actually covers; other days stay unknown
            uv_days = {t.date() for t in uv_map}
            uv = [u if u is not None else (0.0 if not d and local(h).date() in uv_days else None)
                  for u, d, h in zip(uv, isday, hours)]
        else:
            uv_days = set()
        # days EPA doesn't cover: MET Norway clear-sky UV (hourly, then every 6 h further out)
        met = self.met_uv(lat, lon)
        used_met = False
        for i, h in enumerate(hours):
            if local(h).date() not in uv_days and h in met:
                uv[i] = met[h]
                used_met = used_met or local(h).date() > now_local.date() or not uv_map
        parts = (["EPA (today)"] if uv_map else []) + (["MET Norway clear-sky" + (" (later days)" if uv_map else "")] if used_met else [])
        self.meta["SYS_UV_SOURCE"] = " + ".join(parts)

        def iso(h):
            return local(h).strftime("%Y-%m-%dT%H:00")

        hourly = {"time": [iso(h) for h in hours], "temperature_2m": temp, "apparent_temperature": feels,
                  "precipitation_probability": pop, "precipitation": qpf, "weather_code": wx,
                  "cloud_cover": sky, "wind_speed_10m": wind, "wind_gusts_10m": gust, "uv_index": uv,
                  "is_day": isday}

        # daily: group hours by local calendar day
        dly = {k: [] for k in ("time", "weather_code", "temperature_2m_max", "temperature_2m_min",
                               "precipitation_probability_max", "wind_gusts_10m_max", "uv_index_max",
                               "sunrise", "sunset", "apparent_temperature_max")}
        for d in days[:7]:
            idx = [i for i, h in enumerate(hours) if local(h).date() == d]
            pick = lambda arr: [arr[i] for i in idx if arr[i] is not None]
            ts, fs, ps, gs, us = pick(temp), pick(feels), pick(pop), pick(gust), pick(uv)
            pmax = max(ps) if ps else 0
            wet = [wx[i] for i in idx if wx[i] is not None and (pop[i] or 0) >= 30]
            if wet:
                code = next(c for _, c in NWS_WX_CODES if c in wet)
            else:
                day_sky = [sky[i] for i in idx if sky[i] is not None and isday[i]] or pick(sky)
                mean = sum(day_sky) / len(day_sky) if day_sky else 0
                code = 0 if mean <= 30 else (2 if mean <= 70 else 3)
            rise, sset = sun[d]
            dly["time"].append(d.isoformat())
            dly["weather_code"].append(code)
            dly["temperature_2m_max"].append(max(ts) if ts else None)
            dly["temperature_2m_min"].append(min(ts) if ts else None)
            dly["precipitation_probability_max"].append(pmax)
            dly["wind_gusts_10m_max"].append(max(gs) if gs else None)
            day_max = max(us) if us else None
            if d == now_local.date():
                seen = self.uv_peak.get(d.isoformat())
                if day_max is not None or seen is not None:
                    day_max = max(x for x in (day_max, seen) if x is not None)
                    if self.uv_peak.get(d.isoformat()) != day_max:
                        self.uv_peak = {d.isoformat(): day_max}  # only today's is kept
                        self.persist["uv_peak"] = self.uv_peak
                        self.save_persist()
            dly["uv_index_max"].append(day_max)
            dly["sunrise"].append(local(rise).strftime("%Y-%m-%dT%H:%M") if rise else "")
            dly["sunset"].append(local(sset).strftime("%Y-%m-%dT%H:%M") if sset else "")
            dly["apparent_temperature_max"].append(max(fs) if fs else None)

        # current: this hour of the grid, refined by the latest station observation when fresh
        i = hours.index(now_utc) if now_utc in hours else 0
        cur = {"time": iso(now_utc), "temperature_2m": temp[i], "apparent_temperature": feels[i],
               "relative_humidity_2m": rh[i], "dew_point_2m": dew[i], "is_day": self.day_now(sun, local),
               "precipitation": qpf[i], "weather_code": wx[i] if (pop[i] or 0) >= 30 else None,
               "cloud_cover": sky[i], "pressure_msl": None, "wind_speed_10m": wind[i],
               "wind_direction_10m": wdir[i], "wind_gusts_10m": gust[i]}
        self.meta.update(SYS_STATION_ID=pt.get("station") or "", SYS_STATION_NAME=pt.get("station_name", ""),
                         SYS_STATION_DISTANCE=pt.get("station_where", ""), SYS_STATION_OBS_TIME="",
                         SYS_CURRENT_SOURCE="Forecast hour (no station)" if not pt.get("station") else "")
        self.apply_observation(cur, pt.get("station_list") or [])
        return {"current": cur, "hourly": hourly, "daily": dly}

    @staticmethod
    def day_now(sun, local):
        """1 between sunrise and sunset right now (the forecast hours use the hour's start)."""
        now = datetime.now(timezone.utc)
        rise, sset = sun.get(local(now).date(), (None, None))
        if rise is None or sset is None:
            return 1 if 6 <= local(now).hour < 18 else 0
        return 1 if rise <= now < sset else 0

    def newest_observation(self, station_id):
        """Newest report with a temperature from the station's recent observations.
        NWS's /observations/latest can lag hours behind (it returns the newest report that passed its
        quality checks), so read the recent list first and fall back to /latest."""
        try:
            d = http_json(f"https://api.weather.gov/stations/{station_id}/observations?limit=5", self.ua)
            best = None
            for f in d.get("features") or []:
                o = f.get("properties") or {}
                if not o.get("timestamp"):
                    continue
                filled = fill_from_metar(o)  # the API sometimes leaves values null that the raw report has
                if filled:
                    o["_metar_filled"] = filled
                if (o.get("temperature") or {}).get("value") is None:
                    continue
                if best is None or parse_utc(o["timestamp"]) > parse_utc(best["timestamp"]):
                    best = o
            if best:
                return best
        except Exception as e:
            log.info("recent observations unavailable from %s (%s); trying /latest", station_id, e)
        o = http_json(f"https://api.weather.gov/stations/{station_id}/observations/latest", self.ua)["properties"]
        filled = fill_from_metar(o)
        if filled:
            o["_metar_filled"] = filled
        return o

    def apply_observation(self, cur, stations):
        """Overlay the latest observation from the nearest station with a report under 90 minutes old
        (tries up to 3 stations, nearest first). Station states describe the station actually used."""
        if not stations:
            return
        o = None
        stale = []
        for st in stations:
            try:
                obs = self.newest_observation(st["id"])
                obs_t = parse_utc(obs["timestamp"])
            except Exception as e:
                log.info("observation unavailable from %s: %s", st["id"], e)
                stale.append(st["id"])
                continue
            if datetime.now(timezone.utc) - obs_t > timedelta(minutes=90):
                stale.append(st["id"])
                continue
            if (obs.get("temperature") or {}).get("value") is None:
                stale.append(st["id"])
                continue
            o = obs
            if obs.get("_metar_filled"):
                log.info("%s: filled %s from the raw report", st["id"], ", ".join(obs["_metar_filled"]))
            self.meta.update(SYS_STATION_ID=st["id"], SYS_STATION_NAME=st["name"], SYS_STATION_DISTANCE=st["where"],
                             SYS_CURRENT_SOURCE=f"Station {st['id']}" + (f" ({', '.join(stale)} no recent report)" if stale else ""),
                             SYS_STATION_OBS_TIME=obs_t.astimezone().strftime("%I:%M %p").lstrip("0"))
            break
        if o is None:
            self.meta["SYS_CURRENT_SOURCE"] = f"Forecast hour (no recent report from {', '.join(stale)})"
            return
        m = self.metric
        val = lambda k: (o.get(k) or {}).get("value")
        u = lambda k: unit_of(o.get(k))
        t = to_temp(val("temperature"), u("temperature"), m)
        if t is not None:
            cur["temperature_2m"] = t
            feel = val("heatIndex") if val("heatIndex") is not None else val("windChill")
            unit = u("heatIndex") if val("heatIndex") is not None else u("windChill")
            cur["apparent_temperature"] = to_temp(feel, unit, m) if feel is not None else t
        for k, dest, conv in (("dewpoint", "dew_point_2m", to_temp), ("windSpeed", "wind_speed_10m", to_speed)):
            if val(k) is not None:
                cur[dest] = conv(val(k), u(k), m)
        if val("relativeHumidity") is not None:
            cur["relative_humidity_2m"] = val("relativeHumidity")
        if val("windDirection") is not None:
            cur["wind_direction_10m"] = val("windDirection")
        g = to_speed(val("windGust"), u("windGust"), m)
        if g is not None:
            cur["wind_gusts_10m"] = g
        elif val("windSpeed") is not None:
            # stations only report a gust when it's gusting: no gust in a report = gust equals the wind
            cur["wind_gusts_10m"] = cur["wind_speed_10m"]
        p = val("seaLevelPressure") or val("barometricPressure")
        if p is not None:
            cur["pressure_msl"] = p / 100.0  # Pa -> hPa

    # ---------------- source selection ----------------
    @property
    def contact_email(self):
        """Contact sent to the data providers: Blueprint's Contact Email first, else config.json."""
        return (self.persist.get("contact") or str(self.cfg.get("contact_email") or "")).strip()

    @property
    def ua(self):
        # NWS, EPA, MET Norway and USNO ask for an identifying User-Agent with contact info
        return f"(SavantOpenWx/{VERSION}, {self.contact_email or 'unknown'})"

    def contact_is_placeholder(self):
        return not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", self.contact_email) or \
            bool(re.search(r"@(example\.com|yourcompany\.com)$", self.contact_email, re.I))

    def key_setting(self):
        """What's in the API key field: Blueprint value first, else config.json."""
        return (self.persist.get("apikey") or self.cfg.get("openmeteo_api_key") or "").strip()

    def is_private(self):
        return self.key_setting().lower() == "private"

    def api_key(self):
        """A real Open-Meteo key, or '' (the word 'private' is not a key)."""
        return "" if self.is_private() else self.key_setting()

    def primary_source(self):
        mode = str(self.cfg.get("forecast_source", "auto")).lower()
        if mode in ("nws", "openmeteo"):
            return mode
        return "openmeteo" if self.key_setting() else "nws"

    def set_sun_meta(self, today, local):
        """Today's dawn/dusk and the sun source, as Savant states."""
        if not today:
            return
        fmt = lambda dt: local(dt).strftime("%I:%M %p").lstrip("0") if dt else ""
        self.meta.update(SUN_DAWN=fmt(today["dawn"]), SUN_DUSK=fmt(today["dusk"]), SYS_SUN_SOURCE=today["source"])

    def apply_usno_to_openmeteo(self, fc, lat, lon):
        """Replace Open-Meteo's sunrise/sunset with USNO times (same source as the free path)."""
        off = (fc.get("utc_offset_seconds") or 0) / 3600
        local_tz = timezone(timedelta(hours=off))
        local = lambda dt: dt.astimezone(local_tz)
        dy = fc.get("daily") or {}
        first = None
        for i, ds in enumerate(dy.get("time") or []):
            d = parse_iso(ds).date()
            sun = self.sun_for(d, lat, lon, off)
            if sun["source"] == "US Naval Observatory":
                if sun["rise"]:
                    dy["sunrise"][i] = local(sun["rise"]).strftime("%Y-%m-%dT%H:%M")
                if sun["set"]:
                    dy["sunset"][i] = local(sun["set"]).strftime("%Y-%m-%dT%H:%M")
            first = first or sun
        if first and first["source"] != "US Naval Observatory":
            first = dict(first, source="Open-Meteo")
        self.set_sun_meta(first, local)

    def fetch_any_forecast(self, lat, lon):
        """Returns (forecast, source label). Key present -> Open-Meteo commercial, else free NWS.
        If Open-Meteo fails, falls back to NWS for that refresh."""
        primary = self.primary_source()
        self.meta = {}
        if primary == "nws":
            return self.fetch_nws_forecast(lat, lon), "NWS (free)"
        try:
            if self.api_key():
                label = "Open-Meteo (API key)"
            else:
                label = "Open-Meteo free (private, non-commercial use only)"
            fc = self.fetch_forecast(lat, lon)
            self.meta.update(SYS_CURRENT_SOURCE="Open-Meteo model", SYS_STATION_ID="", SYS_STATION_NAME="",
                             SYS_STATION_DISTANCE="", SYS_STATION_OBS_TIME="", SYS_UV_SOURCE="Open-Meteo")
            try:
                self.apply_usno_to_openmeteo(fc, lat, lon)
            except Exception as e:
                log.info("USNO override skipped: %s", e)
            return fc, label
        except Exception as e:
            log.warning("Open-Meteo failed (%s); using NWS for this update", e)
            return self.fetch_nws_forecast(lat, lon), "NWS (Open-Meteo unavailable)"

    def fetch_alerts(self, lat, lon):
        try:
            d = http_json(f"https://api.weather.gov/alerts/active?point={lat:.4f},{lon:.4f}", self.ua)
            return [f["properties"] for f in d.get("features", [])], None
        except Exception as e:
            return None, str(e)

    # ---------------- compute ----------------
    def compute(self, fc, alerts):
        th = self.th
        v = {}
        c = fc["current"]
        hr = fc["hourly"]
        dy = fc["daily"]
        now_iso = c.get("time", "")
        # index of current hour in hourly arrays
        times = hr["time"]
        cur_hour = now_iso[:13] if now_iso else datetime.now().strftime("%Y-%m-%dT%H")
        start = next((i for i, t in enumerate(times) if t[:13] >= cur_hour), 0)

        def H(name, i):
            arr = hr.get(name) or []
            return arr[i] if i < len(arr) else None

        uv_now = H("uv_index", start)
        is_day = bool(c.get("is_day"))
        gust_now = c.get("wind_gusts_10m")
        v["CUR_TEMP"] = rnd(c.get("temperature_2m"))
        v["CUR_FEELS"] = rnd(c.get("apparent_temperature"))
        v["CUR_HUMIDITY"] = rnd(c.get("relative_humidity_2m"))
        v["CUR_DEWPOINT"] = rnd(c.get("dew_point_2m"))
        v["CUR_WIND"] = rnd(c.get("wind_speed_10m"))
        v["CUR_GUST"] = rnd(gust_now)
        v["CUR_WIND_DIR"] = cardinal(c.get("wind_direction_10m"))
        v["CUR_WIND_DEG"] = rnd(c.get("wind_direction_10m"))
        v["CUR_UV"] = rnd(uv_now)
        v["CUR_UV_LEVEL"] = uv_level(uv_now)
        v["CUR_CLOUD"] = rnd(c.get("cloud_cover"))
        pr = c.get("precipitation")
        v["CUR_PRECIP"] = "" if pr is None else f"{pr:.2f}" if not self.metric else f"{pr:.1f}"
        v["CUR_PRESSURE"] = rnd(c.get("pressure_msl"))
        v["CUR_IS_DAY"] = 1 if is_day else 0
        v["CUR_SKY"] = sky_label(c.get("cloud_cover"), is_day)
        v["CUR_WEATHER"] = weather_label(c.get("weather_code"), c.get("cloud_cover"), is_day)
        v["CUR_COMFORT"] = comfort_label(c.get("apparent_temperature"), self.metric)
        v["CUR_SUMMARY"] = f"{v['CUR_COMFORT']} & {v['CUR_WEATHER']}".strip(" &")
        v["CUR_ICON"] = icon_key(c.get("weather_code"), c.get("cloud_cover"), is_day, gust_now, th["wind_icon_gust"])

        freeze = th["freeze_temp"] if not self.metric else 0
        # windows
        for w, n in WINDOWS.items():
            idx = list(range(start, min(start + n, len(times))))
            temps = [H("temperature_2m", i) for i in idx if H("temperature_2m", i) is not None]
            feels = [H("apparent_temperature", i) for i in idx if H("apparent_temperature", i) is not None]
            pops = [H("precipitation_probability", i) or 0 for i in idx]
            precs = [H("precipitation", i) or 0 for i in idx]
            winds = [H("wind_speed_10m", i) or 0 for i in idx]
            gusts = [(H("wind_gusts_10m", i) or 0, i) for i in idx]
            uvs = [H("uv_index", i) for i in idx if H("uv_index", i) is not None]
            skies = [sky_label(H("cloud_cover", i), H("is_day", i)) for i in idx]
            wx = []
            for i in idx:
                lab = weather_label(H("weather_code", i), H("cloud_cover", i), H("is_day", i))
                # precipitation codes only count if the hour's chance is meaningful
                if lab in ("Stormy", "Rainy", "Snowy", "Icy") and (H("precipitation_probability", i) or 0) < 30:
                    lab = weather_label(None, H("cloud_cover", i), H("is_day", i))
                wx.append(lab)
            gmax, gi = max(gusts, key=lambda g: g[0]) if gusts else (None, None)  # earliest hour on ties
            rain_max = max(pops) if pops else 0
            sig = next((s for s in SIGNIFICANCE[:5] if s in wx), None)
            if sig is None:
                # no precip/fog: use the dominant sky type
                sig = Counter(x for x in wx if x).most_common(1)[0][0] if any(wx) else ""
            if feels and max(feels) >= (82 if not self.metric else 28):
                comf = comfort_label(max(feels), self.metric)
            else:
                comf = comfort_label(min(feels) if feels else None, self.metric)
            total = sum(precs)
            v[f"{w}_TEMP_HIGH"] = rnd(max(temps)) if temps else ""
            v[f"{w}_TEMP_LOW"] = rnd(min(temps)) if temps else ""
            v[f"{w}_FEELS_HIGH"] = rnd(max(feels)) if feels else ""
            v[f"{w}_FEELS_LOW"] = rnd(min(feels)) if feels else ""
            v[f"{w}_RAIN_CHANCE"] = rnd(rain_max)
            v[f"{w}_RAIN_TOTAL"] = f"{total:.2f}" if not self.metric else f"{total:.1f}"
            v[f"{w}_WIND_MAX"] = rnd(max(winds)) if winds else ""
            v[f"{w}_GUST_MAX"] = rnd(gmax)
            v[f"{w}_GUST_MAX_TIME"] = hour_label(times[gi]) if gi is not None else ""
            v[f"{w}_UV_MAX"] = rnd(max(uvs)) if uvs else ""
            v[f"{w}_SKY"] = Counter(s for s in skies if s).most_common(1)[0][0] if any(skies) else ""
            v[f"{w}_WEATHER"] = sig
            v[f"{w}_COMFORT"] = comf
            rain_txt = f", {rnd(rain_max)}% rain" if rain_max >= 20 else ""
            v[f"{w}_SUMMARY"] = f"{comf} & {sig}{rain_txt}".strip(" &")
            icon_map = {"Stormy": "thunder", "Icy": "sleet", "Snowy": "snow", "Rainy": "rain", "Foggy": "fog",
                        "Cloudy": "cloudy", "Partly Cloudy": "partly-day", "Sunny": "clear-day", "Clear": "clear-night"}
            v[f"{w}_ICON"] = "wind" if (gmax or 0) >= th["wind_icon_gust"] and sig not in ("Stormy",) \
                else icon_map.get(sig, "")
            v[f"{w}_RAIN_EXPECTED"] = 1 if rain_max >= th["rain_expected_chance"] else 0
            v[f"{w}_FREEZE_EXPECTED"] = 1 if temps and min(temps) <= freeze else 0

        # hourly strip
        for s in range(8):
            i = start + s * 3
            if i >= len(times):
                break
            n = s + 1
            v[f"HR{n}_TIME"] = "Now" if s == 0 else hour_label(times[i])
            v[f"HR{n}_TEMP"] = rnd(H("temperature_2m", i))
            v[f"HR{n}_RAIN"] = rnd(H("precipitation_probability", i))
            v[f"HR{n}_GUST"] = rnd(H("wind_gusts_10m", i))
            v[f"HR{n}_ICON"] = icon_key(H("weather_code", i) if (H("precipitation_probability", i) or 0) >= 30
                                        else None, H("cloud_cover", i), H("is_day", i),
                                        H("wind_gusts_10m", i), th["wind_icon_gust"])

        # daily
        for d in range(5):
            if d >= len(dy["time"]):
                break
            code = dy["weather_code"][d]
            pop = (dy.get("precipitation_probability_max") or [None] * 7)[d] or 0
            if pop < 30 and code_kind(code) not in ("none", "fog"):
                code = 2  # low chance: show as partly cloudy instead of a rain icon
            wl = weather_label(code, 50 if code == 2 else (90 if code == 3 else 10), True)
            hi = dy["temperature_2m_max"][d]
            feels_hi = (dy.get("apparent_temperature_max") or [hi] * 7)[d]
            name = "Today" if d == 0 else parse_iso(dy["time"][d]).strftime("%a")
            v[f"D{d}_NAME"] = name
            v[f"D{d}_HIGH"] = rnd(hi)
            v[f"D{d}_LOW"] = rnd(dy["temperature_2m_min"][d])
            v[f"D{d}_RAIN_CHANCE"] = rnd(pop)
            v[f"D{d}_GUST_MAX"] = rnd(dy["wind_gusts_10m_max"][d])
            v[f"D{d}_UV_MAX"] = rnd(dy["uv_index_max"][d])
            v[f"D{d}_WEATHER"] = wl
            comf = comfort_label(feels_hi, self.metric)
            v[f"D{d}_SUMMARY"] = f"{comf} & {wl}" + (f", {rnd(pop)}% rain" if pop >= 20 else "")
            v[f"D{d}_ICON"] = icon_key(code, 50 if code == 2 else (90 if code == 3 else 10), True,
                                       dy["wind_gusts_10m_max"][d], th["wind_icon_gust"])
        v["SUN_RISE"] = time_label(dy["sunrise"][0])
        v["SUN_SET"] = time_label(dy["sunset"][0])

        # alerts
        if alerts is not None:
            alerts = sorted(alerts, key=lambda a: -SEVERITY_RANK.get(a.get("severity", "Unknown"), 0))
            # NWS often issues the same alert more than once (overlapping zones, updates): keep one per
            # event name, the one ending latest
            def ends_of(a):
                try:
                    return parse_iso(a.get("ends") or a.get("expires") or "")
                except Exception:
                    return datetime.min
            uniq = {}
            for a in alerts:
                e = a.get("event", "")
                if e not in uniq or ends_of(a) > ends_of(uniq[e]):
                    uniq[e] = a
            alerts = list(uniq.values())
            v["ALERT_ACTIVE"] = 1 if alerts else 0
            v["ALERT_COUNT"] = len(alerts)
            v["ALERT_HIGHEST_SEVERITY"] = alerts[0].get("severity", "Unknown") if alerts else "None"
            v["ALERT_HEADLINE"] = (alerts[0].get("headline") or alerts[0].get("event", "")) if alerts else ""
            events = list(dict.fromkeys(a.get("event", "") for a in alerts))
            v["ALERT_EVENTS"] = ", ".join(events)
            for cat, words in ALERT_CATEGORIES.items():
                hit = any(any(wd in e.lower() for wd in words) for e in events)
                if cat == "WIND":  # don't flag wind chill as a wind event
                    hit = any(("wind" in e.lower() and "chill" not in e.lower()) or "gale" in e.lower()
                              for e in events)
                v[f"ALERT_{cat}"] = 1 if hit else 0
            for i in range(1, 4):
                a = alerts[i - 1] if i <= len(alerts) else {}
                v[f"ALERT{i}_EVENT"] = a.get("event", "")
                v[f"ALERT{i}_SEVERITY"] = a.get("severity", "")
                ends = a.get("ends") or a.get("expires") or ""
                try:
                    v[f"ALERT{i}_EXPIRES"] = parse_iso(ends).strftime("%a %I:%M %p").replace(" 0", " ") if ends else ""
                except Exception:
                    v[f"ALERT{i}_EXPIRES"] = ends
                v[f"ALERT{i}_HEADLINE"] = a.get("headline", "")
            parts = []
            for a in alerts:
                ends = a.get("ends") or a.get("expires") or ""
                try:
                    until = " until " + parse_iso(ends).strftime("%a %I:%M %p").replace(" 0", " ") if ends else ""
                except Exception:
                    until = ""
                parts.append(a.get("event", "") + until)
            v["ALERTS_LIST"] = " · ".join(parts) if parts else "No active alerts"

        self.add_display_text(v, alerts is not None)

        # action flags
        g3 = v.get("H3_GUST_MAX") or 0
        v["ACT_WIND_PROTECT"] = 1 if max(v["CUR_GUST"] or 0, g3) >= th["wind_protect_gust"] else 0
        v["ACT_RAIN_SOON"] = 1 if (v.get("H3_RAIN_CHANCE") or 0) >= th["rain_soon_chance"] else 0
        freeze_alert = (v.get("ALERT_FREEZE") if alerts is not None else self.values.get("ALERT_FREEZE")) or 0
        v["ACT_FREEZE_TONIGHT"] = 1 if v.get("H12_FREEZE_EXPECTED") or freeze_alert else 0
        v["ACT_HIGH_UV"] = 1 if (v["CUR_UV"] or 0) >= th["high_uv"] else 0
        heat_alert = (v.get("ALERT_HEAT") if alerts is not None else self.values.get("ALERT_HEAT")) or 0
        heat_thr = th["heat_feels"] if not self.metric else (th["heat_feels"] - 32) * 5 / 9
        v["ACT_HEAT"] = 1 if (v["CUR_FEELS"] or 0) >= heat_thr or heat_alert else 0
        return v

    def add_display_text(self, v, have_alerts):
        """Ready-to-display strings for Savant labels."""
        deg = lambda x: "" if x in ("", None) else f"{x}°"
        speed = "km/h" if self.metric else "mph"
        v["CUR_TEMP_TEXT"] = deg(v.get("CUR_TEMP"))
        v["CUR_FEELS_TEXT"] = f"Feels like {deg(v.get('CUR_FEELS'))}" if v.get("CUR_FEELS") != "" else ""
        # the hourly strip's "Now" slot shows what's actually happening, not the forecast hour
        if v.get("HR1_TIME") == "Now" and v.get("CUR_TEMP") not in ("", None):
            v["HR1_TEMP"] = v["CUR_TEMP"]
            if v.get("CUR_ICON"):
                v["HR1_ICON"] = v["CUR_ICON"]
        wind = v.get("CUR_WIND")
        if wind not in ("", None):
            calm = wind == 0
            txt = "Calm" if calm else f"{wind} {speed} {v.get('CUR_WIND_DIR', '')}".rstrip()
            if v.get("CUR_GUST") not in ("", None) and v["CUR_GUST"] > wind:
                txt += f", gusts {v['CUR_GUST']}"
            v["CUR_WIND_TEXT"] = txt
        v["CUR_LINE"] = " ".join(x for x in (deg(v.get("CUR_TEMP")), v.get("CUR_SUMMARY")) if x)
        hilo = lambda hi, lo: f"{deg(hi)} / {deg(lo)}" if hi not in ("", None) else ""
        for w, hrs in WINDOWS.items():
            v[f"{w}_HILO_TEXT"] = hilo(v.get(f"{w}_TEMP_HIGH"), v.get(f"{w}_TEMP_LOW"))
            rain = v.get(f"{w}_RAIN_CHANCE") or 0
            v[f"{w}_LINE"] = " ".join(x for x in (f"Next {hrs}h", v[f"{w}_HILO_TEXT"], v.get(f"{w}_WEATHER"),
                                                  f"{rain}%" if rain >= 20 else "") if x)
        for i in range(1, 9):
            if f"HR{i}_TEMP" in v:
                v[f"HR{i}_TEMP_TEXT"] = deg(v[f"HR{i}_TEMP"])
        for i in range(5):
            if f"D{i}_HIGH" in v:
                v[f"D{i}_HILO_TEXT"] = hilo(v[f"D{i}_HIGH"], v[f"D{i}_LOW"])
                rain = v.get(f"D{i}_RAIN_CHANCE") or 0
                v[f"D{i}_LINE"] = " ".join(x for x in (v[f"D{i}_NAME"], v[f"D{i}_HILO_TEXT"], v.get(f"D{i}_WEATHER"),
                                                       f"{rain}%" if rain >= 20 else "") if x)
        if have_alerts:
            if v.get("ALERT_ACTIVE"):
                until = f" until {v['ALERT1_EXPIRES']}" if v.get("ALERT1_EXPIRES") else ""
                more = f" (+{v['ALERT_COUNT'] - 1} more)" if v.get("ALERT_COUNT", 0) > 1 else ""
                v["ALERT_TEXT"] = f"ALERT: {v['ALERT1_EVENT']}{until}{more}"
            else:
                v["ALERT_TEXT"] = "No active alerts"

    # ---------------- refresh cycle ----------------
    async def refresh(self):
        try:
            loop = asyncio.get_event_loop()
            loc_warning = await loop.run_in_executor(None, self.ensure_location)
            lat, lon, name, source, _ = self.loc
            fc, fsrc = await loop.run_in_executor(None, self.fetch_any_forecast, lat, lon)
            alerts, aerr = await loop.run_in_executor(None, self.fetch_alerts, lat, lon)
            new = self.compute(fc, alerts)
            new.update({
                "SYS_LOCATION_NAME": name, "SYS_LOCATION_SOURCE": source, "SYS_FORECAST_SOURCE": fsrc, **self.meta,
                "SYS_CONTACT_SET": 0 if self.contact_is_placeholder() else 1,
                "SYS_LAT": f"{lat:.4f}", "SYS_LON": f"{lon:.4f}",
                "SYS_LAST_UPDATE": datetime.now().strftime("%I:%M %p").lstrip("0"),
                "SYS_LAST_UPDATE_EPOCH": int(time.time()),
                **self.threshold_states(),
                "SYS_ONLINE": 1, "SYS_ERROR": "; ".join(x for x in (loc_warning, f"alerts: {aerr}" if aerr else "") if x),
            })
            self.last_ok = time.time()
            self.fail_count = 0
            await self.publish(new)
            log.info("updated: %s %s, %s", new.get("CUR_TEMP"), new.get("CUR_SUMMARY"), name)
        except Exception as e:
            self.fail_count += 1
            log.error("refresh failed: %s", e)
            stale = time.time() - self.last_ok > 3 * self.cfg["refresh_seconds"]
            await self.publish({"SYS_ERROR": str(e)[:180], "SYS_ONLINE": 0 if stale else self.values["SYS_ONLINE"]})

    def memory_mb(self):
        """Current resident memory in MB (ps works on macOS and Linux)."""
        try:
            out = subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
            return int(out.decode().strip()) // 1024
        except Exception:
            import resource
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return peak // (1024 * 1024) if sys.platform == "darwin" else peak // 1024

    async def watchdog(self):
        """Exit with code 3 if memory passes max_memory_mb; launchd/systemd restart the bridge."""
        limit = int(self.cfg.get("max_memory_mb") or 0)
        n = 0
        while True:
            mb = self.memory_mb()
            await self.publish({"SYS_MEMORY_MB": mb})
            if n % 60 == 0:
                log.info("memory: %s MB (limit %s)", mb, limit or "off")
            n += 1
            if limit and mb > limit:
                log.error("memory %s MB exceeds limit %s MB, restarting", mb, limit)
                self.request_stop("memory limit", code=3)
                return
            await asyncio.sleep(60)

    def request_stop(self, reason, code=0):
        if not self.stopping.is_set():
            self.stop_reason, self.exit_code = reason, code
            self.stopping.set()

    async def refresh_loop(self):
        while True:
            await self.refresh()
            delay = self.cfg["refresh_seconds"] if self.fail_count == 0 else min(60 * self.fail_count, self.cfg["refresh_seconds"])
            try:
                await asyncio.wait_for(self.refresh_event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
            self.refresh_event.clear()

    # ---------------- TCP / Savant ----------------
    @staticmethod
    def fmt(k, val):
        s = str(val).replace("\r", " ").replace("\n", " ")[:250]
        return f"{k}={s}\n"

    async def publish(self, new):
        changed = {k: val for k, val in new.items() if k in self.values and self.values[k] != val}
        self.values.update(changed)
        if changed and self.clients:
            payload = "".join(self.fmt(k, val) for k, val in changed.items()).encode(SAVANT_ENCODING, "replace")
            for w in list(self.clients):
                try:
                    w.write(payload)
                    await w.drain()
                except Exception:
                    self.clients.discard(w)

    async def send_all(self, w):
        w.write("".join(self.fmt(k, self.values[k]) for k in STATE_KEYS).encode(SAVANT_ENCODING, "replace"))
        await w.drain()

    async def handle_tcp(self, reader, writer):
        peer = writer.get_extra_info("peername")
        log.info("savant connected: %s", peer)
        self.clients.add(writer)
        try:
            await self.send_all(writer)
            # Commands may end in CR, LF, CRLF, or nothing at all (a 300 ms pause then ends the command),
            # so this works however the Savant profile terminates what it sends.
            buf = b""
            while True:
                try:
                    chunk = await asyncio.wait_for(reader.read(1024), timeout=0.3 if buf else None)
                except asyncio.TimeoutError:
                    chunk = b"\n"
                if not chunk:
                    break
                buf += chunk
                parts = re.split(rb"[\r\n]+", buf)
                buf = parts.pop()  # unterminated tail stays buffered
                if len(buf) > 4096:
                    buf = b""
                for part in parts:
                    cmd = part.decode(SAVANT_ENCODING, errors="replace").strip()
                    if cmd:
                        await self.command(cmd, writer)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            self.clients.discard(writer)
            try:
                writer.close()
            except Exception:
                pass
            log.info("savant disconnected: %s", peer)

    async def command(self, cmd, writer):
        verb, _, arg = cmd.partition(" ")
        verb = verb.upper()
        arg = arg.strip()
        log.info("cmd: %s", cmd)
        if verb == "PING":
            writer.write(b"PONG\n")
        elif verb == "REFRESH":
            self.refresh_event.set()
        elif verb == "DUMP":
            await self.send_all(writer)
        elif verb == "SITE":
            m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)", arg)
            if m and not (float(m.group(1)) == 0 and float(m.group(2)) == 0):
                site = f"{float(m.group(1)):.4f},{float(m.group(2)):.4f}"
                if site != self.persist.get("site"):
                    self.persist["site"] = site
                    self.save_persist()
                    self.refresh_event.set()
            else:
                log.info("SITE ignored (blank/invalid): %r", arg)
        elif verb == "OVERRIDE":
            val = "" if arg.upper() in ("", "CLEAR", "NONE", "AUTO") else arg
            if val != self.persist.get("override"):
                self.persist["override"] = val
                self.save_persist()
                self.refresh_event.set()
        elif verb == "CONTACT":
            # CONTACT <email>  (blank/CLEAR = use contact_email from config.json)
            val = "" if arg.upper() in ("", "CLEAR", "NONE") else arg.strip()
            if val and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", val):
                log.warning("CONTACT ignored: %r is not an email address", val)
                return
            if val != self.persist.get("contact", ""):
                self.persist["contact"] = val
                self.save_persist()
                log.info("contact email for data providers: %s", self.contact_email or "(none)")
                if self.contact_is_placeholder():
                    log.warning("contact email is still a placeholder; NWS and EPA ask for real contact info")
        elif verb == "APIKEY":
            # APIKEY <key>  (blank/CLEAR = no key from Savant; config.json key, if any, still applies)
            key = "" if arg.upper() in ("", "CLEAR", "NONE") else arg
            if key != self.persist.get("apikey", ""):
                self.persist["apikey"] = key
                self.save_persist()
                shown = "private (free Open-Meteo, personal use)" if key.lower() == "private" else (f"set (...{key[-4:]})" if key else "cleared")
                log.info("Open-Meteo API key %s from Savant; forecast source now %s", shown, self.primary_source())
                self.refresh_event.set()
        elif verb == "SET":
            # SET <threshold> <number>   (blank number = back to the config.json value)
            key, _, raw = arg.partition(" ")
            key, raw = key.strip().lower(), raw.strip()
            if key not in THRESHOLD_KEYS:
                log.warning("SET ignored: unknown threshold %r", key)
                return
            ov = self.persist.setdefault("thresholds", {})
            if raw.upper() in ("", "CLEAR", "DEFAULT"):
                changed = ov.pop(key, None) is not None
            else:
                try:
                    num = float(raw)
                except ValueError:
                    log.warning("SET %s ignored: %r is not a number", key, raw)
                    return
                changed = ov.get(key) != num
                ov[key] = num
            if changed:
                log.info("threshold %s = %s", key, ov.get(key, f"{self.cfg['thresholds'].get(key)} (config.json)"))
                self.save_persist()
                await self.publish(self.threshold_states())
                self.refresh_event.set()  # recompute the ACT_ flags with the new value
        else:
            writer.write(f"SYS_ERROR=unknown command {verb}\n".encode(SAVANT_ENCODING, "replace"))
        await writer.drain()

    # ---------------- HTTP dashboard ----------------
    async def handle_http(self, reader, writer):
        try:
            req = await asyncio.wait_for(reader.readline(), 10)
            while (await reader.readline()) not in (b"\r\n", b"\n", b""):
                pass
            path = req.decode(errors="ignore").split(" ")[1] if req else "/"
            if path.startswith("/api/state"):
                body = json.dumps(self.values).encode()
                ctype = "application/json"
            elif path == "/" or path.startswith("/?") or path.startswith("/index"):
                body = (Path(__file__).parent / "dashboard.html").read_bytes()
                ctype = "text/html; charset=utf-8"
            else:
                writer.write(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                return
            writer.write(f"HTTP/1.1 200 OK\r\nContent-Type: {ctype}\r\nContent-Length: {len(body)}\r\n"
                         f"Cache-Control: no-store\r\nConnection: close\r\n\r\n".encode() + body)
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    async def run(self):
        """Serve until SIGTERM/SIGINT/SIGHUP or the memory watchdog trips; returns the exit code."""
        loop = asyncio.get_event_loop()
        self.stopping = asyncio.Event()
        self.stop_reason, self.exit_code = "", 0
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            try:
                loop.add_signal_handler(sig, self.request_stop, "signal " + sig.name)
            except (NotImplementedError, RuntimeError, ValueError):
                pass
        tcp = await asyncio.start_server(self.handle_tcp, "0.0.0.0", self.cfg["tcp_port"])
        http = await asyncio.start_server(self.handle_http, "0.0.0.0", self.cfg["http_port"])
        log.info("Savant TCP on :%s, dashboard on :%s, pid %s", self.cfg["tcp_port"], self.cfg["http_port"], os.getpid())
        tasks = [asyncio.ensure_future(self.refresh_loop()), asyncio.ensure_future(self.watchdog())]
        await self.stopping.wait()

        log.info("shutting down (%s)", self.stop_reason)
        for t in tasks:
            t.cancel()
        tcp.close()
        http.close()
        for w in list(self.clients):
            try:
                w.close()
            except Exception:
                pass
        await asyncio.gather(*tasks, return_exceptions=True)
        for srv in (tcp, http):
            try:
                await asyncio.wait_for(srv.wait_closed(), 3)
            except Exception:
                pass
        self.save_persist()
        log.info("stopped, exit code %s", self.exit_code)
        return self.exit_code


def load_config(path):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    p = Path(path)
    if p.exists():
        user = json.loads(p.read_text())
        th = user.pop("thresholds", {})
        cfg.update(user)
        cfg["thresholds"].update(th)
    cfg["refresh_seconds"] = max(60, int(cfg["refresh_seconds"]))
    return cfg


def main():
    ap = argparse.ArgumentParser(description="Savant OpenWx weather bridge")
    ap.add_argument("-c", "--config", default=str(Path(__file__).parent / "config.json"))
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-l", "--logfile", help="log to a rotating file (1 MB x 3) instead of the console")
    ap.add_argument("--probe", metavar="LOCATION",
                    help="fetch once for a zip / lat,lon / 'City, ST', print the key values and exit (doesn't touch the running service)")
    ap.add_argument("--source", choices=["auto", "nws", "openmeteo"], help="with --probe: force a forecast source")
    a = ap.parse_args()
    handlers = [logging.handlers.RotatingFileHandler(a.logfile, maxBytes=1000000, backupCount=3, encoding="utf-8")] \
        if a.logfile else [logging.StreamHandler()]
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    cfg = load_config(a.config)
    global USE_CURL
    USE_CURL = cfg.get("fetcher", "auto") != "python"
    if cfg.get("fetcher") == "curl" and not CURL:
        raise SystemExit("fetcher=curl but curl was not found")
    if re.search(r"@(example\.com|yourcompany\.com)$", str(cfg.get("contact_email", ""))) or not cfg.get("contact_email"):
        log.info("contact_email in config.json is a placeholder; set Contact Email in Blueprint or edit config.json "
                 "(NWS and EPA ask for real contact info)")
    log.info("Savant OpenWx bridge %s, Python %s, fetching via %s", VERSION, sys.version.split()[0],
             "curl" if USE_CURL and CURL else "python urllib")
    if a.probe:
        import tempfile
        if a.source:
            cfg["forecast_source"] = a.source
        b = Bridge(cfg, tempfile.mkdtemp())          # temp state: never touches the service's saved settings
        saved = Bridge(cfg, Path(a.config).parent).persist
        b.persist["apikey"] = saved.get("apikey", "")    # but use the service's key
        b.persist["contact"] = saved.get("contact", "")  # and its contact email
        b.persist["override"] = a.probe
        asyncio.get_event_loop().run_until_complete(b.refresh())
        v = b.values
        for k in ("SYS_FORECAST_SOURCE", "SYS_LOCATION_NAME", "SYS_ONLINE", "SYS_ERROR", "SYS_CURRENT_SOURCE",
                  "SYS_STATION_NAME", "SYS_STATION_DISTANCE", "SYS_STATION_OBS_TIME", "SYS_UV_SOURCE", "SYS_SUN_SOURCE",
                  "SUN_DAWN", "SUN_DUSK", "D1_UV_MAX", "CUR_LINE", "CUR_FEELS_TEXT",
                  "CUR_WIND_TEXT", "CUR_HUMIDITY", "CUR_UV", "CUR_UV_LEVEL", "H12_LINE", "H12_GUST_MAX", "H12_GUST_MAX_TIME",
                  "H24_LINE", "D0_LINE", "D0_UV_MAX", "D1_LINE", "D2_LINE", "SUN_RISE", "SUN_SET", "ALERT_TEXT"):
            print(f"{k:20} {v.get(k)}")
        sys.exit(0 if v.get("SYS_ONLINE") == 1 else 1)
    loop = asyncio.get_event_loop()
    try:
        code = loop.run_until_complete(Bridge(cfg, Path(a.config).parent).run())
    except OSError as e:
        log.error("could not start: %s (is the port already in use?)", e)
        code = 2
    sys.exit(code)


if __name__ == "__main__":
    main()
