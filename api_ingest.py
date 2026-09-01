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

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel

import auth
import localtime
import validate
import ticket_urls
from database import SessionLocal
from scrapers import SCRAPERS
from scrapers.base import MovieListing, Showtime, Theater
from sync import get_or_create_cinema_source, upsert_listing, upsert_screening, upsert_theatre

router = APIRouter(prefix="/api/ingest", tags=["ingest"])
log = logging.getLogger("ingest")

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
    # Computed by the pusher: this host cannot reach Movieland's or Planet's
    # image servers, so it could never hash these posters itself.
    poster_hash: str | None = None


class ShowtimeIn(BaseModel):
    source_theatre_id: str
    source_movie_id: str
    starts_at: str
    ticket_url: str
    venue_type: str = "regular"
    dubbed_language: str | None = None
    original_language: str | None = None
    subtitled_language: str | None = None
    # Planet only. Carried through the push so the server learns a screening is
    # full even though it can never ask Planet itself.
    sold_out: bool | None = None


class IngestPayload(BaseModel):
    theatres: list[TheaterIn]
    movies: list[MovieIn]
    showtimes: list[ShowtimeIn]
    # How many days ahead this payload covers. Needed to retire screenings
    # safely: anything stored inside this window and absent from the payload is
    # gone, but rows beyond it were simply never sent and must not be judged.
    # Older senders omit it, in which case nothing is retired.
    window_days: int | None = None


class IngestResult(BaseModel):
    chain: str
    theatres: int
    listings: int
    new_screenings: int
    skipped_unknown: int
    rejected_urls: int
    retired: int
    restored: int
    received_at: str


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
        import posters

        stats = posters.run()
        if stats.get("adopted"):
            log.info("posters: %s pushed listing(s) joined an existing film",
                     stats["adopted"])
    except Exception as exc:
        # The push already stored everything; grouping is an improvement on top.
        log.warning("post-ingest poster grouping skipped: %s: %s",
                    type(exc).__name__, exc)

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
    auth.check_token(x_ingest_token)
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
        rejected = 0
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

            # The token proves the push came from a holder of the secret. It
            # says nothing about where the URLs inside it point, and this is
            # the one path by which a string from outside the deployment
            # becomes a link a user taps to pay. Checked on the way in.
            reason = ticket_urls.rejection_reason(chain, showtime.ticket_url)
            if reason:
                log.warning("ingest %s: refused ticket_url -- %s", chain, reason)
                rejected += 1
                continue

            if upsert_screening(db, listing.id, theatre.id, showtime):
                new_count += 1
        db.commit()

        # Retire whatever the push did not carry. This is the only route by
        # which Movieland and Planet get their stale screenings cleared: the
        # server cannot fetch either chain, so the pushed payload is the only
        # statement of what is still on sale that it will ever see.
        retired = restored = 0
        if payload.window_days:
            try:
                live = [Showtime(**item.model_dump()) for item in payload.showtimes]
                outcome = validate.retire_from_payload(
                    db, source, live, payload.window_days
                )
                retired, restored = outcome["marked"], outcome["revived"]
            except Exception as exc:
                # Never fail the push over this -- the data itself is already
                # stored, and leaving screenings visible is the safe direction.
                db.rollback()
                log.warning("post-ingest retirement skipped for %s: %s: %s",
                            chain, type(exc).__name__, exc)

        log.info("ingested %s: %s theatres, %s listings, %s new screenings%s%s",
                 chain, len(theatres), len(listings), new_count,
                 f", {rejected} REFUSED for bad ticket_url" if rejected else "",
                 f", {retired} retired" if retired else "")

        background.add_task(_finish_ingest)

        return IngestResult(
            chain=chain,
            theatres=len(theatres),
            listings=len(listings),
            new_screenings=new_count,
            skipped_unknown=skipped,
            rejected_urls=rejected,
            retired=retired,
            restored=restored,
            received_at=localtime.now().isoformat(timespec="seconds"),
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
