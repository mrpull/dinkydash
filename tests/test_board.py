"""What the dashboard shows, especially on a day the generation failed.

The design claim being tested: when a morning's run fails, the times, turns and
countdowns on the wall are still *today's*. The headline gives way to one
worked out from the day. A stored note stays on the view and is not rendered.
"""

import json
from datetime import date, datetime, timezone

import pytest

from dinkydash.board import build_view, computed_headline
from dinkydash.config import tzinfo_for

CONFIG = {
    "family_name": "The Wilsons",
    "timezone": "Europe/Berlin",  # set up: a real family's dashboard, not the starter
    "theme": "light",
    "people": [{"name": "Mia", "date_of_birth": "2017-03-15"}],
    "recurring": [{"title": "Set the table", "emoji": "🍽", "choices": ["Mia", "Theo"]}],
    "special_dates": [{"title": "Christmas", "emoji": "🎄", "date": "12/25"}],
}

TODAY = date(2026, 9, 3)


def event(day, time_, title, all_day=False):
    return {
        "title": title, "date": day, "time": None if all_day else time_,
        "all_day": all_day, "start": f"{day}T{time_ or '00:00'}:00+02:00",
        "location": None, "calendar": "Family",
    }


def payload(for_date, events=None, headline="Big morning", note="An octopus fact"):
    return {
        "generated_for_date": for_date,
        "generated_at": f"{for_date}T04:32:00+02:00",
        "headline": headline,
        "note": note,
        "note_kind": "fact",
        "events": events or [],
    }


class TestComputedHeadline:
    def test_nothing_on(self):
        assert computed_headline([]) == "Nothing booked in today."

    def test_one_thing(self):
        assert computed_headline([event("2026-09-03", "08:20", "School run")]) == \
            "1 thing on today, starting at 08:20."

    def test_several_things_lead_with_the_first_time(self):
        events = [event("2026-09-03", "08:20", "School run"),
                  event("2026-09-03", "15:45", "Swimming")]
        assert computed_headline(events) == "2 things on today, starting at 08:20."

    def test_all_day_only_has_no_start_time(self):
        events = [event("2026-09-03", None, "Inset day", all_day=True)]
        assert computed_headline(events) == "1 thing on today."


class TestFreshBoard:
    def test_shows_the_generated_headline_and_note(self):
        view = build_view(CONFIG, payload("2026-09-03"), TODAY)
        assert view["state"] == "ready"
        assert view["stale"] is False
        assert view["headline"] == "Big morning"
        assert view["note"] == "An octopus fact"

    def test_shows_only_todays_events_in_order(self):
        data = payload("2026-09-03", [
            event("2026-09-04", "09:00", "Tomorrow"),
            event("2026-09-03", "08:20", "School run"),
        ])
        view = build_view(CONFIG, data, TODAY)
        assert [e["title"] for e in view["events"]] == ["School run"]

    def test_recomputes_chores_and_countdowns_from_config(self):
        view = build_view(CONFIG, payload("2026-09-03"), TODAY)
        assert view["chores"][0]["assigned_to"] in {"Mia", "Theo"}
        assert view["countdowns"][0]["title"] == "Christmas"


class TestStaleBoard:
    """A payload from yesterday, still on the wall this morning."""

    data = payload("2026-09-02", [
        event("2026-09-03", "08:20", "School run"),
        event("2026-09-03", "15:45", "Swimming"),
    ])

    def test_is_flagged_stale(self):
        view = build_view(CONFIG, self.data, TODAY)
        assert view["stale"] is True
        assert view["state"] == "stale"
        assert view["stale_days"] == 1

    def test_agenda_is_still_todays(self):
        # Yesterday's fetch reached 14 days ahead, so today's events are in it.
        view = build_view(CONFIG, self.data, TODAY)
        assert [e["title"] for e in view["events"]] == ["School run", "Swimming"]

    def test_chores_are_todays_not_yesterdays(self):
        view = build_view(CONFIG, self.data, TODAY)
        fresh = build_view(CONFIG, payload("2026-09-03"), TODAY)
        assert view["chores"] == fresh["chores"]

    def test_countdowns_are_todays(self):
        view = build_view(CONFIG, self.data, TODAY)
        assert view["countdowns"][0]["days"] == 113  # Christmas, from 3 September

    def test_the_stale_headline_gives_way_to_a_computed_one(self):
        # A day-old headline can be actively wrong, so it is replaced.
        view = build_view(CONFIG, self.data, TODAY)
        assert view["headline"] == "2 things on today, starting at 08:20."

    def test_the_note_survives_because_it_is_harmless(self):
        view = build_view(CONFIG, self.data, TODAY)
        assert view["note"] == "An octopus fact"


