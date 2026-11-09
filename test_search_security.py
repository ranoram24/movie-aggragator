"""Attack every path that carries request input, and report anything that gets through.

    python test_search_security.py
    python test_search_security.py --url https://on-cinema-now.fly.dev

Companion to test_ticket_url_security.py, which covers the links we hand OUT.
This one covers what comes IN. Run it after touching api_movies.py, main.py, or
the search box.

The offline half needs no network and writes nothing. The --url half is
read-only too: it sends hostile GETs and checks what comes back, then confirms
the API still works, which is how a successful injection would announce itself.

## What actually crosses the boundary

The search boxes do not. Both filter arrays the client already holds (see
frontend/src/api/search.ts), so a query is never serialised into a request and
cannot reach SQL -- the strongest version of that defence is that the data path
does not exist, and TEST 1 asserts it stays that way.

What does cross: `?chains=`, the `/api/movies/{film_id}` path segment, `lat`,
`lon`, `limit`, and every unmatched URL via the SPA fallback. Those are what the
rest of this file attacks.

## The one that was real

TEST 5. The SPA fallback joined the request path onto the build directory with
no containment check, which served arbitrary files off the production host --
/etc/passwd and the app's own source, confirmed against the live deployment in
November 2026. FastAPI hands a {path:path} parameter over percent-decoded, so
`/..%2f..%2f..%2fetc/passwd` arrives as `../../../etc/passwd` with nothing in
front of it having normalised anything. The lesson worth keeping: the injection
risk here was never the search box the feature added, it was the oldest and
most boring line of routing in the app.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent

# Payloads that must never be interpreted as anything but opaque text.
SQL_PAYLOADS = [
    "' OR '1'='1",
    "'; DROP TABLE screenings; --",
    '" OR 1=1 --',
    "1; DELETE FROM theatres",
    "planet' UNION SELECT token FROM cinema_sources --",
    "admin'--",
    "' OR 1=1 /*",
    ") OR ('a'='a",
    "%27%20OR%201%3D1",          # pre-encoded, in case something decodes twice
    "cinema_city\x00planet",     # NUL truncation
]

XSS_PAYLOADS = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    '"><svg/onload=alert(1)>',
    "javascript:alert(1)",
    "</script><script>alert(1)</script>",
]

# Each must NOT return the file it is reaching for.
TRAVERSAL_PAYLOADS = [
    "/%2e%2e%2f%2e%2e%2f%2e%2e%2fetc/passwd",
    "/..%2f..%2f..%2fetc%2fpasswd",
    "/%2e%2e/%2e%2e/%2e%2e/etc/passwd",
    "/..%2f..%2fmain.py",
    "/..%2f..%2fapi_movies.py",
    "/..%2f..%2f.env",
    "/..%2f..%2f..%2fdata%2fmovie_aggregator.db",
    "/..%2f..%2f..%2fproc%2fself%2fenviron",
    "/%2e%2e%5c%2e%2e%5cmain.py",            # backslash, for a Windows host
    "/....//....//etc/passwd",
    "/..%252f..%252fmain.py",                # double-encoded (CWE-174)
]

results: list[tuple[bool, str]] = []


def record(ok: bool, label: str) -> None:
    results.append((ok, label))


# Block comments, then line comments. The negative lookbehind keeps "https://"
# intact, since a // inside a string literal is not a comment -- without it the
# scanner eats the rest of any line containing a URL.
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT_RE = re.compile(r"(?<!:)//[^\n]*")


def code_only(source: str) -> str:
    """Source with its comments removed.

    Both of the scanners below search for identifiers, and on the first run
    both reported a file for a name that appeared only in a comment ABOUT the
    rule -- SearchBar.tsx documents that it contains no dangerouslySetInnerHTML
    and was flagged for saying so. A sink named in prose is not a sink, and a
    check that cannot tell the difference trains you to ignore it.
    """
    return _LINE_COMMENT_RE.sub("", _BLOCK_COMMENT_RE.sub("", source))


def section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


# ------------------------------------------------------------------ 1. the claim

def test_search_stays_client_side() -> None:
    """The search query must have no route to the server.

    Asserted structurally rather than by probing, because the property worth
    protecting is the absence of a code path: no fetch inside the matcher, and
    no caller handing a query to the API client. If a later change adds
    server-side search, this fails and the rest of this file stops being a
    complete account of the input surface.
    """
    section("1. search never reaches the server")

    matcher = code_only((ROOT / "frontend/src/api/search.ts").read_text(encoding="utf-8"))
    for forbidden in ("fetch(", "XMLHttpRequest", "axios", "import.meta.env"):
        record(forbidden not in matcher,
               f"matcher does not reference {forbidden}")

    # No request-building code may carry a free-text key. Checked as a property
    # name in code rather than by looking for the word "search", which appears
    # legitimately in both files' comments and in URLSearchParams.
    client = code_only((ROOT / "frontend/src/api/client.ts").read_text(encoding="utf-8"))
    record(not re.search(r"\b(q|search|query|title|name)\s*:", client),
           "api client sends no free-text parameter")
    record("search" not in client.replace("searchParams", ""),
           "api client does not import the matcher")

    # The backend must expose no q=/search= parameter either.
    api = (ROOT / "api_movies.py").read_text(encoding="utf-8")
    record(not re.search(r'Query\(.*\b(q|search|title|name)\b\s*=', api),
           "no server-side search parameter exists")


# ------------------------------------------------------------------ 2. XSS sinks

def test_no_xss_sinks() -> None:
    """No way to turn a string into markup, anywhere in the app.

    React escapes interpolated text, so the defence is simply never opting out
    of it. These are the opt-outs.
    """
    section("2. no XSS sinks in the frontend")

    sinks = ["dangerouslySetInnerHTML", "innerHTML", "outerHTML",
             "document.write", "eval(", "new Function", "srcdoc",
             "insertAdjacentHTML"]
    sources = list((ROOT / "frontend/src").rglob("*.ts")) + \
              list((ROOT / "frontend/src").rglob("*.tsx"))
    record(bool(sources), "frontend sources found")

    for sink in sinks:
        hits = [f.relative_to(ROOT).as_posix()
                for f in sources
                if sink in code_only(f.read_text(encoding="utf-8"))]
        record(not hits, f"no {sink}" + (f" (found in {hits})" if hits else ""))

    # The query is also never used to build a URL, which is the other way text
    # becomes executable (javascript: in an href).
    for name in ("components/SearchBar.tsx", "screens/BrowseScreen.tsx",
                 "screens/MovieDetailScreen.tsx"):
        text = code_only((ROOT / "frontend/src" / name).read_text(encoding="utf-8"))
        hrefs = re.findall(r"(?:href|src|action|style)=\{([^}]*)\}", text)
        tainted = [h for h in hrefs
                   if re.search(r"\b(query|city|value)\b", h)]
        record(not tainted, f"{name} never puts the query in a URL or style"
                            + (f" ({tainted})" if tainted else ""))


# ------------------------------------------------------------------ 3. SQL

def test_sql_is_parameterised() -> None:
    """Run the payloads through the real query path against the real database.

    Not a source inspection: the payloads are bound as values to the same
    SQLAlchemy queries the endpoints use, and the test passes only if they come
    back as zero rows with the tables still standing. A string that became SQL
    would either error, return everything, or drop something.
    """
    section("3. SQL injection through the live query path")

    from database import SessionLocal
    from models import CinemaSource, Screening, SourceMovieListing, Theatre
    from api_movies import _chain_filter, canonical_movie_ids, listing_ids_for_film

    db = SessionLocal()
    try:
        before = {
            "sources": db.query(CinemaSource).count(),
            "theatres": db.query(Theatre).count(),
            "listings": db.query(SourceMovieListing).count(),
            "screenings": db.query(Screening).count(),
        }
        record(all(v > 0 for v in before.values()),
               f"database populated: {before}")

        canonical = canonical_movie_ids(db)

        for payload in SQL_PAYLOADS + XSS_PAYLOADS:
            label = payload[:34].replace("\x00", "\\0")

            # ?chains= -- parsed to a set, then compared in Python. Never SQL.
            parsed = _chain_filter(payload)
            record(all(isinstance(k, str) for k in parsed),
                   f"chains parses to strings: {label}")

            # The same value bound into the queries the endpoints run.
            try:
                rows = db.query(CinemaSource).filter(
                    CinemaSource.key == payload).all()
                record(rows == [], f"no rows for chain key: {label}")

                hits = db.query(Theatre).filter(
                    Theatre.name.like(f"%{payload}%")).all()
                record(hits == [], f"LIKE finds nothing for: {label}")
            except Exception as exc:
                record(False, f"query RAISED for {label}: {type(exc).__name__}")

            # /api/movies/{film_id} -- resolved by comparing in Python.
            try:
                ids = listing_ids_for_film(db, payload, canonical)
                record(ids == [], f"film id resolves to nothing: {label}")
            except Exception as exc:
                record(False, f"film id RAISED for {label}: {type(exc).__name__}")

        # Nothing was dropped, deleted or truncated along the way.
        db.expire_all()
        after = {
            "sources": db.query(CinemaSource).count(),
            "theatres": db.query(Theatre).count(),
            "listings": db.query(SourceMovieListing).count(),
            "screenings": db.query(Screening).count(),
        }
        record(before == after, f"row counts unchanged: {after}")
    finally:
        db.close()


# ------------------------------------------------------------------ 4. raw SQL

def test_no_raw_sql_with_input() -> None:
    """No f-string reaches a cursor carrying anything request-shaped.

    migrate.py does interpolate, because SQLite cannot parameterise an
    identifier in ALTER TABLE. Its values come from the model metadata in
    models.py -- names fixed in the source, never from a request -- so it is
    allowed here by name, and that is the exemption to re-examine if the
    migration ever takes an argument.
    """
    section("4. no raw SQL carrying request input")

    allowed = {"migrate.py"}
    for path in sorted(ROOT.glob("*.py")):
        if path.name.startswith("test_"):
            continue
        text = path.read_text(encoding="utf-8")
        interpolated = re.findall(r'text\(\s*f["\']', text)
        ok = not interpolated or path.name in allowed
        record(ok, f"{path.name}: "
                   + ("no interpolated SQL" if not interpolated
                      else "interpolated SQL, allowlisted (internal identifiers)"))


# ------------------------------------------------------------------ 5. traversal

def test_spa_fallback_contains_paths() -> None:
    """The SPA fallback must refuse a path that escapes the build directory.

    This is the regression test for the real finding. Exercised against the
    handler's own logic so it runs without a server or a built frontend.
    """
    section("5. SPA fallback path containment")

    root = (ROOT / "frontend" / "dist").resolve()

    def allowed(full_path: str) -> bool:
        """The containment rule as main.py now implements it."""
        candidate = (root / full_path).resolve()
        inside = candidate == root or candidate.is_relative_to(root)
        return bool(full_path) and inside

    escapes = [
        "../../../etc/passwd",          # what FastAPI hands over after decoding
        "../../main.py",
        "../../.env",
        "../../../data/movie_aggregator.db",
        "../../../proc/self/environ",
        "..\\..\\main.py",
        "a/../../../etc/passwd",        # escapes only after normalising
        "./../../main.py",
        "/etc/passwd",                  # absolute, which / joining honours
    ]
    for path in escapes:
        record(not allowed(path), f"refused: {path}")

    for path in ["index.html", "assets/index.js", "favicon.ico",
                 "movie/m17", "a/b/c.png"]:
        record(allowed(path), f"still reachable: {path}")

    # And that the deployed handler carries the check at all.
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    record("is_relative_to" in source and ".resolve()" in source,
           "main.py performs resolve + containment")


# ------------------------------------------------------------------ 6. live

def test_live(base: str) -> None:
    """Hostile GETs against a running server. Read-only."""
    import requests

    section(f"6. live probes against {base}")
    session = requests.Session()
    session.headers["User-Agent"] = "on-cinema-security-test"

    def get(path: str, **kwargs):
        return session.get(f"{base}{path}", timeout=30, **kwargs)

    baseline = get("/api/movies?limit=5")
    record(baseline.status_code == 200, f"baseline /api/movies -> {baseline.status_code}")

    # Traversal. A refusal looks like the SPA's index.html, so compare against
    # it: equal body means the fallback fired, which is the correct answer.
    index = get("/").text
    for path in TRAVERSAL_PAYLOADS:
        response = session.get(f"{base}{path}", timeout=30, allow_redirects=False)
        body = response.text
        leaked = (
            "root:x:0:0" in body                     # /etc/passwd
            or body.lstrip().startswith("import ")   # python source
            or "INGEST_TOKEN" in body
            or "TMDB_TOKEN" in body
            or "SQLite format" in body
        )
        served_app = body == index or "<!doctype html" in body[:200].lower()
        record(not leaked and (served_app or response.status_code in (400, 403, 404)),
               f"traversal refused ({response.status_code}): {path}")

    # ?chains= and the film id path.
    for payload in SQL_PAYLOADS + XSS_PAYLOADS:
        label = payload[:30].replace("\x00", "\\0")

        response = get("/api/movies", params={"chains": payload, "limit": 5})
        record(response.status_code == 200 and response.json() == [],
               f"chains={label} -> {response.status_code}, empty")

        # Two different routes can answer this, depending on the payload.
        # A payload containing a slash -- "</script>", "/*" -- is more than one
        # path segment, so it never matches /api/movies/{film_id} and falls
        # through to the SPA, which answers 200 text/html. That is not a
        # finding: the HTML is the static build, identical for every request.
        #
        # So the assertion is the property both routes must have rather than a
        # status code: the payload does not come back. An echoed <script> in an
        # HTML response would be reflected XSS; in a JSON response it would be
        # inert but still worth knowing about.
        response = get(f"/api/movies/{payload}")
        reflected = payload.strip() and payload in response.text
        record(not reflected, f"film id {label} is not reflected "
                              f"({response.status_code})")
        record(response.status_code in (200, 404, 422),
               f"film id {label} -> {response.status_code}, no server error")
        if "application/json" in response.headers.get("content-type", ""):
            # It did reach the endpoint, so the clipped detail applies.
            detail = response.json().get("detail", "")
            record(len(detail) < 200, f"film id {label} detail is bounded")

    # Out-of-range numerics are rejected by the schema, not clamped silently.
    for params in [{"lat": 999}, {"lon": -999}, {"limit": 99999},
                   {"limit": "abc"}, {"lat": "'; DROP TABLE x--"}]:
        response = get("/api/movies", params=params)
        record(response.status_code == 422,
               f"rejected {params} -> {response.status_code}")

    # Still alive and still correct after all of that.
    final = get("/api/movies?limit=5")
    record(final.status_code == 200 and len(final.json()) > 0,
           "API still serving after the run")
    record(len(final.json()) == len(baseline.json()),
           "same number of films as before the run")


# ------------------------------------------------------------------ main

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="Also probe a running server, e.g. "
                                      "https://on-cinema-now.fly.dev")
    args = parser.parse_args()

    test_search_stays_client_side()
    test_no_xss_sinks()
    test_no_raw_sql_with_input()
    test_spa_fallback_contains_paths()
    try:
        test_sql_is_parameterised()
    except Exception as exc:
        record(False, f"database tests could not run: {type(exc).__name__}: {exc}")

    if args.url:
        test_live(args.url.rstrip("/"))

    failed = [label for ok, label in results if not ok]
    passed = len(results) - len(failed)

    print(f"\n{'=' * 60}\n{passed} passed, {len(failed)} failed")
    if failed:
        print("\nFAILURES:")
        for label in failed:
            print(f"  ✗ {label}")
        return 1
    print("every input path held\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
