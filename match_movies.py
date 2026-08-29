import os
import re
import requests
from dotenv import load_dotenv
from rapidfuzz import fuzz
from database import SessionLocal
from models import SourceMovieListing, Movie
from titles import normalize_title, title_segments, fold_for_compare

load_dotenv()
token = os.getenv("TMDB_TOKEN")


def search_tmdb(query: str, language: str = "he-IL"):
    url = "https://api.themoviedb.org/3/search/movie"
    headers = {"Authorization": f"Bearer {token}", "accept": "application/json"}
    params = {"query": query, "language": language}
    response = requests.get(url, headers=headers, params=params)
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

    best_result = None
    best_score = 0.0
    best_rank = None

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
        if best_score >= threshold:
            break

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


if __name__ == "__main__":
    db = SessionLocal()
    listings = db.query(SourceMovieListing).filter_by(movie_id=None).all()

    print(f"Found {len(listings)} unmatched listings\n")

    matched_count = 0
    unmatched_count = 0

    for listing in listings:
        match, score = find_best_match(listing.raw_title)

        if match:
            # Check if we already have this TMDb movie saved
            movie = db.query(Movie).filter_by(tmdb_id=match["id"]).first()

            if not movie:
                # Fetch the film by id in Hebrew rather than trusting the search
                # result: the search echoes titles in whichever language it was
                # queried with, and carries no runtime.
                details = tmdb_details(match["id"]) or match
                poster_path = details.get("poster_path") or match.get("poster_path")
                poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None

                movie = Movie(
                    tmdb_id=match["id"],
                    title_en=details.get("original_title") or match.get("original_title"),
                    title_he=details.get("title") or match.get("title"),
                    poster_url=poster_url,
                    release_date=details.get("release_date") or match.get("release_date"),
                    overview=details.get("overview") or match.get("overview"),
                    runtime_minutes=details.get("runtime"),
                    original_language=details.get("original_language"),
                )
                db.add(movie)
                db.commit()
                db.refresh(movie)

            # Link the listing to this movie, with its confidence score
            listing.movie_id = movie.id
            listing.match_confidence = score
            matched_count += 1
            print(f"✓ {listing.raw_title} -> {movie.title_he} (score: {score})")
        else:
            unmatched_count += 1
            print(f"✗ {listing.raw_title} -> no confident match (best score: {score})")

    db.commit()
    db.close()
    print(f"\nDone. Matched: {matched_count}, Unmatched: {unmatched_count}")

    db.close()