class TestTheBannerWaitsUntilTheBriefIsDue:
    """Stale is not the same as late, and only late may show the banner.

    A dashboard goes stale at local midnight; the brief is not owed until
    `brief_time`, 06:00 by default. Between the two, an amber
    "today’s note hasn’t arrived" reports a failure that has not happened —
    all night, on a screen in a kitchen. The words are still handled as stale
    throughout, because yesterday’s headline is wrong from midnight on.
    """

    data = payload("2026-09-02", [event("2026-09-03", "08:20", "School run")])

    def view_at(self, hour, minute=0, config=CONFIG, data=None):
        """The dashboard as it reads at that hour on the family’s own clock."""
        moment = datetime(2026, 9, 3, hour, minute, tzinfo=tzinfo_for(config))
        return build_view(config, self.data if data is None else data,
                          moment.date(), now=moment)

    def test_the_small_hours_claim_nothing(self):
        view = self.view_at(1, 30)
        assert view["stale"] is True      # the line on the wall is yesterday’s
        assert view["overdue"] is False   # but nothing was owed yet

    def test_after_the_brief_time_it_is_late(self):
        assert self.view_at(6, 5)["overdue"] is True

    def test_the_hour_is_the_one_the_family_chose(self):
        late = dict(CONFIG, brief_time="08:00")
        assert self.view_at(7, 0, config=late)["overdue"] is False
        assert self.view_at(8, 30, config=late)["overdue"] is True

    def test_it_is_the_family_clock_not_the_server_clock(self):
        # 23:30 UTC is 01:30 in Berlin: their night, not their morning.
        moment = datetime(2026, 9, 2, 23, 30, tzinfo=timezone.utc)
        view = build_view(CONFIG, self.data, date(2026, 9, 3), now=moment)
        assert view["overdue"] is False

    def test_more_than_a_day_behind_is_late_at_any_hour(self):
        old = payload("2026-08-30", [event("2026-09-03", "08:20", "School run")])
        assert self.view_at(1, 30, data=old)["overdue"] is True

    def test_an_agenda_with_no_brief_at_all_is_late_at_any_hour(self):
        # Nothing to be a day behind from, so there is no grace to give.
        agenda = {"events": [event("2026-09-03", "08:20", "School run")],
                  "calendars_fetched_at": "2026-09-03T00:10:00+00:00"}
        assert self.view_at(1, 30, data=agenda)["overdue"] is True

    def test_todays_dashboard_is_never_late(self):
        assert self.view_at(1, 30, data=payload("2026-09-03"))["overdue"] is False

    def test_the_words_are_still_yesterdays_overnight(self):
        # The banner going quiet must not put yesterday’s headline back up:
        # "Ines starts nursery today" was wrong the moment the day changed.
        view = self.view_at(1, 30)
        assert view["headline"] == "1 thing on today, starting at 08:20."
        assert view["note"] == "An octopus fact"
        assert view["stale_days"] == 1

    def test_a_caller_with_no_clock_counts_every_stale_dashboard_as_late(self):
        assert build_view(CONFIG, self.data, TODAY)["overdue"] is True


class TestTomorrow:
    """Tomorrow tops up the agenda, but only with the rows today did not use."""

    def test_a_quiet_today_is_topped_up_from_tomorrow(self):
        data = payload("2026-09-03", [
            event("2026-09-04", "09:00", "Term starts"),
            event("2026-09-04", "14:15", "Dentist"),
        ])
        view = build_view(CONFIG, data, TODAY)
        assert view["events"] == []
        assert [e["title"] for e in view["tomorrow"]] == ["Term starts", "Dentist"]

    def test_today_takes_the_rows_first(self):
        data = payload("2026-09-03", [
            event("2026-09-03", "08:20", "School run"),
            event("2026-09-03", "15:45", "Swimming"),
            event("2026-09-03", "18:00", "Football"),
            event("2026-09-04", "09:00", "Term starts"),
            event("2026-09-04", "14:15", "Dentist"),
            event("2026-09-04", "16:30", "Piano"),
        ])
        view = build_view(CONFIG, data, TODAY)
        assert len(view["events"]) == 3
        # Two rows left in the budget of five, so only two of tomorrow's three.
        assert [e["title"] for e in view["tomorrow"]] == ["Term starts", "Dentist"]

    def test_a_full_today_crowds_tomorrow_out(self):
        data = payload("2026-09-03", [
            event("2026-09-03", f"{hour:02d}:00", f"Thing {hour}")
            for hour in range(8, 13)
        ] + [event("2026-09-04", "09:00", "Term starts")])
        view = build_view(CONFIG, data, TODAY)
        assert len(view["events"]) == 5
        assert view["tomorrow"] == []

    def test_tomorrow_stays_a_footnote_on_a_completely_empty_day(self):
        # Nothing today and a packed tomorrow still reads as today's agenda.
        data = payload("2026-09-03", [
            event("2026-09-04", f"{hour:02d}:00", f"Thing {hour}")
            for hour in range(8, 13)
        ])
        view = build_view(CONFIG, data, TODAY)
        assert len(view["tomorrow"]) == 3

    def test_the_day_after_tomorrow_is_not_included(self):
        data = payload("2026-09-03", [
            event("2026-09-04", "09:00", "Term starts"),
            event("2026-09-05", "09:00", "Too far off"),
        ])
        view = build_view(CONFIG, data, TODAY)
        assert [e["title"] for e in view["tomorrow"]] == ["Term starts"]

    def test_a_stale_payload_still_knows_tomorrow(self):
        # Yesterday's fetch reached 14 days ahead, so tomorrow is in it too.
        data = payload("2026-09-02", [event("2026-09-04", "09:00", "Term starts")])
        view = build_view(CONFIG, data, TODAY)
        assert view["stale"] is True
        assert [e["title"] for e in view["tomorrow"]] == ["Term starts"]


