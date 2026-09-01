"""Re-check screenings we already know about, and retire the ones that vanished.

The full scrape in sync.py only ever inserts and updates. Nothing in it can say
"this screening is gone", because a screening that disappears from a chain's
listing simply stops appearing in the response -- absence is not a record. So a
cancelled or pulled showing stayed on the site, looking bookable, until its
start time passed. Measured on production: 274 such screenings across the five
chains.

This is the other half. It asks one question per stored screening:

    can a ticket still be bought for this?

Not how many seats are left -- a seat count is not the question, and treating
"nearly full" as gone would hide screenings people can still book. For four of
the five chains the answer comes from existence: a cinema that has stopped
selling a showing removes it from its listing, so "still listed" and "still
bookable" are the same fact. Planet additionally reports `soldOut`, which
catches the one case existence cannot -- listed, but full.

Two rules make this safe to run unattended:

1. ONLY JUDGE WHAT WAS FETCHED. A screening five days out is missing from a
   two-day fetch because we did not ask for it, not because it is gone. The
   comparison window is therefore always a strict subset of the fetched window.
   Getting this backwards would blank most of the catalogue in one pass.

2. FAIL OPEN. Chains that cannot be re-fetched cheaply return None from
   validation_showtimes() and are skipped entirely, leaving is_available NULL,
   which displays. Silence is never read as absence.
"""

import logging
from datetime import datetime, timedelta

import localtime
from models import CinemaSource, Screening, SourceMovieListing, Theatre
from scrapers import SCRAPERS

log = logging.getLogger("validate")


def _identity(listing_id: int, theatre_id: int, showtime: str,
              venue_type: str | None, dubbed_language: str | None) -> tuple:
    """What makes a screening one screening.

    Deliberately the same tuple upsert_screening() keys on, so a row written by
    the scraper and the same showing seen by the validator agree by
    construction. Using the chain's own event id instead would need a new column
    and would not work for Planet, whose ticket URL no longer carries one.
    """
    return (listing_id, theatre_id, showtime, venue_type, dubbed_language)


