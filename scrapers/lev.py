"""Lev Cinema.

The only chain with no JSON at all. Everything comes from one WordPress theme
file, ajax_data.php, which returns HTML fragments -- sometimes <li> lists,
sometimes <option> lists, tilde-delimited as "<html>~<count>~<next_passval>".

Two traps found while mapping it:

1. `movie_on_location` honours its `date` parameter but SILENTLY IGNORES `loc`
   -- passing loc=7 and loc=1150 return byte-identical 68KB responses covering
   every location. Same class of bug as Cinema City's TheatreId/TheaterId:
   an unrecognised parameter is dropped rather than rejected, so you get a
   200 with wrong (over-broad) data instead of an error.

2. `movie_on_location_new` looks like the newer, better version of the same
   action. It is a dead end -- it returns a one-line "schedule updates Tuesday"
   notice. Use `movie_on_location`.

Showtimes need the cascading dropdown flow, because the <li> listing carries
pcode but no clock time:
    get_movies(location) -> get_types(movie) -> get_dates(movie) -> get_times(date)
Each step needs data-* attributes threaded from the previous one (lcode, lsub,
excode). The final time <option> carries data-pcode, which is what the order
URL keys on.

Measured cost of a full run: ~575 requests over about five minutes, roughly two
a second -- 71 movie-slots across the 7 branches, ~6 in-window dates each, plus
a 0.25s pause after every call. Slowest of the five by a wide margin, which is
why it runs on its own interval and why its screenings are validated by the
next full scrape rather than by a short timer.
"""

import re
import time
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

import localtime
from .base import (
    CinemaScraper, Theater, MovieListing, Showtime,
    language_from_title,
)

BASE = "https://www.lev.co.il"
AJAX = f"{BASE}/wp-content/themes/lev/ajax_data.php"
TICKET_URL = BASE + "/order/?pcode={pcode}&loc={loc}"

# Addresses live on /contact/, which lists every branch as
# "<cinema name> <address> טלפון ...". That single page covers all seven,
# including Ramat Hasharon -- which has no /location/ page of its own, so the
# per-branch pages are not a complete source.
CONTACT_URL = f"{BASE}/contact/"
PHONE_MARKER = r"(?:טלפון|\*5155)"

REQUEST_DELAY = 0.25