class TestEmptyStates:
    def test_no_payload_at_all_still_shows_the_dashboard(self):
        view = build_view(CONFIG, None, TODAY)
        assert view["state"] == "stale"
        assert view["events"] == []
        assert view["tomorrow"] == []
        # Chores and countdowns still work — they never needed the model.
        assert view["chores"]
        assert view["countdowns"]

    def test_a_quiet_day_keeps_everything_else(self):
        view = build_view(CONFIG, payload("2026-09-03"), TODAY)
        assert view["events"] == []
        assert view["state"] == "ready"
        assert view["chores"]

    def test_an_agenda_with_no_brief_yet_still_shows_the_day(self):
        # A `--tick` that refreshed the calendars before the brief leaves a
        # payload with events and no words — after a first brief that failed,
        # say. For a set-up family the right answer is today's agenda under the
        # amber banner rather than the first-run screen.
        agenda = {"events": [event("2026-09-03", "08:20", "School run")],
                  "calendars_fetched_at": "2026-09-03T03:00:00+00:00"}
        view = build_view(CONFIG, agenda, TODAY)
        assert view["state"] == "stale"
        assert [e["title"] for e in view["events"]] == ["School run"]
        assert view["headline"] == "1 thing on today, starting at 08:20."
        assert view["note"] == ""
        assert view["stale_days"] is None


class TestStillSettingUp:
    """A family that is not set up yet gets the waiting screen, and it says why.

    `config.is_set_up` is false while the household is still the invented
    starter or the timezone is unset. Nothing is being written for such a
    family (`schedule.brief_due`), so the dashboard must not say "writing your
    first dashboard" — and it must not show the invented household's turns under
    an amber banner either.
    """

    STARTER = {**CONFIG, "timezone": "UTC"}

    def test_no_payload_is_waiting_and_says_it_is_not_set_up(self):
        view = build_view(self.STARTER, None, TODAY)
        assert view["state"] == "waiting"
        assert view["set_up"] is False

    def test_a_set_up_family_with_no_payload_sees_its_dashboard_not_a_waiting_screen(self):
        view = build_view(CONFIG, None, TODAY)
        assert view["state"] != "waiting"
        assert view["set_up"] is True
        assert view["reload_seconds"] == 60  # nothing stored yet: look again soon

    def test_an_agenda_with_no_brief_is_still_the_waiting_screen(self):
        # The calendars have been fetched — that half is free and runs
        # regardless — but no brief was attempted, so no amber banner.
        agenda = {"events": [event("2026-09-03", "08:20", "School run")],
                  "calendars_fetched_at": "2026-09-03T03:00:00+00:00"}
        view = build_view(self.STARTER, agenda, TODAY)
        assert view["state"] == "waiting"
        assert view["events"] == []

    def test_an_invented_household_is_not_set_up_whatever_the_timezone(self):
        from dinkydash import config as config_module
        starter = config_module.starter_config()
        starter["timezone"] = "Europe/Berlin"
        assert build_view(starter, None, TODAY)["set_up"] is False

    def test_a_written_brief_renders_as_usual(self):
        # A brief that already exists is shown, set up or not: the family
        # that signed up before this rule still has yesterday's dashboard.
        view = build_view(self.STARTER, payload("2026-09-03"), TODAY)
        assert view["state"] == "ready"


class TestTheme:
    def test_dark_is_carried_through(self):
        view = build_view(dict(CONFIG, theme="dark"), payload("2026-09-03"), TODAY)
        assert view["theme"] == "dark"

    def test_an_unknown_theme_falls_back_to_light(self):
        view = build_view(dict(CONFIG, theme="neon"), payload("2026-09-03"), TODAY)
        assert view["theme"] == "light"


