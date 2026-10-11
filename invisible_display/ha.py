"""Data layer: data models, a small Home Assistant REST client, and parsers.

Calendars come from Home Assistant calendar entities (e.g. the Google Calendar
integration), weather from a Home Assistant weather entity. Nothing here talks
to Google or any weather service directly.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

log = logging.getLogger("ha")


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------
@dataclass
class Event:
    start: dt.datetime          # timezone-aware, local
    end: dt.datetime            # timezone-aware, local (exclusive for all-day)
    title: str
    all_day: bool
    tag: str                    # one-letter calendar tag
    location: str = ""


@dataclass
class Hour:
    time: dt.datetime
    temp: float
    cond: str                   # Home Assistant weather condition string
    feels: float | None = None
    pop: float | None = None    # precipitation probability, percent
    wind: float | None = None
    is_day: bool = True


@dataclass
class Day:
    date: dt.date
    cond: str
    hi: float
    lo: float | None = None
    pop: float | None = None


@dataclass
class Weather:
    current: Hour | None
    hours: list[Hour] = field(default_factory=list)
    days: list[Day] = field(default_factory=list)
    wind_unit: str = ""
    sunrise: dt.time | None = None
    sunset: dt.time | None = None


# Home Assistant weather condition -> (label, icon kind)
CONDITIONS = {
    "sunny": ("Sunny", "clear"),
    "clear-night": ("Clear", "clear"),
    "partlycloudy": ("Partly cloudy", "partly"),
    "cloudy": ("Cloudy", "cloud"),
    "fog": ("Fog", "fog"),
    "rainy": ("Rain", "rain"),
    "pouring": ("Heavy rain", "rain"),
    "snowy": ("Snow", "snow"),
    "snowy-rainy": ("Sleet", "snow"),
    "hail": ("Hail", "snow"),
    "lightning": ("Thunderstorm", "thunder"),
    "lightning-rainy": ("Thunderstorms", "thunder"),
    "windy": ("Windy", "cloud"),
    "windy-variant": ("Windy", "cloud"),
    "exceptional": ("Exceptional", "cloud"),
}


def describe(cond: str) -> tuple[str, str]:
    if cond in CONDITIONS:
        return CONDITIONS[cond]
    return (cond.replace("-", " ").capitalize() or "Unknown", "cloud")


# --------------------------------------------------------------------------
# Home Assistant client
# --------------------------------------------------------------------------
class HA:
    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.token = token

    def _req(self, path: str, body=None, timeout: int = 30):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.url + path,
            data=data,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    def config(self) -> dict:
        return self._req("/api/config")

    def state(self, entity_id: str) -> dict:
        return self._req(f"/api/states/{entity_id}")

    def calendars(self) -> list[dict]:
        return self._req("/api/calendars")

    def calendar_events(self, entity_id: str, start: dt.datetime, end: dt.datetime) -> list[dict]:
        q = urllib.parse.urlencode({"start": start.isoformat(), "end": end.isoformat()})
        return self._req(f"/api/calendars/{entity_id}?{q}")

    def forecast(self, entity_id: str, kind: str) -> list[dict]:
        resp = self._req(
            "/api/services/weather/get_forecasts?return_response",
            {"entity_id": entity_id, "type": kind},
        )
        return resp["service_response"][entity_id]["forecast"]


# --------------------------------------------------------------------------
# Calendar parsing
# --------------------------------------------------------------------------
def _when(v: dict, tz: ZoneInfo) -> tuple[dt.datetime, bool]:
    """Parse HA's {"date": ...} / {"dateTime": ...} into an aware datetime."""
    if "dateTime" not in v:
        d = dt.date.fromisoformat(v["date"])
        return dt.datetime.combine(d, dt.time(0), tz), True
    t = dt.datetime.fromisoformat(v["dateTime"])
    t = t.replace(tzinfo=tz) if t.tzinfo is None else t.astimezone(tz)
    return t, False


def parse_events(raw: list[dict], tag: str, tz: ZoneInfo) -> list[Event]:
    out = []
    for e in raw:
        try:
            start, all_day = _when(e["start"], tz)
            end, _ = _when(e["end"], tz) if e.get("end") else (start, all_day)
            if all_day and end <= start:
                end = start + dt.timedelta(days=1)
            title = (e.get("summary") or "(No title)").strip()
            out.append(Event(start, end, title, all_day, tag, (e.get("location") or "").strip()))
        except (KeyError, ValueError) as exc:
            log.warning("Skipping unparseable event %r: %s", e.get("summary"), exc)
    return out


