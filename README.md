# Invisible Display

Home Assistant add-on repository: calendar + weather pages for an
[Invisible Computers](https://invisible-computers.com) e-paper display, served over its local render protocol.

## Install

In Home Assistant: **Settings → Add-ons → Add-on Store → ⋮ → Repositories**, add

```
https://github.com/kirencaldwell/invisible-display
```

then install **Invisible Display**. See [invisible_display/README.md](invisible_display/README.md) for options and setup.

## Development

```
python3 -m venv .venv && .venv/bin/pip install pillow numpy
.venv/bin/python invisible_display/server.py --demo --preview out/
```

Bump `version` in `invisible_display/config.yaml` and push to `main`; Home Assistant offers the update
(Add-on Store → ⋮ → Check for updates, or enable auto-update on the add-on).
`./deploy.sh` copies the add-on straight to a Home Assistant machine on your network over SSH as a local add-on
(for quick iteration; don't keep both the local and the repository copy installed).
