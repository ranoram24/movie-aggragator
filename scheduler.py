"""Background scraping that runs for as long as the API server is up.

Each chain gets its own loop and its own interval, because their costs differ by
orders of magnitude: Movieland is two HTTP requests, Lev is roughly eight
hundred. Running them on one shared timer would mean either hammering the fast
sites or letting the schedule go stale waiting for the slow one.

Design notes:

* The scrapers are blocking (requests), so each run goes through
  asyncio.to_thread and never stalls the event loop -- the API keeps serving
  while a scrape is in progress.
* A single lock serialises the actual database WRITES, and nothing else.
  SQLite tolerates one writer at a time, so the inserts must queue -- but the
  fetching does not, and both the scrapers and the validator now do their
  network work before taking the lock. Holding it across a fetch used to stall
  every other writer for the length of a scrape: a validation pass measured on
  production waited 2m49s behind Lev, which takes minutes to fetch and seconds
  to store.
* Every chain is staggered on startup so they don't all fire at once.
* A failing site logs and retries on its next tick; it never kills the loop or
  the server.

Two layers run here, on separate schedules:

* The FULL SCRAPE discovers -- new films, new theatres, new showtimes, changed
  schedules. It is additive by nature: a screening that vanishes from a chain
  simply stops appearing, and absence is not a record it can write.
* VALIDATION retires. It re-checks only screenings already stored and close
  enough to matter, and marks the ones that are gone. See validate.py.

Neither replaces the other. Scraping more often would still never retire a
cancelled showing, and validation never discovers anything new.

Intervals can be overridden without editing this file:

    SCRAPE_INTERVAL_LEV=21600      # seconds, per chain
    SCRAPE_INTERVAL_DEFAULT=7200
    SCRAPE_DAYS=9
    VALIDATION_INTERVAL_DEFAULT=900        # 15 min
    VALIDATION_INTERVAL_HOT_CINEMA=3600    # 1h -- costs a request per film
    VALIDATION_HORIZON_HOURS=24            # how far ahead to re-check
    VALIDATION_CHAINS=cinema_city,hot_cinema,movieland,planet
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
from sync import fetch_chain, store_chain

log = logging.getLogger("scraper")

DEFAULT_INTERVAL = int(os.getenv("SCRAPE_INTERVAL_DEFAULT", 2 * 60 * 60))   # 2h
LEV_INTERVAL = int(os.getenv("SCRAPE_INTERVAL_LEV", 6 * 60 * 60))           # 6h
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

# Lev is the expensive one: ~575 requests through a cascading dropdown flow,
# about five minutes at roughly two requests a second. Measured, not guessed --
# 71 movie-slots across 7 branches, ~6 in-window dates each.
#
# At six hours that is ~2,300 requests a day in four short bursts, which is
# modest, and it is four times fresher than the daily run it replaces. Its
# screenings cannot be validated cheaply (see LevScraper.validation_showtimes),
# so the full scrape is the only thing keeping Lev current -- which is the
# argument for not leaving it at 24h.
INTERVALS = {key: DEFAULT_INTERVAL for key in SCRAPERS}
INTERVALS["lev"] = LEV_INTERVAL

# ---- validation ----------------------------------------------------------
VALIDATION_INTERVAL_DEFAULT = int(os.getenv("VALIDATION_INTERVAL_DEFAULT", 15 * 60))
VALIDATION_INTERVALS = {
    # One request per film, so a pass is ~30 rather than ~9. Hourly keeps it
    # proportionate; Cinema City's whole chain is a single bulk call and can
    # afford every quarter hour.
    "hot_cinema": int(os.getenv("VALIDATION_INTERVAL_HOT_CINEMA", 60 * 60)),
}
VALIDATION_HORIZON_HOURS = int(os.getenv("VALIDATION_HORIZON_HOURS", 24))

# Chains cheap enough to re-check on a short timer. Lev is absent by design: it
# has no endpoint that answers "is this screening still on sale" without
# replaying most of its cascade. SKIP_CHAINS is subtracted from this below, so
# on the production host Movieland and Planet drop out for the same reason they
# are not scraped there -- their validation rides on push_local.py instead.
VALIDATION_CHAINS = {
    c.strip()
    for c in os.getenv(
        "VALIDATION_CHAINS", "cinema_city,hot_cinema,movieland,planet"
    ).split(",")
    if c.strip()
}

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


VALIDATION_STATUS: dict[str, dict] = {
    key: {"state": "pending", "last_run": None, "last_result": None,
          "last_error": None, "runs": 0}
    for key in SCRAPERS
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fetch_one(key: str) -> dict:
    """Blocking, network only. No database session, so it needs no lock."""
    return fetch_chain(key, SCRAPE_DAYS)


def _store_one(key: str, fetched: dict) -> dict:
    """Blocking, database only. Runs in a worker thread with its own session.

    SQLAlchemy sessions are not thread-safe, so this must not reuse a session
    created anywhere else.
    """
    db = SessionLocal()
    try:
        return store_chain(db, key, fetched)
    finally:
        db.close()


def _validate_fetch(key: str):
    """Blocking. Works out what to ask for, then asks. No writes, no lock.

    Imported lazily for the same reason the matcher is: a problem in validation
    should degrade to "validation skipped", never stop the server booting.
    """
    import validate

    db = SessionLocal()
    try:
        movie_ids = validate.near_term_movie_ids(db, key, VALIDATION_HORIZON_HOURS)
    finally:
        db.close()
    return validate.fetch_live(key, VALIDATION_HORIZON_HOURS, movie_ids)


def _validate_apply(key: str, live) -> dict:
    """Blocking. Compares and writes, with its own DB session."""
    import validate

    db = SessionLocal()
    try:
        return validate.validate_chain(db, key, VALIDATION_HORIZON_HOURS, live=live)
    except Exception:
        db.rollback()
        raise
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


def _hash_posters() -> dict:
    """Blocking. Hashes any new poster and regroups listings by artwork.

    Runs after a sync for the same reason matching does: a freshly added film
    has no hash yet, and until it does it cannot be recognised as the same film
    another chain already lists. Incremental -- after the first pass this is a
    handful of downloads.
    """
    import posters

    return posters.run()


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
    log.info("%s: full scrape starting (window %sd)", key, SCRAPE_DAYS)

    try:
        # Fetch outside the lock. It is a WRITE lock, and holding it across the
        # network was blocking every other writer for the length of a scrape --
        # Lev takes minutes, which is what pushed validation passes behind it.
        # Chains can now fetch concurrently; only their inserts serialise, which
        # is all SQLite actually requires.
        fetched = await asyncio.to_thread(_fetch_one, key)
        async with _write_lock:
            result = await asyncio.to_thread(_store_one, key, fetched)

        status["last_result"] = result
        status["last_success"] = _now()
        status["last_error"] = None
        status["state"] = "idle"
        log.info(
            "%s: full scrape finished -- %s theatres, %s listings, %s new screenings",
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
                    stats = await asyncio.to_thread(_hash_posters)
                if stats.get("adopted") or stats.get("hashed"):
                    log.info(
                        "posters: %s hashed, %s listing(s) joined an existing film",
                        stats.get("hashed", 0), stats.get("adopted", 0),
                    )
            except Exception as exc:
                # A missing Pillow or an unreachable poster host must not fail
                # the scrape; grouping simply stays as it was.
                log.warning("poster grouping skipped: %s: %s", type(exc).__name__, exc)

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


async def _validate_once(key: str) -> None:
    status = VALIDATION_STATUS[key]
    status["state"] = "running"
    status["last_run"] = _now()
    status["runs"] += 1
    log.info("%s: validation starting (next %sh)", key, VALIDATION_HORIZON_HOURS)

    try:
        # Fetch first, unlocked -- Hot Cinema's pass is ~30 requests and holding
        # a write lock through them would stall a scrape for no reason.
        live = await asyncio.to_thread(_validate_fetch, key)
        # Same lock as the scraper: SQLite takes one writer, and a validation
        # pass committing mid-scrape would contend with it.
        async with _write_lock:
            result = await asyncio.to_thread(_validate_apply, key, live)

        status["last_result"] = result
        status["last_error"] = None
        status["state"] = "idle"

        if result.get("skipped"):
            log.info("%s: validation skipped -- %s", key, result["skipped"])
        else:
            log.info(
                "%s: validation finished -- %s checked, %s marked unavailable, "
                "%s restored",
                key, result["checked"], result["marked"], result["revived"],
            )
    except asyncio.CancelledError:
        status["state"] = "cancelled"
        raise
    except Exception as exc:
        status["state"] = "error"
        status["last_error"] = f"{type(exc).__name__}: {exc}"
        # Never fatal: a failed validation leaves screenings exactly as they
        # were, which is the safe direction.
        log.warning("%s validation failed: %s: %s", key, type(exc).__name__, exc)


async def _validation_loop(key: str, initial_delay: float) -> None:
    """One chain's validation, forever."""
    interval = VALIDATION_INTERVALS.get(key, VALIDATION_INTERVAL_DEFAULT)
    try:
        await asyncio.sleep(initial_delay)
        while True:
            await _validate_once(key)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        log.info("%s validation loop stopped", key)
        raise


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

    # Validation runs on its own timers. Chains this host cannot reach are
    # excluded for the same reason they are not scraped here.
    validating = [k for k in SCRAPERS if k in VALIDATION_CHAINS and k not in SKIP_CHAINS]
    for index, key in enumerate(validating):
        # Offset from the scrape loops so a validation pass does not start in
        # the same second as a scrape and immediately queue on the write lock.
        delay = STARTUP_STAGGER * (len(active) + index) + 30
        tasks.append(
            asyncio.create_task(_validation_loop(key, delay), name=f"validate:{key}")
        )
    for key in SCRAPERS:
        if key not in validating:
            VALIDATION_STATUS[key]["state"] = (
                "external" if key in SKIP_CHAINS else "unsupported"
            )

    log.info(
        "scheduler started for %s (%s), window=%sd, first run %s%s",
        len(active), ", ".join(active), SCRAPE_DAYS,
        "on startup" if RUN_ON_STARTUP else "after one interval",
        f"; pushed externally: {', '.join(sorted(SKIP_CHAINS))}" if SKIP_CHAINS else "",
    )
    log.info(
        "scrape intervals: %s",
        ", ".join(f"{k}={INTERVALS[k] // 60}m" for k in active) or "none",
    )
    log.info(
        "validation every %s for %s (horizon %sh)%s",
        ", ".join(
            f"{VALIDATION_INTERVALS.get(k, VALIDATION_INTERVAL_DEFAULT) // 60}m {k}"
            for k in validating
        ) or "-",
        ", ".join(validating) or "no chains",
        VALIDATION_HORIZON_HOURS,
        "; lev has no cheap validation and relies on its full scrape"
        if "lev" not in validating else "",
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
