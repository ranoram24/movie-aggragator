"""Registry of every cinema chain scraper.

sync.py loops over SCRAPERS, so adding a chain means writing one module and
adding one line here -- nothing in the sync logic changes.
"""

from .base import CinemaScraper, Theater, MovieListing, Showtime
from .cinema_city import CinemaCityScraper
from .movieland import MovielandScraper
from .planet import PlanetScraper
from .hot_cinema import HotCinemaScraper
from .lev import LevScraper

SCRAPERS: dict[str, type[CinemaScraper]] = {
    CinemaCityScraper.source_key: CinemaCityScraper,
    MovielandScraper.source_key: MovielandScraper,
    PlanetScraper.source_key: PlanetScraper,
    HotCinemaScraper.source_key: HotCinemaScraper,
    LevScraper.source_key: LevScraper,
}

__all__ = [
    "SCRAPERS", "CinemaScraper", "Theater", "MovieListing", "Showtime",
    "CinemaCityScraper", "MovielandScraper", "PlanetScraper",
    "HotCinemaScraper", "LevScraper",
]
