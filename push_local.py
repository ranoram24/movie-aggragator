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
import os
import sys
from dataclasses import asdict

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


def collect(chain: str, days: int) -> dict:
    """Run one chain's scraper and shape the result for the ingest endpoint."""
    scraper = SCRAPERS[chain]()
    return {
        "theatres": [asdict(t) for t in scraper.get_theaters()],
        "movies": [asdict(m) for m in scraper.get_movies()],
        "showtimes": [asdict(s) for s in scraper.get_showtimes(days=days)],
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
    parser.add_argument("--days", type=int, default=7, help="days ahead to scrape")
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

        counts = {k: len(v) for k, v in payload.items()}
        print(f"  scraped {counts['theatres']} theatres, {counts['movies']} movies, "
              f"{counts['showtimes']} showtimes")

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
                     if result["skipped_unknown"] else ""))
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
