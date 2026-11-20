#!/usr/bin/env python3
"""Recipes: owns the recipe shown on the e-ink display.

Paste a messy recipe -> Claude (on the mini PC, through the CSA helper service) formats it -> pin it to the display.
Other add-ons (CSA Recipes) send their recipes here to be pinned, so there is one place that says what's on screen.
State lives in /data/state.json: {pinned: recipe | null, saved: [recipe, ...]}.

  GET  /              web UI (relative links, works behind Home Assistant ingress)
  GET  /api/state     {pinned, saved}
  POST /api/format    {text, show}   format pasted text, save it, optionally pin it
  POST /api/pin       {recipe} pin (and save) a recipe | {index} pin saved recipe N | {index: null} unpin
  POST /api/delete    {index}        remove a saved recipe (unpins it if it was showing)
  GET  /pinned.json   {recipe: {...} | null}, polled by the display add-on
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("recipes")
DEFAULTS = {"helper_url": "", "helper_token": "", "display_url": "", "csa_url": ""}
MAX_SAVED = 30


class UserError(Exception):
    pass


def load_options(path: str | None) -> dict:
    opts = dict(DEFAULTS)
    if path and os.path.exists(path):
        with open(path) as f:
            opts.update({k: v for k, v in json.load(f).items() if v is not None})
    return opts


def helper(opts: dict, path: str, body: bytes, ctype: str):
    """Call the CSA helper on the mini PC, which runs Claude Code with the fixed prompts."""
    if not opts["helper_url"] or not opts["helper_token"]:
        raise UserError("Set helper_url and helper_token in the add-on options.")
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


def clean_recipe(r: dict) -> dict | None:
    try:
        rec = {"title": str(r["title"]).strip(), "servings": r.get("servings"), "minutes": r.get("minutes"),
               "ingredients": [{"item": str(i["item"]).strip(), "from_box": bool(i.get("from_box"))} for i in r["ingredients"]],
               "steps": [str(s).strip() for s in r["steps"]]}
    except (KeyError, TypeError):
        return None
    return rec if rec["title"] and rec["ingredients"] and rec["steps"] else None


def opts_url(opts: dict, key: str) -> str:
    return (opts.get(key) or "http://invalid.invalid").rstrip("/")


def csa_items(opts: dict) -> list[dict]:
    """The current CSA box contents (best effort), so the formatter can mark which ingredients came from the box."""
    if not opts["csa_url"]:
        return []
    try:
        with urllib.request.urlopen(opts["csa_url"].rstrip("/") + "/api/state", timeout=5) as r:
            return json.load(r).get("items", [])
    except Exception:
        return []


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
        self.data = {"pinned": None, "saved": []}
        if os.path.exists(path):
            try:
                with open(path) as f:
                    self.data.update(json.load(f))
            except (OSError, ValueError):
                log.warning("Ignoring unreadable %s", path)

    def update(self, fn) -> dict:
        with self.lock:
            fn(self.data)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.data, f)
            os.replace(tmp, self.path)
            return json.loads(json.dumps(self.data))

    def snapshot(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.data))


def save_recipe(d: dict, recipe: dict) -> None:
    d["saved"] = [recipe] + [r for r in d["saved"] if r["title"] != recipe["title"]][:MAX_SAVED - 1]


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

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self._send(200, PAGE.encode(), "text/html")
        if path == "/health":
            ok = {}
            for name, url in (("helper_ok", opts_url(self.opts, "helper_url") + "/health"),
                              ("display_ok", opts_url(self.opts, "display_url") + "/health")):
                try:
                    with urllib.request.urlopen(url, timeout=5) as resp:
                        ok[name] = resp.status == 200
                except Exception:
                    ok[name] = False
            return self._json(ok)
        if path == "/api/state":
            return self._json(self.state.snapshot())
        if path == "/pinned.json":
            return self._json({"recipe": self.state.snapshot()["pinned"]})
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            if path == "/api/format":
                text = str(req.get("text", "")).strip()
                if len(text) < 20:
                    raise UserError("Paste the recipe text first.")
                out = helper(self.opts, "/format", json.dumps({"text": text, "items": csa_items(self.opts)}).encode(),
                             "application/json")
                recipe = clean_recipe(out["recipe"])
                if not recipe:
                    raise UserError("Couldn't find a recipe in that text.")

                def apply(d):
                    save_recipe(d, recipe)
                    if req.get("show"):
                        d["pinned"] = recipe
                result = self.state.update(apply)
                if req.get("show"):
                    poke_display(self.opts)
                return self._json(result)
            if path == "/api/pin":
                if isinstance(req.get("recipe"), dict):
                    recipe = clean_recipe(req["recipe"])
                    if not recipe:
                        raise UserError("That recipe needs a title, ingredients and steps.")
                    new = recipe
                elif req.get("index") is None:
                    new = None
                else:
                    saved = self.state.snapshot()["saved"]
                    idx = req["index"]
                    if not (isinstance(idx, int) and 0 <= idx < len(saved)):
                        raise UserError("No such recipe.")
                    new = saved[idx]

                def apply(d):
                    if new:
                        save_recipe(d, new)
                    d["pinned"] = new
                result = self.state.update(apply)
                poke_display(self.opts)
                return self._json(result)
            if path == "/api/delete":
                idx = req.get("index")
                saved = self.state.snapshot()["saved"]
                if not (isinstance(idx, int) and 0 <= idx < len(saved)):
                    raise UserError("No such recipe.")
                gone = saved[idx]["title"]

                def apply(d):
                    d["saved"].pop(idx)
                    if d["pinned"] and d["pinned"]["title"] == gone:
                        d["pinned"] = None
                was_pinned = (self.state.snapshot()["pinned"] or {}).get("title") == gone
                result = self.state.update(apply)
                if was_pinned:
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
