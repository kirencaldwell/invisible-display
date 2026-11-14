# Weather Radar

Animated NEXRAD radar for your Home Assistant location (US only): the last 50 minutes in 5-minute steps, looping.
Radar from NOAA via [Iowa Environmental Mesonet](https://mesonet.agron.iastate.edu), map © OpenStreetMap contributors
(fetched once and cached in `/data`).

- Appears in the HA sidebar as **Radar** (ingress).
- `http://<ha-host>:8101/radar.gif` animation, for a Picture card

Options: `latitude` / `longitude` (0 = use Home Assistant's location), `zoom` (8 ≈ 150 km across), `width`, `height`,
`frame_ms`, `refresh_minutes`.

Try it locally: `python3 radar.py --options options.json --cache .cache --out out/`
