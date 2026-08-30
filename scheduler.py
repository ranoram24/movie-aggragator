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
    SCRAPE_DAYS=9
    SCRAPE_ON_STARTUP=1            # 0 to wait for the first interval instead
    SCRAPE_MATCH_AFTER_SYNC=1      # 0 to skip the TMDb matching pass
    SCRAPE_GEOCODE_AFTER_SYNC=1    # 0 to skip filling in theatre coordinates
    SCRAPE_SKIP_CHAINS=movieland,planet   # chains pushed in from outside
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
# 9 covers a schedule published on Tuesday afternoon through Wednesday of
# the week after: that last day is 8 past the Tuesday, and the scrapers use
# an exclusive upper bound (today <= date < today + days), so it needs 9.
SCRAPE_DAYS = int(os.getenv("SCRAPE_DAYS", 9))
RUN_ON_STARTUP = os.getenv("SCRAPE_ON_STARTUP", "1") != "0"
MATCH_AFTER_SYNC = os.getenv("SCRAPE_MATCH_AFTER_SYNC", "1") != "0"
GEOCODE_AFTER_SYNC = os.getenv("SCRAPE_GEOCODE_AFTER_SYNC", "1") != "0"

# Chains this host must not try to scrape. Movieland and Planet block the
# production datacenter's IP outright, so attempting them there only produces a
# failed run and an error in the log every few hours -- their data arrives via
# the ingest endpoint instead. Left empty locally, where both are reachable.
SKIP_CHAINS = {
    c.strip() for c in os.getenv("SCRAPE_SKIP_CHAINS", "").split(",") if c.strip()
}

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


def _geocode_missing() -> int:
    """Blocking. Fills in coordinates for any theatre that lacks them.

    Runs after a sync because a theatre is useless for distance sorting until
    it has a position, and only two of the five chains publish coordinates
    themselves. Leaving it as a manual step meant a fresh deploy had 9 of 27
    theatres located and "sort by nearest" quietly did nothing on the live site.

    Normally a no-op: it only touches rows where latitude is NULL, which after
    the first pass means just newly-added venues.
    """
    import geocode

    return geocode.run()


def _match_unmatched() -> dict:
    """Blocking. Links freshly scraped listings to TMDb records."""
    # Imported lazily so a missing/broken TMDb setup degrades to "matching
    # skipped" rather than stopping the server from starting.
    from match_movies import match_unmatched

    db = SessionLocal()
    try:
        return match_unmatched(db)
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

        if GEOCODE_AFTER_SYNC:
            try:
                async with _write_lock:
                    located = await asyncio.to_thread(_geocode_missing)
                if located:
                    log.info("geocoded %s theatre(s)", located)
            except Exception as exc:
                # Nominatim being unreachable must not fail the scrape; the
                # theatres simply stay unlocated until the next run.
                log.warning("geocoding skipped: %s: %s", type(exc).__name__, exc)

        if MATCH_AFTER_SYNC:
            try:
                async with _write_lock:
                    stats = await asyncio.to_thread(_match_unmatched)
                if stats["matched"]:
                    log.info("tmdb: matched %s new listings", stats["matched"])
                elif stats["considered"]:
                    # Worth saying out loud: "considered 170, matched 0" almost
                    # always means the API rejected us, not that 170 films are
                    # genuinely unmatchable.
                    log.warning(
                        "tmdb: considered %s listings and matched none",
                        stats["considered"],
                    )
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
    active = [key for key in SCRAPERS if key not in SKIP_CHAINS]
    for index, key in enumerate(active):
        delay = index * STARTUP_STAGGER if RUN_ON_STARTUP else INTERVALS[key]
        tasks.append(asyncio.create_task(_chain_loop(key, delay), name=f"scrape:{key}"))

    for key in SKIP_CHAINS:
        # Make the gap visible in /scrape/status rather than leaving these
        # looking permanently "pending" for no stated reason.
        if key in STATUS:
            STATUS[key]["state"] = "external"

    log.info(
        "scheduler started for %s (%s), window=%sd, first run %s%s",
        len(active), ", ".join(active), SCRAPE_DAYS,
        "on startup" if RUN_ON_STARTUP else "after one interval",
        f"; pushed externally: {', '.join(sorted(SKIP_CHAINS))}" if SKIP_CHAINS else "",
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