class TestReloadInterval:
    """The dashboard reloads itself on a timer, derived from `refresh_minutes`.

    Five minutes is the ceiling, so the four longer intervals all render the
    same value the template used to hard-code. Only a shorter one moves it.
    """

    def test_the_default_is_five_minutes(self):
        assert build_view(CONFIG, payload("2026-09-03"), TODAY)["reload_seconds"] == 300

    def test_a_longer_fetch_interval_does_not_slow_the_reload(self):
        config = dict(CONFIG, refresh_minutes=1440)
        assert build_view(config, payload("2026-09-03"), TODAY)["reload_seconds"] == 300

    def test_a_quarter_hourly_fetch_still_reloads_every_five_minutes(self):
        config = dict(CONFIG, refresh_minutes=15)
        assert build_view(config, payload("2026-09-03"), TODAY)["reload_seconds"] == 300

    def test_only_an_interval_under_five_minutes_pulls_it_down(self):
        config = dict(CONFIG, refresh_minutes=2)
        assert build_view(config, payload("2026-09-03"), TODAY)["reload_seconds"] == 120

    def test_the_waiting_screen_asks_more_often(self):
        # Nothing to show yet, so fill the screen in a minute rather than five.
        assert build_view(CONFIG, None, TODAY)["reload_seconds"] == 60

    def test_an_unreadable_interval_falls_back_to_five_minutes(self):
        config = dict(CONFIG, refresh_minutes="hourly")
        assert build_view(config, payload("2026-09-03"), TODAY)["reload_seconds"] == 300


class TestAFamilyThatIsSetUpAlwaysSeesItsDashboard:
    """Nothing stored yet is a dashboard with an empty agenda, not a screen that says wait.

    A stale or empty calendar is better on the wall than no calendar, so only the
    starter household (below) is held back. `board.html` is rendered from the
    same file in both modes, so this is true of a Raspberry Pi and of a screen in
    a kitchen.
    """

    @pytest.fixture
    def page(self, tmp_path):
        from dinkydash.store import FileStore
        from tests.conftest import client_for
        from web import create_app

        path = tmp_path / "config.yaml"
        path.write_text('family_name: "The Wilsons"\ntimezone: "Europe/Berlin"\n')
        client = client_for(create_app(FileStore(path)))
        return client.get("/").get_data(as_text=True)

    def test_it_is_the_dashboard(self, page):
        assert 'class="board"' in page and 'data-view-set="month"' in page

    def test_it_says_nothing_about_waiting_or_writing(self, page):
        for words in ("first dashboard", "Fetching", "Writing", "Nearly there"):
            assert words not in page

    def test_it_names_no_command_and_no_button(self, page):
        assert "generate.py" not in page
        assert "Write first daily message" not in page

    def test_a_family_still_setting_up_is_told_that_instead(self, tmp_path):
        # The example file's household is invented, so nothing is being
        # written and the screen must not claim it is.
        from dinkydash.store import FileStore
        from tests.conftest import client_for
        from web import create_app

        path = tmp_path / "config.yaml"
        path.write_text('family_name: "The Wilsons"\ntimezone: "Europe/Berlin"\n'
                        'people:\n  - name: "Mia"\n    date_of_birth: "2017-03-15"\n'
                        '    invented: true\n')
        page = client_for(create_app(FileStore(path))).get("/").get_data(as_text=True)
        assert "Nearly there" in page
        assert "first dashboard" not in page.split("Nearly there")[0]
        assert "Writing" not in page


