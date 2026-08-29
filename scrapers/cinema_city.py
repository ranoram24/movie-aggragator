"""Cinema City.

The HTML parsing (theatersAll blob + movie metadata cards) is reused verbatim
from scrape_cinema_city.py -- that code already works and is not rewritten here.

What changed is how showtimes are fetched. The old sync looped
theater x movie x date with a 0.5s sleep, roughly a thousand requests per run.
/tickets/Events with NO parameters returns every showtime at every theater in a
single response, so this does that instead.

The one catch: the bulk response drops MovieId (it carries only Name +
ExportCode), and SourceMovieListing keys on MovieId. So get_movies() unions
MoviesByTheaterAndVenueType across the 8 physical theaters to rebuild a
Name -> MovieId map, and showtimes join back on Name. Verified 50/50 exact,
zero unmatched.
"""

from datetime import datetime, timedelta

from scrape_cinema_city import (
    BASE,
    fetch_movies_page,
    extract_theaters,
    extract_movies,
)
import localtime
from .base import (
    CinemaScraper, Theater, MovieListing, Showtime,
    clean_address, language_from_title,
)

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


class CinemaCityScraper(CinemaScraper):
    source_key = "cinema_city"
    source_name = "Cinema City"

    def __init__(self, session=None):
        super().__init__(session)
        self._html = None
        self._name_to_movie_id = None
        self._events = None

    def _page(self) -> str:
        if self._html is None:
            self._html = fetch_movies_page()
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

    def get_showtimes(self, days: int = 7) -> list[Showtime]:
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
