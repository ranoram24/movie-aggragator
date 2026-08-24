import requests
import json
import re
from bs4 import BeautifulSoup

BASE = "https://www.cinema-city.co.il"

# A plain Session is enough. The site sets no cookies and none of these
# endpoints check User-Agent, Referer or X-Requested-With -- verified by
# calling all of them from a bare session with no headers at all.
session = requests.Session()


def fetch_movies_page():
    url = f"{BASE}/movies"
    response = session.get(url)
    print(f"Homepage status: {response.status_code}")
    print(f"Redirect history: {[r.url for r in response.history]}")
    return response.text


def extract_theaters(html: str):
    # Find the theatersAll([...]) call and pull out the JSON array inside it
    match = re.search(r"theatersAll\((\[.*?\])\);", html, re.DOTALL)
    if not match:
        raise ValueError("Could not find theatersAll JSON in page")

    theaters_json = match.group(1)
    theaters = json.loads(theaters_json)
    return theaters


def extract_movies(html: str):
    soup = BeautifulSoup(html, "html.parser")
    movie_blocks = soup.find_all("div", class_="movie-thumb")

    movies = []
    for block in movie_blocks:
        link = block.get("data-linkmobile", "")
        movie_id = link.split("/")[-1] if link else None

        title_tag = block.find("h2")
        title = title_tag.get_text(strip=True) if title_tag else None

        img_tag = block.find("img", class_="flip-thumb")
        poster_url = img_tag.get("src") if img_tag else None

        # Metadata lives inside <p class="flip-link"> tags on the back panel,
        # each shaped like: <p class="flip-link">סיווג <span>קומדיה</span></p>
        genre = runtime = premiere_date = age_rating = None
        for p in block.find_all("p", class_="flip-link"):
            label = p.get_text(strip=True)
            span = p.find("span")
            value = span.get_text(strip=True) if span else None

            if "סיווג" in label:
                genre = value
            elif "אורך בדקות" in label:
                runtime = value
            elif "תאריך בכורה" in label:
                premiere_date = value
            elif "הגבלת צפיה" in label:
                age_rating = value

        movies.append({
            "movie_id": movie_id,
            "title": title,
            "poster_url": poster_url,
            "genre": genre,
            "runtime": runtime,
            "premiere_date": premiere_date,
            "age_rating": age_rating,
        })

    return movies


def get_movies_for_theater(theater_id: int, venue_type_id: int = 1):
    url = f"{BASE}/tickets/MoviesByTheaterAndVenueType"
    params = {"theaterId": theater_id, "venueTypeId": venue_type_id}
    response = session.get(url, params=params)
    return response.json()


def get_dates_for_movie_at_theater(theater_id: int, movie_id: int, venue_type_id: int = 1):
    url = f"{BASE}/tickets/GetDatesByTheaterMovieVenueType"
    params = {"theaterId": theater_id, "movieid": movie_id, "venueTypeId": venue_type_id}
    response = session.get(url, params=params)
    return response.json()


def clean_date(raw_date: str) -> str:
    # e.g. "יום\xa0ג 25/08/2026" -> "25/08/2026"
    return raw_date.split()[-1]


def build_theater_id_map(theaters):
    """Map the site's own theater ID -> the ticketing system's TixTheatreId.

    /tickets/Events is the only endpoint that speaks the ticketing system's
    ID space (1170, 1173, ...). The other two use the site's ID (1, 2, 3...).
    Both live side by side in the theatersAll blob.
    """
    return {t["ID"]: t["TixTheatreId"] for t in theaters if t.get("TixTheatreId")}


def get_showtimes(tix_theatre_id: int, movie_id: int, date: str = "0", venue_type_id: int = 1):
    """Showtimes for one movie at one theater.

    tix_theatre_id must be a TixTheatreId (1170...), NOT the site ID (1...).
    date: "dd/MM/yyyy" filters to that day; "0" means no date filter.

    Param names are bound case-insensitively but *unknown names are silently
    ignored* -- note this endpoint spells it Theatre (British), while the two
    endpoints above spell it Theater. A typo here returns 200 with wrong data.
    """
    url = f"{BASE}/tickets/Events"
    params = {
        "TheatreId": tix_theatre_id,
        "VenueTypeId": venue_type_id,
        "MovieId": movie_id,
        "Date": date,
    }
    response = session.get(url, params=params)

    if response.status_code != 200:
        print(f"Request failed: {response.status_code} for {response.url}")
        return None

    return response.json()


if __name__ == "__main__":
    html = fetch_movies_page()
    theaters = extract_theaters(html)
    movies = extract_movies(html)
    print(f"Found {len(theaters)} theaters")
    print(f"Found {len(movies)} movies")

    tix_ids = build_theater_id_map(theaters)

    site_theater_id = 1
    theater_movies = get_movies_for_theater(site_theater_id)
    print(f"Theater {site_theater_id} shows {len(theater_movies)} movies")

    # Pick the first movie and trace it all the way through
    test_movie = theater_movies[0]
    print(f"\nTesting: {test_movie['Name']} (ID {test_movie['MovieId']})")

    dates = get_dates_for_movie_at_theater(site_theater_id, test_movie["MovieId"])
    print(f"Dates: {dates}")

    if dates:
        first_date = clean_date(dates[0])
        showtimes = get_showtimes(1170, test_movie["MovieId"], first_date)
        print("Raw showtimes structure:")
        print(json.dumps(showtimes, indent=2, ensure_ascii=False))