def _fetch_days(horizon_hours: int) -> int:
    """Days to ask the chain for, to be certain the horizon is covered.

    Scrapers filter on whole dates (today <= date < today + days), so asking for
    exactly one day covers only the remainder of today -- at 20:00 that is four
    hours, not twenty-four. One extra day guarantees the compared window sits
    strictly inside the fetched one, which is rule 1 above.
    """
    return max(1, -(-horizon_hours // 24)) + 1


def near_term_movie_ids(db, key: str, horizon_hours: int = 24) -> set[str] | None:
    """Which titles have a screening inside the horizon. Read-only.

    Exists so the caller can work out what to ask the chain for BEFORE taking a
    write lock, and then fetch without holding it. None means the chain is not
    in the database yet.
    """
    source = db.query(CinemaSource).filter_by(key=key).first()
    if source is None:
        return None
    now = localtime.now()
    stored = stored_in_window(
        db, source, now.isoformat(),
        (now + timedelta(hours=horizon_hours)).isoformat(),
    )
    return {listing.source_movie_id for _, listing in stored}


def fetch_live(key: str, horizon_hours: int, movie_ids: set[str] | None):
    """The network half, on its own. No database, so it needs no lock."""
    return SCRAPERS[key]().validation_showtimes(
        _fetch_days(horizon_hours), movie_ids=movie_ids
    )


def validate_chain(db, key: str, horizon_hours: int = 24, live=None) -> dict:
    """Re-check one chain's near-term screenings. Returns a small summary.

    `live` may be supplied by a caller that already fetched it -- the scheduler
    does exactly that, so the write lock is only held for the comparison and
    the writes, never across the network request.
    """
    scraper = SCRAPERS[key]()
    days = _fetch_days(horizon_hours)

    now = localtime.now()
    now_iso = now.isoformat()
    horizon_iso = (now + timedelta(hours=horizon_hours)).isoformat()

    source = db.query(CinemaSource).filter_by(key=key).first()
    if source is None:
        return {"chain": key, "skipped": "chain not in database"}

    # The stored screenings under judgement: this chain, still upcoming, and
    # inside the horizon. Loaded before the fetch so we can tell the scraper
    # which titles are actually worth asking about.
    stored = stored_in_window(db, source, now_iso, horizon_iso)
    if not stored:
        return {"chain": key, "checked": 0, "marked": 0, "revived": 0}

    if live is None:
        movie_ids = {listing.source_movie_id for _, listing in stored}
        live = scraper.validation_showtimes(days, movie_ids=movie_ids)
    if live is None:
        # Not a failure: this chain has opted out because re-fetching it costs
        # as much as a full scrape. Its rows keep whatever state they had.
        return {"chain": key, "skipped": "no cheap validation for this chain"}

    result = apply_live(db, source, live, stored, now_iso)
    result["horizon_hours"] = horizon_hours
    return result


def apply_live(db, source, live, stored, now_iso: str) -> dict:
    """Compare a fetched set of screenings against the stored rows in a window.

    Split out so the ingest endpoint can reuse it. Movieland and Planet cannot
    be fetched from the production host at all, so their comparison runs there
    against the payload pushed in from a machine that can reach them -- the
    same logic, a different source of "live".

    `stored` must already be scoped to the window `live` covers. That coupling
    is the whole safety property: rows outside it are never judged.
    """
    key = source.key

    # Source ids -> database ids. Lookup only; validation never creates rows,
    # so anything the chain has just added is left for the next full scrape.
    theatre_ids = {
        t.source_theatre_id: t.id
        for t in db.query(Theatre).filter_by(cinema_source_id=source.id).all()
    }
    listing_ids = {
        l.source_movie_id: l.id
        for l in db.query(SourceMovieListing)
        .filter_by(cinema_source_id=source.id).all()
    }

    live_keys: set[tuple] = set()
    sold_out_keys: set[tuple] = set()
    for s in live:
        theatre_id = theatre_ids.get(s.source_theatre_id)
        listing_id = listing_ids.get(s.source_movie_id)
        if theatre_id is None or listing_id is None:
            continue  # a theatre or title we have not stored yet
        identity = _identity(listing_id, theatre_id, s.starts_at,
                             s.venue_type, s.dubbed_language)
        live_keys.add(identity)
        if s.sold_out:
            sold_out_keys.add(identity)

    now = now_iso
    marked = revived = 0
    for screening, listing in stored:
        identity = _identity(
            screening.source_movie_listing_id, screening.theatre_id,
            screening.showtime, screening.venue_type, screening.dubbed_language,
        )
        listed = identity in live_keys
        available = listed and identity not in sold_out_keys

        if not available and screening.is_available is not False:
            marked += 1
            log.info(
                "unavailable: %s | %s | %s | %s (%s)",
                key, screening.showtime[:16], listing.raw_title[:40],
                "sold out" if identity in sold_out_keys else "no longer listed",
                f"theatre {screening.theatre_id}",
            )
        elif available and screening.is_available is False:
            # It came back -- a chain reinstating a screening, or a transient
            # gap in its feed. Restoring is why this sets state rather than
            # deleting rows.
            revived += 1
            log.info("available again: %s | %s | %s",
                     key, screening.showtime[:16], listing.raw_title[:40])

        screening.is_available = available
        screening.last_validated_at = now

    db.commit()
    return {
        "chain": key,
        "checked": len(stored),
        "marked": marked,
        "revived": revived,
        "live": len(live_keys),
    }


def stored_in_window(db, source, start_iso: str, end_iso: str):
    """Screenings for one chain between two timestamps, with their listings."""
    return (
        db.query(Screening, SourceMovieListing)
        .join(SourceMovieListing,
              SourceMovieListing.id == Screening.source_movie_listing_id)
        .filter(SourceMovieListing.cinema_source_id == source.id)
        .filter(Screening.showtime >= start_iso)
        .filter(Screening.showtime <= end_iso)
        .all()
    )


def retire_from_payload(db, source, live, window_days: int) -> dict:
    """Retire screenings missing from a pushed full scrape.

    The push carries a complete `window_days` scrape of a chain, so anything
    stored inside that window and absent from the payload is gone -- the same
    inference validate_chain makes, without a fetch this host could not perform.
    """
    now = localtime.now()
    end = datetime.combine(
        (now + timedelta(days=window_days)).date(), datetime.min.time()
    )
    stored = stored_in_window(db, source, now.isoformat(), end.isoformat())
    if not stored:
        return {"chain": source.key, "checked": 0, "marked": 0, "revived": 0}
    return apply_live(db, source, live, stored, now.isoformat())
