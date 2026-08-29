"""Accept scraped data pushed from elsewhere.

Two chains cannot be scraped from the server at all. Movieland answers Fly's
datacenter IP with a Cloudflare challenge that never resolves, and Planet with
an outright firewall block ("Attention Required"). Neither is a request-shaping
problem -- cloudscraper, TLS fingerprint impersonation and a real headless
Chromium all fail identically -- so the only fix is to scrape from an IP those
sites accept, which in practice means a home connection in Israel.

So push_local.py runs on a machine that can reach them and posts the results
here. The server stays authoritative for everything else and keeps serving
normally whether or not a push ever arrives: this only adds data.

The records are the same dataclasses the scrapers produce and go through the
same upsert functions as a local sync, so an ingested chain is indistinguishable
from a scraped one once stored.
"""

import logging
import os
import secrets

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel

import localtime
from database import SessionLocal
from scrapers import SCRAPERS
from scrapers.base import MovieListing, Showtime, Theater
from sync import get_or_create_cinema_source, upsert_listing, upsert_screening, upsert_theatre

router = APIRouter(prefix="/api/ingest", tags=["ingest"])
log = logging.getLogger("ingest")

# Shared secret, set as a platform secret. With no token configured the
# endpoint refuses everything rather than defaulting to open -- an unauthenticated
# write path would let anyone rewrite the schedule.
INGEST_TOKEN = os.getenv("INGEST_TOKEN", "")


class TheaterIn(BaseModel):
    source_theatre_id: str
    name: str
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class MovieIn(BaseModel):
    source_movie_id: str
    title: str
    poster_url: str | None = None
    genre: str | None = None
    runtime_minutes: int | None = None
    premiere_date: str | None = None
    age_rating: str | None = None


class ShowtimeIn(BaseModel):
    source_theatre_id: str
    source_movie_id: str
    starts_at: str
    ticket_url: str
    venue_type: str = "regular"
    dubbed_language: str | None = None
    original_language: str | None = None
    subtitled_language: str | None = None


class IngestPayload(BaseModel):
    theatres: list[TheaterIn]
    movies: list[MovieIn]
    showtimes: list[ShowtimeIn]


class IngestResult(BaseModel):
    chain: str
    theatres: int
    listings: int
    new_screenings: int
    skipped_unknown: int
    received_at: str


def _check_token(provided: str | None) -> None:
    if not INGEST_TOKEN:
        raise HTTPException(503, "Ingest is not configured on this server.")
    # Constant-time: a plain == leaks the secret one character at a time to
    # anyone willing to measure.
    if not provided or not secrets.compare_digest(provided, INGEST_TOKEN):
        raise HTTPException(401, "Invalid or missing ingest token.")


def _finish_ingest() -> None:
    """The two follow-up passes a scheduled sync normally performs.

    Both matter for a pushed chain, and both were previously tied to sync only:

    Geocoding, because just two of the five chains publish their own positions.
    An ingested chain that does not -- Movieland -- stays unlocated and drops
    out of distance sorting.

    TMDb matching, because until a listing is matched it cannot merge with the
    same film from other chains. Straight after a push, Spider-Man appeared
    twice: once as the matched card and once as an unmatched Movieland/Planet
    pair.

    Both run after the response is sent. Geocoding is limited to one request a
    second and matching makes a call per unmatched title, so doing either inline
    would hold the push open for minutes.
    """
    try:
        import geocode

        located = geocode.run()
        if located:
            log.info("geocoded %s newly ingested theatre(s)", located)
    except Exception as exc:
        # Not fatal: the next scheduled sync geocodes whatever is still missing.
        log.warning("post-ingest geocoding skipped: %s: %s", type(exc).__name__, exc)

    try:
        from match_movies import match_unmatched

        db = SessionLocal()
        try:
            stats = match_unmatched(db)
        finally:
            db.close()
        if stats["matched"]:
            log.info("tmdb: matched %s pushed listing(s)", stats["matched"])
        elif stats["considered"]:
            log.warning("tmdb: considered %s listings and matched none",
                        stats["considered"])
    except Exception as exc:
        log.warning("post-ingest matching skipped: %s: %s", type(exc).__name__, exc)


@router.post("/{chain}", response_model=IngestResult)
def ingest(
    chain: str,
    payload: IngestPayload,
    background: BackgroundTasks,
    x_ingest_token: str | None = Header(None),
):
    """Store one chain's scrape, exactly as a local sync would."""
    _check_token(x_ingest_token)
    if chain not in SCRAPERS:
        raise HTTPException(404, f"Unknown chain '{chain}'. Options: {', '.join(SCRAPERS)}")

    scraper_name = SCRAPERS[chain].source_name
    db = SessionLocal()
    try:
        source = get_or_create_cinema_source(db, chain, scraper_name)

        theatres = {
            t.source_theatre_id: upsert_theatre(db, source.id, Theater(**t.model_dump()))
            for t in payload.theatres
        }
        db.commit()

        listings = {
            m.source_movie_id: upsert_listing(db, source.id, MovieListing(**m.model_dump()))
            for m in payload.movies
        }
        db.commit()

        new_count = 0
        skipped = 0
        # Same in-run dedupe as sync.py: the session is autoflush=False, so a
        # pending insert is invisible to the existence check.
        seen: set[tuple] = set()

        for item in payload.showtimes:
            showtime = Showtime(**item.model_dump())
            theatre = theatres.get(showtime.source_theatre_id)
            listing = listings.get(showtime.source_movie_id)
            if theatre is None or listing is None:
                skipped += 1
                continue

            key = (listing.id, theatre.id, showtime.starts_at,
                   showtime.venue_type, showtime.dubbed_language)
            if key in seen:
                continue
            seen.add(key)

            if upsert_screening(db, listing.id, theatre.id, showtime):
                new_count += 1
        db.commit()

        log.info("ingested %s: %s theatres, %s listings, %s new screenings",
                 chain, len(theatres), len(listings), new_count)

        background.add_task(_finish_ingest)

        return IngestResult(
            chain=chain,
            theatres=len(theatres),
            listings=len(listings),
            new_screenings=new_count,
            skipped_unknown=skipped,
            received_at=localtime.now().isoformat(timespec="seconds"),
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
