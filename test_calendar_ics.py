"""Tests for the screening calendar file and the endpoint that serves it.

    python test_calendar_ics.py
    python test_calendar_ics.py --url https://on-cinema-now.fly.dev

Ported from frontend/tests/calendar.test.ts when generation moved to the
server. The format assertions are the same ones, for the same reason: iCalendar
fails silently and late. A file with an unescaped comma, an unfolded long line
or LF endings is accepted by one calendar app and rejected without explanation
by another, and the person finds out when the event is not there.

What the move added is the second half of this file. The endpoint takes ids and
reads every field of the event from the database, so the headers and the
refusal to accept caller-supplied text are now part of the contract:

  * text/calendar with an INLINE disposition. attachment would force a download,
    which is the behaviour this whole change exists to stop.
  * Ids in, nothing out. A caller chooses WHICH screening, never what the file
    says about it, so an .ics -- a line-based format full of separators -- can
    never be assembled from somebody's query string.
"""

import argparse
import re
import sys
from datetime import datetime, timezone

import calendar_ics

passed = 0
failures: list[str] = []


def check(label: str, condition: bool) -> None:
    global passed
    if condition:
        passed += 1
    else:
        failures.append(label)


def eq(label: str, actual, expected) -> None:
    global passed
    if actual == expected:
        passed += 1
    else:
        failures.append(f"{label}\n    expected {expected!r}\n    actual   {actual!r}")


BASE = dict(
    film_title="האודיסאה",
    cinema="סינמה סיטי נתניה",
    chain="Cinema City",
    address="המחקר 3, נתניה",
    showtime="2026-11-12T20:20:00",
    runtime_minutes=150,
    venue_type="regular",
    ticket_url="https://tickets.cinema-city.co.il/order/849691",
)
NOW = datetime(2026, 11, 9, 18, 30, tzinfo=timezone.utc)

ics = calendar_ics.build_ics(**BASE, now=NOW)
lines = ics.split("\r\n")


def value(prefix: str) -> str | None:
    """A folded value, reassembled: continuation lines begin with one space."""
    unfolded = ics.replace("\r\n ", "")
    for line in unfolded.split("\r\n"):
        if line.startswith(prefix):
            return line[len(prefix):]
    return None


# ------------------------------------------------------------------ structure

eq("opens as a calendar", lines[0], "BEGIN:VCALENDAR")
eq("closes cleanly", lines[-2], "END:VCALENDAR")
check("ends with CRLF", ics.endswith("\r\n"))
check("every line break is CRLF, never a bare LF",
      not re.search(r"[^\r]\n", ics))
check("declares version 2.0", "VERSION:2.0" in lines)
eq("has exactly one event", lines.count("BEGIN:VEVENT"), 1)

# ------------------------------------------------------------------ the alarm

check("has an alarm at all", "BEGIN:VALARM" in lines)
check(f"alarm fires {calendar_ics.REMINDER_HOURS} hours before",
      f"TRIGGER:-PT{calendar_ics.REMINDER_HOURS}H" in lines)
check("the alarm is displayable", "ACTION:DISPLAY" in lines)
check("the alarm is closed", "END:VALARM" in lines)

# ------------------------------------------------------------------ times

eq("starts at the advertised time", value("DTSTART:"), "20261112T202000")
# 150 of film + 20 of adverts = 170, so 20:20 -> 23:10.
eq("ends after the film plus the adverts", value("DTEND:"), "20261112T231000")
eq("duration is runtime plus adverts", calendar_ics.duration_minutes(150), 170)
eq("an unknown runtime falls back to two hours",
   calendar_ics.duration_minutes(None), 120)
eq("a nonsense runtime falls back too", calendar_ics.duration_minutes(0), 120)

# Floating, deliberately. A trailing Z would make these UTC and shift every
# event by Israel's offset; a TZID without a VTIMEZONE block is what strict
# parsers reject.
check("DTSTART carries no zone",
      not re.search(r"^DTSTART[;:].*(Z|TZID)", ics, re.M))
check("DTEND carries no zone",
      not re.search(r"^DTEND[;:].*(Z|TZID)", ics, re.M))
# DTSTAMP is the exception: a real moment, so it must be absolute.
eq("DTSTAMP is UTC", value("DTSTAMP:"), "20261109T183000Z")

