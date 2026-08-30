"""Planet (Yes Planet).

Richest of the five. The quickbook API exposes structured addresses AND
lat/lng for every cinema, which is the only chain that fills those columns.

Two things to watch:

1. attributeIds is one flat tag list per film/event that mixes three different
   concepts -- age rating ("14-plus"), genre ("horror"), venue type ("imax"),
   plus language plumbing we ignore. They are split apart below.

2. THE BOOKING LINK TRAP. The obvious field, `bookingLink`, is dead -- it 404s,
   as do compositeBookingLink.bookingUrl and obsoleteBookingUrl. All three point
   at a retired tickets5.planetcinema.co.il host. Only bookingRouterLaunchLink
   resolves (302 -> br.planetcinema.co.il/launch/{eventId}). Do not "simplify"
   this to the shorter-looking field.
"""

import re
from datetime import datetime, timedelta

import localtime
from .base import CinemaScraper, Theater, MovieListing, Showtime

BASE = "https://www.planetcinema.co.il"
TENANT = "10100"
API = f"{BASE}/il/data-api-service/v1/quickbook/{TENANT}"

VENUE_ATTRS = {"imax", "4dx", "screenx", "vip"}
# Language/subtitle plumbing -- not a genre, not a rating.
IGNORED_ATTR_RE = re.compile(r"^(first-subbed-lang-|second-subbed-lang-|original-lang-|subbed$|dubbed$)")
AGE_ATTR_RE = re.compile(r"^(\d+-plus|all)$")


def _split_attributes(attribute_ids: list[str]) -> tuple[str | None, str | None, str]:
    """attributeIds -> (genre, age_rating, venue_type)."""
    genres, ratings, venues = [], [], []
    for attr in attribute_ids or []:
        if IGNORED_ATTR_RE.match(attr):
            continue
        if AGE_ATTR_RE.match(attr):
            ratings.append(attr)
        elif attr in VENUE_ATTRS:
            venues.append(attr)
        else:
            genres.append(attr)
    return (
        ", ".join(genres) or None,
        ratings[0] if ratings else None,
        venues[0].upper() if venues else "regular",
    )


def _first(values) -> str | None:
    """First entry of one of Planet's language arrays, or None if empty."""
    return values[0] if values else None


class PlanetScraper(CinemaScraper):
    source_key = "planet"
    source_name = "Planet"

    def __init__(self, session=None):
        super().__init__(session)
        self._cinemas = None

    @staticmethod
    def _until(days: int) -> str:
        return (localtime.today() + timedelta(days=days)).isoformat()

    def _cinema_rows(self, days: int = 30) -> list[dict]:
        if self._cinemas is None:
            data = self.get_json(f"{API}/cinemas/with-event/until/{self._until(days)}")
            self._cinemas = data["body"]["cinemas"]
        return self._cinemas

    def get_theaters(self) -> list[Theater]:
        theaters = []
        for c in self._cinema_rows():
            # `address` also carries a stray GUID in address4 on some rows;
            # rebuild from the structured parts and skip anything GUID-shaped.
            info = c.get("addressInfo") or {}
            parts = [
                info.get("address1"),
                info.get("city"),
            ]
            address = ", ".join(p for p in parts if p) or c.get("address")
            theaters.append(
                Theater(
                    source_theatre_id=str(c["id"]),
                    name=c["displayName"],
                    address=address,
                    latitude=c.get("latitude"),
                    longitude=c.get("longitude"),
                )
            )
        return theaters

    def get_movies(self, days: int = 30) -> list[MovieListing]:
        data = self.get_json(f"{API}/films/until/{self._until(days)}")
        listings = []
        for f in data["body"]["films"]:
            genre, age_rating, _ = _split_attributes(f.get("attributeIds"))
            release = f.get("releaseDate")
            listings.append(
                MovieListing(
                    source_movie_id=str(f["id"]),
                    title=f["name"],
                    poster_url=f.get("posterLink"),
                    genre=genre,
                    runtime_minutes=f.get("length"),
                    premiere_date=release.split("T")[0] if release else None,
                    age_rating=age_rating,
                )
            )
        return listings

    def get_showtimes(self, days: int = 9) -> list[Showtime]:
        today = localtime.today()
        cutoff = today + timedelta(days=days)

        showtimes = []
        # These queries are by businessDay, not calendar day: a 00:30 screening
        # belongs to the PREVIOUS business day, so it comes back under both that
        # date and its own. Deduping on the event id keeps each showing once.
        seen_event_ids: set[str] = set()

        for cinema in self._cinema_rows():
            cinema_id = str(cinema["id"])
            dates = self.get_json(
                f"{API}/dates/in-cinema/{cinema_id}/until/{self._until(days)}"
            )["body"]["dates"]

            for date in dates:
                if not (today <= datetime.fromisoformat(date).date() < cutoff):
                    continue

                body = self.get_json(
                    f"{API}/film-events/in-cinema/{cinema_id}/at-date/{date}"
                )["body"]

                for event in body.get("events", []):
                    event_id = str(event.get("id"))
                    if event_id in seen_event_ids:
                        continue
                    seen_event_ids.add(event_id)

                    # See module docstring: this is the ONLY working link field.
                    ticket_url = event.get("bookingRouterLaunchLink")
                    if not ticket_url:
                        continue
                    try:
                        starts_at = datetime.fromisoformat(event["eventDateTime"])
                    except (ValueError, KeyError, TypeError):
                        continue
                    if not (today <= starts_at.date() < cutoff):
                        continue

                    _, _, venue_type = _split_attributes(event.get("attributeIds"))

                    # The richest language data of any chain, and crucially
                    # per-EVENT: Planet serves the dubbed and original cuts of a
                    # film under one filmId, distinguished only here.
                    languages = event.get("languages") or {}
                    dubbed = _first(languages.get("dubbed"))
                    original = _first(languages.get("original"))
                    subtitles = _first(languages.get("subtitles"))

                    showtimes.append(
                        Showtime(
                            source_theatre_id=cinema_id,
                            source_movie_id=str(event["filmId"]),
                            starts_at=starts_at.isoformat(),
                            ticket_url=ticket_url,
                            venue_type=venue_type,
                            dubbed_language=dubbed,
                            original_language=None if dubbed else original,
                            subtitled_language=subtitles,
                        )
                    )
        return showtimes