class LevScraper(CinemaScraper):
    source_key = "lev"
    source_name = "Lev Cinema"

    def __init__(self, session=None):
        super().__init__(session)
        self._html = None
        # sync_chain calls get_theaters(), get_movies() and get_showtimes() in
        # turn, and the latter two each call get_theaters() again -- so /contact/
        # was fetched three times a run, and the per-branch movie list twice.
        # Caching both is free: nothing here changes within one run.
        self._address_map = None
        self._movies_by_site: dict[str, list[dict]] = {}

    # ---- plumbing -------------------------------------------------------

    def _ajax(self, action: str, passval: str = "", **extra) -> str:
        params = {
            "action": action, "passval": passval, "lcode": "", "excode": "",
            "siteid": "", "lsub": "", "ldub": "", "lsub2": "", "eventid": "",
        }
        params.update(extra)
        response = self.session.get(AJAX, params=params, timeout=30)
        response.raise_for_status()
        time.sleep(REQUEST_DELAY)
        return response.text

    @staticmethod
    def _strip_comments(html: str) -> str:
        # The theme emits a commented-out duplicate of nearly every row; parsing
        # them would double every result.
        return re.sub(r"<!--.*?-->", "", html, flags=re.S)

    def _options(self, html: str) -> list[dict]:
        """Parse an <option> fragment into dicts of value/text/data-attrs."""
        soup = BeautifulSoup(self._strip_comments(html.split("~")[0]), "html.parser")
        out = []
        for opt in soup.find_all("option"):
            value = opt.get("value") or ""
            if not value:
                continue  # the "choose..." placeholder
            row = {"value": value, "text": opt.get_text(strip=True)}
            row.update({k: v for k, v in opt.attrs.items() if k.startswith("data-")})
            out.append(row)
        return out

    def _page(self) -> str:
        if self._html is None:
            self._html = self.session.get(BASE + "/", timeout=30).text
        return self._html

    # ---- interface ------------------------------------------------------

    def get_theaters(self) -> list[Theater]:
        # The cascade API keys locations by their Hebrew display name, so that
        # is what we store as the source id -- there is no numeric id that
        # identifies a *cinema* (the numeric `loc` in order URLs is a per-screen
        # venue code, and several map to one building).
        soup = BeautifulSoup(self._page(), "html.parser")
        select = soup.find("select", id="filter_by_loc")
        names = []
        if select:
            names = [
                opt.get("value").strip()
                for opt in select.find_all("option")
                if opt.get("value") and opt.get("value").strip()
            ]
        addresses = self._addresses()
        return [
            Theater(source_theatre_id=n, name=n, address=addresses.get(n))
            for n in dict.fromkeys(names)
        ]

    def _addresses(self) -> dict[str, str]:
        """Branch name -> street address, scraped from /contact/. Cached."""
        if self._address_map is not None:
            return self._address_map
        self._address_map = self._fetch_addresses()
        return self._address_map

    def _fetch_addresses(self) -> dict[str, str]:
        try:
            response = self.session.get(CONTACT_URL, timeout=30)
            response.raise_for_status()
        except Exception:
            return {}

        # Flatten to plain text: the addresses sit in prose, not in tagged fields.
        text = " ".join(re.sub(r"<[^>]+>", " ", response.text).split())

        found: dict[str, str] = {}
        for name in self._branch_names():
            match = re.search(
                re.escape(name) + r"\s*(.{4,70}?)\s*" + PHONE_MARKER, text
            )
            if match:
                found[name] = " ".join(match.group(1).split())
        return found

    def _branch_names(self) -> list[str]:
        soup = BeautifulSoup(self._page(), "html.parser")
        select = soup.find("select", id="filter_by_loc")
        if not select:
            return []
        return [
            opt.get("value").strip()
            for opt in select.find_all("option")
            if opt.get("value") and opt.get("value").strip()
        ]

    def _movies_at(self, site: str) -> list[dict]:
        """The <option> rows for one branch, fetched once per run."""
        if site not in self._movies_by_site:
            self._movies_by_site[site] = self._options(self._ajax("get_movies", site))
        return self._movies_by_site[site]

    def get_movies(self) -> list[MovieListing]:
        listings: dict[str, MovieListing] = {}
        for theater in self.get_theaters():
            for opt in self._movies_at(theater.source_theatre_id):
                listings.setdefault(
                    opt["value"], MovieListing(source_movie_id=opt["value"], title=opt["text"])
                )
        return list(listings.values())

    def validation_showtimes(self, days: int, movie_ids=None) -> list[Showtime] | None:
        """Not possible cheaply, so this deliberately returns None.

        Reaching a single screening's time slot needs the whole cascade: the
        get_times call is keyed on lcode/lsub/excode, and those only exist as
        data-* attributes threaded out of the get_types and get_dates responses
        for that exact movie. There is no endpoint that answers "is pcode X
        still on sale", and none of that context is stored on the screening row.

        So validating one Lev showing costs three requests, and validating a
        day's worth costs most of a full scrape. Lev relies on its (now 6-hourly)
        full scrape instead; the validator skips it, leaving is_available NULL,
        which displays.
        """
        return None

    def get_showtimes(self, days: int = 9) -> list[Showtime]:
        today = localtime.today()
        cutoff = today + timedelta(days=days)

        showtimes = []
        for theater in self.get_theaters():
            site = theater.source_theatre_id

            for movie in self._movies_at(site):
                movie_id = movie["value"]

                # get_types hands back the lcode/lsub pair every later step needs.
                types = self._options(self._ajax("get_types", movie_id, siteid=site))
                if not types:
                    continue
                fmt = types[0]
                # The format option's own label spells out the language, e.g.
                # "שפת מקור (צרפתית) עם כתוביות (עברית + אנגלית)".
                label = fmt.get("text", "")
                dubbed, original = language_from_title(label)
                if not dubbed and not original:
                    dubbed, original = language_from_title(movie["text"])
                subtitles = "he" if "כתוביות" in label else None

                ctx = {
                    "siteid": site,
                    "lcode": fmt.get("data-lcode", ""),
                    "lsub": fmt.get("data-lsub", ""),
                    "lsub2": fmt.get("data-lsub2", ""),
                    "ldub": fmt.get("data-ldub", ""),
                }

                for date_opt in self._options(self._ajax("get_dates", movie_id, **ctx)):
                    try:
                        day = datetime.fromisoformat(date_opt["value"]).date()
                    except ValueError:
                        continue
                    if not (today <= day < cutoff):
                        continue

                    times = self._options(
                        self._ajax(
                            "get_times", date_opt["value"],
                            excode=date_opt.get("data-excode", ""), **ctx
                        )
                    )
                    for slot in times:
                        pcode = slot.get("data-pcode")
                        hour = slot["text"].strip()
                        if not pcode or not re.match(r"^\d{1,2}:\d{2}$", hour):
                            continue
                        starts_at = datetime.combine(
                            day, datetime.strptime(hour, "%H:%M").time()
                        )
                        showtimes.append(
                            Showtime(
                                source_theatre_id=site,
                                source_movie_id=movie_id,
                                starts_at=starts_at.isoformat(),
                                # pcode alone identifies the screening; `loc`
                                # only preselects the cinema on the order page.
                                # The numeric loc from the <li> listing is NOT
                                # usable here -- that listing and the cascade
                                # return disjoint pcode sets, so it never
                                # matches. The site name works and resolves 200.
                                ticket_url=TICKET_URL.format(pcode=pcode, loc=site),
                                dubbed_language=dubbed,
                                original_language=original,
                                subtitled_language=subtitles,
                            )
                        )
        return showtimes
