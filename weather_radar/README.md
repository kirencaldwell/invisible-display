# Weather Radar

Animated radar for your Home Assistant location (US and Canada), looping: the last `past_minutes` (20 by default) of observed
radar, then a nowcast about 70 minutes ahead (blue border, "NOWCAST").

Everything comes from one source, [Environment and Climate Change Canada's](https://eccc-msc.github.io/open-data/msc-data/obs_radar/readme_radar_geomet_en)
North American radar composite (open data licence; GeoMet): the observed rain and snow rates, and its radar extrapolation (a
PySTEPS motion field moves the newest picture forward; it does not predict rain forming or fading, so it is best for the first
hour). Because past and future are the same product they look alike. Colours are Environment Canada's own scale
(rain and snow shown together). Map © OpenStreetMap contributors (fetched once and cached in `/data`).

- Appears in the HA sidebar as **Radar** (ingress).
- `http://<ha-host>:8101/radar.gif` animation, for a Picture card

Options: `latitude` / `longitude` (0 = use Home Assistant's location), `zoom` (8 ≈ 150 km across), `width`, `height`,
`frame_ms` (observed frames), `refresh_minutes`, `past_minutes` (observed history, default 20, max 50), `forecast_minutes`
(how far ahead, default 72, 0 = none), `forecast_step_min` (default 6, the source's step; multiples of 6), `forecast_frame_ms`
(time per future frame, default 800), `source`: `eccc` (default) or `iem` (the older mix: NOAA NEXRAD tiles from the Iowa
Environmental Mesonet for the past, NOAA HRRR model frames for the future, which reach up to 18 h but look different from the
observed frames).
If Environment Canada is unreachable the add-on falls back to the `iem` mix by itself.

Try it locally: `python3 radar.py --options options.json --cache .cache --out out/`