class TestTheBannerOnTheDashboard:
    """The one part of this a family reads, so the page itself is checked.

    Rendered through the real route, because that is what decides which moment
    `build_view` is given — a dashboard that knows it is 01:30 and a template
    that shows the banner anyway would pass every test above.
    """

    BANNER = "headline hasn&rsquo;t arrived"

    def page_at(self, tmp_path, monkeypatch, hour, minute=0, data=None):
        from dinkydash import config as config_module
        from dinkydash.store import FileStore
        from tests.conftest import client_for
        from web import create_app

        path = tmp_path / "config.yaml"
        path.write_text('family_name: "The Wilsons"\ntimezone: "Europe/Berlin"\n')
        (tmp_path / "dashboard_data.json").write_text(json.dumps(data or
            payload("2026-09-02", [event("2026-09-03", "08:20", "School run")])))
        moment = datetime(2026, 9, 3, hour, minute,
                          tzinfo=tzinfo_for({"timezone": "Europe/Berlin"}))
        monkeypatch.setattr(config_module, "now_for", lambda _: moment)
        return client_for(create_app(FileStore(path))).get("/").get_data(as_text=True)

    def test_the_night_is_quiet(self, tmp_path, monkeypatch):
        page = self.page_at(tmp_path, monkeypatch, 1, 30)
        assert self.BANNER not in page
        assert "An octopus fact" not in page

    def test_the_morning_shows_no_headline_and_no_banner_about_one(self, tmp_path, monkeypatch):
        page = self.page_at(tmp_path, monkeypatch, 7, 0)
        assert self.BANNER not in page
        assert "worked out from the day" not in page
        assert 'class="headline' not in page
        assert "An octopus fact" not in page
        assert "Yesterday&rsquo;s note" not in page

    def test_an_older_brief_still_renders_without_its_note(self, tmp_path, monkeypatch):
        old = payload("2026-08-30", [event("2026-09-03", "08:20", "School run")])
        page = self.page_at(tmp_path, monkeypatch, 7, 0, data=old)
        assert "School run" in page
        assert "An octopus fact" not in page
        assert "Older note" not in page
        assert "Yesterday" not in page

    def test_an_agenda_with_no_brief_raises_no_banner(self, tmp_path, monkeypatch):
        agenda = {"events": [event("2026-09-03", "08:20", "School run")],
                  "calendars_fetched_at": "2026-09-03T00:10:00+00:00"}
        page = self.page_at(tmp_path, monkeypatch, 7, 0, data=agenda)
        assert self.BANNER not in page
        assert "older one below" not in page


class TestTheFactOfTheDayIsNotShown:
    """A stored note must not come back onto the dashboard.

    The brief can still carry one — an older file, an export, a row written
    before the dashboard stopped asking for it — and the page has to render
    the rest of that brief without printing the note.
    """

    def test_a_fresh_dashboard_drops_the_note(self, tmp_path, monkeypatch):
        from dinkydash import config as config_module
        from dinkydash.store import FileStore
        from tests.conftest import client_for
        from web import create_app

        path = tmp_path / "config.yaml"
        path.write_text(
            'family_name: "The Wilsons"\ntimezone: "Europe/Berlin"\n'
            'people:\n  - name: "Mia"\n    date_of_birth: "2017-03-15"\n'
            'recurring:\n  - title: "Set the table"\n    emoji: "🍽"\n'
            '    choices: ["Mia"]\n'
        )
        (tmp_path / "dashboard_data.json").write_text(json.dumps(payload(
            "2026-09-03",
            [event("2026-09-03", "08:20",
                   "A very long appointment title that has to wrap on a narrow column")],
            headline="Big morning",
            note="Did you know? Violins are made from over 70 separate pieces of wood.",
        )))
        moment = datetime(2026, 9, 3, 9, 0,
                          tzinfo=tzinfo_for({"timezone": "Europe/Berlin"}))
        monkeypatch.setattr(config_module, "now_for", lambda _: moment)
        page = client_for(create_app(FileStore(path))).get("/").get_data(as_text=True)
        assert "Big morning" not in page
        assert "A very long appointment title that has to wrap" in page
        assert "Set the table" in page
        assert "Did you know?" not in page
        assert "Violins are made" not in page
        assert 'class="note' not in page
        # The title is allowed to wrap; it is not clipped in the markup.
        assert "overflow-wrap: break-word" in page


CALENDARS = {"calendars": [{"label": "Kallee & Jake"}, {"label": "Family"}]}


def on(day, title, calendar, time_="09:00", all_day=False):
    return {**event(day, time_, title, all_day), "calendar": calendar}


class TestCalendarColours:
    """An event looks the same in the day, week and month views."""

    def test_colours_follow_the_order_the_calendars_are_listed_in(self):
        from dinkydash.board import calendar_colors
        assert calendar_colors(CALENDARS) == {"Kallee & Jake": "blue", "Family": "green"}

    def test_two_entries_sharing_a_label_share_a_colour(self):
        from dinkydash.board import calendar_colors
        both = {"calendars": [{"label": "A"}, {"label": "A"}, {"label": "B"}]}
        assert calendar_colors(both) == {"A": "blue", "B": "green"}

    def test_every_view_gives_an_event_the_same_colour(self):
        events = [on("2026-09-03", "Dinner", "Family")]
        view = build_view({**CONFIG, **CALENDARS}, payload("2026-09-03", events), TODAY)
        assert view["events"][0]["color"] == "green"
        assert view["week"]["days"][3]["events"][0]["color"] == "green"
        thursday = [c for w in view["month"]["weeks"] for c in w if c["iso"] == "2026-09-03"][0]
        assert thursday["events"][0]["color"] == "green"

    def test_a_calendar_the_config_no_longer_lists_gets_the_first_colour(self):
        events = [on("2026-09-03", "Old", "Deleted calendar")]
        view = build_view({**CONFIG, **CALENDARS}, payload("2026-09-03", events), TODAY)
        assert view["events"][0]["color"] == "blue"


