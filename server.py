#!/usr/bin/env python3
"""Invisible Computers local render server for Home Assistant.

Alternates a shared-calendar page and a weather page on an Invisible e-paper
display, using Home Assistant calendar and weather entities as data sources.

Protocol: https://github.com/Invisible-Computers/local-render-server
  GET /render  -> full 1-bit buffer, or an empty body if nothing changed
  GET /ack     -> device confirms the buffer reached the panel
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import io
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

import numpy as np

import demo
import ha
import render

log = logging.getLogger("server")

DISPLAYS = {"7_5_inch": (800, 480), "10_2_inch": (960, 640)}
FORCE_REFRESH_SECONDS = 20 * 3600      # the display wants a full refresh at least daily

DEFAULTS = {
    "calendars": [],                    # [] = use every calendar entity in Home Assistant
    "weather_entity": "weather.forecast_home",
    "display_model": "7_5_inch",
    "page_minutes": 10,
    "clock_24h": False,
    "week_starts_monday": False,
    "agenda_days": 7,
    "calendar_refresh_minutes": 15,
    "weather_refresh_minutes": 30,
    "ha_url": "",
    "ha_token": "",
}


def load_options(path: str | None) -> dict:
    opts = dict(DEFAULTS)
    if path and os.path.exists(path):
        with open(path) as f:
            opts.update({k: v for k, v in json.load(f).items() if v is not None})
    return opts


def pack(img, display: str) -> bytes:
    """1-bit image -> raw e-paper buffer (see the protocol README)."""
    px = np.array(img.convert("L")) > 127            # True = white
    if display == "10_2_inch":
        px = px[::-1]                                # flip top-to-bottom
    return np.packbits(px.reshape(-1)[::-1]).tobytes()


def assign_tags(defs: list[dict]) -> None:
    """Give every calendar a unique one-character tag."""
    used: set[str] = set()
    for d in defs:
        want = (d.get("tag") or "").strip()[:1].upper()
        if want and want not in used:
            d["tag"] = want
        else:
            d["tag"] = ""
        used.add(d["tag"]) if d["tag"] else None
    for d in defs:
        if d["tag"]:
            continue
        name = d.get("name") or d["entity_id"].split(".", 1)[-1]
        pool = [ch.upper() for ch in name if ch.isalnum()] + list("ABCDEFGHJKLMNPQRSTUVWXYZ123456789")
        d["tag"] = next(ch for ch in pool if ch not in used)
        used.add(d["tag"])


class Data:
    """Holds the latest calendar/weather data and refreshes it in the background."""

    def __init__(self, opts: dict, client: ha.HA | None, demo_mode: bool):
        self.opts, self.ha, self.demo = opts, client, demo_mode
        self.tz = ZoneInfo(os.environ.get("TZ") or "UTC")
        self.location = ""
        self.cal_defs: list[dict] = []
        self.cal_events: dict[str, list[ha.Event]] = {}
        self.weather: ha.Weather | None = None
        self.configured = False
        self.lock = threading.Lock()

    # -- setup -----------------------------------------------------------
    def configure(self) -> None:
        if self.demo:
            self.tz = ZoneInfo(os.environ.get("TZ") or "America/Los_Angeles")
            self.cal_defs = [{"entity_id": f"demo.{n.lower()}", "tag": t, "name": n} for t, n in demo.LEGEND]
            self.location = "Home"
            self.configured = True
            return
        cfg = self.ha.config()
        self.tz = ZoneInfo(cfg.get("time_zone") or "UTC")
        self.location = cfg.get("location_name", "")
        defs = [dict(c) for c in self.opts["calendars"]]
        try:
            found = {c["entity_id"]: c.get("name") for c in self.ha.calendars()}
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            found = {}          # HA has no calendar integration loaded yet
        log.info("Calendar entities in Home Assistant: %s", ", ".join(found) or "(none)")
        if not defs:
            defs = [{"entity_id": eid, "name": name} for eid, name in found.items()]
        for d in defs:
            d.setdefault("name", found.get(d["entity_id"]) or d["entity_id"])
            d["name"] = d.get("name") or found.get(d["entity_id"]) or d["entity_id"]
        assign_tags(defs)
        self.cal_defs = defs
        self.configured = True
        log.info("Using calendars: %s", ", ".join(f"{d['tag']}={d['entity_id']}" for d in defs))

    # -- refresh ---------------------------------------------------------
    def refresh_calendars(self) -> None:
        if self.demo:
            now = dt.datetime.now(self.tz)
            with self.lock:
                self.cal_events = {"demo": demo.events(now)}
            return
        now = dt.datetime.now(self.tz)
        start = dt.datetime.combine(now.date(), dt.time(0), self.tz)
        end = start + dt.timedelta(days=45)
        for d in self.cal_defs:
            try:
                raw = self.ha.calendar_events(d["entity_id"], start, end)
                evs = ha.parse_events(raw, d["tag"], self.tz)
                with self.lock:
                    self.cal_events[d["entity_id"]] = evs
            except Exception as exc:
                log.warning("Calendar %s failed (keeping previous data): %s", d["entity_id"], exc)

    def refresh_weather(self) -> None:
        now = dt.datetime.now(self.tz)
        if self.demo:
            with self.lock:
                self.weather = demo.weather(now)
            return
        try:
            wx = ha.fetch_weather(self.ha, self.opts["weather_entity"], self.tz, now)
            with self.lock:
                self.weather = wx
        except Exception as exc:
            log.warning("Weather %s failed (keeping previous data): %s", self.opts["weather_entity"], exc)

    def events(self) -> list[ha.Event] | None:
        with self.lock:
            if not self.cal_events:
                return None
            return [e for evs in self.cal_events.values() for e in evs]

    def legend(self) -> list[tuple[str, str]]:
        return [(d["tag"], d["name"]) for d in self.cal_defs]

    def run(self) -> None:
        """Background loop; also retries configuration while HA is still starting."""
        last_cal = last_wx = 0.0
        while True:
            try:
                if not self.configured:
                    self.configure()
                now = time.time()
                cal_every = self.opts["calendar_refresh_minutes"] * 60
                wx_every = self.opts["weather_refresh_minutes"] * 60
                if now - last_cal >= cal_every:
                    self.refresh_calendars()
                    # nothing fetched yet -> retry in 30 s instead of waiting a full interval
                    last_cal = now if self.events() is not None else now - cal_every + 30
                if now - last_wx >= wx_every:
                    self.refresh_weather()
                    last_wx = now if self.weather is not None else now - wx_every + 30
            except Exception as exc:
                log.warning("Home Assistant not ready yet: %s", exc)
            time.sleep(15)


class Frames:
    """Chooses the page for the current time and renders it."""

    def __init__(self, opts: dict, data: Data):
        self.opts, self.data = opts, data
        self.W, self.H = DISPLAYS[opts["display_model"]]
        self.pages = ["calendar", "weather"]

    def page_at(self, now: dt.datetime) -> str:
        slot = int(now.timestamp() // (self.opts["page_minutes"] * 60))
        return self.pages[slot % len(self.pages)]

    def render(self, page: str, now: dt.datetime):
        o = self.opts
        if page == "calendar":
            with self.data.lock:
                wx = self.data.weather
            return render.calendar_page(self.W, self.H, now, self.data.events(), wx,
                                        clock24=o["clock_24h"], week_starts_monday=o["week_starts_monday"],
                                        agenda_days=o["agenda_days"])
        with self.data.lock:
            wx = self.data.weather
        return render.weather_page(self.W, self.H, now, wx, self.data.location, clock24=o["clock_24h"])


class Handler(BaseHTTPRequestHandler):
    frames: Frames
    state: dict
    state_lock = threading.Lock()

    def log_message(self, fmt, *args):      # one line per request, with the sender's IP
        log.info("request from %s: %s", self.client_address[0], fmt % args)

    def _send(self, code=200, body=b"", ctype="application/octet-stream", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        now = dt.datetime.now(self.frames.data.tz)

        if url.path == "/render":
            page = self.frames.page_at(now)
            buf = pack(self.frames.render(page, now), self.frames.opts["display_model"])
            digest = hashlib.sha1(buf).hexdigest()
            headers = {}
            temp = q.get("measured-temperature", [None])[0]
            if temp is not None:
                try:
                    headers["Temperature-To-Assume"] = str(round(float(temp)))
                except ValueError:
                    pass
            with self.state_lock:
                fresh = (self.state["confirmed"] == digest
                         and time.time() - self.state["confirmed_at"] < FORCE_REFRESH_SECONDS)
                if fresh:
                    log.info("render %-8s unchanged", page)
                    return self._send(200, b"", headers=headers)
                self.state["pending"] = digest
            log.info("render %-8s sending %d bytes", page, len(buf))
            return self._send(200, buf, headers=headers)

        if url.path == "/ack":
            with self.state_lock:
                if self.state["pending"]:
                    self.state.update(confirmed=self.state["pending"], confirmed_at=time.time(), pending=None)
            log.info("ack      %s", q.get("software-version", ["?"])[0])
            return self._send(200, b"ok", "text/plain")

        if url.path.startswith("/preview/") and url.path.endswith(".png"):
            page = url.path[len("/preview/"):-4]
            if page in self.frames.pages:
                buf = io.BytesIO()
                self.frames.render(page, now).convert("L").save(buf, "PNG")
                return self._send(200, buf.getvalue(), "image/png")

        if url.path == "/":
            body = ("<!doctype html><title>Invisible display</title><body style='font-family:sans-serif'>"
                    "<h2>Invisible display</h2><p>Point the display at this server's base URL.</p>"
                    + "".join(f"<h3>{html.escape(p)}</h3><img src='preview/{p}.png' style='border:1px solid #888'>"
                              for p in self.frames.pages)).encode()
            return self._send(200, body, "text/html")

        self._send(404, b"not found", "text/plain")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--options", default="/data/options.json" if os.path.exists("/data/options.json") else "options.json",
                    help="JSON options file (Home Assistant add-on options)")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--demo", action="store_true", help="use synthetic data, no Home Assistant needed")
    ap.add_argument("--preview", metavar="DIR", help="write PNGs of both pages to DIR and exit")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    opts = load_options(args.options)
    if opts["display_model"] not in DISPLAYS:
        raise SystemExit(f"display_model must be one of {sorted(DISPLAYS)}")

    client = None
    if not args.demo:
        token = os.environ.get("SUPERVISOR_TOKEN")
        if token:
            client = ha.HA("http://supervisor/core", token)
        else:
            url = opts["ha_url"] or os.environ.get("HA_URL", "")
            token = opts["ha_token"] or os.environ.get("HA_TOKEN", "")
            if not (url and token):
                raise SystemExit("Not running as an add-on: set ha_url and ha_token (a long-lived access token), "
                                 "or use --demo.")
            client = ha.HA(url, token)

    data = Data(opts, client, args.demo)
    frames = Frames(opts, data)

    if args.preview:
        os.makedirs(args.preview, exist_ok=True)
        data.configure()
        data.refresh_calendars()
        data.refresh_weather()
        now = dt.datetime.now(data.tz)
        for page in frames.pages:
            frames.render(page, now).convert("L").save(os.path.join(args.preview, f"{page}.png"))
            print("wrote", os.path.join(args.preview, f"{page}.png"))
        return

    threading.Thread(target=data.run, daemon=True).start()
    Handler.frames = frames
    Handler.state = {"pending": None, "confirmed": None, "confirmed_at": 0.0}
    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    log.info("Serving %s display on port %d (pages alternate every %d min)",
             opts["display_model"], args.port, opts["page_minutes"])
    srv.serve_forever()


if __name__ == "__main__":
    main()
