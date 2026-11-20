#!/usr/bin/env bash
# Start an interactive Claude Code session (in tmux) to fix failing checks. Usage: autofix.sh <report.json>
# The session works on a new branch in ~/invisible-display, can't push or deploy, and pings the phone (via the HA
# webhook) whenever it needs approval or finishes. Attach with: ssh -t minipc tmux attach -t autofix
set -euo pipefail
REPORT="${1:?report path}"
REPO="$HOME/invisible-display"
SESSION=autofix
export PATH="$HOME/.local/bin:$PATH"

if tmux has-session -t "$SESSION" 2>/dev/null; then echo "autofix session already running"; exit 0; fi
if [ ! -d "$REPO/.git" ]; then git clone -q https://github.com/kirencaldwell/invisible-display "$REPO"; fi
cd "$REPO"
git fetch -q origin && git checkout -q main && git reset -q --hard origin/main
BRANCH="autofix/$(date +%Y%m%d-%H%M)"
git checkout -q -b "$BRANCH"
cp "$REPORT" "$HOME/.csa-tests/fix-report.json"

PROMPT="The periodic health checks for our Home Assistant add-ons failed. The report is in ~/.csa-tests/fix-report.json
(each result has a check name, ok, and detail). This repo (invisible-display) holds four add-ons: invisible_display
(e-ink calendar/weather/lists/recipe renderer), weather_radar, csa_recipes and recipes; ops/ holds the test runner.
Read ops/run_tests.py to see what each check does, and the add-on code it exercises. The add-ons run on a Home Assistant
Green at 192.168.4.54; you can read their live state with curl against the ports in ops/run_tests.py (read-only: never
POST to them or change what is pinned on the display).
Find the root cause. If it is a bug in our code or a change in Home Assistant that our code must adapt to (for example a
changed API, entity or service), fix it in this repo, bump the add-on's version in its config.yaml, verify with
python3 -m py_compile and, where possible, ~/.csa-tests/venv/bin/python invisible_display/server.py --demo --preview /tmp/preview,
and commit on this branch (never push, never deploy). If the cause is outside this repo (a device is offline, an entity was
removed or renamed in Home Assistant, the mini PC helper is down), do not guess at fixes: write a short diagnosis instead.
Either way, finish by writing ~/.csa-tests/fix-summary.md with: what failed, the root cause, what you changed (or what the
user must do), and how to deploy it. Keep changes minimal."
tmux new-session -d -s "$SESSION" -c "$REPO" \
  "claude --settings $HOME/.csa-tests/ops/autofix-settings.json $(printf '%q' "$PROMPT"); bash"
echo "started autofix on $BRANCH"
