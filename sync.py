"""Chain-agnostic sync: pulls every registered cinema chain into the database.

Replaces sync_cinema_city.py. Nothing here knows which chain it is talking to --
each scraper returns the same three record types, so this loop is identical for
all five. Adding a sixth chain needs no changes to this file.

Usage:
    python sync.py                      # all chains
    python sync.py cinema_city          # one chain
    python sync.py cinema_city planet   # a subset
    python sync.py --days 3             # narrower window
"""

import argparse
import logging
import sys
import traceback
from datetime import datetime

import localtime
import ticket_urls
from database import SessionLocal
from models import CinemaSource, Theatre, SourceMovieListing, Screening
from scrapers import SCRAPERS


log = logging.getLogger(__name__)


def get_or_create_cinema_source(db, key: str, name: str) -> CinemaSource:
    source = db.query(CinemaSource).filter_by(key=key).first()
    if not source:
        source = CinemaSource(key=key, name=name)
        db.add(source)
        db.commit()
        db.refresh(source)
    return source


def upsert_theatre(db, cinema_source_id: int, theater) -> Theatre:
    # Scoped by cinema_source_id: two chains can legitimately reuse the same
    # internal id, so source_theatre_id alone is not unique.
    row = db.query(Theatre).filter_by(
        cinema_source_id=cinema_source_id,
        source_theatre_id=theater.source_theatre_id,
    ).first()
    if not row:
        row = Theatre(
            cinema_source_id=cinema_source_id,
            source_theatre_id=theater.source_theatre_id,
        )
        db.add(row)

    row.name = theater.name
    row.address = theater.address
    if theater.latitude is not None:
        row.latitude = theater.latitude
    if theater.longitude is not None:
        row.longitude = theater.longitude
    return row


def upsert_listing(db, cinema_source_id: int, movie) -> SourceMovieListing:
    row = db.query(SourceMovieListing).filter_by(
        cinema_source_id=cinema_source_id,
        source_movie_id=movie.source_movie_id,
    ).first()
    if not row:
        row = SourceMovieListing(
            cinema_source_id=cinema_source_id,
            source_movie_id=movie.source_movie_id,
            movie_id=None,          # left unmatched; match_movies.py fills this in
            match_confidence=None,
        )
        db.add(row)

    row.raw_title = movie.title
    # Refreshed every run, but never overwrite a real value with a null -- some
    # chains expose metadata on only one of their endpoints.
    for field in ("poster_url", "genre", "runtime_minutes", "premiere_date", "age_rating"):
        value = getattr(movie, field)
        if value is not None:
            setattr(row, field, value)
    return row


def upsert_screening(db, listing_id: int, theatre_id: int, showtime) -> bool:
    """Returns True if this was a new screening.

    venue_type AND the dub language are part of the identity, not just
    attributes. A cinema can run the same film at the same minute in IMAX and in
    a regular hall, and can run a Hebrew-dubbed and an original-audio showing at
    the same time -- Planet serves both under a single film id. Each is a
    separately bookable event with its own ticket URL, so keying on
    (listing, theatre, time) alone would collapse them and send someone to the
    wrong showing's checkout.
    """
    row = db.query(Screening).filter_by(
        source_movie_listing_id=listing_id,
        theatre_id=theatre_id,
        showtime=showtime.starts_at,
        venue_type=showtime.venue_type,
        dubbed_language=showtime.dubbed_language,
    ).first()
    is_new = row is None
    if is_new:
        row = Screening(
            source_movie_listing_id=listing_id,
            theatre_id=theatre_id,
            showtime=showtime.starts_at,
            venue_type=showtime.venue_type,
            dubbed_language=showtime.dubbed_language,
        )
        db.add(row)

    row.original_language = showtime.original_language
    row.subtitled_language = showtime.subtitled_language
    row.ticket_url = showtime.ticket_url
    row.last_verified_at = localtime.now().isoformat()
    return is_new


