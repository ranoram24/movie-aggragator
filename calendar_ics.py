"""Building the iCalendar file for one screening.

Ported from the browser, and the port is the point. The file used to be
assembled in JavaScript and handed over as a Blob with a download attribute,
which is always a file save: on a phone it lands in Downloads and needs finding,
tapping and an "open with" before any calendar sees it.

Served from a real URL as text/calendar with no attachment disposition, the
same bytes are a document the browser hands straight to whatever app claims
that type -- which on Android is the calendar's own import screen. Nothing about
the file changed; only where it comes from.

A second thing falls out of moving it here. The event's text no longer comes
from the client at all: the endpoint is given ids, and the title, cinema,
address, runtime and ticket link are read from the database. So nothing a
caller types can reach the file, and the escaping below is defence in depth
rather than the only thing standing between a query string and a malformed
calendar entry.

The format rules worth knowing, all of which fail silently when broken -- one
calendar app accepts the file and another rejects it with no explanation:

  * CRLF line endings, always.
  * Content lines fold at 75 OCTETS, not characters. Hebrew is two bytes a
    letter in UTF-8, so a Hebrew title reaches the limit in half the characters
    an English one would.
  * Comma, semicolon and backslash are separators in TEXT values and must be
    escaped. Real film titles contain all three.
  * Times are floating -- no Z, no TZID. See _local_stamp.
"""

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

# Hours before the screening that the reminder fires. The whole reason this is
# a file rather than a link to Google Calendar, whose prefill interface has no
# parameter for an alarm of any kind.
REMINDER_HOURS = 2

# Minutes of trailers and advertising before the feature starts. The listed
# time is when the session begins, not when the film does. Added to the runtime
# rather than the start, so the event covers the time someone is actually in
# the building -- the question a calendar block answers is "when am I free
# again".
ADVERTS_MINUTES = 20

# Used when the chain never published a runtime.
FALLBACK_MINUTES = 120

PRODID = "-//On Cinema//Screenings//HE"
UID_DOMAIN = "on-cinema-now.fly.dev"


def duration_minutes(runtime_minutes: int | None) -> int:
    """How long to block out: the feature plus the adverts in front of it."""
    if runtime_minutes and runtime_minutes > 0:
        return runtime_minutes + ADVERTS_MINUTES
    return FALLBACK_MINUTES


def escape_text(value: str) -> str:
    """Escape a TEXT value. Backslash first, or the escapes get escaped."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def fold(line: str) -> str:
    """Fold a content line to 75 octets, per RFC 5545.

    Measured in bytes, so this cannot be a simple slice: iterating by character
    and measuring each one is what keeps a two-byte Hebrew letter from being
    cut in half across the fold.
    """
    if len(line.encode("utf-8")) <= 75:
        return line

    parts: list[str] = []
    current = ""
    used = 0
    for char in line:
        size = len(char.encode("utf-8"))
        # A continuation line begins with a space, which counts toward its 75.
        limit = 75 if not parts else 74
        if used + size > limit:
            parts.append(current)
            current = ""
            used = 0
        current += char
        used += size
    if current:
        parts.append(current)
    return "\r\n ".join(parts)


def _local_stamp(showtime: str) -> str:
    """"2026-11-12T15:30:00" -> "20261112T153000".

    Floating: no Z and no TZID, which iCalendar reads in the viewer's own
    timezone. Right for a cinema ticket in Israel held by a phone set to
    Israeli time, and it avoids both alternatives being worse -- converting to
    UTC would bake in a DST offset computed for the screening's date, and Israel
    switches in late March and late October, inside a booking window; a bare
    TZID=Asia/Jerusalem wants an accompanying VTIMEZONE block, without which
    strict parsers reject the file.
    """
    moment = datetime.fromisoformat(showtime)
    return moment.strftime("%Y%m%dT%H%M%S")


def _end_stamp(showtime: str, minutes: int) -> str:
    return (datetime.fromisoformat(showtime) + timedelta(minutes=minutes)).strftime(
        "%Y%m%dT%H%M%S"
    )


def _uid(showtime: str, ticket_url: str) -> str:
    """Stable per screening, so re-adding one updates rather than duplicates."""
    digest = 0x811C9DC5
    for char in ticket_url or "":
        digest ^= ord(char) & 0xFF
        digest = (digest * 0x01000193) & 0xFFFFFFFF
    return f"{_local_stamp(showtime)}-{digest:08x}@{UID_DOMAIN}"


def build_ics(
    *,
    film_title: str,
    cinema: str,
    chain: str,
    address: str | None,
    showtime: str,
    runtime_minutes: int | None,
    venue_type: str | None,
    ticket_url: str | None,
    now: datetime | None = None,
) -> str:
    """The whole .ics document for one screening."""
    now = now or datetime.now(timezone.utc)
    minutes = duration_minutes(runtime_minutes)

    summary = f"{film_title} — {cinema}"
    location = f"{cinema}, {address}" if address else cinema
    description = "\n".join(
        part for part in (
            chain,
            venue_type if venue_type and venue_type != "regular" else None,
            ticket_url,
        ) if part
    )

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{_uid(showtime, ticket_url or '')}",
        f"DTSTAMP:{now.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART:{_local_stamp(showtime)}",
        f"DTEND:{_end_stamp(showtime, minutes)}",
        f"SUMMARY:{escape_text(summary)}",
        f"LOCATION:{escape_text(location)}",
        f"DESCRIPTION:{escape_text(description)}",
        "BEGIN:VALARM",
        f"TRIGGER:-PT{REMINDER_HOURS}H",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{escape_text(summary)}",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(fold(line) for line in lines) + "\r\n"


_UNSAFE = re.compile(r"[^\w֐-׿-]+")


def filename_for(film_title: str, showtime: str) -> str:
    """A filename derived from the film, for the Content-Disposition header."""
    stamp = showtime.replace(":", "-").replace("T", "-")[:16]
    slug = _UNSAFE.sub("-", f"{film_title}-{stamp}").strip("-")
    return f"{slug or 'screening'}.ics"


def content_disposition(filename: str) -> str:
    """An `inline` disposition carrying a possibly-Hebrew filename.

    `inline` and not `attachment`, which is the entire point of serving this
    over HTTP: `attachment` tells the browser to save the file, which is the
    behaviour being replaced. `inline` lets it hand the document to whatever
    handles text/calendar.

    Two filename forms because HTTP header values are latin-1. A Hebrew name
    cannot be written literally, so RFC 5987's filename* carries the real one
    percent-encoded and the plain filename is an ASCII fallback for anything
    that does not understand it.
    """
    ascii_name = filename.encode("ascii", "ignore").decode("ascii").strip("-") or "screening.ics"
    if not ascii_name.endswith(".ics"):
        ascii_name = "screening.ics"
    return f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