late = calendar_ics.build_ics(**{**BASE, "showtime": "2026-11-12T23:30:00",
                                 "runtime_minutes": 100}, now=NOW)
check("a late screening rolls into the next day",
      "DTEND:20261113T013000" in late)
month_end = calendar_ics.build_ics(**{**BASE, "showtime": "2026-11-30T23:00:00"}, now=NOW)
check("and across a month boundary", "DTEND:20261201T015000" in month_end)

# ------------------------------------------------------------------ escaping

awkward = calendar_ics.build_ics(
    **{**BASE, "film_title": "מואנה, הסרט; גרסה מיוחדת\\רגילה",
       "cinema": "קולנוע, תל אביב"}, now=NOW)
check("commas are escaped", "\\," in awkward)
check("semicolons are escaped", "\\;" in awkward)
check("backslashes are escaped first", "\\\\" in awkward)
check("no bare comma survives in SUMMARY",
      not re.search(r"^SUMMARY:[^\r\n]*[^\\],", awkward, re.M))

# ------------------------------------------------------------------ folding

long_title = calendar_ics.build_ics(
    **{**BASE,
       "film_title": "הרפתקאותיו המופלאות של הילד שרצה להיות גיבור על בממלכה רחוקה מאוד"},
    now=NOW)
check("no content line exceeds 75 octets",
      all(len(l.encode("utf-8")) <= 75 for l in long_title.split("\r\n")))
check("continuation lines are marked with a leading space", "\r\n " in long_title)
check("the folded title survives unfolding",
      "הרפתקאותיו המופלאות" in long_title.replace("\r\n ", ""))
check("no replacement characters from a split codepoint",
      "�" not in long_title)

# ------------------------------------------------------------------ identity

again = calendar_ics.build_ics(**BASE, now=datetime(2026, 11, 10, 9, tzinfo=timezone.utc))
eq("the same screening keeps the same UID across runs",
   value("UID:"),
   next(l[4:] for l in again.replace("\r\n ", "").split("\r\n") if l.startswith("UID:")))
other = calendar_ics.build_ics(**{**BASE, "showtime": "2026-11-12T21:40:00"}, now=NOW)
check("a different screening gets a different UID",
      value("UID:") != next(l[4:] for l in other.split("\r\n") if l.startswith("UID:")))

# ------------------------------------------------------------------ content

check("the summary names the film and the cinema",
      "האודיסאה" in (value("SUMMARY:") or "")
      and "סינמה סיטי נתניה" in (value("SUMMARY:") or ""))
check("the location includes the address", "המחקר 3" in (value("LOCATION:") or ""))
check("the description links back to the booking",
      "tickets.cinema-city.co.il" in (value("DESCRIPTION:") or ""))
check("a missing address does not leak 'None'",
      "None" not in calendar_ics.build_ics(**{**BASE, "address": None}, now=NOW))
check("a VIP hall is noted",
      "VIP" in calendar_ics.build_ics(**{**BASE, "venue_type": "VIP"}, now=NOW))
check("an ordinary hall is not spelled out",
      "regular" not in (value("DESCRIPTION:") or ""))

# ------------------------------------------------------------------ headers

name = calendar_ics.filename_for("האודיסאה", "2026-11-12T20:20:00")
check("the filename ends in .ics", name.endswith(".ics"))
check("the filename has no path separators or spaces",
      not re.search(r"[\\/\s]", name))
eq("a title of pure punctuation still yields a filename",
   calendar_ics.filename_for("***", ""), "screening.ics")

disposition = calendar_ics.content_disposition(name)
# The whole reason the file is served rather than generated in the page.
check("disposition is inline, NOT attachment",
      disposition.startswith("inline;") and "attachment" not in disposition)
check("carries the real name RFC 5987 encoded", "filename*=UTF-8''" in disposition)
check("header is latin-1 safe, as HTTP requires",
      disposition.encode("latin-1", "strict") is not None)
check("has an ASCII fallback filename",
      re.search(r'filename="[\x20-\x7e]+\.ics"', disposition) is not None)


# ------------------------------------------------------------------ live

