import logging
import os
import re
import requests
from dotenv import load_dotenv
from rapidfuzz import fuzz
from database import SessionLocal
from models import SourceMovieListing, Movie
from titles import (normalize_title, title_segments, fold_for_compare,
                    near_identical, shares_script)

load_dotenv()
token = os.getenv("TMDB_TOKEN")


log = logging.getLogger(__name__)


def search_tmdb(query: str, language: str = "he-IL"):
    url = "https://api.themoviedb.org/3/search/movie"
    headers = {"Authorization": f"Bearer {token}", "accept": "application/json"}
    params = {"query": query, "language": language}
    response = requests.get(url, headers=headers, params=params, timeout=25)

    # A bad token returns 401 with no "results" key, which used to be
    # indistinguishable from an honest "no match" -- so a misconfigured
    # deployment matched nothing at all and said nothing about why. Anything
    # other than 200 is now reported.
    if response.status_code != 200:
        log.warning(
            "TMDb search failed: %s%s",
            response.status_code,
            " -- check TMDB_TOKEN is the v4 read token, not the v3 API key"
            if response.status_code == 401 else "",
        )
        return []

    return response.json().get("results", [])


def tmdb_details(tmdb_id: int, language: str = "he-IL") -> dict:
    """Canonical record for one film.

    Needed because the *search* endpoint is not enough on two counts. It never
    returns runtime at all -- which is why movies.runtime_minutes sat empty --
    and the title it echoes back is in whatever language the search asked for,
    so a Russian-title match would store Cyrillic in title_he. Asking for the
    film by id in Hebrew gives the right title regardless of how we found it.
    """
    url = f"https://api.themoviedb.org/3/movie/{tmdb_id}"
    headers = {"Authorization": f"Bearer {token}", "accept": "application/json"}
    try:
        response = requests.get(url, headers=headers, params={"language": language}, timeout=20)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return {}


def find_best_match(raw_title: str, threshold: int = 85):
    """Best TMDb match for a scraped title, trying each script it contains.

    A single query is not enough. "ЧЕЛОВЕК-ПАУК: НОВЫЙ ДЕНЬ" only matches when
    searched as Russian, while "ספיידרמן: יום חדש מדובב לרוסית - ЧЕЛОВЕК-ПАУК"
    matches on its Hebrew half. Trying every segment in its own language is what
    lets a Russian-dubbed listing collapse into the film's existing card instead
    of standing alone.
    """
    cleaned = normalize_title(raw_title)
    queries = title_segments(cleaned) or [(cleaned, "he-IL")]

    # Longest segment first, and no stopping at the first confident hit.
    #
    # Both halves of that are a fix for the same failure. Segments used to be
    # tried in the order they appear and the loop broke as soon as one scored
    # above the threshold, which means a SHORT LEADING LABEL decided the match
    # before the film's real name was ever searched. "טרום בכורה - כבשה
    # בקופסה" was searched as "טרום בכורה" first; TMDb has an entry titled
    # exactly that, it scored 100, the loop stopped, and three unrelated films
    # ended up on one card.
    #
    # normalize_title now strips that particular prefix, but the ordering was
    # the deeper problem: any leading fragment that happens to name something
    # on TMDb could do the same. Searching the most specific segment first and
    # letting every segment compete makes the winner the best evidence rather
    # than the earliest. The early exit survives only as "stop once a segment
    # matched perfectly", where nothing later can beat it.
    queries = sorted(queries, key=lambda q: len(q[0]), reverse=True)

    best_result = None
    best_score = 0.0
    best_rank = None
    best_length = 0

    for query, language in queries:
        for candidate in search_tmdb(query, language=language):
            score = _score(query, candidate)
            if score < best_score:
                continue
            # Tie-break toward the film most likely to be the one in cinemas.
            # TMDb carries "Minions & Monsters" as both a 2021 and a 2026
            # entry with identical titles; without this the older one wins by
            # arriving first and the currently-showing film splits in two.
            rank = _prominence_rank(candidate)
            if score > best_score or best_rank is None or rank > best_rank:
                best_score, best_rank, best_result = score, rank, candidate
                best_length = len(query)
        # A perfect hit on a segment cannot be improved on, so the remaining
        # (shorter) segments are not worth a request.
        if best_score >= 100:
            break

    # A short segment has to clear a higher bar than a long one. Two or three
    # words match far too many things on TMDb, and when they do it is usually
    # a label rather than a title -- which is exactly how this went wrong.
    if best_length < 12 and best_score < 95:
        return None, best_score

    if best_score >= threshold:
        return best_result, best_score
    return None, best_score