def sync_chain(db, key: str, days: int) -> dict:
    scraper = SCRAPERS[key]()
    source = get_or_create_cinema_source(db, key, scraper.source_name)

    theaters = scraper.get_theaters()
    theatres = {t.source_theatre_id: upsert_theatre(db, source.id, t) for t in theaters}
    db.commit()

    movies = scraper.get_movies()
    listings = {m.source_movie_id: upsert_listing(db, source.id, m) for m in movies}
    db.commit()

    new_count = 0
    skipped_unknown = 0
    duplicates = 0
    rejected_urls = 0
    # The session is autoflush=False, so a pending INSERT is invisible to the
    # existence query in upsert_screening until the next commit. If a scraper
    # emits the same showing twice in one run, both rows would be written.
    # Tracking the keys here is cheaper than flushing on every row.
    seen: set[tuple[int, int, str, str, str | None]] = set()

    for showtime in scraper.get_showtimes(days=days):
        theatre = theatres.get(showtime.source_theatre_id)
        listing = listings.get(showtime.source_movie_id)
        if theatre is None or listing is None:
            # A showtime referencing a theater or title that never appeared in
            # the list endpoints. Counted rather than silently dropped, because
            # a large number here means the two endpoints disagree.
            skipped_unknown += 1
            continue

        # Named `identity`, not `key`: `key` is this function's chain-name
        # parameter, and assigning the tuple to it shadowed the chain from the
        # first iteration onward.
        identity = (listing.id, theatre.id, showtime.starts_at,
                    showtime.venue_type, showtime.dubbed_language)
        if identity in seen:
            duplicates += 1
            continue
        seen.add(identity)

        reason = ticket_urls.rejection_reason(key, showtime.ticket_url)
        if reason:
            # Dropped rather than stored with a blank link: a screening whose
            # checkout we cannot vouch for is worth less than the risk of
            # rendering it as a tappable button.
            log.warning("%s: refused ticket_url -- %s", key, reason)
            rejected_urls += 1
            continue

        if upsert_screening(db, listing.id, theatre.id, showtime):
            new_count += 1
    db.commit()

    return {
        "theatres": len(theatres),
        "listings": len(listings),
        "new_screenings": new_count,
        "skipped_unknown": skipped_unknown,
        "duplicates": duplicates,
        "rejected_urls": rejected_urls,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync cinema showtimes into the database.")
    parser.add_argument("chains", nargs="*", default=None,
                        help=f"chains to sync (default: all). options: {', '.join(SCRAPERS)}")
    parser.add_argument("--days", type=int, default=7, help="days ahead to fetch (default: 7)")
    args = parser.parse_args()

    chains = args.chains or list(SCRAPERS)
    unknown = [c for c in chains if c not in SCRAPERS]
    if unknown:
        print(f"Unknown chain(s): {', '.join(unknown)}")
        print(f"Available: {', '.join(SCRAPERS)}")
        return 2

    db = SessionLocal()
    results, failures = {}, {}

    for key in chains:
        print(f"\n=== {key} ===")
        try:
            stats = sync_chain(db, key, args.days)
            results[key] = stats
            print(f"  theatres={stats['theatres']}  listings={stats['listings']}  "
                  f"new screenings={stats['new_screenings']}"
                  + (f"  (skipped {stats['skipped_unknown']} unresolvable)"
                     if stats["skipped_unknown"] else "")
                  + (f"  (collapsed {stats['duplicates']} repeats)"
                     if stats["duplicates"] else ""))
        except Exception as exc:
            # One dead site must not abort the whole run.
            db.rollback()
            failures[key] = exc
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            traceback.print_exc(limit=3)

    db.close()

    print("\n" + "=" * 50)
    for key, stats in results.items():
        print(f"  {key:14} {stats['theatres']:>3} theatres  {stats['listings']:>4} listings  "
              f"{stats['new_screenings']:>5} new screenings")
    for key in failures:
        print(f"  {key:14} FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
