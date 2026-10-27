# Invisible Display — Home Assistant add-on

Alternates two pages on an Invisible Computers e-paper display (7.5" or 10.2"),
served from your Home Assistant Green using the display's
[local render protocol](https://github.com/Invisible-Computers/local-render-server):

- **Calendar** – agenda for the next days from your Home Assistant calendars, a mini month view
  with busy days dotted, and a one-letter tag per calendar.
- **Lists** – optional checklist page: one column per Home Assistant to-do entity (Todoist, Shopping List, …),
  showing open items. Enabled by setting `lists`.
- **Weather** – the current hour (icon, temperature, feels-like, rain, wind, sunrise/sunset),
  the next 8 hours, and a simpler 7-day forecast alongside. Underneath, rain-gear advice for the
  next morning and evening bike commute: jacket, pants, both, "pack" (maybe) or nothing.

Calendars come from the calendar entities you already have in Home Assistant (e.g. the Google Calendar
integration), so shared calendars work without secret iCal URLs. Weather comes from a Home Assistant
weather entity. Location, timezone and units follow your Home Assistant settings.

## Install (Home Assistant Green)

1. Add the **Samba share** or **Advanced SSH & Web Terminal** add-on if you don't have one.
2. Copy this whole folder to the `addons` share as `addons/invisible_display/`.
3. **Settings → Add-ons → Add-on Store → ⋮ → Check for updates**. "Invisible Display" appears under *Local add-ons*.
4. Install it, open **Configuration**, set the options below, then **Start**.
5. Open `http://<your-HA-ip>:8080/` to preview both pages in a browser.
6. In the Invisible app choose **Set up a local device** and enter `http://<your-HA-ip>:8080`
   (plain `http://`, not https).

## Options

| Option | Default | Notes |
| --- | --- | --- |
| `calendars` | `[]` | List of `entity_id` (+ optional `tag`, `name`). Empty = use every calendar entity in HA. |
| `weather_entity` | `weather.forecast_home` | Any HA weather entity that supports hourly and daily forecasts. |
| `weather_fallback_entity` | `""` | Backup weather entity used when `weather_entity` is unavailable. |
| `display_model` | `7_5_inch` | or `10_2_inch`. |
| `page_minutes` | `10` | How long each page stays up before switching. |
| `clock_24h` | `false` | |
| `week_starts_monday` | `false` | Mini-month layout. |
| `agenda_days` | `7` | How many days the agenda looks ahead. |
| `lists` | `[]` | To-do entities for the Lists page: `entity_id` (+ optional `title`). Empty = no Lists page. |
| `lists_refresh_minutes` | `5` | |
| `todo_entity` / `todo_title` | `""` / `To do` | A to-do entity shown as a checklist under the mini month on the calendar page. |
| `calendar_refresh_minutes` / `weather_refresh_minutes` | `15` / `30` | |
| `commute_morning` / `commute_evening` | `07:30` / `16:30` | When you leave home / work for the bike commute (24 h `HH:MM`). `""` hides that row. Weekends are skipped. |
| `commute_minutes` | `60` | Door to door, including the daycare stop. The forecast hours overlapping this window are checked. |

### Bike commute rain gear

For each commute window the weather page takes the worst hour's chance of rain, the wettest hour's amount and
the coldest temperature, and decides jacket and pants separately (thresholds are constants at the top of
`commute.py`):

- **Jacket**: chance of rain ≥ 50% (≥ 40% when it's below 8 °C / 46 °F); "pack" from 25%.
- **Pants**: ≥ 60% with steady rain (≥ 1 mm/h, or ≥ 0.5 mm/h in the cold), a downpour/thunderstorm, or ≥ 40% with
  ≥ 2.5 mm/h; "maybe" for ≥ 40% with drizzle, or when it rained in the 2 hours before leaving (road spray).
- **Drizzle**: jacket + pants whenever an hour is saturated (humidity ≥ 97%, or temperature within 1 °C of the
  dew point) and has any rain in the forecast (≥ 10% or a rainy condition). Seattle drizzle gets a low chance and
  almost no amount, but an hour in it soaks you.
- If the weather entity has no rain amount (e.g. NWS) or no probability (e.g. Met.no), the condition fills in.

Example `calendars`:

```yaml
calendars:
  - entity_id: calendar.family
    tag: F
    name: Family
  - entity_id: calendar.work_shared
    tag: W
    name: Shared work
```

The add-on log lists every calendar entity it finds, which is handy for getting the entity ids.

## How it behaves

- The display wakes about once a minute. The server answers with an empty body when the picture is
  unchanged, so the panel only redraws when the page switches or the content changes.
- A full redraw is forced at least every 20 hours, as the display recommends.
- The add-on keeps the last good data if Home Assistant, a calendar or the weather entity has a hiccup.
- Local mode means the display no longer contacts the cloud and gets no over-the-air firmware updates.
  Local mode needs newer firmware; email info@invisible-computers.com if setup doesn't offer it.

## Developing / previewing without Home Assistant

```
pip install pillow numpy
python server.py --demo --preview out/     # writes out/calendar.png and out/weather.png
python server.py --demo --port 8080         # serve demo pages
```

To run against a real Home Assistant from another machine, copy `options.example.json` to
`options.json`, fill in `ha_url` and a long-lived access token, and run `python server.py`.
Requires Python 3.11+.

