# Weather Radar

Animated radar for your Home Assistant location (US), looping: the last `past_minutes` (20 by default) of observed NEXRAD
radar in 5-minute steps, then the future in two parts, each with a coloured border and label:

- **NOWCAST** (blue border, about the next 70 minutes): Environment and Climate Change Canada's radar extrapolation
  (a PySTEPS motion field moves the newest North American radar composite forward; it doesn't predict rain forming or
  fading), recoloured to match the observed frames.
- **MODEL** (amber border, after that, up to `forecast_minutes`): NOAA's HRRR simulated radar. Smoother, and a model's
  guess rather than a measurement.

Data: observed radar from NOAA via [Iowa Environmental Mesonet](https://mesonet.agron.iastate.edu); nowcast data source:
Environment and Climate Change Canada (GeoMet, open data licence); map © OpenStreetMap contributors (fetched once and cached in `/data`).

- Appears in the HA sidebar as **Radar** (ingress).
- `http://<ha-host>:8101/radar.gif` animation, for a Picture card

Options: `latitude` / `longitude` (0 = use Home Assistant's location), `zoom` (8 ≈ 150 km across), `width`, `height`,
`frame_ms` (observed frames), `refresh_minutes`, `past_minutes` (observed history, default 20, max 50), `nowcast_minutes`
(0 = no nowcast, default 70), `forecast_minutes` (total look-ahead incl. the nowcast, default 180, 0 = none),
`forecast_step_min` (15), `forecast_frame_ms` (time per future frame, default 1000).
If the nowcast source is unreachable the model frames start at +15 min instead.

Try it locally: `python3 radar.py --options options.json --cache .cache --out out/`
