import os
import re
import requests
from dotenv import load_dotenv
from rapidfuzz import fuzz
from database import SessionLocal
from models import SourceMovieListing, Movie

load_dotenv()
token = os.getenv("TMDB_TOKEN")


def search_tmdb(query: str, language: str = "he-IL"):
    url = "https://api.themoviedb.org/3/search/movie"
    headers = {"Authorization": f"Bearer {token}", "accept": "application/json"}
    params = {"query": query, "language": language}
    response = requests.get(url, headers=headers, params=params)
    return response.json().get("results", [])


def normalize_title(title: str) -> str:
    # Strip dub/language suffixes like "-מדובב", "-אנגלית", "-מדובב לצרפתית", etc.
    # Pattern: a dash, followed by מדובב/אנגלית, optionally followed by
    # a "ל<language>" word (e.g. "לצרפתית"), anchored to the end of the string.
    title = re.sub(r"-\s*(מדובב|אנגלית)(\s+ל\S+)?\s*$", "", title)
    return title.strip()


def find_best_match(raw_title: str, threshold: int = 85):
    cleaned = normalize_title(raw_title)
    candidates = search_tmdb(cleaned)

    if not candidates:
        return None, 0

    best_result = None
    best_score = 0

    for candidate in candidates:
        candidate_title = candidate.get("title", "")
        score = fuzz.ratio(cleaned, candidate_title)
        if score > best_score:
            best_score = score
            best_result = candidate

    if best_score >= threshold:
        return best_result, best_score
    return None, best_score


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
                # Save it as a new Movie record
                poster_path = match.get("poster_path")
                poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None

                movie = Movie(
                    tmdb_id=match["id"],
                    title_en=match.get("original_title"),  # closest to English we have from this call
                    title_he=match.get("title"),            # this IS Hebrew, since we searched with language=he-IL
                    poster_url=poster_url,
                    release_date=match.get("release_date"),
                    overview=match.get("overview"),
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