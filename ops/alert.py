#!/usr/bin/env python3
"""Send a phone notification through the Home Assistant webhook (URL in ~/.csa-tests/alert-url).

  alert.py "Title" "Message"
  <Claude Code hook JSON on stdin> | alert.py --hook approval|done
"""
import json
import os
import subprocess
import sys
import urllib.request

HOME = os.path.expanduser("~")
URL_FILE = os.path.join(HOME, ".csa-tests", "alert-url")


def send(title: str, message: str) -> None:
    with open(URL_FILE) as f:
        url = f.read().strip()
    body = json.dumps({"title": title, "message": message[:1000]}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=15).read()


def hook(kind: str) -> None:
    try:
        ev = json.load(sys.stdin)
    except ValueError:
        ev = {}
    attach = "Attach: ssh -t minipc tmux attach -t autofix"
    if kind == "approval":
        send("Claude needs your approval", f"{ev.get('message', 'The fix session is waiting for permission.')}\n{attach}")
        return
    cwd = ev.get("cwd") or os.path.join(HOME, "invisible-display")
    branch = subprocess.run(["git", "-C", cwd, "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
    ahead = subprocess.run(["git", "-C", cwd, "rev-list", "--count", "origin/main..HEAD"], capture_output=True, text=True).stdout.strip()
    if ahead and ahead != "0":
        last = subprocess.run(["git", "-C", cwd, "log", "-1", "--format=%s"], capture_output=True, text=True).stdout.strip()
        detail = f"{ahead} commit(s) on {branch}, latest: {last}"
    else:
        detail = "No code changes were made (see ~/.csa-tests/fix-summary.md)."
    send("Autofix session finished", f"{detail}\n{attach}")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--hook":
        hook(sys.argv[2])
    elif len(sys.argv) == 3:
        send(sys.argv[1], sys.argv[2])
    else:
        sys.exit(__doc__)
