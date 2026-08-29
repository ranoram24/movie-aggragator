"""Product API: what's playing, where, and when.

Separate from main.py, which is scraper plumbing (health, status, manual
triggers). These are the two endpoints the mobile app actually renders.

Two things here are less obvious than they look:

* **Film identity.** The same film is a separate SourceMovieListing per chain.
  The TMDb match collapses them, so a matched film is keyed by movies.id and
  carries every chain's screenings under one card. Listings TMDb can't match
  (opera broadcasts, live events, the odd title that defeats the matcher) still
  need to be browsable, so they stay keyed by their own listing id. Hence a
  string id: "m123" for a merged film, "l456" for a lone listing.

* **Where each field comes from.** It is not one table. overview/title_en are
  TMDb-only and absent for unmatched films; runtime has to come from the chain
  listing because TMDb's *search* endpoint never returns it (movies.runtime_minutes
  is empty for every row); poster prefers TMDb but falls back to the chain's.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

import localtime
from database import SessionLocal
from models import CinemaSource, Movie, Screening, SourceMovieListing, Theatre

router = APIRouter(prefix="/api", tags=["movies"])

EARTH_RADIUS_KM = 6371.0


# ---------------------------------------------------------------- response models

class ChainOut(BaseModel):
    key: str
    name: str


class MovieSummary(BaseModel):
    id: str                              # "m{movie_id}" or "l{listing_id}"
    title_he: str
    title_en: str | None = None
    poster_url: str | None = None
    theatre_count: int
    nearest_km: float | None = None
    chains: list[str]


class ShowtimeOut(BaseModel):
    time: str                            # "20:20"
    venue_type: str
    ticket_url: str
    # ISO-639-1. dubbed_language is None when the film plays in its original
    # audio; spoken_language is whichever the audience actually hears, so the
    # client can render one flag without re-deriving the rule.
    dubbed_language: str | None = None
    original_language: str | None = None
    subtitled_language: str | None = None
    spoken_language: str | None = None


class DateGroup(BaseModel):
    date: str                            # "2026-08-25"
    label: str                           # "Today" | "Tomorrow" | "Thu 27 Aug"
    showtimes: list[ShowtimeOut]


class TheatreOut(BaseModel):
    id: int
    name: str
    chain: str
    address: str | None = None
    distance_km: float | None = None
    dates: list[DateGroup]


class MovieDetail(BaseModel):
    id: str
    title_he: str
    title_en: str | None = None
    poster_url: str | None = None
    overview: str | None = None
    genre: str | None = None
    runtime_minutes: int | None = None
    age_rating: str | None = None
    theatres: list[TheatreOut]


# ---------------------------------------------------------------- helpers

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = (sin(dlat / 2) ** 2
         + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2)
    return round(2 * EARTH_RADIUS_KM * asin(sqrt(a)), 1)


# Hebrew weekday names, indexed by date.weekday() (Monday = 0).
HEBREW_WEEKDAYS = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]


def day_label(day: date, today: date) -> str:
    """Server-side so the two screens can never disagree about 'today'.

    Hebrew, because the app is Hebrew-first -- strftime's %a would emit English
    weekday names into an otherwise RTL Hebrew interface.
    """
    delta = (day - today).days
    if delta == 0:
        return "היום"
    if delta == 1:
        return "מחר"
    return f"יום {HEBREW_WEEKDAYS[day.weekday()]} {day.strftime('%d/%m')}"


def film_key(listing: SourceMovieListing) -> str:
    return f"m{listing.movie_id}" if listing.movie_id else f"l{listing.id}"


def _rows(db: Session):
    """Every upcoming screening joined to its listing, theatre, chain and movie.

    One query rather than per-film lookups: the whole dataset is ~13k rows and
    both endpoints need the same join, so N+1 here would be pointless.
    """
    return (
        db.query(Screening, SourceMovieListing, Theatre, CinemaSource, Movie)
        .join(SourceMovieListing, SourceMovieListing.id == Screening.source_movie_listing_id)
        .join(Theatre, Theatre.id == Screening.theatre_id)
        .join(CinemaSource, CinemaSource.id == Theatre.cinema_source_id)
        .outerjoin(Movie, Movie.id == SourceMovieListing.movie_id)  # outer: unmatched films
        # Israel time, not the server's: showtimes are naive local times, and a
        # UTC container is 3 hours behind, which surfaced screenings that had
        # already started.
        .filter(Screening.showtime >= localtime.now_iso())
        .all()
    )


def _chain_filter(chains: Optional[str]) -> set[str]:
    """Parse the ?chains= query into a set of keys. Empty set means 'all'."""
    if not chains:
        return set()
    return {c.strip() for c in chains.split(",") if c.strip()}


def _distance(theatre: Theatre, lat: Optional[float], lon: Optional[float]):
    if lat is None or lon is None or theatre.latitude is None or theatre.longitude is None:
        return None
    return haversine_km(lat, lon, theatre.latitude, theatre.longitude)


# ---------------------------------------------------------------- endpoints

@router.get("/movies", response_model=list[MovieSummary])
def list_movies(
    lat: Optional[float] = Query(None, ge=-90, le=90),
    lon: Optional[float] = Query(None, ge=-180, le=180),
    limit: int = Query(100, ge=1, le=300),
    chains: Optional[str] = Query(
        None,
        description="Comma-separated chain keys, e.g. 'planet,lev'. Omit for all.",
    ),
):
    """Films currently playing, nearest first when coordinates are supplied.

    Without coordinates -- which is the normal case when location permission is
    denied -- falls back to "showing at the most theatres", which is a decent
    proxy for prominence, then title.
    """
    wanted = _chain_filter(chains)

    db = SessionLocal()
    try:
        films: dict[str, dict] = {}

        for screening, listing, theatre, source, movie in _rows(db):
            # Filtering here rather than in SQL keeps theatre_count and
            # nearest_km honest: they must describe only the chains the user
            # asked for, not the full set.
            if wanted and source.key not in wanted:
                continue
            key = film_key(listing)
            film = films.get(key)
            if film is None:
                film = films[key] = {
                    "id": key,
                    "title_he": (movie.title_he if movie else None) or listing.raw_title,
                    "title_en": movie.title_en if movie else None,
                    "poster_url": (movie.poster_url if movie else None) or listing.poster_url,
                    "theatres": set(),
                    "chains": set(),
                    "nearest_km": None,
                }
            film["theatres"].add(theatre.id)
            film["chains"].add(source.name or source.key)

            distance = _distance(theatre, lat, lon)
            if distance is not None:
                current = film["nearest_km"]
                film["nearest_km"] = distance if current is None else min(current, distance)

        summaries = [
            MovieSummary(
                id=f["id"],
                title_he=f["title_he"],
                title_en=f["title_en"],
                poster_url=f["poster_url"],
                theatre_count=len(f["theatres"]),
                nearest_km=f["nearest_km"],
                chains=sorted(f["chains"]),
            )
            for f in films.values()
        ]

        if lat is not None and lon is not None:
            # Films with no geocoded theatre sort last rather than first.
            summaries.sort(key=lambda m: (m.nearest_km is None,
                                          m.nearest_km if m.nearest_km is not None else 0,
                                          -m.theatre_count))
        else:
            summaries.sort(key=lambda m: (-m.theatre_count, m.title_he))

        return summaries[:limit]
    finally:
        db.close()


@router.get("/movies/{film_id}", response_model=MovieDetail)
def movie_detail(
    film_id: str,
    lat: Optional[float] = Query(None, ge=-90, le=90),
    lon: Optional[float] = Query(None, ge=-180, le=180),
    chains: Optional[str] = Query(None, description="Comma-separated chain keys."),
):
    """One film: metadata plus every theatre showing it, nearest first."""
    db = SessionLocal()
    try:
        wanted = _chain_filter(chains)
        matching = [
            r for r in _rows(db)
            if film_key(r[1]) == film_id and (not wanted or r[3].key in wanted)
        ]
        if not matching:
            raise HTTPException(404, f"No current screenings for film '{film_id}'")

        today = localtime.today()
        by_theatre: dict[int, dict] = {}
        meta = {"title_he": None, "title_en": None, "poster_url": None,
                "overview": None, "genre": None, "runtime_minutes": None,
                "age_rating": None}

        for screening, listing, theatre, source, movie in matching:
            # Merge metadata across chains: any chain that supplies a field wins
            # over one that leaves it null, so a film listed by five chains ends
            # up with the union of what they each know.
            meta["title_he"] = meta["title_he"] or (movie.title_he if movie else None) or listing.raw_title
            meta["title_en"] = meta["title_en"] or (movie.title_en if movie else None)
            meta["poster_url"] = meta["poster_url"] or (movie.poster_url if movie else None) or listing.poster_url
            meta["overview"] = meta["overview"] or (movie.overview if movie else None)
            meta["genre"] = meta["genre"] or listing.genre
            meta["runtime_minutes"] = meta["runtime_minutes"] or listing.runtime_minutes
            meta["age_rating"] = meta["age_rating"] or listing.age_rating

            entry = by_theatre.setdefault(theatre.id, {
                "id": theatre.id,
                "name": theatre.name,
                "chain": source.name or source.key,
                "address": theatre.address,
                "distance_km": _distance(theatre, lat, lon),
                "days": defaultdict(list),
            })

            try:
                starts_at = datetime.fromisoformat(screening.showtime)
            except (ValueError, TypeError):
                continue
            entry["days"][starts_at.date()].append(
                ShowtimeOut(
                    time=starts_at.strftime("%H:%M"),
                    venue_type=screening.venue_type or "regular",
                    ticket_url=screening.ticket_url,
                    dubbed_language=screening.dubbed_language,
                    original_language=screening.original_language,
                    subtitled_language=screening.subtitled_language,
                    spoken_language=(screening.dubbed_language
                                     or screening.original_language),
                )
            )

        theatres = []
        for entry in by_theatre.values():
            dates = [
                DateGroup(
                    date=day.isoformat(),
                    label=day_label(day, today),
                    showtimes=sorted(times, key=lambda s: s.time),
                )
                for day, times in sorted(entry["days"].items())
            ]
            theatres.append(TheatreOut(
                id=entry["id"], name=entry["name"], chain=entry["chain"],
                address=entry["address"], distance_km=entry["distance_km"], dates=dates,
            ))

        theatres.sort(key=lambda t: (t.distance_km is None,
                                     t.distance_km if t.distance_km is not None else 0,
                                     t.name))

        return MovieDetail(id=film_id, theatres=theatres, **meta)
    finally:
        db.close()


@router.get("/chains", response_model=list[ChainOut])
def list_chains():
    """The cinema chains available to filter by, for the browse screen's chips."""
    db = SessionLocal()
    try:
        return [
            ChainOut(key=source.key, name=source.name or source.key)
            for source in db.query(CinemaSource).order_by(CinemaSource.id)
            if source.key
        ]
    finally:
        db.close()