class TestWeekAndMonth:
    def test_the_week_runs_monday_to_sunday_by_default(self):
        view = build_view(CONFIG, payload("2026-09-03"), TODAY)  # a Thursday
        days = view["week"]["days"]
        assert [d["iso"] for d in days][0] == "2026-08-31"
        assert [d["iso"] for d in days][-1] == "2026-09-06"
        assert [d["is_today"] for d in days].count(True) == 1
        assert view["week"]["title"] == "31 Aug – 6 Sep"

    def test_the_week_can_start_on_sunday(self):
        view = build_view({**CONFIG, "week_start": "sunday"}, payload("2026-09-03"), TODAY)
        assert view["week"]["days"][0]["iso"] == "2026-08-30"

    def test_the_month_is_whole_weeks_with_the_neighbouring_days_marked(self):
        view = build_view(CONFIG, payload("2026-09-03"), TODAY)
        cells = [c for week in view["month"]["weeks"] for c in week]
        assert view["month"]["title"] == "September 2026"
        assert len(cells) % 7 == 0
        assert cells[0]["iso"] == "2026-08-31" and not cells[0]["in_month"]
        assert sum(c["in_month"] for c in cells) == 30

    def test_a_crowded_day_says_how_many_more(self):
        events = [on("2026-09-03", f"Thing {i}", "Family", f"{8 + i:02d}:00") for i in range(8)]
        view = build_view(CONFIG, payload("2026-09-03", events), TODAY)
        cell = [c for w in view["month"]["weeks"] for c in w if c["iso"] == "2026-09-03"][0]
        assert len(cell["events"]) == 5 and cell["more"] == 3

    def test_events_from_before_today_reach_the_month(self):
        events = [on("2026-09-01", "Earlier this week", "Family")]
        view = build_view(CONFIG, payload("2026-09-03", events), TODAY)
        cell = [c for w in view["month"]["weeks"] for c in w if c["iso"] == "2026-09-01"][0]
        assert [e["title"] for e in cell["events"]] == ["Earlier this week"]


class TestTheSidebarOnTheDashboard:
    def page(self, tmp_path, monkeypatch):
        from dinkydash import config as config_module
        from dinkydash.store import FileStore
        from tests.conftest import client_for
        from web import create_app

        path = tmp_path / "config.yaml"
        path.write_text('family_name: "The Wilsons"\ntimezone: "Europe/Berlin"\n'
                        'calendars:\n  - label: "Family"\n    url: "https://example.invalid/x.ics"\n')
        (tmp_path / "dashboard_data.json").write_text(json.dumps(payload(
            "2026-09-03", [on("2026-09-03", "Dinner", "Family")])))
        moment = datetime(2026, 9, 3, 10, tzinfo=tzinfo_for({"timezone": "Europe/Berlin"}))
        monkeypatch.setattr(config_module, "now_for", lambda _: moment)
        return client_for(create_app(FileStore(path))).get("/").get_data(as_text=True)

    def test_all_three_views_and_the_theme_toggle_are_offered(self, tmp_path, monkeypatch):
        page = self.page(tmp_path, monkeypatch)
        for name in ("day", "week", "month"):
            assert f'data-view-set="{name}"' in page
        assert "data-theme-toggle" in page
        assert 'class="view-week"' in page and 'class="view-month"' in page

    def test_the_default_is_the_day_view_so_a_page_without_script_still_reads(self, tmp_path, monkeypatch):
        assert 'data-view="day"' in self.page(tmp_path, monkeypatch)

    def test_the_legend_names_each_calendar_with_its_colour(self, tmp_path, monkeypatch):
        page = self.page(tmp_path, monkeypatch)
        assert 'legend-item cal-blue' in page and "Family" in page


class TestFiveDayWeek:
    def test_it_is_monday_to_friday(self):
        view = build_view(CONFIG, payload("2026-09-03"), TODAY)  # a Thursday
        days = view["week5"]["days"]
        assert [d["iso"] for d in days] == ["2026-08-31", "2026-09-01", "2026-09-02",
                                            "2026-09-03", "2026-09-04"]
        assert view["week5"]["title"] == "31 Aug – 4 Sep"
        assert view["week"]["days"][-1]["iso"] == "2026-09-06"  # the 7-day week is untouched

    def test_a_sunday_start_still_gives_monday_to_friday(self):
        view = build_view({**CONFIG, "week_start": "sunday"}, payload("2026-09-03"), TODAY)
        assert [d["weekday"] for d in view["week5"]["days"]] == ["Mon", "Tue", "Wed", "Thu", "Fri"]

    def test_events_carry_the_same_colour_as_the_seven_day_week(self):
        events = [on("2026-09-03", "Dinner", "Family")]
        view = build_view({**CONFIG, **CALENDARS}, payload("2026-09-03", events), TODAY)
        assert view["week5"]["days"][3]["events"][0]["color"] == "green"


