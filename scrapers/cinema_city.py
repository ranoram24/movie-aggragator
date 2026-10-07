"""Cinema City.

Rewritten in October 2026, when the chain replaced its site. The old one was an
ASP.NET app that served HTML plus a /tickets/* JSON API; everything this scraper
used is gone:

    /movies            -> 301 to a Wix page, no theatersAll([...]) blob
    /tickets/Events    -> 404
    /tickets/movies    -> 404

The marketing site is now Wix, which renders its film grid from a Wix
collection and exposes no usable data endpoint. Scraping it would mean driving a
headless browser through a JavaScript repeater.

The ticketing system is the better source and is a separate application --
tickets.cinema-city.co.il, a Nuxt app with a plain REST API behind it. Two calls
cover the whole chain:

    /api/features        every film, with real metadata
    /api/presentations   every screening at every cinema, ~3,600 rows

"Presentation" is their word for a screening, and its id is what the order URL
takes, so the ticket link is built straight from it.

This is a better source than what it replaces. The old site had no per-screening
language field at all -- the dub had to be inferred from a "-מדובב" suffix on the
title -- and no venue types. The API states both outright, along with a
synopsis, an English title and a sold-out flag.

Two ids are deliberately kept from the old system so nothing is orphaned:
venueLocationId is the same value the old TixTheatreId had (1170, 1173, ...),
and featureId occupies the same space as the old MovieId. Stored theatres keep
their geocoded positions and stored listings keep their TMDb matches.
"""

import re
from datetime import datetime, timedelta

import localtime
from .base import CinemaScraper, Theater, MovieListing, Showtime

API = "https://tickets.cinema-city.co.il/api"

TICKET_URL = "https://tickets.cinema-city.co.il/order/{presentation_id}"

# venueTypeId, as seen across a full feed. Anything unrecognised is treated as
# an ordinary hall rather than invented, since venue_type is part of a
# screening's identity and a wrong value would split one showing into two.
VENUE_TYPES = {1: "regular", 4: "Prime", 30: "VIP"}

_TAGS = re.compile(r"<[^>]+>")


def _text(html: str | None) -> str | None:
    """Flatten the API's HTML synopsis into a plain paragraph."""
    if not html:
        return None
    text = _TAGS.sub(" ", html)
    text = (text.replace("&nbsp;", " ").replace("&quot;", '"')
                .replace("&amp;", "&").replace("&#39;", "'"))
    return " ".join(text.split()) or None


class CinemaCityScraper(CinemaScraper):
    source_key = "cinema_city"
    source_name = "Cinema City"

    def __init__(self, session=None):
        super().__init__(session)
        self._features_cache = None
        self._presentations_cache = None

    # ---- the two calls --------------------------------------------------

    def _features(self) -> list[dict]:
        if self._features_cache is None:
            self._features_cache = self.get_json(f"{API}/features")
        return self._features_cache

    def _presentations(self) -> list[dict]:
        """Every screening the chain is selling, in one request.

        Cached because all three interface methods read it: the theatre list is
        derived from it, and it is a ~5MB response.
        """
        if self._presentations_cache is None:
            body = self.get_json(f"{API}/presentations")
            self._presentations_cache = body.get("presentations", [])
        return self._presentations_cache

    # ---- interface ------------------------------------------------------

    def get_theaters(self) -> list[Theater]:
        """Derived from the screenings, since the API has no cinema endpoint.

        address is left None deliberately: this feed does not carry one
        (venueCity and venueLocation are null throughout), and upsert_theatre
        keeps the stored value rather than overwriting it with nothing. The
        eight addresses were captured from the old site and are already
        geocoded, so there is nothing to re-fetch.
        """
        seen: dict[str, Theater] = {}
        for row in self._presentations():
            location_id = row.get("venueLocationId")
            name = row.get("locationName")
            if location_id is None or not name:
                continue
            seen.setdefault(
                str(location_id),
                # Same id the old TixTheatreId used, so existing rows match.
                Theater(source_theatre_id=str(location_id), name=name),
            )
        return list(seen.values())

    def get_movies(self) -> list[MovieListing]:
        # /api/features lists everything the chain has on file, including films
        # months out with nothing scheduled. Only those actually playing are
        # returned, so the database does not fill with listings that have no
        # screenings and would still be hashed and sent to TMDb.
        showing = {str(p.get("featureId")) for p in self._presentations()}

        listings = []
        for feature in self._features():
            feature_id = str(feature.get("id"))
            if feature_id not in showing:
                continue
            duration = feature.get("duration")
            listings.append(
                MovieListing(
                    source_movie_id=feature_id,
                    title=feature.get("name") or "",
                    poster_url=feature.get("imageData"),
                    genre=feature.get("categoryName"),
                    runtime_minutes=int(duration) if duration else None,
                    premiere_date=feature.get("dateStarted"),
                    age_rating=feature.get("ratingName"),
                    # Arrives as HTML; 132 of 133 films have one.
                    synopsis=_text(feature.get("synopsis")),
                )
            )
        return listings

    def get_showtimes(self, days: int = 9) -> list[Showtime]:
        today = localtime.today()
        cutoff = today + timedelta(days=days)

        showtimes = []
        for row in self._presentations():
            presentation_id = row.get("id")
            feature_id = row.get("featureId")
            location_id = row.get("venueLocationId")
            if not presentation_id or feature_id is None or location_id is None:
                continue

            try:
                starts_at = datetime.strptime(row["dateTime"], "%Y-%m-%d %H:%M")
            except (ValueError, KeyError, TypeError):
                continue
            # The feed runs months ahead for advance sales, far past the window
            # the site shows.
            if not (today <= starts_at.date() < cutoff):
                continue

            # Stated per screening now, rather than guessed from a title
            # suffix. dubbedLanguageISO is null when the film plays in its own
            # language, which is exactly the distinction the cards rely on.
            dubbed = row.get("dubbedLanguageISO")
            spoken = row.get("languageISO")

            showtimes.append(
                Showtime(
                    source_theatre_id=str(location_id),
                    source_movie_id=str(feature_id),
                    starts_at=starts_at.isoformat(),
                    ticket_url=TICKET_URL.format(presentation_id=presentation_id),
                    venue_type=VENUE_TYPES.get(row.get("venueTypeId"), "regular"),
                    dubbed_language=dubbed,
                    original_language=None if dubbed else spoken,
                    subtitled_language=row.get("subLanguageISO"),
                    # New here: only Planet used to report this.
                    sold_out=bool(row.get("soldout")),
                )
            )
        return showtimes

    def validation_showtimes(self, days: int, movie_ids=None) -> list[Showtime] | None:
        """Cheap: the whole chain is two calls regardless of the window.

        /api/presentations is unparameterised, so re-checking one day costs the
        same as a full nine-day scrape. Well inside a per-quarter-hour budget,
        and it now carries soldout, so validation can retire a screening that is
        still listed but full.
        """
        return self.get_showtimes(days=days)
