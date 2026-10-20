"""The week and month views, and the colour each calendar keeps in all three.

All of it is computed from the stored events and today's date, so a stale
payload still draws the right days.
"""

from datetime import date

from dinkydash.board import (CALENDAR_COLORS, MAX_MONTH_CELL, build_month,
                             build_view, build_week, calendar_colors)

CONFIG = {
    "timezone": "Europe/Berlin",
    "calendars": [{"label": "Kallee & Jake"}, {"label": "Family"}],
}


def event(day, title, calendar="Family", time_="09:00", all_day=False):
    return {"title": title, "date": day, "time": None if all_day else time_,
            "all_day": all_day, "start": f"{day}T{time_ or '00:00'}:00+02:00",
            "location": None, "calendar": calendar}


class TestColours:
    def test_each_calendar_gets_its_own_colour_in_listed_order(self):
        assert calendar_colors(CONFIG) == {
            "Kallee & Jake": CALENDAR_COLORS[0], "Family": CALENDAR_COLORS[1]}

    def test_a_shared_label_shares_a_colour(self):
        config = {"calendars": [{"label": "A"}, {"label": "A"}, {"label": "B"}]}
        assert calendar_colors(config) == {"A": CALENDAR_COLORS[0], "B": CALENDAR_COLORS[1]}

    def test_the_same_event_has_the_same_colour_in_every_view(self):
        events = [event("2026-10-20", "Dinner", calendar="Family")]
        payload = {"generated_for_date": "2026-10-20", "events": events}
        config = {**CONFIG, "people": [{"name": "Mia", "date_of_birth": "2017-03-15"}]}
        view = build_view(config, payload, date(2026, 10, 20))
        day = view["events"][0]["color"]
        week = next(d for d in view["week"]["days"] if d["is_today"])["events"][0]["color"]
        month = next(c for w in view["month"]["weeks"] for c in w if c["is_today"])["events"][0]["color"]
        assert day == week == month == CALENDAR_COLORS[1]


class TestWeek:
    def test_a_monday_week_holds_today(self):
        week = build_week([], date(2026, 10, 20), "24h", {}, first_day=0)  # a Tuesday
        assert [d["iso"] for d in week["days"]][0] == "2026-10-19"
        assert week["days"][-1]["iso"] == "2026-10-25"
        assert week["title"] == "19 – 25 October"
        assert [d["is_today"] for d in week["days"]].count(True) == 1

    def test_a_sunday_week_starts_on_sunday(self):
        week = build_week([], date(2026, 10, 20), "24h", {}, first_day=6)
        assert week["days"][0]["iso"] == "2026-10-18"

    def test_a_week_across_a_month_names_both(self):
        week = build_week([], date(2026, 10, 1), "24h", {}, first_day=0)
        assert week["title"] == "28 Sep – 4 Oct"

    def test_events_land_on_their_day(self):
        events = [event("2026-10-22", "Swimming")]
        week = build_week(events, date(2026, 10, 20), "24h", {})
        thursday = next(d for d in week["days"] if d["iso"] == "2026-10-22")
        assert [e["title"] for e in thursday["events"]] == ["Swimming"]


class TestMonth:
    def test_the_grid_is_whole_weeks_around_the_month(self):
        month = build_month([], date(2026, 10, 20), "24h", {}, first_day=0)
        days = [c for w in month["weeks"] for c in w]
        assert len(days) % 7 == 0
        assert days[0]["iso"] == "2026-09-28" and not days[0]["in_month"]
        assert days[-1]["iso"] == "2026-11-01"
        assert sum(c["in_month"] for c in days) == 31
        assert month["title"] == "October 2026"

    def test_a_crowded_day_says_how_many_it_left_out(self):
        events = [event("2026-10-20", f"Thing {i}") for i in range(MAX_MONTH_CELL + 2)]
        month = build_month(events, date(2026, 10, 20), "24h", {})
        today = next(c for w in month["weeks"] for c in w if c["is_today"])
        assert len(today["events"]) == MAX_MONTH_CELL and today["more"] == 2

    def test_times_follow_the_families_clock(self):
        events = [event("2026-10-20", "Dinner", time_="17:45")]
        month = build_month(events, date(2026, 10, 20), "12h", {})
        today = next(c for w in month["weeks"] for c in w if c["is_today"])
        assert today["events"][0]["time"] == "5:45 pm"