class TestMonthChipsHaveNoTimes:
    def page(self, tmp_path, monkeypatch):
        return TestTheSidebarOnTheDashboard().page(tmp_path, monkeypatch)

    def test_the_month_shows_titles_only_and_the_week_keeps_times(self, tmp_path, monkeypatch):
        page = self.page(tmp_path, monkeypatch)
        month = page[page.index('class="view-month"'):]
        week = page[page.index('data-panel="week"'):page.index('class="view-month"')]
        assert "Dinner" in month and 'class="chip-time"' not in month
        assert 'class="chip-time"' in week

    def test_both_week_views_are_offered(self, tmp_path, monkeypatch):
        page = self.page(tmp_path, monkeypatch)
        assert 'data-view-set="week5"' in page and 'data-view-set="week"' in page
        assert 'data-panel="week5"' in page


class TestFourWeeks:
    def test_the_top_row_is_this_week_and_three_more_follow(self):
        view = build_view(CONFIG, payload("2026-09-03"), TODAY)  # a Thursday
        rolling = view["rolling"]
        assert len(rolling["weeks"]) == 4
        assert rolling["weeks"][0][0]["iso"] == "2026-08-31"  # that week's Monday
        assert rolling["weeks"][-1][-1]["iso"] == "2026-09-27"
        assert rolling["title"] == "31 Aug – 27 Sep"
        assert [c["is_today"] for w in rolling["weeks"] for c in w].count(True) == 1

    def test_the_first_of_a_month_carries_its_name(self):
        view = build_view(CONFIG, payload("2026-09-03"), TODAY)
        cells = {c["iso"]: c for w in view["rolling"]["weeks"] for c in w}
        assert cells["2026-09-01"]["label"] == "Sep 1"
        assert cells["2026-09-02"]["label"] is None

    def test_events_are_coloured_like_every_other_view(self):
        events = [on("2026-09-10", "Dinner", "Family")]
        view = build_view({**CONFIG, **CALENDARS}, payload("2026-09-03", events), TODAY)
        cell = {c["iso"]: c for w in view["rolling"]["weeks"] for c in w}["2026-09-10"]
        assert cell["events"][0]["color"] == "green"

    def test_it_follows_the_sunday_start(self):
        view = build_view({**CONFIG, "week_start": "sunday"}, payload("2026-09-03"), TODAY)
        assert view["rolling"]["weeks"][0][0]["iso"] == "2026-08-30"

    def test_the_page_offers_it_with_titles_only(self, tmp_path, monkeypatch):
        page = TestTheSidebarOnTheDashboard().page(tmp_path, monkeypatch)
        assert 'data-view-set="rolling"' in page and 'data-panel="rolling"' in page
        rolling = page[page.index('<section class="view-month" data-panel="rolling"'):]
        assert 'class="chip-time"' not in rolling


class TestDayDetails:
    """What the day modal shows: every event on a day, not the few a cell has room for."""

    def view(self, events, config=None):
        return build_view({**CONFIG, **CALENDARS, **(config or {})}, payload("2026-09-03", events), TODAY)

    def detail(self, view, iso):
        return next(d for d in view["details"] if d["iso"] == iso)

    def test_a_crowded_day_keeps_every_event_that_its_cell_drops(self):
        events = [on("2026-09-03", f"Thing {i}", "Family", f"{8 + i:02d}:00") for i in range(9)]
        view = self.view(events)
        cell = [c for w in view["month"]["weeks"] for c in w if c["iso"] == "2026-09-03"][0]
        assert len(cell["events"]) < 9
        assert [e["title"] for e in self.detail(view, "2026-09-03")["events"]] == [f"Thing {i}" for i in range(9)]

    def test_all_day_events_come_first_and_colours_match_the_grids(self):
        events = [on("2026-09-03", "Dinner", "Family", "18:00"),
                  on("2026-09-03", "Holiday", "Kallee & Jake", None, all_day=True)]
        day = self.detail(self.view(events), "2026-09-03")
        assert [(e["title"], e["color"]) for e in day["events"]] == [("Holiday", "blue"), ("Dinner", "green")]

    def test_times_follow_the_familys_clock(self):
        events = [on("2026-09-03", "Dinner", "Family", "17:45")]
        day = self.detail(self.view(events, {"clock": "12h"}), "2026-09-03")
        assert day["events"][0]["time"] == "5:45 pm"

    def test_every_day_a_grid_can_show_has_a_detail(self):
        view = self.view([])
        dates = {c["iso"] for g in (view["month"], view["rolling"]) for w in g["weeks"] for c in w}
        dates |= {d["iso"] for d in view["week"]["days"]}
        assert dates <= {d["iso"] for d in view["details"]}
        assert self.detail(view, "2026-09-03")["heading"] == "Thursday, 3 September"

    def test_an_empty_day_still_has_a_detail(self):
        assert self.detail(self.view([]), "2026-09-04")["events"] == []