def test_live(base: str) -> None:
    """The endpoint itself: headers, lookup, and what it refuses."""
    import requests

    session = requests.Session()
    movies = session.get(f"{base}/api/movies", params={"limit": 300}, timeout=30).json()
    check("catalogue returned films", bool(movies))

    # Find a film with a theatre and a showtime to ask about.
    target = None
    for film in movies[:12]:
        detail = session.get(f"{base}/api/movies/{film['id']}", timeout=30).json()
        for theatre in detail.get("theatres", []):
            for group in theatre.get("dates", []):
                for show in group.get("showtimes", []):
                    target = (film["id"], theatre["id"],
                              f"{group['date']}T{show['time']}:00",
                              show["venue_type"], show.get("dubbed_language"))
                    break
                if target:
                    break
            if target:
                break
        if target:
            break

    if not target:
        check("found a screening to test", False)
        return

    film_id, theatre_id, at, venue, dub = target
    params = {"film": film_id, "theatre": theatre_id, "at": at, "venue_type": venue}
    if dub:
        params["dub"] = dub
    response = session.get(f"{base}/api/screening.ics", params=params, timeout=30)

    eq("endpoint serves the file", response.status_code, 200)
    check("served as text/calendar",
          "text/calendar" in response.headers.get("content-type", ""))
    check("declares utf-8, so Hebrew is not mojibake",
          "utf-8" in response.headers.get("content-type", "").lower())
    disposition = response.headers.get("content-disposition", "")
    check("disposition is inline, so the phone can hand it to a calendar",
          disposition.startswith("inline"))
    check("never attachment", "attachment" not in disposition)

    body = response.text
    check("body is a calendar", body.startswith("BEGIN:VCALENDAR"))
    check("body carries the reminder",
          f"TRIGGER:-PT{calendar_ics.REMINDER_HOURS}H" in body)
    check("body uses CRLF", "\r\n" in body)

    # Ids in, nothing out. None of these may be reflected or honoured.
    for payload in ["<script>alert(1)</script>", "' OR '1'='1",
                    "x\r\nSUMMARY:injected", "../../etc/passwd"]:
        bad = session.get(f"{base}/api/screening.ics",
                          params={"film": payload, "theatre": theatre_id, "at": at},
                          timeout=30)
        check(f"refuses a bogus film id ({payload[:22]})",
              bad.status_code in (404, 422))
        check(f"does not reflect it ({payload[:22]})", payload not in bad.text)

    # A CRLF in `at` is the one that would matter most: it is the only caller
    # value that reaches a parser, and an injected line is exactly how an .ics
    # gains a field it was never meant to have.
    injected = session.get(f"{base}/api/screening.ics",
                           params={"film": film_id, "theatre": theatre_id,
                                   "at": f"{at}\r\nSUMMARY:injected"}, timeout=30)
    check("a CRLF in `at` is rejected", injected.status_code in (404, 422))
    # The property that matters is that it never becomes a calendar, NOT that
    # the value is absent from the reply. FastAPI's validation error quotes the
    # rejected input back, which is its standard behaviour and inert in a JSON
    # body -- an earlier version of this test asserted non-reflection and
    # failed on exactly that, which is the test being wrong rather than the
    # endpoint. What would be a finding is the payload reaching a file.
    check("the refusal is not a calendar",
          "text/calendar" not in injected.headers.get("content-type", ""))
    check("no calendar body was produced",
          "BEGIN:VCALENDAR" not in injected.text)
    # Note what is NOT asserted: that the string "SUMMARY:injected" is absent
    # from the reply. It is present, quoted inside the JSON error — and a
    # payload quoted in a JSON string is not a calendar field. Asserting its
    # absence tests the echo rather than the injection, which is how the two
    # previous versions of this check managed to fail against an endpoint that
    # was behaving correctly.

    missing = session.get(f"{base}/api/screening.ics",
                          params={"film": film_id, "theatre": 999999, "at": at},
                          timeout=30)
    eq("an unknown theatre is a 404", missing.status_code, 404)

    malformed = session.get(f"{base}/api/screening.ics",
                            params={"film": film_id, "theatre": theatre_id,
                                    "at": "not-a-date"}, timeout=30)
    eq("a malformed time is a 422", malformed.status_code, 422)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="also probe a running server")
    args = parser.parse_args()

    if args.url:
        test_live(args.url.rstrip("/"))

    print(f"\n{passed} passed, {len(failures)} failed")
    for failure in failures:
        print(f"  FAIL  {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