def _score(query: str, candidate: dict) -> float:
    """How well a TMDb result matches the query.

    Case-folded, because chains publish Russian titles in caps
    ("ЧЕЛОВЕК-ПАУК") while TMDb returns sentence case -- a case-sensitive ratio
    scores that correct pair at 25.

    partial_ratio is included so a chain's shortened title still matches:
    Planet lists "קיוטי נגד אקמי" where TMDb has "לוני טונס מציגים: קיוטי נגד
    אקמי", which plain ratio penalises to 61 purely for being shorter. It is
    gated on a reasonably long query, since a short one is a substring of far
    too many titles.
    """
    q = fold_for_compare(query)
    titles = [
        fold_for_compare(candidate.get("title")),
        fold_for_compare(candidate.get("original_title")),
    ]
    best = max(fuzz.ratio(q, t) for t in titles)
    if len(q) >= 8:
        # Slightly discounted: a containment match is weaker evidence than an
        # exact one, so it should not outrank a true full-title hit.
        best = max(best, max(fuzz.partial_ratio(q, t) for t in titles) - 3)
    return best


def _prominence_rank(candidate: dict) -> tuple:
    """Tie-break between candidates whose titles score identically.

    Popularity first, release year second. Year alone is the wrong signal: it
    correctly picks the 2026 "Minions & Monsters" over a 2021 entry of the same
    name, but then wrongly picks an obscure 2024 film over Pixar's Brave for a
    retro screening of "אמיצה". Popularity gets both right, because a film
    currently in cinemas -- new release or advertised revival -- is the one
    people are looking at.
    """
    year = (candidate.get("release_date") or "")[:4]
    return (candidate.get("popularity") or 0, int(year) if year.isdigit() else 0)


def find_local_match(db, raw_title: str):
    """A film we have ALREADY matched whose Hebrew title is the same as this one.

    The fallback for titles TMDb cannot find at all. Two chains spell the same
    film differently -- "אדיוטים" and "אידיוטים" -- and TMDb returns an empty
    result set for one of them, so it stays unmatched and becomes a duplicate
    card for a film that already has one.

    Searching our own movies table instead works because the OTHER spelling has
    usually already been matched by a chain that used it. Costs no request, and
    linking to the existing row means the listing inherits the real synopsis,
    runtime and original language rather than just being visually merged.
    """
    cleaned = normalize_title(raw_title)
    for movie in db.query(Movie).filter(Movie.title_he.isnot(None)):
        if near_identical(cleaned, movie.title_he):
            return movie
    return None


# How far a listing's title may drift from the film it is linked to before
# the link is treated as wrong. Two bars, because the two kinds of match carry
# different evidence:
#
#   * A TITLE match stored the score that produced it, so the titles resembled
#     each other at the time. If they no longer do, something changed
#     underneath -- and TMDb is user-edited, which is exactly what happened:
#     entry 1324241 was once labelled as the new Hunger Games and was later
#     corrected to "Regnmannen", silently leaving every listing that matched it
#     pointing at the wrong film.
#   * A POSTER or SPELLING match never involved the title, so disagreement is
#     normal there -- three chains word one opera three ways. Only total
#     unrelatedness is evidence of a mistake.
TITLE_MATCH_FLOOR = 70
ADOPTED_MATCH_FLOOR = 40


def _agreement(raw_title: str, movie) -> float | None:
    """How much a listing's title still looks like the film it is linked to.

    None means "no basis to judge", which is NOT the same as a low score and
    must not be treated as one. A Russian-dubbed listing is titled "КЛЭЙФЕЙС"
    while its film is stored as "קלייפייס": the same film, deliberately
    matched across scripts, and scoring one against the other returns nearly
    zero purely because the alphabets differ. Only titles sharing a writing
    system with the listing are compared, and if none do, the link stands.

    Learned the hard way — a repair pass that scored across scripts unlinked
    every correct Russian-to-Hebrew match it met and split those films onto
    extra cards.
    """
    cleaned = normalize_title(raw_title)
    comparable = [t for t in (movie.title_he, movie.title_en)
                  if t and shares_script(cleaned, t)]
    if not comparable:
        return None
    return max(_score(cleaned, {"title": t, "original_title": t})
               for t in comparable)


