"""Identify the same film across chains by its poster.

Titles are an unreliable key. The chains spell the same film differently
("אדיוטים" / "אידיוטים"), word it differently ("לה טראוויאטה - אופרה בקולנוע" /
"אופרה בקולנוע-לה טראוויאטה"), and TMDb's search returns nothing at all for some
of those spellings -- so a film ends up with one card per wording.

The artwork does not vary. Every chain publishes the same poster, just at its
own size and re-encoded, so the bytes and the URL differ while the image does
not. A perceptual hash sees through that.

Measured on real posters from this catalogue, with a 256-bit dHash:

    same film, different chains      0, 5, 6, 7, 10
    different films                  112, 113, 131, 134

There is no overlap and an enormous gap, which is why the threshold below can
sit at 25 and still be nowhere near either side. Compare that with titles, where
the safe threshold had to be tuned to avoid merging "מואנה" with "מונה".

Hashing happens once per listing and is stored, so nothing is downloaded on the
serving path. Failure is silent by design: a poster that will not download or
decode leaves poster_hash NULL and the listing groups by title exactly as it did
before.
"""

import io
import logging
from datetime import datetime

import requests

from models import SourceMovieListing

log = logging.getLogger("posters")

# 16 -> a 16x17 grayscale grid -> 256 comparisons -> 256-bit hash.
HASH_SIZE = 16

# Same-film pairs measured at most 10 apart, different films at least 112.
# 25 sits far from both, so a cropped or recoloured variant still matches and
# two genuinely different posters never do.
MAX_DISTANCE = 25

REQUEST_TIMEOUT = 25

# Some chains serve posters only to a browser-shaped request; base.py sets the
# same UA for the same reason.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def dhash(data: bytes, size: int = HASH_SIZE) -> str:
    """Difference hash of an image, as hex.

    Each bit records whether one pixel is brighter than the pixel to its right,
    on a tiny greyscale copy. That makes it blind to scale, re-encoding and
    modest colour shifts -- exactly the differences between two chains' copies
    of one poster -- while staying sensitive to actual composition.
    """
    from PIL import Image

    image = Image.open(io.BytesIO(data)).convert("L").resize(
        (size + 1, size), Image.LANCZOS
    )
    pixels = list(image.getdata())
    bits = 0
    for row in range(size):
        offset = row * (size + 1)
        for col in range(size):
            brighter = pixels[offset + col] < pixels[offset + col + 1]
            bits = (bits << 1) | (1 if brighter else 0)
    return f"{bits:0{size * size // 4}x}"


def distance(a: str | None, b: str | None) -> int:
    """Hamming distance between two hex hashes. Large number if either is absent."""
    if not a or not b:
        return 10_000
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def _fetch(url: str, session: requests.Session) -> str | None:
    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return dhash(response.content)
    except Exception as exc:
        # Not worth an error: a chain with a broken poster link should cost us
        # a grouping opportunity, never a scrape.
        log.debug("poster hash failed for %s: %s: %s", url, type(exc).__name__, exc)
        return None


def hash_missing(db, limit: int | None = None) -> dict:
    """Hash every listing that has a poster and no hash yet.

    Incremental: after the first pass this only touches newly added films, so
    it costs a handful of requests per sync rather than a few hundred.
    """
    pending = (
        db.query(SourceMovieListing)
        .filter(SourceMovieListing.poster_url.isnot(None))
        .filter(SourceMovieListing.poster_hash.is_(None))
        .all()
    )
    if limit:
        pending = pending[:limit]
    if not pending:
        return {"considered": 0, "hashed": 0}

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    hashed = 0
    for listing in pending:
        value = _fetch(listing.poster_url, session)
        if value:
            listing.poster_hash = value
            hashed += 1
    db.commit()
    if hashed:
        log.info("hashed %s new poster(s)", hashed)
    return {"considered": len(pending), "hashed": hashed}


def group(db) -> dict:
    """Cluster listings by poster and record which cluster each belongs to.

    Union-find, not greedy assignment against a representative. Greedy is
    order-dependent and splits real groups: if A is within range of B and B of
    C, but A and C are just outside it, whichever of A or C is seen first
    becomes a representative and the other starts a second cluster for the same
    film. That happened -- one film came out as three cards.

    Transitivity is safe here precisely because of the gap in the measurements:
    chaining two different films together would need a run of near-misses
    spanning a hundred bits, and the closest unrelated pair observed is 112.

    Where a cluster contains a listing TMDb already matched, that film id is
    copied to the rest. This is what pulls a stubborn spelling onto the real
    card, complete with synopsis and runtime, rather than merely drawing them
    side by side.
    """
    listings = (
        db.query(SourceMovieListing)
        .filter(SourceMovieListing.poster_hash.isnot(None))
        .order_by(SourceMovieListing.id)
        .all()
    )

    parent = list(range(len(listings)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        a, b = find(i), find(j)
        if a != b:
            parent[max(a, b)] = min(a, b)

    for i in range(len(listings)):
        for j in range(i + 1, len(listings)):
            if find(i) == find(j):
                continue
            if distance(listings[i].poster_hash, listings[j].poster_hash) <= MAX_DISTANCE:
                union(i, j)

    clusters: dict[int, list] = {}
    for index, listing in enumerate(listings):
        clusters.setdefault(find(index), []).append(listing)

    grouped = adopted = 0
    for root, members in clusters.items():
        # The lowest listing id in the cluster names it, so the group key is
        # stable across runs rather than depending on iteration order.
        rep_hash = listings[root].poster_hash
        for member in members:
            if member.poster_group != rep_hash:
                member.poster_group = rep_hash
                grouped += 1

        if len(members) < 2:
            continue

        # Propagate a known film id across the cluster.
        known = next((m.movie_id for m in members if m.movie_id), None)
        if not known:
            continue
        for member in members:
            if not member.movie_id:
                member.movie_id = known
                member.match_confidence = 0.0    # matched by poster, not TMDb
                adopted += 1
                log.info("poster match: %s -> film %s", member.raw_title[:50], known)

    db.commit()
    multi = sum(1 for members in clusters.values() if len(members) > 1)
    return {
        "listings": len(listings),
        "clusters": len(clusters),
        "multi_chain_clusters": multi,
        "grouped": grouped,
        "adopted": adopted,
    }


def run(db=None) -> dict:
    """Hash whatever is new, then regroup. Safe to call after every sync."""
    from database import SessionLocal

    own = db is None
    db = db or SessionLocal()
    try:
        hashed = hash_missing(db)
        clustered = group(db)
        return {**hashed, **clustered}
    finally:
        if own:
            db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")
    print(run())
