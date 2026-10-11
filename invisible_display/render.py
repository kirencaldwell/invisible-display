"""Drawing code: turns calendar/weather data into 1-bit images.

All layout is done in a logical 800-px-wide space and scaled to the panel, so
the same code serves the 7.5" (800x480) and 10.2" (960x640) displays.
"""
from __future__ import annotations

import calendar as pycal
import datetime as dt
import functools
import math

from PIL import Image, ImageDraw, ImageFont

from ha import Event, Weather, describe, events_on

_FONT_PATHS = {
    False: [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansCondensed.ttf",
        "/usr/share/fonts/TTF/DejaVuSansCondensed.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "DejaVuSansCondensed.ttf",
        "Arial.ttf",
    ],
    True: [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansCondensed-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSansCondensed-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "DejaVuSansCondensed-Bold.ttf",
        "Arial Bold.ttf",
    ],
}


@functools.lru_cache(maxsize=None)
def font(px: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for p in _FONT_PATHS[bold]:
        try:
            return ImageFont.truetype(p, px)
        except OSError:
            continue
    return ImageFont.load_default(px)


class Canvas:
    """Drawing surface that takes logical (800-wide) coordinates."""

    def __init__(self, width: int, height: int):
        self.W, self.H = width, height
        self.S = width / 800
        self.LH = height / self.S          # logical height (480 or ~533)
        self.img = Image.new("L", (width, height), 255)
        self.d = ImageDraw.Draw(self.img)

    def _xy(self, *v):
        return [a * self.S for a in v]

    def _w(self, w):
        return max(1, round(w * self.S))

    def text(self, x, y, s, size, bold=False, anchor="la", fill=0):
        self.d.text((x * self.S, y * self.S), s, font=font(round(size * self.S), bold), fill=fill, anchor=anchor)

    def textw(self, s, size, bold=False) -> float:
        return self.d.textlength(s, font=font(round(size * self.S), bold)) / self.S

    def fit(self, s, size, maxw, bold=False) -> str:
        if self.textw(s, size, bold) <= maxw:
            return s
        while s and self.textw(s + "…", size, bold) > maxw:
            s = s[:-1]
        return s.rstrip() + "…"

    def line(self, x1, y1, x2, y2, w=1, fill=0):
        self.d.line(self._xy(x1, y1, x2, y2), fill=fill, width=self._w(w))

    def rect(self, x1, y1, x2, y2, fill=None, outline=None, w=1, r=0):
        box = self._xy(x1, y1, x2, y2)
        if r:
            self.d.rounded_rectangle(box, radius=r * self.S, fill=fill, outline=outline, width=self._w(w))
        else:
            self.d.rectangle(box, fill=fill, outline=outline, width=self._w(w))

    def ellipse(self, x1, y1, x2, y2, fill=None, outline=None, w=1):
        self.d.ellipse(self._xy(x1, y1, x2, y2), fill=fill, outline=outline, width=self._w(w))

    def polygon(self, pts, fill=0):
        self.d.polygon([(x * self.S, y * self.S) for x, y in pts], fill=fill)

    def done(self) -> Image.Image:
        return self.img.point(lambda v: 255 if v >= 128 else 0).convert("1")


# --------------------------------------------------------------------------
# Weather icons (outline style, drawn in a box of logical size s around cx, cy)
# --------------------------------------------------------------------------
def _cloud(c: Canvas, cx, cy, s, w):
    circles = [(-0.17, 0.05, 0.16), (0.02, -0.06, 0.21), (0.21, 0.06, 0.14)]
    for grow, fill in ((w, 0), (0, 255)):       # black outline pass, then white fill
        for dx, dy, r in circles:
            rr = r * s + grow
            c.ellipse(cx + dx * s - rr, cy + dy * s - rr, cx + dx * s + rr, cy + dy * s + rr, fill=fill)
        c.rect(cx - 0.17 * s, cy + 0.05 * s, cx + 0.21 * s, cy + 0.21 * s + grow, fill=fill)


def _sun(c: Canvas, cx, cy, s, w, r=0.2, ray0=0.30, ray1=0.45):
    c.ellipse(cx - r * s, cy - r * s, cx + r * s, cy + r * s, outline=0, w=w)
    for i in range(8):
        a = i * math.pi / 4
        c.line(cx + math.cos(a) * ray0 * s, cy + math.sin(a) * ray0 * s,
               cx + math.cos(a) * ray1 * s, cy + math.sin(a) * ray1 * s, w=w)


def _moon(c: Canvas, cx, cy, s, r=0.26):
    R = r * s
    c.ellipse(cx - R, cy - R, cx + R, cy + R, fill=0)
    r2, ox, oy = 0.86 * R, 0.5 * R, -0.34 * R
    c.ellipse(cx + ox - r2, cy + oy - r2, cx + ox + r2, cy + oy + r2, fill=255)


def draw_icon(c: Canvas, kind: str, cx: float, cy: float, s: float, night: bool = False):
    w = max(2.0, s * 0.05)
    if kind == "clear":
        _moon(c, cx, cy, s) if night else _sun(c, cx, cy, s, w)
    elif kind == "partly":
        if night:
            _moon(c, cx - 0.12 * s, cy - 0.12 * s, s * 0.8, r=0.24)
        else:
            _sun(c, cx - 0.14 * s, cy - 0.14 * s, s, w, r=0.15, ray0=0.23, ray1=0.34)
        _cloud(c, cx + 0.06 * s, cy + 0.10 * s, s * 0.85, w)
    elif kind == "cloud":
        _cloud(c, cx, cy + 0.02 * s, s, w)
    elif kind == "fog":
        for i, (x1, x2) in enumerate([(-0.30, 0.30), (-0.22, 0.34), (-0.34, 0.26), (-0.18, 0.30)]):
            y = cy + (-0.18 + i * 0.12) * s
            c.line(cx + x1 * s, y, cx + x2 * s, y, w=w)
    elif kind == "rain":
        _cloud(c, cx, cy - 0.12 * s, s, w)
        for x in (-0.15, 0.02, 0.19):
            c.line(cx + x * s, cy + 0.17 * s, cx + (x - 0.06) * s, cy + 0.34 * s, w=w)
    elif kind == "snow":
        _cloud(c, cx, cy - 0.12 * s, s, w)
        for x, y in ((-0.14, 0.20), (0.04, 0.20), (0.22, 0.20), (-0.05, 0.34), (0.13, 0.34)):
            r = 0.04 * s
            c.ellipse(cx + x * s - r, cy + y * s - r, cx + x * s + r, cy + y * s + r, fill=0)
    elif kind == "thunder":
        _cloud(c, cx, cy - 0.14 * s, s, w)
        bolt = [(0.05, 0.10), (-0.08, 0.30), (0.00, 0.30), (-0.06, 0.48), (0.11, 0.25), (0.02, 0.25), (0.10, 0.10)]
        c.polygon([(cx + x * s, cy + y * s) for x, y in bolt])
    else:
        _cloud(c, cx, cy + 0.02 * s, s, w)


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------
def fmt_time(t: dt.datetime | dt.time, clock24=False) -> str:
    if clock24:
        return f"{t.hour:02d}:{t.minute:02d}"
    h = t.hour % 12 or 12
    suffix = "AM" if t.hour < 12 else "PM"
    return f"{h} {suffix}" if t.minute == 0 else f"{h}:{t.minute:02d} {suffix}"


def fmt_hour(t: dt.datetime, clock24=False) -> str:
    return f"{t.hour:02d}" if clock24 else fmt_time(t.replace(minute=0))


def deg(v) -> str:
    return f"{round(v)}°"


def _header(c: Canvas, left: str, right: str = ""):
    c.text(24, 8, left, 30, bold=True)
    if right:
        c.text(776, 16, right, 20, anchor="ra")
    c.line(24, 52, 776, 52, w=3)


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------
def message_page(W: int, H: int, title: str, msg: str) -> Image.Image:
    c = Canvas(W, H)
    _header(c, title)
    y = 90
    for ln in msg.split("\n"):
        c.text(24, y, c.fit(ln, 22, 752), 22)
        y += 32
    return c.done()


def calendar_page(W: int, H: int, now: dt.datetime, events: list[Event] | None,
                  wx: Weather | None, *, clock24=False, week_starts_monday=False,
                  agenda_days=7) -> Image.Image:
    if events is None:
        return message_page(W, H, "Calendar", "Calendar data isn't available yet.\nCheck the add-on log.")
    c = Canvas(W, H)
    bottom = c.LH - 12
    _header(c, f"{now:%A}, {now:%B} {now.day}")

    # ---- agenda (left) ----
    X0, X1 = 24, 524
    rows: list[tuple] = []
    today = now.date()
    for i in range(agenda_days):
        day = today + dt.timedelta(days=i)
        evs = events_on(events, day)
        if i == 0:
            evs = [e for e in evs if e.all_day or e.end >= now]
        if i > 0 and not evs:
            continue
        head = "TODAY" if i == 0 else "TOMORROW" if i == 1 else f"{day:%a %b} {day.day}".upper()
        rows.append(("head", head))
        if not evs:
            rows.append(("none", "Nothing else today"))
        for e in evs:
            rows.append(("ev", e))
    if all(r[0] != "ev" for r in rows):
        rows = [("head", "TODAY"), ("none", f"No events in the next {agenda_days} days")]

    HEAD_H, EV_H, MORE_H = 32, 29, 26
    heights = {"head": HEAD_H, "ev": EV_H, "none": EV_H}
    y, k = 64, 0
    while k < len(rows) and y + heights[rows[k][0]] <= bottom:
        y += heights[rows[k][0]]
        k += 1
    if k < len(rows):                       # overflow: leave room for "+N more"
        while k > 0 and y + MORE_H > bottom:
            k -= 1
            y -= heights[rows[k][0]]
    while k > 0 and rows[k - 1][0] == "head" and k < len(rows):
        k -= 1                              # no orphaned heading
        y -= HEAD_H
    hidden = sum(1 for r in rows[k:] if r[0] == "ev")

    y = 64
    for kind, val in rows[:k]:
        if kind == "head":
            c.text(X0, y + 6, val, 16, bold=True)
            c.line(X0, y + 28, X1, y + 28, w=1)
        elif kind == "none":
            c.text(X0 + 4, y + 4, val, 18)
        else:
            e: Event = val
            c.text(X0, y + 4, "All day" if e.all_day else fmt_time(e.start, clock24), 17)
            tx = X0 + 82
            c.rect(tx, y + 4, tx + 21, y + 25, fill=0, r=3)
            c.text(tx + 10.5, y + 15, e.tag, 15, bold=True, anchor="mm", fill=255)
            c.text(tx + 32, y + 3, c.fit(e.title, 19, X1 - (tx + 32)), 19)
        y += heights[kind]
    if hidden:
        c.text(X0, y + 4, f"+ {hidden} more", 16, bold=True)

    # ---- mini month + today's forecast (right) ----
    c.line(538, 64, 538, bottom, w=1)
    MX, CW = 552, 32
    c.text(MX + CW * 3.5, 62, f"{now:%B %Y}", 20, bold=True, anchor="ma")
    first = 0 if week_starts_monday else 6
    letters = ["M", "T", "W", "T", "F", "S", "S"] if week_starts_monday else ["S", "M", "T", "W", "T", "F", "S"]
    for i, ch in enumerate(letters):
        c.text(MX + CW * (i + 0.5), 94, ch, 14, bold=True, anchor="ma")
    for r, week in enumerate(pycal.Calendar(first).monthdayscalendar(now.year, now.month)):
        for i, dnum in enumerate(week):
            if not dnum:
                continue
            cx, cy = MX + CW * (i + 0.5), 124 + r * 30
            day = dt.date(now.year, now.month, dnum)
            busy = bool(events_on(events, day))
            if day == today:
                c.rect(cx - 15, cy - 13, cx + 15, cy + 13, fill=0, r=4)
            c.text(cx, cy - 3, str(dnum), 16, bold=(day == today), anchor="mm", fill=255 if day == today else 0)
            if busy:
                c.ellipse(cx - 2, cy + 7, cx + 2, cy + 11, fill=255 if day == today else 0)

    ly = 124 + 6 * 30 + 14
    c.text(MX, ly, "TODAY'S FORECAST", 13, bold=True)
    c.line(MX, ly + 19, 776, ly + 19, w=1)
    y0 = ly + 30
    day = next((d for d in wx.days if d.date == today), None) if wx else None
    if day is None:
        c.text(MX, y0, "Forecast unavailable", 16)
        return c.done()
    label, kind = describe(day.cond)
    draw_icon(c, kind, MX + 28, y0 + 26, 50)
    c.text(MX + 70, y0 - 4, deg(day.hi), 34, bold=True)
    if day.lo is not None:
        c.text(MX + 70 + c.textw(deg(day.hi), 34, True) + 10, y0 + 8, deg(day.lo), 22)
    c.text(MX, y0 + 52, c.fit(label, 18, 776 - MX), 18)
    bits = []
    if day.pop is not None:
        bits.append(f"Rain {round(day.pop)}%")
    if wx.current is not None:
        bits.append(f"Now {deg(wx.current.temp)}")
    if bits and y0 + 74 < bottom:
        c.text(MX, y0 + 74, "  ·  ".join(bits), 15)

    # every-3-hours strip, only when the panel is tall enough (10.2")
    ys = y0 + 106
    if wx.current is not None and ys + 62 <= bottom:
        steps = [h for h in wx.hours if h.time > wx.current.time and h.time.hour % 3 == 0][:4]
        c.line(MX, ys - 8, 776, ys - 8, w=1)
        colw = (776 - MX) / 4
        for i, h in enumerate(steps):
            cx = MX + colw * (i + 0.5)
            _, k = describe(h.cond)
            c.text(cx, ys, fmt_hour(h.time, clock24), 13, bold=True, anchor="ma")
            draw_icon(c, k, cx, ys + 31, 30, night=not h.is_day)
            c.text(cx, ys + 46, deg(h.temp), 16, bold=True, anchor="ma")
    return c.done()


def lists_page(W: int, H: int, now: dt.datetime, lists: list[tuple[str, list[str] | None]]) -> Image.Image:
    """Checklist columns (e.g. to-do and groceries), one column per list."""
    c = Canvas(W, H)
    bottom = c.LH - 12
    _header(c, "Lists", f"{now:%a %b} {now.day}")
    n = max(1, len(lists))
    gap = 36
    colw = (752 - gap * (n - 1)) / n
    ROW = 30
    for i, (title, items) in enumerate(lists):
        x0 = 24 + i * (colw + gap)
        x1 = x0 + colw
        if i:
            c.line(x0 - gap / 2, 64, x0 - gap / 2, bottom, w=1)
        c.text(x0, 68, c.fit(title.upper(), 18, colw - 50, bold=True), 18, bold=True)
        if items is not None:
            c.text(x1, 71, str(len(items)), 15, anchor="ra")
        c.line(x0, 94, x1, 94, w=1)
        if items is None:
            c.text(x0 + 2, 108, "Unavailable", 18)
            continue
        if not items:
            c.text(x0 + 2, 108, "Nothing here", 18)
            continue
        fit = int((bottom - 104) // ROW)
        shown = items if len(items) <= fit else items[:max(fit - 1, 0)]
        y = 104
        for text in shown:
            c.rect(x0 + 2, y + 5, x0 + 20, y + 23, outline=0, w=2, r=2)
            c.text(x0 + 32, y + 3, c.fit(text, 19, colw - 34), 19)
            y += ROW
        if len(shown) < len(items):
            c.text(x0 + 2, y + 4, f"+ {len(items) - len(shown)} more", 16, bold=True)
    return c.done()


def weather_page(W: int, H: int, now: dt.datetime, wx: Weather | None, location: str = "",
                 *, clock24=False) -> Image.Image:
    if wx is None or wx.current is None:
        return message_page(W, H, "Weather", "Weather data isn't available yet.\nCheck the add-on log and weather entity.")
    c = Canvas(W, H)
    bottom = c.LH - 12
    cur = wx.current
    label, kind = describe(cur.cond)

    _header(c, f"{now:%A} · {fmt_hour(now, clock24)}", "7-day forecast")
    if location:
        c.text(466, 16, c.fit(location, 20, 200), 20, anchor="ra")

    # ---- now (left) ----
    draw_icon(c, kind, 88, 126, 112, night=not cur.is_day)
    c.text(160, 54, deg(cur.temp), 96, bold=True)
    c.text(162, 152, c.fit(label, 26, 300), 26)
    lines = []
    if cur.feels is not None:
        lines.append(f"Feels like {deg(cur.feels)}")
    extra = []
    if cur.pop is not None:
        extra.append(f"Rain {round(cur.pop)}%")
    if cur.wind is not None:
        extra.append(f"Wind {round(cur.wind)} {wx.wind_unit}".strip())
    if extra:
        lines.append("  ·  ".join(extra))
    if wx.sunrise and wx.sunset:
        lines.append(f"Sunrise {fmt_time(wx.sunrise, clock24)}  ·  Sunset {fmt_time(wx.sunset, clock24)}")
    y = 198
    for ln in lines:
        c.text(28, y, ln, 19)
        y += 25

    # ---- next hours strip ----
    c.line(24, 284, 466, 284, w=1)
    nxt = [h for h in wx.hours if h.time > cur.time][:8]
    colw = 442 / 8
    for i, h in enumerate(nxt):
        cx = 24 + colw * (i + 0.5)
        _, k = describe(h.cond)
        c.text(cx, 296, fmt_hour(h.time, clock24), 16, bold=True, anchor="ma")
        draw_icon(c, k, cx, 358, 44, night=not h.is_day)
        c.text(cx, 388, deg(h.temp), 22, bold=True, anchor="ma")
        if h.pop is not None and h.pop >= 10:
            c.text(cx, 420, f"{round(h.pop)}%", 15, anchor="ma")
    if not nxt:
        c.text(24, 300, "Hourly forecast unavailable", 18)

    # ---- week (right) ----
    c.line(480, 64, 480, bottom, w=1)
    days = wx.days[:7]
    if not days:
        c.text(494, 80, "Daily forecast unavailable", 18)
    else:
        top = 62
        rh = (bottom - top) / 7
        for i, d in enumerate(days):
            yc = top + rh * (i + 0.5)
            if i:
                c.line(494, top + rh * i, 776, top + rh * i, w=1)
            name = "Today" if d.date == now.date() else f"{d.date:%a}"
            c.text(494, yc, name, 22, bold=True, anchor="lm")
            _, k = describe(d.cond)
            draw_icon(c, k, 600, yc, 44)
            if d.pop is not None and d.pop >= 20:
                c.text(636, yc, f"{round(d.pop)}%", 15, anchor="lm")
            c.text(722, yc, deg(d.hi), 24, bold=True, anchor="rm")
            if d.lo is not None:
                c.text(776, yc, deg(d.lo), 22, anchor="rm")
    return c.done()
