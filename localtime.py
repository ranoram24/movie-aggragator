"""One source of truth for "what time is it, in cinema terms".

Every showtime in the database is a naive local Israel timestamp, because that
is how the chains publish them -- "20:20" means 20:20 in the cinema's lobby, not
20:20 UTC. Nothing in the string records that.

So any comparison against `datetime.now()` is only correct if the process
happens to be running on Israel time. It isn't in production: a container runs
on UTC, which in summer is **three hours behind** Israel. That made the API
treat anything up to three hours in the past as still upcoming -- at 11:20 in
Tel Aviv the server thought it was 08:20 and happily offered a 10:50 screening
that had already started.

Import `now()` and `today()` from here instead of calling datetime directly, and
the answer is the same whether the code runs on a laptop in Israel or a machine
in Paris.
"""

from datetime import date, datetime, timedelta, timezone

CINEMA_TZ_NAME = "Asia/Jerusalem"

try:
    from zoneinfo import ZoneInfo

    CINEMA_TZ = ZoneInfo(CINEMA_TZ_NAME)
except Exception:  # pragma: no cover - depends on the host's tz database
    # zoneinfo needs a tz database, which Windows does not ship and slim Linux
    # images often omit; the `tzdata` package in requirements.txt supplies it.
    # If it is somehow still missing, fall back to a fixed +03:00 rather than
    # silently reverting to UTC and resurrecting the bug above. This is correct
    # for Israeli summer time and one hour off in winter -- wrong, but wrong by
    # an hour instead of by three, and it fails loudly in the log.
    import logging

    logging.getLogger(__name__).warning(
        "No tz database found for %s; falling back to a fixed UTC+3. "
        "Install the 'tzdata' package to fix this.", CINEMA_TZ_NAME,
    )
    CINEMA_TZ = timezone(timedelta(hours=3))


def now() -> datetime:
    """Current wall-clock time in Israel, as a naive datetime.

    Naive on purpose: it is compared against the naive timestamps stored in the
    database, and mixing aware and naive datetimes raises in Python.
    """
    return datetime.now(CINEMA_TZ).replace(tzinfo=None)


def today() -> date:
    """Today's date in Israel."""
    return now().date()


def now_iso() -> str:
    """Current Israel time as the same ISO string format used for showtimes.

    Screening.showtime is stored as text, so filtering compares strings. That
    works because the format is fixed-width ISO, where lexical and chronological
    order agree.
    """
    return now().strftime("%Y-%m-%dT%H:%M:%S")
