"""When a film reaches digital, from the MoviesOnlineDates Telegram channel.

    python digital_dates.py              # scan the recent window
    python digital_dates.py --backfill   # walk the whole channel history once
    python digital_dates.py --dry-run    # parse and report, write nothing

The app answers "what is in cinemas". This answers the question a person asks
while looking at that: this is playing, but is it about to be at home? The
channel is a human-curated feed of Israeli digital release dates; the app shows
the date it gives and says nothing else about it.

## Why this is not a chain scraper

It does not implement CinemaScraper and is not in scrapers/. Nothing here
produces theatres, listings or showtimes -- it produces one date per film, for
films that may not be in any cinema at all. Forcing it into that interface
would mean four stub methods and a fake theatre.

## Why the matching is trivial, unusually

Every film post embeds a themoviedb.org link, and movies.tmdb_id is already
unique and indexed. So the join is an integer equality, not a title comparison.
That matters more here than it sounds: this project has lost a lot of blood to
Hebrew titles -- "אדיוטים" vs "אידיוטים", word order, chain decoration, TMDb
search returning nothing for a variant spelling -- and a feed with its own
Hebrew wording would have walked straight into all of it. The channel hands us
the id instead, so none of that applies. If a post ever lacks the link it is
skipped rather than guessed at.

## The update problem, and why this re-reads

The channel corrects itself, which is the main reason it is worth using. It
does so in TWO ways, and they need different handling:

  * It EDITS THE ORIGINAL POST in place. The post id does not change, the
    position in the channel does not change, and only the dates inside it
    differ. Nothing about the feed announces this.
  * It POSTS A SEPARATE NOTE quoting the original -- "הוקדם תאריך ה-Digital של
    הסרט ... בשבוע". That note is for humans; it carries no structured date.

So a scanner that reads only posts newer than the last one it saw would miss
every correction, which is most of the value. Each run therefore re-reads a
WINDOW of recent posts and overwrites what it finds, rather than consuming a
stream. The window is the one real tuning knob here: see SCAN_PAGES.

A quoted post is also a trap for the parser. Telegram embeds the original
inside the reply, so an update note looks like it contains the original's
fields. _own_text strips the quote before anything is read out of a post.

## Failure behaviour

Opposite to validate.py, deliberately. There, silence from a chain means a
screening probably vanished. Here, failing to re-read a date does not make the
date wrong -- it is almost certainly still correct -- so nothing is ever
deleted or blanked on a failed scan. The stored value stands until the channel
says otherwise.
"""

import argparse
import html
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

log = logging.getLogger("digital")

CHANNEL = os.getenv("DIGITAL_CHANNEL", "MoviesOnlineDates")
BASE_URL = f"https://t.me/s/{CHANNEL}"

# How many pages of 20 posts each run re-reads. The trade-off: a correction to
# a post older than the window is invisible until the next backfill, while a
# bigger window costs one request per page every two hours.
#
# 12 (~240 posts, roughly four months of this channel) is sized so that a film
# still playing in cinemas is almost certainly inside it -- the useful life of
# a cinema listing is far shorter than that. --backfill exists for the rest.
SCAN_PAGES = int(os.getenv("DIGITAL_SCAN_PAGES", 12))

# Polite pause between page requests. This is somebody's public channel.
PAGE_DELAY = float(os.getenv("DIGITAL_PAGE_DELAY", 0.8))
REQUEST_TIMEOUT = 30

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# ---- post anatomy ---------------------------------------------------------

# Each post is one of these divs. Splitting on the opening tag keeps a post's
# id, text and links together; parsing the page with one big regex let a
# non-greedy match run across the boundary and pair the wrong text with the
# wrong id.
POST_SPLIT_RE = re.compile(r'(?=<div class="tgme_widget_message[ "])')
POST_ID_RE = re.compile(r'data-post="[^/"]+/(\d+)"')
# The quoted parent of a reply. Removed before the body is read.
REPLY_RE = re.compile(r'<a class="tgme_widget_message_reply".*?</a>', re.S)
BODY_RE = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
TMDB_RE = re.compile(r"themoviedb\.org/movie/(\d+)")
BR_RE = re.compile(r"<br\s*/?>")
TAG_RE = re.compile(r"<[^>]+>")

