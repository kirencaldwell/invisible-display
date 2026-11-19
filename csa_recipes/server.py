#!/usr/bin/env python3
"""CSA Recipes: photo of a CSA delivery letter -> ingredient list -> recipe ideas -> one pinned for the e-ink display.

Reading the letter and writing recipes is done by Claude Code on the mini PC, through the CSA helper service
(csa_helper/). State lives in /data/state.json.

  GET  /              web UI (works behind Home Assistant ingress: all links are relative)
  GET  /api/state     {items, recipes, pinned}
  POST /api/letter    image bytes -> reads the letter, replaces items
  POST /api/items     {items: [...]} user-corrected ingredient list
  POST /api/recipes   generates recipe ideas from the current items
  POST /api/pin       {index: N} pin recipe N (or {index: null} to unpin)
  GET  /pinned.json   {recipe: {...} | null}, polled by the display add-on
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image, ImageOps

log = logging.getLogger("csa")
DEFAULTS = {"display_url": "", "helper_url": "", "helper_token": "", "recipe_count": 4, "dietary_notes": ""}

def load_options(path: str | None) -> dict:
    opts = dict(DEFAULTS)
    if path and os.path.exists(path):
        with open(path) as f:
            opts.update({k: v for k, v in json.load(f).items() if v is not None})
    return opts


class UserError(Exception):
    pass


def helper(opts: dict, path: str, body: bytes, ctype: str):
    """Call the CSA helper on the mini PC, which runs Claude Code with the fixed prompts."""
    if not opts["helper_url"] or not opts["helper_token"]:
        raise UserError("Set helper_url and helper_token in the add-on options (Settings → Add-ons → CSA Recipes → Configuration).")
    req = urllib.request.Request(opts["helper_url"].rstrip("/") + path, data=body, headers={
        "Authorization": f"Bearer {opts['helper_token']}", "Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        log.warning("helper error %s: %s", exc.code, detail)
        try:
            msg = json.loads(detail).get("error", "")
        except ValueError:
            msg = ""
        raise UserError(f"The mini PC helper failed ({exc.code}): {msg or 'check the helper token'}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise UserError("Couldn't reach the helper on the mini PC. Is it on, and is helper_url right?") from exc


def prepare_image(data: bytes) -> bytes:
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except OSError as exc:
        raise UserError("That file doesn't look like a photo.") from exc
    img.thumbnail((1800, 1800))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def read_letter(opts: dict, data: bytes) -> list[dict]:
    items = helper(opts, "/letter", prepare_image(data), "image/jpeg")["items"]
    return [{"name": str(i["name"]).strip(), "quantity": str(i.get("quantity", "")).strip()}
            for i in items if isinstance(i, dict) and str(i.get("name", "")).strip()]


def suggest_recipes(opts: dict, items: list[dict]) -> list[dict]:
    body = json.dumps({"items": items, "count": opts["recipe_count"], "notes": opts["dietary_notes"]}).encode()
    raw = helper(opts, "/recipes", body, "application/json")["recipes"]
    out = []
    for r in raw:
        try:
            out.append({
                "title": str(r["title"]).strip(), "servings": r.get("servings"), "minutes": r.get("minutes"),
                "ingredients": [{"item": str(i["item"]).strip(), "from_box": bool(i.get("from_box"))} for i in r["ingredients"]],
                "steps": [str(s).strip() for s in r["steps"]]})
        except (KeyError, TypeError):
            continue
    if not out:
        raise UserError("No usable recipes came back, please try again.")
    return out


def poke_display(opts: dict) -> None:
    """Tell the display add-on to re-read the pinned recipe now instead of at its next poll."""
    if not opts["display_url"]:
        return
    try:
        urllib.request.urlopen(opts["display_url"].rstrip("/") + "/refresh-recipe", timeout=5).read()
    except Exception as exc:
        log.warning("Couldn't notify the display (it will pick the change up within a minute): %s", exc)


class State:
    def __init__(self, path: str):
        self.path, self.lock = path, threading.Lock()
        self.data = {"items": [], "recipes": [], "pinned": None}
        if os.path.exists(path):
            try:
                with open(path) as f:
                    self.data.update(json.load(f))
            except (OSError, ValueError):
                log.warning("Ignoring unreadable %s", path)

    def save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f)
        os.replace(tmp, self.path)

    def update(self, **kw) -> dict:
        with self.lock:
            self.data.update(kw)
            self.save()
            return dict(self.data)

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.data)


PAGE = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")).read()


class Handler(BaseHTTPRequestHandler):
    state: State
    opts: dict

    def log_message(self, fmt, *args):
        log.info("request from %s: %s", self.client_address[0], fmt % args)

    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj).encode())

    def _body(self) -> bytes:
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self._send(200, PAGE.encode(), "text/html")
        if path == "/api/state":
            return self._json(self.state.snapshot())
        if path == "/pinned.json":
            s = self.state.snapshot()
            r = s["recipes"][s["pinned"]] if s["pinned"] is not None and s["pinned"] < len(s["recipes"]) else None
            return self._json({"recipe": r})
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            body = self._body()
            if path == "/api/letter":
                items = read_letter(self.opts, body)
                return self._json(self.state.update(items=items, recipes=[], pinned=None))
            if path == "/api/items":
                items = [{"name": str(i["name"]).strip(), "quantity": str(i.get("quantity", "")).strip()}
                         for i in json.loads(body)["items"] if str(i.get("name", "")).strip()]
                return self._json(self.state.update(items=items))
            if path == "/api/recipes":
                items = self.state.snapshot()["items"]
                if not items:
                    raise UserError("Add some ingredients first.")
                return self._json(self.state.update(recipes=suggest_recipes(self.opts, items), pinned=None))
            if path == "/api/pin":
                idx = json.loads(body).get("index")
                s = self.state.snapshot()
                if idx is not None and not (isinstance(idx, int) and 0 <= idx < len(s["recipes"])):
                    raise UserError("No such recipe.")
                result = self.state.update(pinned=idx)
                poke_display(self.opts)
                return self._json(result)
        except UserError as exc:
            return self._json({"error": str(exc)}, 400)
        except Exception as exc:
            log.exception("request failed")
            return self._json({"error": f"Something went wrong: {exc}"}, 500)
        self._send(404, b"not found", "text/plain")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--options", default="/data/options.json" if os.path.exists("/data/options.json") else "options.json")
    ap.add_argument("--data", default="/data" if os.path.isdir("/data") else ".data")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    os.makedirs(args.data, exist_ok=True)
    Handler.opts = load_options(args.options)
    Handler.state = State(os.path.join(args.data, "state.json"))
    log.info("Serving on port %d (helper token %s)", args.port, "set" if Handler.opts["helper_token"] else "NOT set")
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
