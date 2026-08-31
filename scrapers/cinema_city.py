"""Cinema City.

Two sources make up one chain. The /movies page is server-rendered HTML and is
the only place the metadata lives -- genre, runtime, premiere date, age rating,
posters -- alongside a `theatersAll([...])` JavaScript call carrying the theatre
list. Everything else comes from /tickets/*, a JSON API.

Showtimes come from ONE unparameterised call. /tickets/Events with no query
string at all returns every showtime at every theatre; the obvious loop over
theatre x movie x date is about a thousand requests for the same data.

The catch is that the bulk response drops MovieId, carrying only Name and
ExportCode, while SourceMovieListing keys on MovieId. So get_movies() unions
MoviesByTheaterAndVenueType across the 8 physical theatres to rebuild a
Name -> MovieId map, and showtimes join back on Name. Verified 50/50 exact,
zero unmatched.

Note the endpoints disagree about spelling: /tickets/Events takes `TheatreId`
(British), the others take `theaterId` (American). Model binding is
case-insensitive but silently ignores names it does not recognise, so the wrong
spelling returns 200 with unfiltered data rather than an error. Only a hazard
if you go back to per-theatre calls -- the bulk call passes nothing at all.
"""

import json
import re
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

import localtime
from .base import (
    CinemaScraper, Theater, MovieListing, Showtime,
    clean_address, language_from_title,
)

BASE = "https://www.cinema-city.co.il"

# One row per physical building. theatersAll also contains VIP/ONYX/Prime/Lounge
# sub-variants of the same buildings, which would duplicate theaters.
PHYSICAL_THEATER_IDS = [1, 2, 3, 4, 5, 13, 17, 25]

TICKET_URL = "https://tickets.cinema-city.co.il/order/{event_id}"

# The /movies page only lists actual films, so live events and one-off
# screenings arrive with no poster from there. The bulk Events feed does carry
# a Pic filename for them, which resolves under the site's own /images/.
# Use the https host, not the raw 80.178.x one it also serves from -- a plain
# http image would be blocked as mixed content on an https page.
POSTER_URL = "https://www.cinema-city.co.il/images/{filename}"


def extract_theaters(html: str) -> list[dict]:
    """The theatre list, out of the theatersAll([...]) call in the page source."""
    match = re.search(r"theatersAll\((\[.*?\])\);", html, re.DOTALL)
    if not match:
        raise ValueError("Could not find theatersAll JSON in page")
    return json.loads(match.group(1))


def extract_movies(html: str) -> list[dict]:
    """Film metadata from the poster cards on the /movies page."""
    soup = BeautifulSoup(html, "html.parser")

    movies = []
    for block in soup.find_all("div", class_="movie-thumb"):
        link = block.get("data-linkmobile", "")
        movie_id = link.split("/")[-1] if link else None

        title_tag = block.find("h2")
        img_tag = block.find("img", class_="flip-thumb")

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
            "title": title_tag.get_text(strip=True) if title_tag else None,
            "poster_url": img_tag.get("src") if img_tag else None,
            "genre": genre,
            "runtime": runtime,
            "premiere_date": premiere_date,
            "age_rating": age_rating,
        })

    return movies


