#!/usr/bin/env python3
"""Run by a systemd timer every 10 minutes. Runs the tests when Home Assistant Core changes version (plus once a day),
alerts the phone with the outcome, and starts a Claude Code fix session when something fails."""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import alert
import run_tests

DIR = os.path.join(os.path.expanduser("~"), ".csa-tests")
STATE = os.path.join(DIR, "state.json")
DAILY = 24 * 3600
FIX_COOLDOWN = 12 * 3600          # don't start another fix session for the same failure within this window


def load() -> dict:
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(st: dict) -> None:
    os.makedirs(DIR, exist_ok=True)
    with open(STATE, "w") as f:
        json.dump(st, f)


def core_version() -> str:
    try:
        return run_tests.get_json(run_tests.url("display", "/health")).get("core_version", "")
    except Exception:
        return ""


def main() -> None:
    force = "--force" in sys.argv
    st, now = load(), time.time()
    version = core_version()
    changed = bool(version) and version != st.get("core_version")
    due = now - st.get("last_run", 0) > DAILY
    if not (force or changed or due):
        return
    reason = f"Home Assistant updated to {version}" if changed and st.get("core_version") else "daily check"
    results = run_tests.run(with_claude=True)
    failed = [r for r in results if not r["ok"]]
    report = {"when": dt.datetime.now().astimezone().isoformat(), "reason": reason, "core_version": version, "results": results}
    with open(os.path.join(DIR, "last-report.json"), "w") as f:
        json.dump(report, f, indent=1)
    st.update(core_version=version or st.get("core_version", ""), last_run=now)
    if not failed:
        if changed or force:
            alert.send("Home Assistant checks passed", f"{reason}: all {len(results)} checks passed.")
        save(st)
        return
    signature = "|".join(sorted(r["check"] for r in failed))
    summary = "; ".join(f"{r['check']} ({r['detail'][:80]})" for r in failed)
    if now - st.get("fix", {}).get(signature, 0) < FIX_COOLDOWN:
        save(st)
        return
    st.setdefault("fix", {})[signature] = now
    save(st)
    alert.send(f"{len(failed)} check(s) failed", f"{reason}. {summary}\nStarting an autofix session.")
    subprocess.run([os.path.join(os.path.dirname(os.path.abspath(__file__)), "autofix.sh"),
                    os.path.join(DIR, "last-report.json")], check=False)


if __name__ == "__main__":
    main()
