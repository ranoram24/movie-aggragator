"""Movieland.

The whole schedule lives behind one unparameterised call: /api/Events returns
every movie, at every theater, on every date -- about 280KB. The site does all
its filtering client-side, so there is nothing to pass and nothing to loop.

Theaters are the only thing not in that payload with full detail. The homepage
embeds `quickOrder.theaters = [...]`, which turns out to be structurally the
same blob Cinema City serves as theatersAll() -- same ID / TixTheatreId split,
same Address field. Both sites evidently run the same vendor platform, so the
Cinema City ID lesson transfers directly: /api/Events reports TixTheatreId as
its TheaterId, not the site's own ID.
"""

import json
import re
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from .base import CinemaScraper, Theater, MovieListing, Showtime

BASE = "https://movieland.co.il"


class MovielandScraper(CinemaScraper):
    source_key = "movieland"
    source_name = "Movieland"

    def __init__(self, session=None):
        super().__init__(session)
        self._events = None
        self._html = None

    def _all_events(self) -> list[dict]:
        if self._events is None:
            self._events = self.get_json(f"{BASE}/api/Events")
        return self._events

    def _page(self) -> str:
        if self._html is None:
            self._html = self.session.get(BASE + "/", timeout=30).text
        return self._html

    def get_theaters(self) -> list[Theater]:
        # The homepage embeds `quickOrder.theaters = [...]` -- structurally the
        # same blob Cinema City serves as theatersAll(), right down to the
        # ID / TixTheatreId split. TixTheatreId is what /api/Events reports as
        # TheaterId, so that is the id we key on.
        theaters = []
        for t in self._theater_rows():
            tix = t.get("TixTheatreId")
            if tix is None:
                continue
            name = (t.get("Name") or "").strip()
            theaters.append(
                Theater(
                    source_theatre_id=str(tix),
                    name=name or f"Movieland {tix}",
                    address=self._clean_address(t.get("Address"), name),
                )
            )
        return theaters

    def _theater_rows(self) -> list[dict]:
        match = re.search(r"quickOrder\.theaters\s*=\s*(\[.*?\]);", self._page(), re.S)
        if not match:
            raise RuntimeError("Could not find quickOrder.theaters in the Movieland homepage")
        return json.loads(match.group(1))

    @staticmethod
    def _clean_address(raw: str | None, name: str = "") -> str | None:
        # Address is a block of HTML paragraphs: usually the branch name, then
        # the street address (sometimes split across several <p>), then a phone
        # line. Drop the phone and the name-echo, keep and rejoin the rest.
        if not raw:
            return None
        lines = [
            " ".join(p.get_text(" ", strip=True).split())
            for p in BeautifulSoup(raw, "html.parser").find_all("p")
        ]
        keep = []
        for line in lines:
            if not line or re.search(r"\d{2,3}-\d{6,7}", line):
                continue  # phone number
            if name and (line == name or line == f"מובילנד {name}"):
                continue  # just repeats the branch name
            keep.append(line.rstrip(" ,"))
        return ", ".join(keep) or None

    def get_movies(self) -> list[MovieListing]:
        listings = []
        for movie in self._all_events():
            length = movie.get("LengthInMinutes")
            listings.append(
                MovieListing(
                    source_movie_id=str(movie["MovieId"]),
                    title=movie["Name"],
                    poster_url=self._poster(movie.get("Pic")),
                    genre=movie.get("Genres"),
                    runtime_minutes=int(length) if length and str(length).isdigit() else None,
                    premiere_date=movie.get("DateStarted"),
                    age_rating=self._rating(movie.get("MovieRating")),
                )
            )
        return listings

    @staticmethod
    def _rating(rating) -> str | None:
        # MovieRating is a nested object here, not a string:
        # {"ID": 13, "Name": "מותר מגיל 8", "RatingId": 13, ...}
        if isinstance(rating, dict):
            return rating.get("Name")
        return rating or None

    @staticmethod
    def _poster(pic: str | None) -> str | None:
        # Pic is a bare filename, e.g. "דג ושמו באסה (4) (1).jpg"
        if not pic:
            return None
        from urllib.parse import quote
        return f"{BASE}/Content/Movies/{quote(pic)}"

    def get_showtimes(self, days: int = 7) -> list[Showtime]:
        today = datetime.now().date()
        cutoff = today + timedelta(days=days)

        showtimes = []
        for movie in self._all_events():
            movie_id = str(movie["MovieId"])
            for slot in movie.get("Dates", []):
                # BookingNativeUrl is the per-event deep link into the
                # biggerpicture.ai checkout; without it we have no way to send
                # someone to this specific showing, so the row is skipped.
                ticket_url = slot.get("BookingNativeUrl")
                if not ticket_url:
                    continue
                try:
                    starts_at = datetime.fromisoformat(slot["Date"])
                except (ValueError, KeyError, TypeError):
                    continue
                if not (today <= starts_at.date() < cutoff):
                    continue

                showtimes.append(
                    Showtime(
                        source_theatre_id=str(slot["TheaterId"]),
                        source_movie_id=movie_id,
                        starts_at=starts_at.isoformat(),
                        ticket_url=ticket_url,
                        venue_type="VIP" if slot.get("IsVip") else "regular",
                    )
                )
        return showtimes