class CinemaCityScraper(CinemaScraper):
    source_key = "cinema_city"
    source_name = "Cinema City"

    def __init__(self, session=None):
        super().__init__(session)
        self._html = None
        self._name_to_movie_id = None
        self._events = None

    def _page(self) -> str:
        """The /movies page, fetched once and reused.

        Goes through self.session so it carries the browser User-Agent the base
        class sets. The site does not check it today -- verified by calling
        every endpoint from a bare session with no headers at all -- but there
        is no reason for this one request to be the odd one out.
        """
        if self._html is None:
            response = self.session.get(f"{BASE}/movies", timeout=30)
            response.raise_for_status()
            self._html = response.text
        return self._html

    def _physical_theaters(self) -> list[dict]:
        by_id = {t["ID"]: t for t in extract_theaters(self._page())}
        return [by_id[i] for i in PHYSICAL_THEATER_IDS if i in by_id]

    def get_theaters(self) -> list[Theater]:
        # source_theatre_id is TixTheatreId, NOT the site's own ID -- the Events
        # endpoint speaks the ticketing system's ID space (1170...), while
        # MoviesByTheaterAndVenueType speaks the site's (1, 2, 3...).
        return [
            Theater(
                source_theatre_id=str(t["TixTheatreId"]),
                name=t["Name"],
                # theatersAll stores this as an HTML blob, not a plain string.
                address=clean_address(t.get("Address")),
            )
            for t in self._physical_theaters()
        ]

    def _movie_ids_by_name(self) -> dict[str, str]:
        if self._name_to_movie_id is None:
            mapping: dict[str, str] = {}
            for theater in self._physical_theaters():
                movies = self.get_json(
                    f"{BASE}/tickets/MoviesByTheaterAndVenueType",
                    params={"theaterId": theater["ID"], "venueTypeId": 1},
                )
                for m in movies:
                    mapping.setdefault(m["Name"], str(m["MovieId"]))
            self._name_to_movie_id = mapping
        return self._name_to_movie_id

    def _bulk_events(self) -> list[dict]:
        """Every showtime at every theater, in one unparameterised call.

        Cached because both get_movies() (for poster fallbacks) and
        get_showtimes() need it, and it is a ~200KB response.
        """
        if self._events is None:
            self._events = self.get_json(f"{BASE}/tickets/Events")
        return self._events

    def get_movies(self) -> list[MovieListing]:
        # Metadata (genre/runtime/premiere/age rating) lives on the /movies page
        # and is keyed by MovieId; the API movie list is the authoritative set of
        # what is actually showing. Movies present in one but not the other are
        # normal, so metadata is merged in where available and left null otherwise.
        metadata = {m["movie_id"]: m for m in extract_movies(self._page()) if m["movie_id"]}
        # Poster of last resort for anything absent from the /movies page.
        pics = {g["Name"]: g.get("Pic") for g in self._bulk_events() if g.get("Pic")}

        listings = []
        for name, movie_id in self._movie_ids_by_name().items():
            meta = metadata.get(movie_id, {})
            runtime = meta.get("runtime")
            listings.append(
                MovieListing(
                    source_movie_id=movie_id,
                    title=name,
                    poster_url=meta.get("poster_url") or self._poster(pics.get(name)),
                    genre=meta.get("genre"),
                    runtime_minutes=int(runtime) if runtime and str(runtime).isdigit() else None,
                    premiere_date=meta.get("premiere_date"),
                    age_rating=meta.get("age_rating"),
                )
            )
        return listings

    @staticmethod
    def _poster(pic: str | None) -> str | None:
        if not pic:
            return None
        from urllib.parse import quote
        return POSTER_URL.format(filename=quote(pic))

    def get_showtimes(self, days: int = 9) -> list[Showtime]:
        # No parameters at all -> every movie, every theater, every date.
        groups = self._bulk_events()
        name_to_id = self._movie_ids_by_name()

        today = localtime.today()
        cutoff = today + timedelta(days=days)

        showtimes = []
        for group in groups:
            movie_id = name_to_id.get(group["Name"])
            if not movie_id:
                continue  # showing somewhere we don't track as a physical theater

            # No per-screening language field exists here: Cinema City ships the
            # dubbed and subtitled cuts as separate movie ids whose titles carry
            # "-מדובב" / "-אנגלית", so the title is the only signal.
            dubbed, original = language_from_title(group["Name"])

            for slot in group.get("Dates", []):
                try:
                    starts_at = datetime.strptime(slot["Date"], "%d/%m/%Y %H:%M")
                except (ValueError, KeyError):
                    continue
                if not (today <= starts_at.date() < cutoff):
                    continue

                showtimes.append(
                    Showtime(
                        source_theatre_id=str(slot["TheaterId"]),
                        source_movie_id=movie_id,
                        starts_at=starts_at.isoformat(),
                        ticket_url=TICKET_URL.format(event_id=slot["EventId"]),
                        dubbed_language=dubbed,
                        original_language=original,
                    )
                )
        return showtimes
