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


# Language/format markers that trail a title. The separator varies by chain:
# Cinema City writes "-מדובב", Movieland "(מדובב)", Hot Cinema " מדובב לעברית".
# All three are the same film, so all three have to normalize identically or the
# same movie shows up as several separate cards.
DUB_WORDS = r"(?:מדובב(?:ת)?|אנגלית|דובר(?:ת)?\s+עברית)"
DUB_SUFFIX_RE = re.compile(rf"[\s\-–—]*\(?\s*{DUB_WORDS}(?:\s+ל?\S+)?\s*\)?\s*$")

# Programming strands the cinemas prepend to an ordinary film, e.g.
# "סינמה נוסטלגיה - פלונטר" is just פלונטר shown in a retro season.
STRAND_PREFIX_RE = re.compile(r"^\s*(?:סינמה נוסטלגיה|קלאסיקה|מועדון[^-–]{0,20})\s*[-–]\s*")

# Trailing event blurbs, e.g. "לה לה לנד-חגיגות העשור".
EVENT_SUFFIX_RE = re.compile(r"\s*[-–]\s*(?:חגיגות[^-–]*|הקרנה מיוחדת|שיח יוצרים.*)\s*$")


def normalize_title(title: str) -> str:
    """Strip chain-specific decoration so the same film matches across all five.

    Applied repeatedly because the markers stack -- Hot Cinema produces titles
    like "סינמה נוסטלגיה - מלך האריות 1994 מדובב לעברית", which needs a prefix
    and a suffix removed before TMDb has any chance of matching it.
    """
    title = STRAND_PREFIX_RE.sub("", title)
    previous = None
    while previous != title:
        previous = title
        title = DUB_SUFFIX_RE.sub("", title)
        title = EVENT_SUFFIX_RE.sub("", title)
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