def events_on(events: list[Event], day: dt.date) -> list[Event]:
    """Events overlapping the given local date, all-day first then by start."""
    out = []
    for e in events:
        last = (e.end - dt.timedelta(microseconds=1)).date() if e.end > e.start else e.start.date()
        if e.start.date() <= day <= last:
            out.append(e)
    out.sort(key=lambda e: (not e.all_day, e.start, e.title.lower()))
    return out


# --------------------------------------------------------------------------
# Weather parsing
# --------------------------------------------------------------------------
def _num(v):
    return float(v) if isinstance(v, (int, float)) else None


def parse_hours(raw: list[dict], tz: ZoneInfo, sunrise: dt.time | None, sunset: dt.time | None) -> list[Hour]:
    out = []
    for f in raw:
        temp = _num(f.get("temperature"))
        if temp is None or not f.get("datetime"):
            continue
        t = dt.datetime.fromisoformat(f["datetime"])
        t = t.replace(tzinfo=tz) if t.tzinfo is None else t.astimezone(tz)
        if isinstance(f.get("is_daytime"), bool):
            is_day = f["is_daytime"]
        elif sunrise and sunset:
            is_day = sunrise <= t.time() < sunset
        else:
            is_day = 7 <= t.hour < 19
        cond = f.get("condition") or "cloudy"
        if cond == "sunny" and not is_day:
            cond = "clear-night"
        out.append(Hour(t, temp, cond, _num(f.get("apparent_temperature")),
                        _num(f.get("precipitation_probability")), _num(f.get("wind_speed")), is_day))
    out.sort(key=lambda h: h.time)
    return out


def parse_days(raw: list[dict]) -> list[Day]:
    out = []
    for f in raw:
        hi = _num(f.get("temperature"))
        if hi is None or not f.get("datetime"):
            continue
        # Use the date as written; some integrations stamp days at UTC midnight.
        out.append(Day(dt.date.fromisoformat(f["datetime"][:10]), f.get("condition") or "cloudy",
                       hi, _num(f.get("templow")), _num(f.get("precipitation_probability"))))
    out.sort(key=lambda d: d.date)
    return out


def fetch_weather(ha: HA, entity_id: str, tz: ZoneInfo, now: dt.datetime) -> Weather:
    state = ha.state(entity_id)
    attrs = state.get("attributes", {})

    sunrise = sunset = None
    try:
        sun = ha.state("sun.sun")["attributes"]
        sunrise = dt.datetime.fromisoformat(sun["next_rising"]).astimezone(tz).time()
        sunset = dt.datetime.fromisoformat(sun["next_setting"]).astimezone(tz).time()
    except Exception as exc:  # sun integration is optional
        log.info("No sun.sun data: %s", exc)

    hours: list[Hour] = []
    days: list[Day] = []
    try:
        hours = parse_hours(ha.forecast(entity_id, "hourly"), tz, sunrise, sunset)
    except Exception as exc:
        log.warning("Hourly forecast unavailable for %s: %s", entity_id, exc)
    try:
        days = parse_days(ha.forecast(entity_id, "daily"))
    except Exception as exc:
        log.warning("Daily forecast unavailable for %s: %s", entity_id, exc)
    days = [d for d in days if d.date >= now.date()][:7]

    # "Current" is the hourly forecast entry for the current hour, falling back
    # to the entity's own state.
    current = None
    for h in hours:
        if h.time.date() == now.date() and h.time.hour == now.hour:
            current = h
            break
    if current is None:
        temp = _num(attrs.get("temperature"))
        if temp is not None:
            is_day = sunrise <= now.time() < sunset if sunrise and sunset else 7 <= now.hour < 19
            current = Hour(now.replace(minute=0, second=0, microsecond=0), temp,
                           state.get("state") or "cloudy", _num(attrs.get("apparent_temperature")),
                           None, _num(attrs.get("wind_speed")), is_day)

    return Weather(current, hours, days, attrs.get("wind_speed_unit", ""), sunrise, sunset)