# ---- the fields inside a post ---------------------------------------------

# 🎬 יער פרא (2026) Wildwood 🎬
TITLE_RE = re.compile(r"🎬\s*(.+?)\s*\((\d{4})\)\s*(.+?)\s*🎬")

# "Digital - 08/12/2026", under a "תאריך יציאה לרשת:" heading. Both hyphen and
# en-dash appear. A date the channel has not fixed yet reads "יפורסם בהמשך"
# (to be announced), which simply fails to match and stays NULL.
DIGITAL_RE = re.compile(r"Digital\s*[-–—]\s*(\d{2}/\d{2}/\d{4})", re.I)
BLURAY_RE = re.compile(r"BluRay\s*[-–—]\s*(\d{2}/\d{2}/\d{4})", re.I)
# Israeli cinema release, flagged with the flag emoji rather than a word.
CINEMA_IL_RE = re.compile(r"🇮🇱\s*[-–—]\s*(\d{2}/\d{2}/\d{4})")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _iso(date_text: str | None) -> str | None:
    """DD/MM/YYYY as the channel writes it -> ISO, so it sorts and compares.

    Day-first, not month-first. Getting this backwards would silently work for
    the first twelve days of every month and then produce nonsense, which is
    the kind of bug that reaches production.
    """
    if not date_text:
        return None
    try:
        return datetime.strptime(date_text, "%d/%m/%Y").date().isoformat()
    except ValueError:
        log.debug("unparseable date %r", date_text)
        return None


def _own_text(block: str) -> str | None:
    """The post's own text, with any quoted parent removed.

    The removal is the important half. An update note is a reply, and Telegram
    renders the original inside it, so without this a note saying only "the
    Digital date was brought forward" parses as a full film post carrying the
    original's now-stale dates -- and would overwrite the corrected values with
    the ones the correction was announcing a change from.
    """
    body = BODY_RE.search(REPLY_RE.sub("", block))
    if not body:
        return None
    text = html.unescape(TAG_RE.sub("", BR_RE.sub("\n", body.group(1))))
    return text.strip() or None


def parse_page(source: str) -> list[dict]:
    """Every post on one page of the channel's web view."""
    posts = []
    for block in POST_SPLIT_RE.split(source):
        post_id = POST_ID_RE.search(block)
        if not post_id:
            continue
        text = _own_text(block)
        if text is None:
            continue
        tmdb = TMDB_RE.search(block)
        posts.append({
            "post_id": int(post_id.group(1)),
            "text": text,
            # Read from the whole block, not the stripped text: the link is an
            # href on the "TMDb" anchor, and the visible text is just "TMDb".
            "tmdb_id": int(tmdb.group(1)) if tmdb else None,
        })
    return posts


def extract_release(post: dict) -> dict | None:
    """A film post's structured fields, or None if this is not one.

    Three things must be present: the 🎬 title line, a TMDb link, and at least
    one date worth storing. Update notes have none of them once the quoted
    parent is stripped, which is how they are filtered out without having to
    recognise their wording.
    """
    title = TITLE_RE.search(post["text"])
    if not title or not post["tmdb_id"]:
        return None

    digital = DIGITAL_RE.search(post["text"])
    bluray = BLURAY_RE.search(post["text"])
    cinema_il = CINEMA_IL_RE.search(post["text"])
    if not (digital or bluray or cinema_il):
        return None

    return {
        "tmdb_id": post["tmdb_id"],
        "title_he": title.group(1).strip(),
        "title_en": title.group(3).strip(),
        "digital_date": _iso(digital.group(1) if digital else None),
        "bluray_date": _iso(bluray.group(1) if bluray else None),
        "cinema_il_date": _iso(cinema_il.group(1) if cinema_il else None),
        "source_post_id": post["post_id"],
    }


def fetch_page(before: int | None = None) -> str:
    url = BASE_URL if before is None else f"{BASE_URL}?before={before}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return response.read().decode("utf-8", errors="replace")


