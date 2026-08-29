"""Whitelist the destinations a showtime link is allowed to point at.

Every screening carries a ticket_url that the app renders as the one button a
user actually taps to spend money. Nothing else in the pipeline constrains that
string, and the trust story is not the same for all five chains:

    cinema_city, hot_cinema, lev   built here from a constant template and an
                                   id, so the host is ours by construction

    movieland, planet              copied verbatim out of the chain's own JSON,
                                   and both arrive over the ingest endpoint
                                   from a machine outside this deployment

For the second group the host is whatever the upstream response said it was.
That is fine while the upstream is honest, but "the link is safe because the
site we scraped is trustworthy and the courier PC is uncompromised and the
ingest token has not leaked" is a chain of three assumptions guarding a
checkout page. A phishing host that renders a convincing Cinema City payment
form is the whole attack -- no XSS required, and React's URL sanitiser does not
help because https://evil.example is a perfectly ordinary URL.

So the host is checked against this table at write time. After this, the
guarantee is structural rather than circumstantial: a stored ticket_url points
at one of five known hosts over https, whatever the scraper, the upstream or a
token-holder tried to store.

Keep entries exact. A suffix test like endswith(".co.il") would accept
evil.co.il, and endswith("lev.co.il") would accept notlev.co.il.
"""

import re
from urllib.parse import unquote, urlparse

# Host AND path prefix, because the host alone is not enough. If any of these
# sites has an open redirect -- a /go?url= or /out?target= of the kind that is
# extremely common -- then https://www.planetcinema.co.il/go?url=https://evil
# passes a host-only check and still lands the user on the attacker's page.
# Planet's own booking path is literally called "booking-router".
#
# Pinning the path is what makes that impossible: the link may only point into
# the part of the site that sells tickets. Verified as a prefix against all
# 16,707 stored URLs, which fit exactly one shape per chain with no exceptions.
#
# A prefix rather than the full shape on purpose. The chains change ids and add
# query parameters routinely, and a rule tight enough to break on that would
# cost a whole chain's listings every time. The prefix is the part that decides
# where the user lands.
ALLOWED: dict[str, tuple[frozenset[str], str]] = {
    "cinema_city": (frozenset({"tickets.cinema-city.co.il"}), "/order/"),
    "hot_cinema": (frozenset({"hotcinema.co.il", "www.hotcinema.co.il"}), "/order"),
    "lev": (frozenset({"lev.co.il", "www.lev.co.il"}), "/order"),
    # Movieland outsources checkout, so its link legitimately leaves the
    # chain's own domain. That is exactly why it needs pinning.
    "movieland": (frozenset({"ecom.biggerpicture.ai"}), "/site/"),
    "planet": (frozenset({"planetcinema.co.il", "www.planetcinema.co.il"}), "/il/booking-router/"),
}

# Backwards-compatible view, and the thing to read when you just want the hosts.
ALLOWED_HOSTS: dict[str, frozenset[str]] = {k: v[0] for k, v in ALLOWED.items()}

# A scheme buried anywhere in the link -- "https://", "//evil.example", or an
# encoded form of either. No legitimate ticket URL contains one: the real ones
# carry numeric ids, a sale-channel code and a language, nothing that nests
# another address. Anything that does is trying to be followed rather than read.
_EMBEDDED_URL = re.compile(r"(?:[a-z][a-z0-9+.\-]*:)?//", re.I)


def _hides_a_url(parsed) -> bool:
    """Whether anything after the host smuggles in a second address.

    Decoded repeatedly, because a single unquote turns %252F%252F into %2F%2F
    rather than // -- double-encoding is the standard way past a filter that
    only looks once.
    """
    probe = (parsed.path or "") + "?" + (parsed.query or "") + "#" + (parsed.fragment or "")
    for _ in range(3):
        if _EMBEDDED_URL.search(probe):
            return True
        decoded = unquote(probe)
        if decoded == probe:
            break
        probe = decoded
    return bool(_EMBEDDED_URL.search(probe))


def rejection_reason(chain: str, url: str | None) -> str | None:
    """Why this URL may not be stored, or None if it is acceptable.

    Returns prose rather than a bool so the caller can log something that
    identifies the offending host -- a silent drop would turn an attempted
    injection, or a chain quietly moving its checkout, into an unexplained
    fall in screening counts.
    """
    if not url:
        return "empty ticket_url"

    entry = ALLOWED.get(chain)
    if entry is None:
        return f"no allowlist defined for chain '{chain}'"
    allowed_hosts, required_path = entry

    try:
        parsed = urlparse(url)
    except ValueError as exc:
        return f"unparseable ticket_url ({exc})"

    # https only: these links carry a booking session, and an http:// link
    # would be a downgrade a network attacker could sit on.
    if parsed.scheme != "https":
        return f"scheme '{parsed.scheme}' is not https"

    # .hostname, not .netloc: netloc keeps any "user:pass@" prefix and port,
    # and "https://tickets.cinema-city.co.il@evil.example/" has a netloc that
    # begins with the real host while pointing at evil.example.
    host = (parsed.hostname or "").lower()
    if host not in allowed_hosts:
        return f"host '{host}' is not an allowed {chain} checkout host"

    if not (parsed.path or "").startswith(required_path):
        return (f"path '{parsed.path}' is outside {chain}'s booking area "
                f"('{required_path}...')")

    if _hides_a_url(parsed):
        return "link contains a second embedded URL"

    return None


def is_allowed(chain: str, url: str | None) -> bool:
    return rejection_reason(chain, url) is None


def audit(db) -> list[tuple[str, str, str]]:
    """Every stored ticket_url that would not be accepted today.

    The allowlist only guards new writes, so it cannot speak for rows written
    before it existed, nor notice a chain quietly moving its checkout to a new
    host months from now. Running this is how that gets caught.
    """
    from models import CinemaSource, Screening, SourceMovieListing

    rows = (
        db.query(CinemaSource.key, Screening.ticket_url)
        .join(SourceMovieListing, SourceMovieListing.cinema_source_id == CinemaSource.id)
        .join(Screening, Screening.source_movie_listing_id == SourceMovieListing.id)
        .all()
    )
    bad = []
    for chain, url in rows:
        reason = rejection_reason(chain, url)
        if reason:
            bad.append((chain, url, reason))
    return bad


if __name__ == "__main__":
    from database import SessionLocal

    db = SessionLocal()
    try:
        offenders = audit(db)
    finally:
        db.close()

    if not offenders:
        print("All stored ticket URLs are on the allowlist.")
    else:
        print(f"{len(offenders)} stored ticket URL(s) would be refused:\n")
        for chain, url, reason in offenders[:40]:
            print(f"  [{chain}] {reason}\n      {url}")
