"""Scrape the chains the server can't reach, and push them to it.

Movieland and Planet block Fly's datacenter IP through Cloudflare -- Movieland
with a challenge that never resolves, Planet with an outright firewall block.
Nothing about the request fixes that: cloudscraper, TLS fingerprint
impersonation and a real headless Chromium all fail the same way. The only IP
those sites accept is a home connection in Israel, so this runs there.

This machine is a courier, not a server. It writes nothing locally and holds no
state; if it never runs, the site simply keeps serving the three chains the
server scrapes for itself.

    python push_local.py                       # both blocked chains
    python push_local.py planet                # just one
    python push_local.py --days 3
    python push_local.py --dry-run             # scrape and report, send nothing

Needs two settings, from the environment or .env:

    INGEST_URL=https://on-cinema-now.fly.dev
    INGEST_TOKEN=<the same secret set on the server>
"""

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

import requests
from dotenv import load_dotenv

from scrapers import SCRAPERS

load_dotenv()

# The chains the server cannot scrape itself. Everything else is left alone --
# pushing a chain the server already handles would just duplicate work.
BLOCKED_CHAINS = ["movieland", "planet"]

INGEST_URL = os.getenv("INGEST_URL", "https://on-cinema-now.fly.dev").rstrip("/")
INGEST_TOKEN = os.getenv("INGEST_TOKEN", "")

# These payloads reach a few MB for a full week of Planet screenings.
REQUEST_TIMEOUT = 180


# Poster URLs are stable for the life of a film, and the hash of one cannot
# change without the URL changing, so a fingerprint only ever has to be
# computed once. Without this cache every push re-downloaded all ~108 posters:
# harmless at six-hourly, but the task now runs every two hours, which would be
# some 1,300 fetches a day from the two chains we are most careful with.
HASH_CACHE = Path(__file__).with_name("poster_hash_cache.json")


def _load_cache() -> dict:
    try:
        return json.loads(HASH_CACHE.read_text(encoding="utf-8"))
    except Exception:
        # Missing or corrupt: start over. Costs one pass of downloads, which is
        # the behaviour before the cache existed, so it fails safe.
        return {}


def _save_cache(cache: dict) -> None:
    try:
        HASH_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    except Exception as exc:
        print(f"  (could not write poster cache: {type(exc).__name__}: {exc})")


def add_poster_hashes(movies: list[dict]) -> int:
    """Fingerprint each poster before sending.

    The server groups films across chains by their artwork, which is the only
    identity the five chains agree on -- they spell and word titles differently
    enough that title matching alone leaves duplicate cards. But it cannot do
    that for these two chains: their image servers sit behind the same
    Cloudflare block that stops it scraping them at all, so every poster fetch
    from there fails and the listings never join a group.

    This machine can reach them, so it does the fetching. Best effort -- a
    poster that will not download simply goes without, and that listing falls
    back to title grouping exactly as before.
    """
    import posters
    import requests

    cache = _load_cache()
    session = None
    downloaded = 0

    for movie in movies:
        url = movie.get("poster_url")
        if not url or movie.get("poster_hash"):
            continue

        cached = cache.get(url)
        if cached:
            movie["poster_hash"] = cached
            continue

        if session is None:
            session = requests.Session()
            session.headers["User-Agent"] = posters.USER_AGENT
        try:
            response = session.get(url, timeout=posters.REQUEST_TIMEOUT)
            response.raise_for_status()
            value = posters.dhash(response.content)
        except Exception:
            # A poster that will not fetch or decode costs this listing its
            # grouping, nothing more. Not cached, so the next run retries it.
            continue
        movie["poster_hash"] = value
        cache[url] = value
        downloaded += 1

    if downloaded:
        _save_cache(cache)
    return downloaded


def collect(chain: str, days: int) -> dict:
    """Run one chain's scraper and shape the result for the ingest endpoint."""
    scraper = SCRAPERS[chain]()
    movies = [asdict(m) for m in scraper.get_movies()]
    add_poster_hashes(movies)
    return {
        "theatres": [asdict(t) for t in scraper.get_theaters()],
        "movies": movies,
        "showtimes": [asdict(s) for s in scraper.get_showtimes(days=days)],
        # Tells the server how far ahead this payload is authoritative, so it
        # can retire screenings that vanished without touching rows beyond the
        # window we actually scraped.
        "window_days": days,
    }


def push(chain: str, payload: dict) -> dict:
    response = requests.post(
        f"{INGEST_URL}/api/ingest/{chain}",
        json=payload,
        headers={"X-Ingest-Token": INGEST_TOKEN},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code == 401:
        raise SystemExit("Rejected: INGEST_TOKEN does not match the server's.")
    if response.status_code == 503:
        raise SystemExit("Rejected: the server has no INGEST_TOKEN configured.")
    response.raise_for_status()
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("chains", nargs="*", default=None,
                        help=f"chains to push (default: {', '.join(BLOCKED_CHAINS)})")
    parser.add_argument("--days", type=int, default=9, help="days ahead to scrape")
    parser.add_argument("--dry-run", action="store_true",
                        help="scrape and report sizes without sending")
    args = parser.parse_args()

    chains = args.chains or BLOCKED_CHAINS
    unknown = [c for c in chains if c not in SCRAPERS]
    if unknown:
        print(f"Unknown chain(s): {', '.join(unknown)}")
        return 2

    if not args.dry_run and not INGEST_TOKEN:
        print("INGEST_TOKEN is not set. Add it to .env or the environment.")
        return 2

    print(f"target: {INGEST_URL}\n")
    failures = 0

    for chain in chains:
        print(f"=== {chain} ===")
        try:
            payload = collect(chain, args.days)
        except Exception as exc:
            # A chain failing here means this machine cannot reach it either,
            # which is worth saying plainly rather than pushing an empty set.
            failures += 1
            print(f"  scrape FAILED: {type(exc).__name__}: {exc}")
            continue

        # Only the record lists -- payload also carries window_days, an int.
        counts = {k: len(v) for k, v in payload.items() if isinstance(v, list)}
        hashed = sum(1 for m in payload["movies"] if m.get("poster_hash"))
        print(f"  scraped {counts['theatres']} theatres, {counts['movies']} movies, "
              f"{counts['showtimes']} showtimes, {hashed} poster hashes")

        if not payload["showtimes"]:
            # Sending nothing is harmless but almost always means a broken
            # scrape rather than a genuinely empty schedule.
            print("  nothing to send -- skipping")
            continue

        if args.dry_run:
            print("  [dry-run] not sent")
            continue

        try:
            result = push(chain, payload)
            print(f"  pushed -> {result['new_screenings']} new screenings"
                  + (f", {result['skipped_unknown']} unresolvable"
                     if result["skipped_unknown"] else "")
                  + (f", {result['retired']} retired"
                     if result.get("retired") else "")
                  + (f", {result['restored']} restored"
                     if result.get("restored") else ""))
            # The server pins each chain's checkout host and drops anything
            # else. A non-zero count here means either the chain moved its
            # booking domain or something rewrote the links in transit --
            # worth seeing in push.log rather than only in the server's logs.
            if result.get("rejected_urls"):
                print(f"  WARNING: server refused {result['rejected_urls']} ticket URL(s) "
                      f"-- run 'python ticket_urls.py' on the server to inspect")
        except SystemExit:
            raise
        except Exception as exc:
            failures += 1
            print(f"  push FAILED: {type(exc).__name__}: {exc}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