def scan(pages: int = SCAN_PAGES, delay: float = PAGE_DELAY) -> dict[int, dict]:
    """Walk back through the channel and collect one record per film.

    Keyed by tmdb_id, newest post wins. A film is occasionally posted more than
    once -- a re-announcement, or a repost after a correction -- and the later
    post is the current one. Pages are walked newest-first, so "first seen
    wins" and "newest wins" are the same rule here.
    """
    releases: dict[int, dict] = {}
    before: int | None = None
    pages_read = 0

    for _ in range(pages):
        try:
            posts = parse_page(fetch_page(before))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Partial results are still worth storing: the pages already read
            # are valid, and nothing here deletes anything.
            log.warning("page fetch failed after %s page(s): %s: %s",
                        pages_read, type(exc).__name__, exc)
            break
        if not posts:
            break

        pages_read += 1
        for post in posts:
            record = extract_release(post)
            if record and record["tmdb_id"] not in releases:
                releases[record["tmdb_id"]] = record

        before = min(p["post_id"] for p in posts)
        if before <= 1:
            break
        time.sleep(delay)

    log.info("read %s page(s), %s film(s) with a date", pages_read, len(releases))
    return releases


def store(db, releases: dict[int, dict]) -> dict:
    """Upsert the scanned records. Never deletes.

    A date that disappears from a post is not treated as a retraction -- the
    channel marks an unknown date "יפורסם בהמשך" rather than removing the line,
    so a missing value here means the parse found nothing, which is far more
    likely to be our problem than a real change. Existing values are therefore
    only ever overwritten by a new value, never by None.
    """
    from models import DigitalRelease

    if not releases:
        return {"scanned": 0, "added": 0, "updated": 0}

    existing = {
        row.tmdb_id: row
        for row in db.query(DigitalRelease)
        .filter(DigitalRelease.tmdb_id.in_(list(releases)))
        .all()
    }

    added = changed = 0
    now = _now()

    for tmdb_id, record in releases.items():
        row = existing.get(tmdb_id)
        if row is None:
            row = DigitalRelease(tmdb_id=tmdb_id, first_seen_at=now)
            db.add(row)
            added += 1
            row_changed = True
        else:
            row_changed = False

        for field in ("digital_date", "bluray_date", "cinema_il_date",
                      "title_he", "title_en", "source_post_id"):
            value = record[field]
            if value is None:
                continue
            if getattr(row, field) != value:
                if field == "digital_date" and getattr(row, field):
                    log.info("%s moved %s -> %s (%s)",
                             record["title_en"], row.digital_date, value, tmdb_id)
                setattr(row, field, value)
                row_changed = True

        if row_changed:
            row.updated_at = now
            if row.tmdb_id in existing:
                changed += 1

    db.commit()
    return {"scanned": len(releases), "added": added, "updated": changed}


# ---------------------------------------------------------------- TMDb fallback

# TMDb release types. 4 is Digital; 5 is Physical and deliberately NOT used,
# because a disc is not the thing a person means by "it's at home already".
TMDB_DIGITAL_TYPE = 4

# Which country's digital date to believe, in order. IL first for the obvious
# reason. US second because it is the best-populated region on TMDb and, for
# the films this fallback actually serves -- older titles, long since released
# everywhere -- it is close enough.
TMDB_COUNTRY_PREFERENCE = ("IL", "US")

# How long a TMDb answer stands before the film is asked about again. Most
# answers are "no digital date yet", which changes exactly once and then never
# again, so re-asking constantly is wasted. A week is far inside the notice a
# digital release gets.
TMDB_RECHECK_DAYS = int(os.getenv("DIGITAL_TMDB_RECHECK_DAYS", 7))

# Films to ask TMDb about per pass. One request each, so this bounds the cost
# of a cycle; the backlog drains over a few passes and then stays near zero.
TMDB_BATCH = int(os.getenv("DIGITAL_TMDB_BATCH", 40))


