"""Rain-gear advice for the bike commute (home -> daycare -> work and back).

Looks at the hourly forecast across each commute window and decides, separately,
whether a rain jacket and rain pants are worth wearing. Pants get a higher bar than
the jacket: light drizzle is fine on the legs, a proper shower or cold rain is not.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from ha import Hour, Weather

# Thresholds. Rain amounts are mm per hour, temperatures °C (converted from the entity's units).
JACKET_POP, JACKET_MAYBE_POP = 50, 25       # % chance of rain
PANTS_POP, PANTS_MAYBE_POP = 60, 40
PANTS_MM, PANTS_MAYBE_MM = 1.0, 0.5         # steady rain vs. drizzle
DOWNPOUR_MM = 2.5                           # pants even at a lower chance
COLD_C = 8                                  # below this, wet is miserable: lower the bar
WET_ROADS_HOURS = 2                         # rain this long before leaving still means road spray
# Seattle drizzle: saturated air with even a slight chance of rain soaks your top over an hour,
# although forecasts give it a low chance and almost no amount (e.g. 2026-10-27: 11-16%, 99% RH).
# It means a jacket; pants still need an actual rain forecast.
DRIZZLE_RH = 97                             # % relative humidity...
DRIZZLE_SPREAD_C = 1.0                      # ...or temperature within this of the dew point
DRIZZLE_POP = 10                            # with at least this chance of rain

RAIN_CONDS = {"rainy", "pouring", "lightning-rainy", "snowy-rainy", "hail"}
HEAVY_CONDS = {"pouring", "lightning-rainy"}

COMMUTE_WEEKDAYS = {0, 1, 2, 3, 4}         # Mon-Fri; weekends are skipped

WEAR, MAYBE, NO = 2, 1, 0


@dataclass
class Advice:
    label: str                  # "AM" / "PM", with the weekday when it isn't today
    start: dt.datetime
    jacket: int = NO            # WEAR / MAYBE / NO
    pants: int = NO
    pop: float | None = None    # worst hour's chance of rain, %
    precip: float | None = None  # wettest hour's amount, in the entity's unit
    temp: float | None = None   # coldest temperature, in the entity's unit
    known: bool = True          # False when the forecast doesn't reach this window

    def verdict(self) -> str:
        if not self.known:
            return "No forecast yet"
        j, p = self.jacket, self.pants
        if j == WEAR and p == WEAR:
            return "Jacket + pants"
        if j == WEAR:
            return "Jacket, pants maybe" if p == MAYBE else "Jacket"
        if j == MAYBE:
            return "Pack jacket + pants" if p == MAYBE else "Pack a jacket"
        return "No rain gear"


def _to_mm(v: float | None, unit: str) -> float | None:
    if v is None:
        return None
    return v * 25.4 if unit.strip().lower() in ("in", "inch", "inches") else v


def _to_c(v: float, unit: str) -> float:
    return (v - 32) * 5 / 9 if "F" in unit else v


def _overlap(hours: list[Hour], start: dt.datetime, end: dt.datetime) -> list[Hour]:
    return [h for h in hours if h.time < end and h.time + dt.timedelta(hours=1) > start]


def _saturated(h: Hour, temp_unit: str) -> bool:
    if h.humidity is not None and h.humidity >= DRIZZLE_RH:
        return True
    if h.dew_point is None:
        return False
    return _to_c(h.temp, temp_unit) - _to_c(h.dew_point, temp_unit) <= DRIZZLE_SPREAD_C


def assess(hours: list[Hour], start: dt.datetime, end: dt.datetime, temp_unit: str, precip_unit: str,
           label: str) -> Advice:
    win = _overlap(hours, start, end)
    if not win:
        return Advice(label, start, known=False)
    pops = [h.pop for h in win if h.pop is not None]
    amounts = [h.precip for h in win if h.precip is not None]
    rainy = any(h.cond in RAIN_CONDS for h in win)
    heavy = any(h.cond in HEAVY_CONDS for h in win)

    # Fill in whatever the weather integration doesn't provide (e.g. NWS has no amounts,
    # Met.no has no probability) from the condition.
    mm = max(_to_mm(a, precip_unit) for a in amounts) if amounts else None
    pop = max(pops) if pops else None
    if pop is None:
        pop = 80 if rainy or (mm or 0) >= 0.1 else 10
    if mm is None:
        mm = 2.5 if heavy else 1.0 if rainy else 0.5
    cold = _to_c(min(h.temp for h in win), temp_unit) < COLD_C
    drizzle = any(_saturated(h, temp_unit) and (h.cond in RAIN_CONDS or
                                                 (h.pop is not None and h.pop >= DRIZZLE_POP)) for h in win)

    if pop >= JACKET_POP or (cold and pop >= JACKET_POP - 10):
        jacket = WEAR
    elif pop >= JACKET_MAYBE_POP or (amounts and mm >= PANTS_MAYBE_MM):
        jacket = MAYBE      # the model itself rains on you, whatever its ensemble chance says
    else:
        jacket = NO

    pants_mm = PANTS_MAYBE_MM if cold else PANTS_MM
    if heavy or (pop >= PANTS_POP and mm >= pants_mm) or (pop >= PANTS_MAYBE_POP and mm >= DOWNPOUR_MM):
        pants = WEAR
    elif pop >= PANTS_MAYBE_POP and mm >= PANTS_MAYBE_MM:
        pants = MAYBE
    else:
        before = [h for h in _overlap(hours, start - dt.timedelta(hours=WET_ROADS_HOURS), start) if h not in win]
        wet_before = sum(_to_mm(h.precip, precip_unit) or 0 for h in before) >= 1.0 or \
            any(h.cond in RAIN_CONDS and (h.pop is None or h.pop >= PANTS_POP) for h in before)
        pants = MAYBE if wet_before else NO     # road spray off the wheels
    if drizzle:
        jacket = WEAR       # pants only for actual rain, not wet air
    jacket = max(jacket, pants)

    return Advice(label, start, jacket, pants, max(pops) if pops else None,
                  max(amounts) if amounts else None, min(h.temp for h in win))


def _next_window(now: dt.datetime, at: dt.time, minutes: int, weekdays: set[int]) -> dt.datetime:
    """Start of the next commute at time `at` that hasn't finished yet, on a commute day."""
    day = now.date()
    for _ in range(8):
        start = dt.datetime.combine(day, at, now.tzinfo)
        if day.weekday() in weekdays and start + dt.timedelta(minutes=minutes) > now:
            return start
        day += dt.timedelta(days=1)
    return dt.datetime.combine(now.date(), at, now.tzinfo)


def parse_time(s: str) -> dt.time | None:
    s = (s or "").strip()
    return dt.time.fromisoformat(s) if s else None


def advise(wx: Weather, now: dt.datetime, morning: dt.time | None, evening: dt.time | None,
           minutes: int, weekdays: set[int] = COMMUTE_WEEKDAYS) -> list[Advice]:
    """Advice for the next morning and evening commutes, in time order."""
    out = []
    for at, name in ((morning, "AM"), (evening, "PM")):
        if at is None:
            continue
        start = _next_window(now, at, minutes, weekdays)
        label = name if start.date() == now.date() else f"{start:%a} {name}"
        out.append(assess(wx.hours, start, start + dt.timedelta(minutes=minutes),
                          wx.temp_unit, wx.precip_unit, label))
    out.sort(key=lambda a: a.start)
    return out
