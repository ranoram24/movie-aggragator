"""Background scraping that runs for as long as the API server is up.

Each chain gets its own loop and its own interval, because their costs differ by
orders of magnitude: Movieland is two HTTP requests, Lev is roughly eight
hundred. Running them on one shared timer would mean either hammering the fast
sites or letting the schedule go stale waiting for the slow one.

Design notes:

* The scrapers are blocking (requests), so each run goes through
  asyncio.to_thread and never stalls the event loop -- the API keeps serving
  while a scrape is in progress.
* A single lock serialises the actual database writes. SQLite tolerates one
  writer at a time, and syncing five chains concurrently would produce
  "database is locked" errors under load.
* Every chain is staggered on startup so they don't all fire at once.
* A failing site logs and retries on its next tick; it never kills the loop or
  the server.

Intervals can be overridden without editing this file:

    SCRAPE_INTERVAL_LEV=43200      # seconds, per chain
    SCRAPE_INTERVAL_DEFAULT=21600
    SCRAPE_DAYS=7
    SCRAPE_ON_STARTUP=1            # 0 to wait for the first interval instead
    SCRAPE_MATCH_AFTER_SYNC=1      # 0 to skip the TMDb matching pass
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

from database import SessionLocal
from scrapers import SCRAPERS
from sync import sync_chain

log = logging.getLogger("scraper")

DEFAULT_INTERVAL = int(os.getenv("SCRAPE_INTERVAL_DEFAULT", 6 * 60 * 60))   # 6h
LEV_INTERVAL = int(os.getenv("SCRAPE_INTERVAL_LEV", 24 * 60 * 60))          # 24h
SCRAPE_DAYS = int(os.getenv("SCRAPE_DAYS", 7))
RUN_ON_STARTUP = os.getenv("SCRAPE_ON_STARTUP", "1") != "0"
MATCH_AFTER_SYNC = os.getenv("SCRAPE_MATCH_AFTER_SYNC", "1") != "0"

# Lev needs ~800 requests through a cascading dropdown flow and takes roughly
# twelve minutes. Its art-house schedule also changes far less often than a
# multiplex's, so once a day is plenty.
INTERVALS = {key: DEFAULT_INTERVAL for key in SCRAPERS}
INTERVALS["lev"] = LEV_INTERVAL

# Seconds to wait before each chain's first run, so five scrapes don't all
# start in the same instant on boot.
STARTUP_STAGGER = 20

# Only one writer at a time (SQLite).
_write_lock = asyncio.Lock()

# Live state, surfaced by the /scrape/status endpoint.
STATUS: dict[str, dict] = {
    key: {
        "state": "pending",
        "last_run": None,
        "last_success": None,
        "last_error": None,
        "last_result": None,
        "runs": 0,
        "failures": 0,
    }
    for key in SCRAPERS
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sync_one(key: str) -> dict:
    """Blocking. Runs in a worker thread, with its own DB session.

    SQLAlchemy sessions are not thread-safe, so this must not reuse a session
    created anywhere else.
    """
    db = SessionLocal()
    try:
        return sync_chain(db, key, SCRAPE_DAYS)
    finally:
        db.close()


def _match_unmatched() -> dict:
    """Blocking. Links freshly scraped listings to TMDb records."""
    # Imported lazily: match_movies reads TMDB_TOKEN at import time, and a
    # missing token should degrade to "matching skipped", not crash the server.
    from match_movies import find_best_match
    from models import SourceMovieListing, Movie

    db = SessionLocal()
    matched = 0
    try:
        pending = db.query(SourceMovieListing).filter_by(movie_id=None).all()
        for listing in pending:
            match, score = find_best_match(listing.raw_title)
            if not match:
                continue
            movie = db.query(Movie).filter_by(tmdb_id=match["id"]).first()
            if not movie:
                poster = match.get("poster_path")
                movie = Movie(
                    tmdb_id=match["id"],
                    title_en=match.get("original_title"),
                    title_he=match.get("title"),
                    poster_url=f"https://image.tmdb.org/t/p/w500{poster}" if poster else None,
                    release_date=match.get("release_date"),
                    overview=match.get("overview"),
                )
                db.add(movie)
                db.flush()
            listing.movie_id = movie.id
            listing.match_confidence = score
            matched += 1
        db.commit()
        return {"considered": len(pending), "matched": matched}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def _run_once(key: str) -> None:
    status = STATUS[key]
    status["state"] = "running"
    status["last_run"] = _now()
    status["runs"] += 1

    try:
        async with _write_lock:
            result = await asyncio.to_thread(_sync_one, key)

        status["last_result"] = result
        status["last_success"] = _now()
        status["last_error"] = None
        status["state"] = "idle"
        log.info(
            "%s: %s theatres, %s listings, %s new screenings",
            key, result["theatres"], result["listings"], result["new_screenings"],
        )

        if MATCH_AFTER_SYNC:
            try:
                async with _write_lock:
                    stats = await asyncio.to_thread(_match_unmatched)
                if stats["matched"]:
                    log.info("tmdb: matched %s new listings", stats["matched"])
            except Exception as exc:
                # Matching is a nice-to-have; a TMDb outage or a missing token
                # must not mark the scrape itself as failed.
                log.warning("tmdb matching skipped: %s: %s", type(exc).__name__, exc)

    except asyncio.CancelledError:
        status["state"] = "cancelled"
        raise
    except Exception as exc:
        status["state"] = "error"
        status["last_error"] = f"{type(exc).__name__}: {exc}"
        status["failures"] += 1
        log.exception("%s scrape failed", key)


async def _chain_loop(key: str, initial_delay: float) -> None:
    """One chain, forever: wait, scrape, repeat."""
    try:
        await asyncio.sleep(initial_delay)
        while True:
            await _run_once(key)
            await asyncio.sleep(INTERVALS[key])
    except asyncio.CancelledError:
        log.info("%s loop stopped", key)
        raise


def start(tasks: list[asyncio.Task]) -> None:
    """Spawn one loop per chain. Called from the app's lifespan startup."""
    for index, key in enumerate(SCRAPERS):
        delay = index * STARTUP_STAGGER if RUN_ON_STARTUP else INTERVALS[key]
        tasks.append(asyncio.create_task(_chain_loop(key, delay), name=f"scrape:{key}"))
    log.info(
        "scheduler started for %s (%s), window=%sd, first run %s",
        len(SCRAPERS), ", ".join(SCRAPERS), SCRAPE_DAYS,
        "on startup" if RUN_ON_STARTUP else "after one interval",
    )


async def stop(tasks: list[asyncio.Task]) -> None:
    """Cancel every loop and wait for them to unwind."""
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    tasks.clear()
    log.info("scheduler stopped")


async def trigger(key: str) -> None:
    """Run one chain now, out of band. Used by the manual endpoint."""
    await _run_once(key)