class TestTheDayModalOnTheDashboard:
    def page(self, tmp_path, monkeypatch, title="Dinner"):
        from dinkydash import config as config_module
        from dinkydash.store import FileStore
        from tests.conftest import client_for
        from web import create_app

        path = tmp_path / "config.yaml"
        path.write_text('family_name: "The Wilsons"\ntimezone: "Europe/Berlin"\n'
                        'calendars:\n  - label: "Family"\n    url: "https://example.invalid/x.ics"\n')
        (tmp_path / "dashboard_data.json").write_text(json.dumps(payload(
            "2026-09-03", [on("2026-09-03", title, "Family")])))
        moment = datetime(2026, 9, 3, 10, tzinfo=tzinfo_for({"timezone": "Europe/Berlin"}))
        monkeypatch.setattr(config_module, "now_for", lambda _: moment)
        return client_for(create_app(FileStore(path))).get("/").get_data(as_text=True)

    def test_week_and_month_days_open_it_and_the_agenda_does_not(self, tmp_path, monkeypatch):
        page = self.page(tmp_path, monkeypatch)
        agenda = page[page.index('<div class="board">'):page.index('<section class="view-week"')]
        assert 'data-date=' not in agenda
        assert page.count('class="month-cell') >= 28 and 'class="week-day' in page
        assert 'role="button" tabindex="0"' in page

    def test_the_modal_and_its_day_store_are_in_the_page_and_hidden(self, tmp_path, monkeypatch):
        page = self.page(tmp_path, monkeypatch)
        assert '<div class="day-modal" hidden>' in page
        assert '<div class="day-store" hidden>' in page
        assert 'data-heading="Thursday, 3 September"' in page

    def test_an_event_title_is_escaped_in_the_modal_too(self, tmp_path, monkeypatch):
        page = self.page(tmp_path, monkeypatch, title="<script>alert(1)</script>")
        store = page[page.index('class="day-store"'):page.index('class="day-modal"')]
        assert "<script>alert(1)</script>" not in store
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in store


class TestFirstRunWithHeadlinesOff:
    """With `ai_headline: false` nothing is written, so nothing may say it is."""

    def client(self, tmp_path, flag="false"):
        from dinkydash.store import FileStore
        from tests.conftest import client_for
        from web import create_app

        tmp_path.mkdir(exist_ok=True)
        path = tmp_path / "config.yaml"
        path.write_text('family_name: "The Wilsons"\ntimezone: "Europe/Berlin"\n'
                        f'ai_headline: {flag}\n')
        return client_for(create_app(FileStore(path)))

    def test_the_dashboard_shows_with_nothing_stored_whatever_the_setting(self, tmp_path):
        for flag in ("false", "true"):
            page = self.client(tmp_path / flag, flag).get("/").get_data(as_text=True)
            assert 'class="board"' in page
            assert "Fetching" not in page and "Writing" not in page

    def test_the_settings_page_offers_a_refresh_rather_than_a_write_button(self, tmp_path):
        page = self.client(tmp_path).get("/settings/").get_data(as_text=True)
        assert "Refresh calendars" in page
        assert "Write first daily message" not in page

    def status(self, tmp_path, config, payload):
        from dinkydash.store import FileStore
        from web import create_app
        from web.setup import status

        path = tmp_path / "config.yaml"
        path.write_text('timezone: "Europe/Berlin"\n')
        with create_app(FileStore(path)).test_request_context("/settings/"):
            return status(config, payload)

    def test_one_fetch_ends_set_up_mode_and_a_headline_is_not_needed(self, tmp_path):
        config = {"timezone": "Europe/Berlin", "ai_headline": False, "people": []}
        assert self.status(tmp_path, config, None)["in_progress"] is True
        fetched = {"calendars_fetched_at": "2026-09-03T08:00:00+00:00"}
        assert self.status(tmp_path, config, fetched)["in_progress"] is False

    def test_with_headlines_on_the_fetch_alone_does_not_end_it(self, tmp_path):
        config = {"timezone": "Europe/Berlin", "people": []}
        fetched = {"calendars_fetched_at": "2026-09-03T08:00:00+00:00"}
        assert self.status(tmp_path, config, fetched)["in_progress"] is True
