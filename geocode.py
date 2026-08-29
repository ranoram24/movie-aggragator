"""Fill in theatre coordinates so the app can sort cinemas by distance.

Most chains give an address but no lat/lng. Planet ships coordinates in its API
and Hot Cinema embeds them in its venue pages, so those are already populated by
the scrapers -- this only handles the rest.

Uses Nominatim (OpenStreetMap): free, no API key, but its usage policy requires
a real identifying User-Agent and **at most one request per second**. That is
fine here: there are well under 40 theatres, it runs once, and results are
written back to the database so it never repeats work.

    python geocode.py            # fill in whatever is missing
    python geocode.py --recheck  # re-geocode everything, even rows that have coords
    python geocode.py --dry-run  # show what would be looked up, write nothing

A wrong coordinate is worse than a missing one -- it silently sorts a cinema to
the wrong place -- so every result is sanity-checked against Israel's bounding
box before it is saved, and anything outside is rejected and reported.
"""

import argparse
import re
import sys
import time
from math import asin, cos, radians, sin, sqrt

import requests

from database import SessionLocal
from models import CinemaSource, Theatre

NOMINATIM = "https://nominatim.openstreetmap.org/search"
# Nominatim blocks generic/library user agents. Identify the project honestly.
USER_AGENT = "movie-screenings-aggregator/1.0 (personal project; contact via github)"
RATE_LIMIT_SECONDS = 1.1  # policy is 1 req/s; leave headroom

# Rough bounding box for Israel. Used only to reject obviously wrong hits --
# Nominatim will happily return a same-named street on another continent.
LAT_RANGE = (29.4, 33.4)
LON_RANGE = (34.2, 35.9)


def geocode(session: requests.Session, query: str, settlement_only: bool = False):
    """Return (lat, lon, display_name) or None.

    settlement_only restricts the search to towns/cities. That matters for the
    anchor lookup: plain "אבן יהודה" resolves to a *street in Jerusalem*, which
    would then reject the correct address as 60km out of place.
    """
    params = {"q": query, "format": "json", "limit": 1, "countrycodes": "il"}
    if settlement_only:
        params["featureType"] = "settlement"

    response = session.get(
        NOMINATIM,
        params=params,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "he,en"},
        timeout=30,
    )
    if response.status_code != 200:
        return None
    results = response.json()
    if not results:
        return None

    hit = results[0]
    latitude, longitude = float(hit["lat"]), float(hit["lon"])
    if not (LAT_RANGE[0] <= latitude <= LAT_RANGE[1]
            and LON_RANGE[0] <= longitude <= LON_RANGE[1]):
        return None  # outside Israel -- almost certainly the wrong place
    return latitude, longitude, hit.get("display_name", "")


# Venue/complex words that lead an Israeli address but mean nothing to
# Nominatim -- "קניון עזריאלי, אחוזה 269, רעננה" fails while "אחוזה 269, רעננה"
# resolves. Stripping them is what makes most of these addresses geocodable.
VENUE_WORDS = r"(?:קניון|מתחם|בית התרבות|מרכז מסחרי|סינמול|ישפרו|פאואר סנטר|כיכר)"

# Chain names that prefix a theatre's title. Stripping them leaves the city,
# which is the single most useful disambiguator we have -- "גיבורי ישראל 17"
# exists in several towns, but "גיבורי ישראל 17, נתניה" does not.
CHAIN_PREFIXES = r"^\s*(?:סינמה סיטי|מובילנד|פלאנט|הוט סינמה|לב)\s*"

# How far a result may sit from its expected city before we reject it.
# Israeli cities are small; a correct hit is almost always within a few km.
MAX_CITY_DISTANCE_KM = 25