def tmdb_digital_date(tmdb_id: int) -> str | None:
    """Earliest digital release date TMDb knows for a film, or None.

    Preference order is IL, then US, then the earliest digital date in any
    country. That last step looks sloppy and is in fact the point: TMDb's
    coverage of older films is scattered, and Shrek -- the case that prompted
    this -- has no IL or US digital entry at all, only a French one. Falling
    back to "earliest anywhere" is what makes a 2001 film correctly read as
    available at home.

    It is safe to be imprecise in that direction because of how the date is
    worded. The UI says "בדיגיטל מאז X" -- on digital SINCE X -- which is a
    lower bound on availability, not a claim to be the first release. Any real
    past digital date makes that sentence true. A future date would not be
    safe to guess at this way, but the channel covers everything upcoming in
    Israel, so this fallback is almost only ever serving the past.
    """
    import requests

    token = os.getenv("TMDB_TOKEN")
    if not token:
        return None

    try:
        response = requests.get(
            f"https://api.themoviedb.org/3/movie/{tmdb_id}/release_dates",
            headers={"Authorization": f"Bearer {token}", "accept": "application/json"},
            timeout=20,
        )
        response.raise_for_status()
        results = response.json().get("results", [])
    except Exception as exc:
        log.debug("tmdb release_dates failed for %s: %s: %s",
                  tmdb_id, type(exc).__name__, exc)
        return None

    by_country: dict[str, list[str]] = {}
    for entry in results:
        country = entry.get("iso_3166_1")
        for release in entry.get("release_dates", []):
            if release.get("type") != TMDB_DIGITAL_TYPE:
                continue
            date_text = (release.get("release_date") or "")[:10]
            if len(date_text) == 10:
                by_country.setdefault(country, []).append(date_text)

    for country in TMDB_COUNTRY_PREFERENCE:
        if by_country.get(country):
            return min(by_country[country])

    everywhere = [d for dates in by_country.values() for d in dates]
    return min(everywhere) if everywhere else None


# Split into read / fetch / write rather than one function, for the same
# reason sync.py and validate.py are: the scheduler must do its network work
# WITHOUT holding the SQLite write lock. A single function that interleaves a
# request and a commit per film would hold that lock across forty HTTP calls.


def tmdb_candidates(db, limit: int = TMDB_BATCH) -> list[int]:
    """Which films are worth asking TMDb about. Read-only, so no lock needed.

    Only films with a tmdb_id and an upcoming screening: this answers a
    question somebody is asking while looking at a listing, and a film nobody
    can see today is not being looked at.

    Films the channel already covers are skipped entirely -- the channel wins
    wherever it has an opinion, so fetching a value that would be ignored is
    pure waste.
    """
    from datetime import datetime as _dt, timedelta

    from models import DigitalRelease, Movie, Screening, SourceMovieListing
    import localtime

    covered = {
        row.tmdb_id
        for row in db.query(DigitalRelease.tmdb_id)
        .filter(DigitalRelease.digital_date.isnot(None))
        .all()
    }
    stale_before = (_dt.now(timezone.utc) - timedelta(days=TMDB_RECHECK_DAYS)).isoformat()

    showing = (
        db.query(Movie)
        .join(SourceMovieListing, SourceMovieListing.movie_id == Movie.id)
        .join(Screening, Screening.source_movie_listing_id == SourceMovieListing.id)
        .filter(Screening.showtime >= localtime.now_iso())
        .filter(Movie.tmdb_id.isnot(None))
        .distinct()
        .all()
    )
    return [
        movie.tmdb_id for movie in showing
        if movie.tmdb_id not in covered
        and (movie.digital_tmdb_checked_at is None
             or movie.digital_tmdb_checked_at < stale_before)
    ][:limit]


def fetch_tmdb_dates(tmdb_ids: list[int]) -> dict[int, str | None]:
    """The network half, on its own. No database, so it needs no lock.

    None for a film TMDb has no digital date for -- which is recorded just as
    deliberately as a date, since it is what stops the film being asked about
    again tomorrow.
    """
    return {tmdb_id: tmdb_digital_date(tmdb_id) for tmdb_id in tmdb_ids}


def apply_tmdb_dates(db, dates: dict[int, str | None]) -> dict:
    """Write what TMDb said. Fast: no network, just the upserts."""
    from models import Movie

    if not dates:
        return {"considered": 0, "found": 0}

    rows = db.query(Movie).filter(Movie.tmdb_id.in_(list(dates))).all()
    found = 0
    now = _now()
    for movie in rows:
        date_text = dates.get(movie.tmdb_id)
        if date_text and date_text != movie.digital_date_tmdb:
            movie.digital_date_tmdb = date_text
            found += 1
        # Stamped whether or not a date came back. Without this the films with
        # no digital date yet -- the majority -- would be re-fetched on every
        # single pass forever.
        movie.digital_tmdb_checked_at = now
    db.commit()

    if found:
        log.info("tmdb digital: asked about %s film(s), %s new date(s)",
                 len(dates), found)
    return {"considered": len(dates), "found": found}


