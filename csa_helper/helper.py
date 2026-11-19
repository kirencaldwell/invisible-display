#!/usr/bin/env python3
"""CSA helper: runs Claude Code with fixed prompts on behalf of the CSA Recipes Home Assistant add-on.

  POST /letter    body = image bytes             -> {"items": [{"name", "quantity"}]}
  POST /recipes   body = {"items": [...], "count": 4, "notes": "", "request": ""}  -> {"recipes": [...]}
  GET  /health

Every request needs `Authorization: Bearer <token>` (the token in ~/.csa-helper/token). Claude Code runs headless
(`claude -p`) with only the tools it needs: Read for the letter photo, none for recipes.
"""
from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("csa-helper")
CLAUDE = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
TIMEOUT = 240
lock = threading.Lock()          # one Claude run at a time

LETTER_PROMPT = """Read the image file {path}. It is a photo of the letter that came with a CSA (community supported
agriculture) produce box. List every item that was included in this delivery. Ignore farm news, recipes, prices, dates
and addresses. Reply with ONLY a JSON array and no other text; each element is {{"name": "...", "quantity": "..."}} where
name is the plain ingredient name (e.g. "kale", "carrots", "delicata squash") and quantity is what the letter says
("1 bunch", "2 lb") or "" if not stated. If the image is not a CSA letter or is unreadable, reply with []."""

RECIPE_PROMPT = """A household got a CSA box containing: {items}.
Suggest {n} different dinner recipes that make good use of these ingredients (each should use at least two of them;
across the set, cover as many as possible). Recipes may also use ordinary pantry items or other groceries not in the box.
{notes}Each recipe must be short enough to read on a small e-ink screen: at most 10 ingredients and 8 steps, one sentence per step.
Reply with ONLY a JSON array and no other text, each element:
{{"title": "...", "servings": 4, "minutes": 35,
  "ingredients": [{{"item": "2 delicata squash", "from_box": true}}, {{"item": "1 tbsp olive oil", "from_box": false}}],
  "steps": ["...", "..."]}}
Set from_box true only for ingredients that come from the CSA box list above."""


class HelperError(Exception):
    pass


def run_claude(prompt: str, tools: str, cwd: str) -> list:
    cmd = [CLAUDE, "-p", prompt, "--output-format", "json", "--tools", tools, "--no-session-persistence"]
    try:
        with lock:
            proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        raise HelperError("Claude took too long") from exc
    if proc.returncode != 0:
        log.warning("claude exited %s: %s", proc.returncode, proc.stderr[:300] or proc.stdout[:300])
        raise HelperError("Claude Code failed (is it signed in on the mini PC?)")
    try:
        text = json.loads(proc.stdout)["result"]
        return json.loads(re.search(r"\[.*\]", text, re.S).group(0))
    except (ValueError, KeyError, AttributeError) as exc:
        log.warning("unparseable reply: %s", proc.stdout[:500])
        raise HelperError("Couldn't understand Claude's reply") from exc


def read_letter(image: bytes) -> list:
    with tempfile.TemporaryDirectory(prefix="csa-") as d:
        name = "letter.jpg"
        with open(os.path.join(d, name), "wb") as f:
            f.write(image)
        return run_claude(LETTER_PROMPT.format(path=name), "Read", d)


def recipes(items: list, count: int, notes: str, request: str = "") -> list:
    listing = ", ".join(f"{i.get('quantity', '')} {i['name']}".strip() for i in items)
    notes = f"Dietary notes: {notes}.\n" if notes else ""
    if request.strip():
        notes += f"The cook's request for this batch (follow it, e.g. cuisine, effort or style): {request.strip()[:500]}\n"
    with tempfile.TemporaryDirectory(prefix="csa-") as d:
        return run_claude(RECIPE_PROMPT.format(items=listing, n=count, notes=notes), "", d)


class Handler(BaseHTTPRequestHandler):
    token: str

    def log_message(self, fmt, *args):
        log.info("%s: %s", self.client_address[0], fmt % args)

    def _send(self, code: int, obj) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        got = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        return hmac.compare_digest(got.encode(), self.token.encode())

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._authed():
            return self._send(401, {"error": "bad token"})
        n = int(self.headers.get("Content-Length") or 0)
        if n > 20_000_000:
            return self._send(413, {"error": "too large"})
        body = self.rfile.read(n)
        try:
            if self.path == "/letter":
                return self._send(200, {"items": read_letter(body)})
            if self.path == "/recipes":
                req = json.loads(body)
                return self._send(200, {"recipes": recipes(req["items"], int(req.get("count", 4)), req.get("notes", ""), req.get("request", ""))})
        except HelperError as exc:
            return self._send(502, {"error": str(exc)})
        except (ValueError, KeyError, TypeError) as exc:
            return self._send(400, {"error": f"bad request: {exc}"})
        self._send(404, {"error": "not found"})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8200)
    ap.add_argument("--token-file", default=os.path.expanduser("~/.csa-helper/token"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with open(args.token_file) as f:
        Handler.token = f.read().strip()
    if len(Handler.token) < 20:
        raise SystemExit("token file must hold a long random token")
    log.info("claude binary: %s", CLAUDE)
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