def city_hint(theatre: Theatre) -> str | None:
    """The city a theatre is in, inferred from its name.

    Every chain names venues after their location -- "סינמה סיטי באר שבע",
    "לב אבן יהודה", or just "נתניה". Strip the chain and any (VIP)/(IMAX)
    qualifier and what remains is the city.
    """
    name = re.sub(r"\([^)]*\)", " ", theatre.name or "")
    name = re.sub(CHAIN_PREFIXES, "", name)
    name = " ".join(name.split()).strip(" -,")
    return name or None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = (sin(dlat / 2) ** 2
         + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2)
    return 2 * 6371.0 * asin(sqrt(a))


_CITY_ANCHORS: dict[str, tuple[float, float] | None] = {}


def city_anchor(session: requests.Session, city: str):
    """Approximate centre of a town, cached. None if it isn't a real settlement.

    Returning None is the correct outcome for names like "סמדר" or "דניאל",
    which are venue names rather than places -- with no anchor we simply skip
    validation for that theatre instead of measuring against a bogus point.
    """
    if city not in _CITY_ANCHORS:
        try:
            hit = geocode(session, f"{city}, ישראל", settlement_only=True)
        except Exception:
            hit = None
        time.sleep(RATE_LIMIT_SECONDS)
        _CITY_ANCHORS[city] = (hit[0], hit[1]) if hit else None
    return _CITY_ANCHORS[city]


def anchor_city_for(theatre: Theatre) -> str | None:
    """Which place name to validate against.

    The tail of the address is more trustworthy than the venue's name --
    "לויד ג'ורג' 4, המושבה הגרמנית, ירושלים" knows it is in Jerusalem, while the
    name "לב סמדר" does not. Fall back to the name only when there is no address.
    """
    address = (theatre.address or "").strip()
    if address:
        parts = [p.strip() for p in re.split(r"[,،]", address) if p.strip()]
        if parts:
            tail = re.sub(rf"^\s*{VENUE_WORDS}\s*", "", parts[-1]).strip()
            if tail and not re.search(r"\d", tail):
                return tail
            # No comma before the city, e.g. "רמת ים 60 בהרצליה" or
            # "יוניצמן 21 תל אביב" -- take the words after the street number.
            trailing = trailing_place(parts[-1])
            if trailing:
                return trailing
    return city_hint(theatre)


def trailing_place(line: str) -> str | None:
    """The place name after a street number in a single-line address.

    Also strips the Hebrew "ב" locative prefix, so "בהרצליה" becomes "הרצליה" --
    otherwise it geocodes as a different word entirely.
    """
    match = re.search(r"\d+\s+(.{2,30})$", line)
    if not match:
        return None
    place = " ".join(match.group(1).split()).strip(" ,.-")
    if not place or re.search(r"\d", place):
        return None
    # "בהרצליה" -> "הרצליה"; only for a single word, to avoid mangling
    # legitimate names that happen to start with bet.
    if len(place.split()) == 1 and place.startswith("ב") and len(place) > 3:
        place = place[1:]
    return place or None


def address_variants(theatre: Theatre) -> list[str]:
    """Progressively looser queries, best first.

    Nominatim's Hebrew coverage is uneven: a full address with a mall name
    usually misses, while the bare street or even the city hits. Trying a
    ladder of variants gets far better coverage than one shot, and the
    bounding-box check in geocode() stops a loose query from matching
    something absurd.
    """
    variants: list[str] = []
    address = (theatre.address or "").strip()
    city = city_hint(theatre)

    if address:
        # Always try with the city appended first. Dropping a venue name like
        # "קניון אבן יהודה" can take the only city reference with it, leaving a
        # bare street that resolves to the wrong town entirely.
        if city and city not in address:
            variants.append(f"{address}, {city}")
        variants.append(address)

        parts = [p.strip() for p in re.split(r"[,،]", address) if p.strip()]
        without_venue = [p for p in parts if not re.match(rf"^\s*{VENUE_WORDS}", p)]

        street = next((p for p in (without_venue or parts) if re.search(r"\d", p)), None)
        if street and city:
            variants.append(f"{street}, {city}")
        if without_venue and without_venue != parts:
            variants.append(", ".join(without_venue))

    # Last resorts: the venue's own name (OSM often has cinemas), then the bare
    # town, which at least puts the pin in the right place.
    variants.append(theatre.name)
    anchor_town = anchor_city_for(theatre)
    if anchor_town:
        variants.append(anchor_town)
    if city:
        variants.append(city)

    # Pin every variant to Israel and de-duplicate, preserving order.
    seen, out = set(), []
    for v in variants:
        q = f"{v}, ישראל"
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


