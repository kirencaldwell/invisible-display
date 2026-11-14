#!/usr/bin/env python3
"""Animated weather radar server for Home Assistant.

Fetches the last ~50 minutes of NEXRAD composite radar (Iowa Environmental Mesonet tiles, US only) over an
OpenStreetMap basemap and serves it as an animated GIF.

  GET /            -> small viewer page (relative links, so it works behind Home Assistant ingress)
  GET /radar.gif   -> animation
  GET /frame/N.png -> single colour frame, 0 = oldest
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import logging
import math
import os
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger("radar")
UA = {"User-Agent": "ha-weather-radar-addon (github.com/kirencaldwell/invisible-display)"}
IEM = "https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/nexrad-n0q-900913{suffix}/{z}/{x}/{y}.png"
OSM = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
AGES = list(range(50, -1, -5))            # minutes ago, oldest first; IEM offers m05m..m50m plus the current frame

DEFAULTS = {"weather_entity": "weather.forecast_home", "weather_fallback_entity": "", "latitude": 0, "longitude": 0, "zoom": 8, "width": 800, "height": 480, "frame_ms": 500,
            "refresh_minutes": 5}


def load_options(path: str | None) -> dict:
    opts = dict(DEFAULTS)
    if path and os.path.exists(path):
        with open(path) as f:
            opts.update({k: v for k, v in json.load(f).items() if v is not None})
    return opts


def home_location(opts: dict) -> tuple[float, float]:
    if opts["latitude"] or opts["longitude"]:
        return float(opts["latitude"]), float(opts["longitude"])
    if HA_TOKEN:
        cfg = ha_request("/api/config")
        return cfg["latitude"], cfg["longitude"]
    raise SystemExit("Set latitude and longitude in the options.")


# --------------------------------------------------------------------------
# Home Assistant weather
# --------------------------------------------------------------------------
HA_URL = "http://supervisor/core" if os.environ.get("SUPERVISOR_TOKEN") else os.environ.get("HA_URL", "").rstrip("/")
HA_TOKEN = os.environ.get("SUPERVISOR_TOKEN") or os.environ.get("HA_TOKEN", "")


def ha_request(path: str, body=None):
    req = urllib.request.Request(
        HA_URL + path, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def ha_forecast(entity_id: str, kind: str) -> list[dict]:
    resp = ha_request("/api/services/weather/get_forecasts?return_response", {"entity_id": entity_id, "type": kind})
    return resp["service_response"][entity_id]["forecast"]


def fold_twice_daily(raw: list[dict]) -> list[dict]:
    """Day/night periods -> one entry per date (high from the day period, low from the night)."""
    days: dict[str, dict] = {}
    for p in raw:
        d = days.setdefault(p["datetime"][:10], {"datetime": p["datetime"], "temperature": None, "templow": None,
                                                 "condition": None, "precipitation_probability": None})
        if p.get("is_daytime", True):
            d.update(temperature=p.get("temperature"), condition=p.get("condition"),
                     precipitation_probability=p.get("precipitation_probability"))
        else:
            d["templow"] = p.get("temperature")
            d["condition"] = d["condition"] or p.get("condition")
            if d["precipitation_probability"] is None:
                d["precipitation_probability"] = p.get("precipitation_probability")
    return list(days.values())


def fetch_weather(opts: dict) -> dict:
    for eid in (opts["weather_entity"], opts["weather_fallback_entity"]):
        if not eid:
            continue
        try:
            state = ha_request(f"/api/states/{eid}")
            if state["state"] in ("unavailable", "unknown"):
                log.warning("Weather %s is %s", eid, state["state"])
                continue
            out = {"entity": eid, "state": state["state"], "attributes": state["attributes"], "hourly": [], "daily": []}
            try:
                out["hourly"] = ha_forecast(eid, "hourly")
            except Exception as exc:
                log.warning("Hourly forecast unavailable for %s: %s", eid, exc)
            try:
                out["daily"] = ha_forecast(eid, "daily")
            except Exception:
                try:
                    out["daily"] = fold_twice_daily(ha_forecast(eid, "twice_daily"))
                except Exception as exc:
                    log.warning("Daily forecast unavailable for %s: %s", eid, exc)
            return out
        except Exception as exc:
            log.warning("Weather %s failed: %s", eid, exc)
    raise RuntimeError("no weather entity available")


# --------------------------------------------------------------------------
# Tiles
# --------------------------------------------------------------------------
def fetch(url: str) -> Image.Image:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        return Image.open(io.BytesIO(r.read())).convert("RGBA")


def world(lat: float, lon: float, z: int) -> tuple[float, float]:
    n = 256 * 2 ** z
    return (lon + 180) / 360 * n, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n


def mosaic(url: str, z: int, cx: float, cy: float, w: int, h: int, **fmt) -> Image.Image:
    x0, y0 = int((cx - w / 2) // 256), int((cy - h / 2) // 256)
    x1, y1 = int((cx + w / 2) // 256), int((cy + h / 2) // 256)
    big = Image.new("RGBA", ((x1 - x0 + 1) * 256, (y1 - y0 + 1) * 256))
    for tx in range(x0, x1 + 1):
        for ty in range(y0, y1 + 1):
            big.paste(fetch(url.format(z=z, x=tx, y=ty, **fmt)), ((tx - x0) * 256, (ty - y0) * 256))
    ox, oy = int(cx - w / 2 - x0 * 256), int(cy - h / 2 - y0 * 256)
    return big.crop((ox, oy, ox + w, oy + h))


def basemap(opts: dict, lat: float, lon: float, cache_dir: str) -> Image.Image:
    """OSM basemap, fetched once per location/size and cached on disk (OSM asks clients not to refetch)."""
    w, h, z = opts["width"], opts["height"], opts["zoom"]
    path = os.path.join(cache_dir, f"basemap_{z}_{lat:.3f}_{lon:.3f}_{w}x{h}.png")
    if os.path.exists(path):
        return Image.open(path).convert("RGBA")
    cx, cy = world(lat, lon, z)
    img = mosaic(OSM, z, cx, cy, w, h)
    os.makedirs(cache_dir, exist_ok=True)
    img.save(path)
    return img


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------
def _font(px: int, bold=False):
    for p in ("/usr/share/fonts/dejavu/DejaVuSans%s.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf",
              "/System/Library/Fonts/Supplemental/Arial%s.ttf"):
        try:
            return ImageFont.truetype(p % ("-Bold" if bold else "") if "Arial" not in p else p % (" Bold" if bold else ""), px)
        except OSError:
            continue
    return ImageFont.load_default(px)


def stamp(img: Image.Image, text: str) -> None:
    d = ImageDraw.Draw(img)
    f = _font(16, True)
    tw = d.textlength(text, font=f)
    d.rectangle((6, 6, 18 + tw, 32), fill=(255, 255, 255), outline=(60, 60, 60))
    d.text((12, 8), text, font=f, fill=(30, 30, 30))


def marker(img: Image.Image) -> None:
    d = ImageDraw.Draw(img)
    x, y = img.width // 2, img.height // 2
    d.ellipse((x - 7, y - 7, x + 7, y + 7), fill=(255, 255, 255), outline=0, width=2)
    d.ellipse((x - 3, y - 3, x + 3, y + 3), fill=0)


def label(age: int, when: dt.datetime) -> str:
    return f"{when:%-I:%M %p}" + ("  now" if age == 0 else f"  -{age} min")


def color_frame(base: Image.Image, rad: Image.Image, text: str) -> Image.Image:
    gray = base.convert("L").point(lambda v: 110 + v * 145 // 255).convert("RGBA")     # fade the map
    out = Image.alpha_composite(gray, rad.point(lambda v: v))
    out = out.convert("RGB")
    marker(out)
    stamp(out, text)
    return out


def gif(frames: list[Image.Image], frame_ms: int) -> bytes:
    buf = io.BytesIO()
    durations = [frame_ms] * (len(frames) - 1) + [frame_ms * 4]        # linger on the latest frame
    frames = [f.quantize(colors=128, dither=Image.Dither.NONE) for f in frames]
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=durations, loop=0, optimize=False)
    return buf.getvalue()


class Radar:
    def __init__(self, opts: dict, lat: float, lon: float, cache_dir: str):
        self.opts, self.lat, self.lon, self.cache_dir = opts, lat, lon, cache_dir
        self.lock = threading.Lock()
        self.color_gif = b""
        self.frames: list[bytes] = []
        self.updated: dt.datetime | None = None
        self.weather: dict | None = None

    def refresh(self) -> None:
        o = self.opts
        w, h, z = o["width"], o["height"], o["zoom"]
        try:
            wx = fetch_weather(o)
            with self.lock:
                self.weather, self.updated = wx, dt.datetime.now().astimezone()
        except Exception as exc:
            log.warning("weather refresh failed (keeping previous): %s", exc)
        base = basemap(o, self.lat, self.lon, self.cache_dir)
        cx, cy = world(self.lat, self.lon, z)
        now = dt.datetime.now().astimezone()
        color, pngs = [], []
        for age in AGES:
            suffix = f"-m{age:02d}m" if age else ""
            try:
                rad = mosaic(IEM, z, cx, cy, w, h, suffix=suffix)
            except Exception as exc:
                log.warning("radar frame -%d min failed: %s", age, exc)
                continue
            text = label(age, now - dt.timedelta(minutes=age))
            cf = color_frame(base, rad, text)
            color.append(cf)
            b = io.BytesIO()
            cf.save(b, "PNG")
            pngs.append(b.getvalue())
        if not color:
            raise RuntimeError("no radar frames could be fetched")
        cg = gif(color, o["frame_ms"])
        with self.lock:
            self.color_gif, self.frames = cg, pngs
        log.info("updated %d frames (%d KB)", len(color), len(cg) // 1024)

    def run(self) -> None:
        every = self.opts["refresh_minutes"] * 60
        while True:
            try:
                self.refresh()
                time.sleep(every)
            except Exception as exc:
                log.warning("refresh failed, retrying in 60 s: %s", exc)
                time.sleep(60)


PAGE = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")).read()


class Handler(BaseHTTPRequestHandler):
    radar: Radar

    def log_message(self, fmt, *args):
        log.info("request from %s: %s", self.client_address[0], fmt % args)

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        r = self.radar
        path = self.path.split("?")[0]
        with r.lock:
            ready = bool(r.color_gif)
            cg, frames, updated, wx = r.color_gif, r.frames, r.updated, r.weather
        if path in ("/", "/index.html"):
            return self._send(200, PAGE.encode(), "text/html")
        if path == "/weather.json":
            body = json.dumps({"weather": wx, "updated": updated.isoformat() if updated else None})
            return self._send(200, body.encode(), "application/json")
        if not ready:
            return self._send(503, b"loading", "text/plain")
        if path == "/radar.gif":
            return self._send(200, cg, "image/gif")
        if path.startswith("/frame/") and path.endswith(".png"):
            try:
                return self._send(200, frames[int(path[7:-4])], "image/png")
            except (ValueError, IndexError):
                pass
        self._send(404, b"not found", "text/plain")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--options", default="/data/options.json" if os.path.exists("/data/options.json") else "options.json")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--cache", default="/data" if os.path.isdir("/data") else ".cache")
    ap.add_argument("--out", metavar="DIR", help="write radar.gif to DIR and exit")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    opts = load_options(args.options)
    lat, lon = home_location(opts)
    log.info("Radar centred on %.4f, %.4f (zoom %d)", lat, lon, opts["zoom"])
    radar = Radar(opts, lat, lon, args.cache)

    if args.out:
        radar.refresh()
        os.makedirs(args.out, exist_ok=True)
        for name, data in (("radar.gif", radar.color_gif),):
            with open(os.path.join(args.out, name), "wb") as f:
                f.write(data)
            print("wrote", os.path.join(args.out, name))
        return

    threading.Thread(target=radar.run, daemon=True).start()
    Handler.radar = radar
    log.info("Serving radar on port %d", args.port)
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
