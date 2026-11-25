# Weather Radar

Animated NEXRAD radar for your Home Assistant location (US only): the last 50 minutes in 5-minute steps, then a
forecast (NOAA HRRR model simulated radar, `forecast_minutes` ahead in `forecast_step_min` steps; those frames carry an
amber border and "FORECAST"), looping. Radar from NOAA via [Iowa Environmental Mesonet](https://mesonet.agron.iastate.edu), map © OpenStreetMap contributors
(fetched once and cached in `/data`).

- Appears in the HA sidebar as **Radar** (ingress).
- `http://<ha-host>:8101/radar.gif` animation, for a Picture card

Options: `latitude` / `longitude` (0 = use Home Assistant's location), `zoom` (8 ≈ 150 km across), `width`, `height`,
`frame_ms`, `refresh_minutes`, `forecast_minutes` (0 = no forecast, default 120), `forecast_step_min` (15).

Try it locally: `python3 radar.py --options options.json --cache .cache --out out/`
