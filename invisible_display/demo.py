"""Synthetic data so the pages can be previewed without Home Assistant."""
from __future__ import annotations

import datetime as dt
import math

from ha import Day, Event, Hour, Weather

LEGEND = [("F", "Family"), ("W", "Work"), ("K", "Kids")]


def events(now: dt.datetime) -> list[Event]:
    tz = now.tzinfo
    d0 = dt.datetime.combine(now.date(), dt.time(0), tz)

    def at(day, h, m=0):
        return d0 + dt.timedelta(days=day, hours=h, minutes=m)

    def timed(day, h, m, mins, title, tag):
        s = at(day, h, m)
        return Event(s, s + dt.timedelta(minutes=mins), title, False, tag)

    def allday(day, title, tag, span=1):
        return Event(at(day, 0), at(day + span, 0), title, True, tag)

    return [
        allday(0, "Soccer tournament", "K"),
        timed(0, 17, 30, 60, "Pick up groceries", "F"),
        timed(0, 19, 0, 90, "Dinner with the neighbors", "F"),
        timed(1, 9, 0, 45, "Dentist appointment", "F"),
        timed(1, 13, 0, 60, "Project sync", "W"),
        timed(1, 16, 30, 60, "Piano lesson", "K"),
        allday(2, "Dad's birthday", "F"),
        timed(2, 10, 0, 30, "Quarterly planning review with a very long title that overflows", "W"),
        timed(3, 18, 0, 120, "School concert", "K"),
        allday(4, "Trip to the coast", "F", span=3),
        timed(5, 8, 30, 30, "Vet check-up", "F"),
        timed(9, 12, 0, 60, "Lunch with Sam", "F"),
    ]


def weather(now: dt.datetime) -> Weather:
    tz = now.tzinfo
    start = dt.datetime.combine(now.date(), dt.time(0), tz)
    pattern = ["sunny", "sunny", "partlycloudy", "cloudy", "rainy", "rainy", "partlycloudy", "lightning-rainy",
               "snowy", "fog", "cloudy", "sunny"]
    hours = []
    for i in range(48):
        t = start + dt.timedelta(hours=i)
        is_day = 7 <= t.hour < 19
        cond = pattern[(i // 3 + (now.day % 3)) % len(pattern)]
        if cond == "sunny" and not is_day:
            cond = "clear-night"
        temp = 58 + 12 * math.sin((t.hour - 9) / 24 * 2 * math.pi)
        hours.append(Hour(t, temp, cond, temp - 3, 10 * (i % 7) if "rain" in cond else 0, 6 + (i % 5), is_day))
    cur = next(h for h in hours if h.time.hour == now.hour)
    conds = ["partlycloudy", "sunny", "rainy", "cloudy", "lightning-rainy", "snowy", "fog"]
    days = [Day(now.date() + dt.timedelta(days=i), conds[i % 7], 72 - i * 2, 51 - i, [10, 0, 80, 30, 60, 90, 20][i])
            for i in range(7)]
    return Weather(cur, hours, days, "mph", dt.time(7, 12), dt.time(18, 31))


LISTS = [
    ("To do", ["Renew car registration", "Call the plumber", "Book flights for the coast trip",
               "Return library books", "Fix the back gate latch", "Order new filters", "Schedule dentist for the kids",
               "Water the plants", "Back up the photo library", "Sign the permission slip"]),
    ("Costco", ["Paper towels", "Rotisserie chicken", "Olive oil", "Coffee beans", "Eggs (5 dozen)", "Frozen berries",
                "Dish soap", "Rice"]),
    ("Non-Costco", ["Milk", "Sourdough bread", "Bananas", "Cheddar", "Spinach", "Oat milk", "Apples", "Greek yogurt"]),
]