def fill_from_tmdb(db, limit: int = TMDB_BATCH) -> dict:
    """All three phases, for the CLI and for run(). The scheduler calls the
    phases separately so it can fetch outside the write lock."""
    candidates = tmdb_candidates(db, limit)
    if not candidates:
        return {"considered": 0, "found": 0}
    return apply_tmdb_dates(db, fetch_tmdb_dates(candidates))


def run(db=None, pages: int = SCAN_PAGES) -> dict:
    """Scan the channel, store it, then top up from TMDb. Safe on a timer."""
    from database import SessionLocal

    own = db is None
    db = db or SessionLocal()
    try:
        result = store(db, scan(pages))
        try:
            result.update(fill_from_tmdb(db))
        except Exception as exc:
            # The channel is the real source; TMDb is a nice-to-have. A TMDb
            # outage or a missing token must not lose the channel scan that
            # has already been committed above.
            log.warning("tmdb digital fallback skipped: %s: %s",
                        type(exc).__name__, exc)
        return result
    finally:
        if own:
            db.close()


def _report(db) -> None:
    """What the badge would say today, for the films actually in cinemas."""
    from datetime import date

    from models import DigitalRelease, Movie, Screening, SourceMovieListing
    import localtime

    showing = {
        movie.tmdb_id: movie.title_he or movie.title_en
        for movie in db.query(Movie)
        .join(SourceMovieListing, SourceMovieListing.movie_id == Movie.id)
        .join(Screening, Screening.source_movie_listing_id == SourceMovieListing.id)
        .filter(Screening.showtime >= localtime.now_iso())
        .filter(Movie.tmdb_id.isnot(None))
        .distinct()
        .all()
    }
    if not showing:
        print("\nnothing currently showing with a tmdb id")
        return

    rows = (
        db.query(DigitalRelease)
        .filter(DigitalRelease.tmdb_id.in_(list(showing)))
        .filter(DigitalRelease.digital_date.isnot(None))
        .order_by(DigitalRelease.digital_date)
        .all()
    )

    today = date.today().isoformat()
    print(f"\nin cinemas now: {len(showing)} films; {len(rows)} have a digital date")
    for row in rows:
        marker = "already out" if row.digital_date < today else "upcoming   "
        print(f"  {marker}  {row.digital_date}  {showing[row.tmdb_id]}")


def _utf8_stdout() -> None:
    """Make the CLI printable on a Windows console.

    Everything this tool reports is Hebrew film titles, and the default Windows
    code page here is cp1255, which raises UnicodeEncodeError on the first one
    -- after the work is done but before anything is shown. Only touches this
    process's stdout, and only when it is not already UTF-8.
    """
    if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass


def main() -> int:
    _utf8_stdout()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backfill", action="store_true",
                        help="walk the entire channel history (slow, one-off)")
    parser.add_argument("--pages", type=int, default=None,
                        help=f"pages to read (default {SCAN_PAGES})")
    parser.add_argument("--dry-run", action="store_true",
                        help="parse and print, write nothing")
    parser.add_argument("--report", action="store_true",
                        help="show what the app would display today")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")

    from database import SessionLocal

    db = SessionLocal()
    try:
        if args.report:
            _report(db)
            return 0

        # 500 pages is 10,000 posts, comfortably more than the channel holds;
        # scan() stops on its own when a page comes back empty.
        pages = args.pages or (500 if args.backfill else SCAN_PAGES)
        releases = scan(pages)

        if args.dry_run:
            for record in sorted(releases.values(),
                                 key=lambda r: r["digital_date"] or "9999"):
                print(f"  {record['digital_date'] or '    -     '}  "
                      f"tmdb {record['tmdb_id']:<8} {record['title_en']}")
            print(f"\n{len(releases)} film(s) parsed, nothing written")
            return 0

        result = store(db, releases)
        print(f"scanned {result['scanned']}, added {result['added']}, "
              f"updated {result['updated']}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
