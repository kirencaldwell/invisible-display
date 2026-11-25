# Weather Radar

Animated NEXRAD radar for your Home Assistant location (US only): the last `past_minutes` (20 by default) in 5-minute steps, then a
forecast (NOAA HRRR model simulated radar, `forecast_minutes` ahead in `forecast_step_min` steps; those frames carry an
amber border and "FORECAST"), looping. Radar from NOAA via [Iowa Environmental Mesonet](https://mesonet.agron.iastate.edu), map © OpenStreetMap contributors
(fetched once and cached in `/data`).

- Appears in the HA sidebar as **Radar** (ingress).
- `http://<ha-host>:8101/radar.gif` animation, for a Picture card

Options: `latitude` / `longitude` (0 = use Home Assistant's location), `zoom` (8 ≈ 150 km across), `width`, `height`,
`frame_ms`, `refresh_minutes`, `forecast_minutes` (0 = no forecast, default 120), `forecast_step_min` (15), `past_minutes` (observed history, default 20, max 50), `forecast_frame_ms` (time per forecast frame, default 1000; observed frames use `frame_ms`).

Try it locally: `python3 radar.py --options options.json --cache .cache --out out/`