def run(recheck: bool = False, dry_run: bool = False, verbose: bool = False) -> int:
    """Geocode theatres and return how many were resolved.

    Callable from the scheduler as well as the CLI. With the defaults it only
    touches rows where latitude is NULL, so it is a no-op once everything is
    located and cheap to call after every sync.
    """
    db = SessionLocal()
    http = requests.Session()

    chains = {source.id: source.key for source in db.query(CinemaSource)}
    query = db.query(Theatre)
    if not recheck:
        query = query.filter(Theatre.latitude.is_(None))
    theatres = query.all()

    if not theatres:
        _say(verbose, "Nothing to do -- every theatre already has coordinates.")
        db.close()
        return 0

    _say(verbose, f"Geocoding {len(theatres)} theatre(s) via Nominatim "
          f"(~{RATE_LIMIT_SECONDS}s each, ~{len(theatres) * RATE_LIMIT_SECONDS:.0f}s total)\n")

    resolved = failed = 0
    for theatre in theatres:
        chain = chains.get(theatre.cinema_source_id, "?")
        variants = address_variants(theatre)

        if dry_run:
            _say(verbose, f"  [dry-run] {chain:12} {theatre.name[:22]:<22}")
            for v in variants:
                _say(verbose, f"              try: {v[:66]}")
            continue

        # Where should this theatre roughly be? Used to reject a hit that
        # resolved to a same-named street in the wrong town -- the failure mode
        # that silently sorts a cinema 30km off instead of erroring.
        city = anchor_city_for(theatre)
        anchor = city_anchor(http, city) if city else None

        hit = None
        used = ""
        for variant in variants:
            candidate = None
            try:
                candidate = geocode(http, variant)
            except Exception as exc:
                _say(verbose, f"  ERROR   {chain:12} {theatre.name[:22]:<22} "
                      f"{type(exc).__name__}: {exc}")
            time.sleep(RATE_LIMIT_SECONDS)

            if not candidate:
                continue

            if anchor:
                away = haversine_km(anchor[0], anchor[1], candidate[0], candidate[1])
                if away > MAX_CITY_DISTANCE_KM:
                    _say(verbose, f"  reject  {chain:12} {theatre.name[:22]:<22} "
                          f"{away:.0f}km from {city} <- {variant[:34]}")
                    continue

            hit = candidate
            used = variant
            break

        if hit:
            theatre.latitude, theatre.longitude, display = hit
            resolved += 1
            _say(verbose, f"  OK      {chain:12} {theatre.name[:22]:<22} "
                  f"{theatre.latitude:.5f},{theatre.longitude:.5f}  <- {used[:40]}")
        else:
            failed += 1
            _say(verbose, f"  FAILED  {chain:12} {theatre.name[:22]:<22} "
                  f"({len(variants)} variants tried)")

    if not dry_run:
        db.commit()
        remaining = db.query(Theatre).filter(Theatre.latitude.is_(None)).count()
        _say(verbose, f"\nResolved {resolved}, failed {failed}. "
              f"Theatres still without coordinates: {remaining}")

    db.close()
    return resolved


def _say(verbose: bool, *args) -> None:
    """print() only when running interactively; silent when the scheduler calls."""
    if verbose:
        print(*args)


def main() -> int:
    parser = argparse.ArgumentParser(description="Geocode theatres missing coordinates.")
    parser.add_argument("--recheck", action="store_true",
                        help="re-geocode every theatre, not just those missing coords")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be looked up without writing")
    args = parser.parse_args()
    run(recheck=args.recheck, dry_run=args.dry_run, verbose=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
