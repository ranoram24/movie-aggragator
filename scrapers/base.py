"""Shared interface every cinema chain scraper implements.

The three methods are deliberately coarse -- get everything, not one
theater/movie/date at a time. The five chains disagree about which slice is
"natural": Movieland and Cinema City hand back the whole schedule in a single
call, Hot Cinema is movie-first (one call = all theaters for one movie), and
only Planet and Lev are genuinely per-(theater, date). A fine-grained interface
would force the bulk chains to refetch the same payload hundreds of times.

So each scraper picks its own most efficient path internally and returns flat,
denormalized records. Showtime carries both foreign keys, which means sync.py
never has to know which chain produced a given row.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import html as html_module
import re
import requests


def clean_address(raw: Optional[str]) -> Optional[str]:
    """Flatten a CMS address field into one plain line.

    Several chains store this as an HTML blob with entities and phone numbers
    mixed in ("<p>קניון ראש העין 32, רה&rdquo;ע</p>"). Left as-is it is useless
    both for display and for geocoding, which needs a clean street string.
    """
    if not raw:
        return None
    text = html_module.unescape(raw)
    text = re.sub(r"<[^>]+>", " ", text)          # tags -> space
    text = text.replace("&nbsp;", " ")
    text = re.sub(r"[‎‏‪-‮]", "", text)  # bidi marks
    text = re.sub(r"0\d{1,2}-?\d{7}|\*\d{4}", " ", text)     # phone numbers
    text = " ".join(text.split())
    return text.strip(" ,.-") or None


@dataclass
class Theater:
    source_theatre_id: str          # the chain's own theater id, as a string
    name: str
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


@dataclass
class MovieListing:
    source_movie_id: str            # the chain's own movie id, as a string
    title: str
    poster_url: Optional[str] = None
    genre: Optional[str] = None
    runtime_minutes: Optional[int] = None
    premiere_date: Optional[str] = None
    age_rating: Optional[str] = None


@dataclass
class Showtime:
    source_theatre_id: str
    source_movie_id: str
    starts_at: str                  # ISO-8601: "2026-08-25T20:20:00"
    ticket_url: str                 # REQUIRED: deep link to THIS showtime's checkout
    venue_type: str = "regular"     # "regular", "VIP", "IMAX", ...

    # ISO-639-1 codes. dubbed_language is None when the film plays in its
    # original audio. Every chain exposes this somewhere, but no two agree
    # where -- see each scraper for the specifics.
    dubbed_language: Optional[str] = None
    original_language: Optional[str] = None
    subtitled_language: Optional[str] = None

    @property
    def spoken_language(self) -> Optional[str]:
        """What the audience actually hears -- the dub if there is one."""
        return self.dubbed_language or self.original_language


# Chains name languages in Hebrew prose, in English, or as ISO codes depending
# on the endpoint. Normalising to ISO-639-1 keeps the UI's flag lookup simple.
_LANGUAGE_CODES = {
    "עברית": "he", "עברי": "he", "מדובב לעברית": "he", "hebrew": "he", "he": "he",
    "אנגלית": "en", "אנגלי": "en", "english": "en", "en": "en",
    "צרפתית": "fr", "french": "fr", "fr": "fr",
    "רוסית": "ru", "russian": "ru", "ru": "ru",
    "ספרדית": "es", "spanish": "es", "es": "es",
    "ערבית": "ar", "arabic": "ar", "ar": "ar",
    "איטלקית": "it", "it": "it",
    "גרמנית": "de", "de": "de",
}


def normalize_language(value: Optional[str]) -> Optional[str]:
    """Map whatever a chain calls a language onto an ISO-639-1 code."""
    if not value:
        return None
    key = " ".join(str(value).split()).strip().lower()
    if key in _LANGUAGE_CODES:
        return _LANGUAGE_CODES[key]
    # Fall back to a substring hit: values arrive as prose like
    # "מדובב לעברית + כתוביות בעברית".
    for name, code in _LANGUAGE_CODES.items():
        if name in key:
            return code
    return None


def language_from_title(title: str) -> tuple[Optional[str], Optional[str]]:
    """(dubbed_language, original_language) inferred from a listing's title.

    Cinema City has no per-screening language field at all -- it publishes the
    dubbed and subtitled versions as two different movie ids, distinguished
    only by a title suffix ("...-מדובב" vs "...-אנגלית"). This reads that back.
    """
    if not title:
        return None, None

    dub = re.search(r"מדובב(?:ת)?(?:\s+ל(\S+))?", title)
    if dub:
        # "מדובב לצרפתית" names its target; a bare "מדובב" means Hebrew.
        return (normalize_language(dub.group(1)) or "he"), None

    if re.search(r"\bאנגלית\b", title):
        return None, "en"
    return None, None


class CinemaScraper(ABC):
    """Base class for a single cinema chain."""

    source_key: str = ""            # stable slug stored in CinemaSource.key
    source_name: str = ""           # human-readable, e.g. "Cinema City"

    # Cinema City, Movieland, Planet and Hot Cinema ignore headers entirely --
    # they answer a bare session with no UA at all. Lev does NOT: its Wordfence
    # install returns 403 for the default "python-requests/x.y" User-Agent that
    # requests.Session() ships with.
    #
    # Note this must be a plain assignment, not setdefault(): a Session already
    # HAS a User-Agent header, so setdefault() is a silent no-op and leaves the
    # python-requests value in place. That 403 is real bot detection -- which is
    # a different failure from a 404, where the path is simply wrong.
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = self.USER_AGENT

    def get_json(self, url: str, **kwargs):
        """GET + .json() with a clear error if the route is wrong.

        Named explicitly because a 404 here means the PATH is wrong -- that is
        decided by routing, before headers or bot detection are ever consulted.
        Chasing it with headers or cloudscraper is wasted effort.
        """
        response = self.session.get(url, timeout=30, **kwargs)
        if response.status_code == 404:
            raise RuntimeError(
                f"404 from {response.url}\n"
                f"  A 404 is a routing failure -- check the PATH, not the headers."
            )
        response.raise_for_status()
        return response.json()

    @abstractmethod
    def get_theaters(self) -> list[Theater]:
        """All physical locations for this chain."""

    @abstractmethod
    def get_movies(self) -> list[MovieListing]:
        """All currently-listed titles, with whatever metadata the chain exposes."""

    @abstractmethod
    def get_showtimes(self, days: int = 7) -> list[Showtime]:
        """Every showtime in the next `days` days, across all theaters."""

    def get_movies_at_theater(self, source_theatre_id: str, days: int = 7) -> list[MovieListing]:
        """Convenience view: which titles play at one theater.

        Derived from get_showtimes() rather than being its own fetch, so bulk
        chains don't pay for an extra round trip.
        """
        wanted = {
            s.source_movie_id
            for s in self.get_showtimes(days=days)
            if s.source_theatre_id == str(source_theatre_id)
        }
        return [m for m in self.get_movies() if m.source_movie_id in wanted]
