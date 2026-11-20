#!/usr/bin/env python3
"""Smoke-test every add-on and integration. Read-only: it never changes what's on the display.

  run_tests.py [--claude] [--json]     exit 0 if every check passed
Config: ~/.csa-tests/config.json {"ha": "192.168.4.54"}; ports are the host ports the add-ons publish.
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import time
import urllib.request

HOME = os.path.expanduser("~")
CFG = {"ha": "192.168.4.54", "helper": "http://localhost:8200"}
try:
    with open(os.path.join(HOME, ".csa-tests", "config.json")) as f:
        CFG.update(json.load(f))
except OSError:
    pass
PORTS = {"display": 8099, "radar": 8101, "csa": 8102, "recipes": 8103}


def url(svc: str, path: str) -> str:
    return f"http://{CFG['ha']}:{PORTS[svc]}{path}"


def get(u: str, timeout: int = 60) -> tuple[int, bytes]:
    with urllib.request.urlopen(u, timeout=timeout) as r:
        return r.status, r.read()


def get_json(u: str):
    return json.loads(get(u)[1])


def png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return struct.unpack(">II", data[16:24])


# Each check raises AssertionError (or any exception) on failure and returns a short detail string on success.
def display_health():
    h = get_json(url("display", "/health"))
    assert h["configured"], "display add-on hasn't connected to Home Assistant"
    assert h["calendar_events"] is not None, "no calendar data loaded"
    assert h["weather"] and h["weather"]["hours"] and h["weather"]["days"], f"weather data missing: {h['weather']}"
    assert h["lists"] and all(v is not None for v in h["lists"].values()), f"to-do lists missing: {h['lists']}"
    return f"HA {h['core_version']}, {h['calendar_events']} events, {len(h['lists'])} lists"


def display_pages():
    sizes = []
    for page in ("calendar", "weather", "lists"):
        sizes.append(png_size(get(url("display", f"/preview/{page}.png"))[1]))
    assert len(set(sizes)) == 1 and sizes[0] in ((960, 640), (800, 480)), f"unexpected page sizes {sizes}"
    return f"3 pages at {sizes[0][0]}x{sizes[0][1]}"


def display_render():
    n = len(get(url("display", "/render"))[1])
    assert n in (0, 76800, 48000), f"/render returned {n} bytes"
    return f"{n} bytes"


def radar_weather():
    d = get_json(url("radar", "/weather.json"))
    wx = d["weather"]
    assert wx and wx["state"], "no weather in the radar add-on"
    assert wx["hourly"] and wx["daily"], f"forecast missing (hourly {len(wx['hourly'])}, daily {len(wx['daily'])})"
    return f"{wx['entity']}: {wx['state']}"


def radar_gif():
    data = get(url("radar", "/radar.gif"))[1]
    assert data[:4] == b"GIF8" and len(data) > 100_000, f"radar.gif is {len(data)} bytes"
    return f"{len(data) // 1024} KB"


def csa_health():
    h = get_json(url("csa", "/health"))
    assert all(h.values()), f"CSA Recipes: {h}"
    return "helper, recipes and to-do list reachable"


def recipes_health():
    h = get_json(url("recipes", "/health"))
    assert all(h.values()), f"Recipes: {h}"
    assert "recipe" in get_json(url("recipes", "/pinned.json"))
    return "helper and display reachable"


def helper_health():
    assert json.loads(get(CFG["helper"] + "/health")[1]).get("ok"), "helper not ok"
    return "up"


def claude_smoke():
    claude = os.path.join(HOME, ".local", "bin", "claude")
    out = subprocess.run([claude, "-p", "Reply with exactly: ok"], capture_output=True, text=True, timeout=120).stdout.strip()
    assert out == "ok", f"claude replied {out!r}"
    return "ok"


CHECKS = [("display: data loaded", display_health), ("display: pages render", display_pages),
          ("display: /render", display_render), ("weather: forecast", radar_weather), ("weather: radar gif", radar_gif),
          ("csa: integrations", csa_health), ("recipes: integrations", recipes_health), ("helper: up", helper_health)]


def run(with_claude: bool = False, retries: int = 3, wait: int = 20) -> list[dict]:
    checks = CHECKS + ([("helper: claude works", claude_smoke)] if with_claude else [])
    results = []
    for name, fn in checks:
        detail, ok = "", False
        for attempt in range(retries):            # add-ons may still be restarting after an update
            try:
                detail, ok = fn(), True
                break
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                if attempt < retries - 1:
                    time.sleep(wait)
        results.append({"check": name, "ok": ok, "detail": detail})
    return results


if __name__ == "__main__":
    res = run(with_claude="--claude" in sys.argv)
    if "--json" in sys.argv:
        print(json.dumps(res, indent=1))
    else:
        for r in res:
            print(("PASS " if r["ok"] else "FAIL ") + r["check"] + " - " + r["detail"])
    sys.exit(0 if all(r["ok"] for r in res) else 1)
