"""Hot Cinema.

Structurally the inverse of the others: there is no "showtimes at theater X"
endpoint. /tickets/movieevents?movieid=N returns every theater showing that one
movie, so the loop is over movies, not theaters. Theaters are therefore derived
from the responses rather than fetched from a list endpoint.

The ticket link is /order?theaterId=&eventId=, which is a redirector -- it
rewrites theaterId=16 into an internal site id (302 ->
tickets.hotcinema.co.il/site/1197?code=1197-133196). The short form is stored
deliberately: letting the site resolve it means we don't break if that internal
mapping changes.

Note the spelling hazard, same family as Cinema City's: this site's own JS uses
`theatreid` (British) on MovieEventsDaysFilter but `theaterId` (American) on
/order. Unknown parameter names are ignored silently rather than rejected.
"""

import re
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from .base import CinemaScraper, Theater, MovieListing, Showtime

BASE = "https://hotcinema.co.il"
TICKET_URL = BASE + "/order?theaterId={theater_id}&eventId={event_id}"

# Each /theater/{id} page embeds a Google Maps link carrying the exact
# coordinates, e.g. ".../maps/@31.889012,34.963161,16z". That is better than
# geocoding an address string -- it is the venue's own pin, not a guess.
COORDS_RE = re.compile(r"maps/@(-?\d+\.\d+),(-?\d+\.\d+)")
MAPS_PLACE_RE = re.compile(r"maps/place/([^/\"?]+)")


class HotCinemaScraper(CinemaScraper):
    source_key = "hot_cinema"
    source_name = "Hot Cinema"

    def __init__(self, session=None):
        super().__init__(session)
        self._movies = None
        self._events_by_movie: dict[str, list] = {}

    def _movie_rows(self) -> list[dict]:
        if self._movies is None:
            # EventsCount == 0 means nothing scheduled; skipping those saves a
            # request each, and this endpoint lists ~90 titles.
            rows = self.get_json(f"{BASE}/tickets/movies")
            self._movies = [m for m in rows if (m.get("EventsCount") or 0) > 0]
        return self._movies

    def _events_for(self, movie_id: str) -> list[dict]:
        if movie_id not in self._events_by_movie:
            self._events_by_movie[movie_id] = self.get_json(
                f"{BASE}/tickets/movieevents", params={"movieid": movie_id}
            )
        return self._events_by_movie[movie_id]

    def get_movies(self) -> list[MovieListing]:
        # This endpoint carries title only; richer metadata would need one HTML
        # page fetch per movie, which is not worth ~90 extra requests here.
        return [
            MovieListing(source_movie_id=str(m["MovieId"]), title=m["Name"])
            for m in self._movie_rows()
        ]

    def get_theaters(self) -> list[Theater]:
        names: dict[str, str] = {}
        for movie in self._movie_rows():
            for group in self._events_for(str(movie["MovieId"])):
                tid = group.get("TheaterID") or group.get("TheaterId")
                if tid is None:
                    continue
                # Some groups carry a null TheaterName, so take the first
                # non-empty one rather than whichever group we happen to see
                # first -- otherwise a theater ends up permanently unnamed.
                name = (group.get("TheaterName") or "").strip()
                if name and not names.get(str(tid)):
                    names[str(tid)] = name
                names.setdefault(str(tid), "")
        theaters = []
        for tid, name in sorted(names.items(), key=lambda kv: int(kv[0])):
            latitude, longitude, address = self._location(tid)
            theaters.append(
                Theater(
                    source_theatre_id=tid,
                    name=name or f"Hot Cinema {tid}",
                    address=address,
                    latitude=latitude,
                    longitude=longitude,
                )
            )
        return theaters

    def _location(self, theatre_id: str):
        """Coordinates + address from the venue's own page.

        Returns (lat, lon, address), any of which may be None -- a venue with no
        map link should not break the theatre list.
        """
        try:
            response = self.session.get(f"{BASE}/theater/{theatre_id}", timeout=30)
            if response.status_code != 200:
                return None, None, None
            html = response.text
        except Exception:
            return None, None, None

        coords = COORDS_RE.search(html)
        latitude = float(coords.group(1)) if coords else None
        longitude = float(coords.group(2)) if coords else None

        address = None
        place = MAPS_PLACE_RE.search(html)
        if place:
            # The href is HTML-escaped first, then URL-escaped, so it has to be
            # unwound in that order -- otherwise "&#x2B;" survives as literal
            # text instead of becoming the "+" that unquote_plus turns to space.
            import html as html_module
            from urllib.parse import unquote_plus
            raw = unquote_plus(html_module.unescape(place.group(1)))
            address = " ".join(raw.replace("‭", "").replace("‬", "").split())[:200]
        if not address:
            soup = BeautifulSoup(html, "html.parser")
            node = soup.select_one("[class*=address], [class*=Address]")
            if node:
                address = " ".join(node.get_text(" ", strip=True).split())[:200] or None

        return latitude, longitude, address

    def get_showtimes(self, days: int = 7) -> list[Showtime]:
        today = datetime.now().date()
        cutoff = today + timedelta(days=days)

        showtimes = []
        for movie in self._movie_rows():
            movie_id = str(movie["MovieId"])
            for group in self._events_for(movie_id):
                for slot in group.get("Dates", []):
                    try:
                        starts_at = datetime.fromisoformat(slot["Date"])
                    except (ValueError, KeyError, TypeError):
                        continue
                    if not (today <= starts_at.date() < cutoff):
                        continue

                    theater_id = slot.get("TheaterId") or group.get("TheaterID")
                    event_id = slot.get("EventId")
                    if theater_id is None or not event_id:
                        continue

                    showtimes.append(
                        Showtime(
                            source_theatre_id=str(theater_id),
                            source_movie_id=movie_id,
                            starts_at=starts_at.isoformat(),
                            ticket_url=TICKET_URL.format(
                                theater_id=theater_id, event_id=event_id
                            ),
                            venue_type="VIP" if slot.get("IsVIP") else "regular",
                        )
                    )
        return showtimes