def unlink_stale_matches(db, verbose: bool = False) -> dict:
    """Break links between a listing and a film that no longer resemble each other.

    Runs before every matching pass, because matching only ever considers
    listings with no film at all -- so without this, one wrong link is
    permanent. Everything it unlinks is re-matched moments later by the pass it
    precedes, so the cost of being slightly too eager is a re-match, while the
    cost of being too timid is a wrong card that never heals.

    Both cards this was written for were of that permanent kind: four chains'
    Hunger Games listings pinned to a Norwegian film, and three different Lev
    films pinned to a TMDb entry titled "preview screening".
    """
    from models import Movie

    movies = {m.id: m for m in db.query(Movie)}
    unlinked = 0
    for listing in (
        db.query(SourceMovieListing)
        .filter(SourceMovieListing.movie_id.isnot(None))
        .all()
    ):
        movie = movies.get(listing.movie_id)
        if movie is None or not (movie.title_he or movie.title_en):
            continue
        if not normalize_title(listing.raw_title or ""):
            continue    # nothing to judge it on

        confident = (listing.match_confidence or 0) > 0
        floor = TITLE_MATCH_FLOOR if confident else ADOPTED_MATCH_FLOOR
        score = _agreement(listing.raw_title, movie)
        if score is None or score >= floor:
            continue    # agrees, or there is no shared script to judge it on

        log.info("unlinking stale match: %r was film %s (%r)",
                 listing.raw_title[:48], movie.id, (movie.title_he or "")[:32])
        if verbose:
            print(f"- {listing.raw_title} =/= {movie.title_he}")
        listing.movie_id = None
        listing.match_confidence = None
        # Cleared too: the group was computed while this listing was in the
        # wrong cluster, and leaving it would keep the card merged even after
        # the film id is corrected.
        listing.poster_group = None
        unlinked += 1

    if unlinked:
        db.commit()
    return {"unlinked": unlinked}


def match_unmatched(db, verbose: bool = False) -> dict:
    """Link every unmatched listing to a TMDb film.

    The single implementation of the matching pass, used both by running this
    module directly and by the background scheduler. It previously existed
    twice, and the copy in the scheduler quietly fell behind -- it never
    fetched canonical details, so films matched on the server came back with a
    non-Hebrew title and no runtime.
    """
    # Break any link that no longer holds before looking for new ones: a
    # listing freed here is re-matched by this same pass, in this same run.
    stale = unlink_stale_matches(db, verbose=verbose)

    pending = db.query(SourceMovieListing).filter_by(movie_id=None).all()
    matched = 0

    local = 0
    for listing in pending:
        match, score = find_best_match(listing.raw_title)
        if not match:
            # TMDb knows nothing about this spelling. Before giving up, see
            # whether we already hold the same film under the other one.
            twin = find_local_match(db, listing.raw_title)
            if twin:
                listing.movie_id = twin.id
                listing.match_confidence = 0.0   # matched locally, not by TMDb
                matched += 1
                local += 1
                log.info("spelling variant: %s -> %s (tmdb %s)",
                         listing.raw_title, twin.title_he, twin.tmdb_id)
                if verbose:
                    print(f"~ {listing.raw_title} -> {twin.title_he} (spelling variant)")
                continue
            if verbose:
                print(f"x {listing.raw_title} -> no confident match (best score: {score})")
            continue

        movie = db.query(Movie).filter_by(tmdb_id=match["id"]).first()
        if not movie:
            # By id and in Hebrew: the search echoes whatever language it was
            # queried in and carries no runtime.
            details = tmdb_details(match["id"]) or match
            poster_path = details.get("poster_path") or match.get("poster_path")
            movie = Movie(
                tmdb_id=match["id"],
                title_en=details.get("original_title") or match.get("original_title"),
                title_he=details.get("title") or match.get("title"),
                poster_url=f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None,
                release_date=details.get("release_date") or match.get("release_date"),
                overview=details.get("overview") or match.get("overview"),
                runtime_minutes=details.get("runtime"),
                original_language=details.get("original_language"),
            )
            db.add(movie)
            db.flush()

        listing.movie_id = movie.id
        listing.match_confidence = score
        matched += 1
        if verbose:
            print(f"v {listing.raw_title} -> {movie.title_he} (score: {score})")

    db.commit()
    return {"considered": len(pending), "matched": matched,
            "spelling_variants": local, "unlinked": stale["unlinked"]}


if __name__ == "__main__":
    db = SessionLocal()
    stats = match_unmatched(db, verbose=True)
    db.close()
    print(f"\nDone. Matched: {stats['matched']}, "
          f"Unmatched: {stats['considered'] - stats['matched']}")
