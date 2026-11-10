"""One endpoint: a calendar file for one screening.

    GET /api/screening.ics?film=m71&theatre=5&at=2026-11-12T15:30:00

Exists so the file arrives over HTTP rather than as a Blob the page builds and
hands to a download. That distinction is the whole feature: a blob with a
download attribute is always a file save, so on a phone it lands in Downloads
and needs finding and opening before a calendar sees it. Served as
text/calendar with an `inline` disposition, the browser treats it as a document
and hands it to whatever app claims that type -- the calendar's import screen.

## Why it takes ids and not the event's text

The obvious shape would accept a title, a cinema and a time and build the file
from them. That would make every field of a calendar entry attacker-controlled,
and an .ics is a format with line-based structure, separators and escaping --
exactly the shape where injected text turns into injected fields. The one
endpoint in this app that writes a document would become its most interesting
input surface.

Instead it is given ids and reads the title, cinema, address, runtime and
ticket link from the database. The caller chooses WHICH screening, never what
the file says about it. Unknown ids get a 404 and nothing is echoed back.

See test_calendar_ics.py, which attacks it on exactly that basis.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy.orm import Session

import calendar_ics
from api_movies import canonical_movie_ids, listing_ids_for_film, normalize_title
from database import SessionLocal
from models import CinemaSource, Movie, Screening, SourceMovieListing, Theatre

router = APIRouter(prefix="/api", tags=["calendar"])


def _find_screening(db: Session, film_id: str, theatre_id: int, at: str,
                    venue_type: Optional[str], dub: Optional[str]):
    """The one screening these ids name, with everything the file needs.

    Matched on film + cinema + start time, because that is what the client can
    name from what it was rendering. venue_type and dub narrow it further for
    the case a cinema genuinely runs two bookable showings at the same minute:
    the Hebrew dub and the original audio in different halls. Without them the
    file could carry the other version's ticket link.
    """
    listing_ids = listing_ids_for_film(db, film_id, canonical_movie_ids(db))
    if not listing_ids:
        return None

    query = (
        db.query(Screening, SourceMovieListing, Theatre, CinemaSource, Movie)
        .join(SourceMovieListing,
              SourceMovieListing.id == Screening.source_movie_listing_id)
        .join(Theatre, Theatre.id == Screening.theatre_id)
        .join(CinemaSource, CinemaSource.id == Theatre.cinema_source_id)
        .outerjoin(Movie, Movie.id == SourceMovieListing.movie_id)
        .filter(Screening.source_movie_listing_id.in_(listing_ids))
        .filter(Screening.theatre_id == theatre_id)
        .filter(Screening.showtime == at)
    )
    if venue_type:
        query = query.filter(Screening.venue_type == venue_type)
    if dub:
        query = query.filter(Screening.dubbed_language == dub)

    return query.first()


@router.get("/screening.ics")
def screening_ics(
    film: str = Query(..., max_length=200, description="Film id, as /api/movies returns it."),
    theatre: int = Query(..., ge=1),
    at: str = Query(..., max_length=32, description="Screening start, ISO, e.g. 2026-11-12T15:30:00"),
    venue_type: Optional[str] = Query(None, max_length=40),
    dub: Optional[str] = Query(None, max_length=8),
):
    """A calendar file for one screening, with a two-hour reminder."""
    # Validated before it reaches a query, so a malformed value is a 422 rather
    # than a scan of the screenings table for a string that cannot match.
    try:
        datetime.fromisoformat(at)
    except ValueError:
        raise HTTPException(422, "`at` must be an ISO datetime.")

    db = SessionLocal()
    try:
        found = _find_screening(db, film, theatre, at, venue_type, dub)
        if not found:
            # Deliberately says nothing about which part was wrong and echoes
            # none of the input back.
            raise HTTPException(404, "No such screening.")

        screening, listing, theatre_row, source, movie = found

        ics = calendar_ics.build_ics(
            # Every one of these is read from the database. Nothing the caller
            # sent reaches the file.
            film_title=(movie.title_he if movie else None)
                       or normalize_title(listing.raw_title)
                       or listing.raw_title,
            cinema=theatre_row.name,
            chain=source.name or source.key,
            address=theatre_row.address,
            showtime=screening.showtime,
            runtime_minutes=listing.runtime_minutes,
            venue_type=screening.venue_type,
            ticket_url=screening.ticket_url,
        )
        filename = calendar_ics.filename_for(
            (movie.title_he if movie else None) or listing.raw_title,
            screening.showtime,
        )

        return Response(
            content=ics.encode("utf-8"),
            # The charset matters: Hebrew titles are the normal case here, and
            # a client guessing latin-1 renders them as mojibake in the event.
            media_type="text/calendar; charset=utf-8",
            headers={
                # inline, NOT attachment -- see calendar_ics.content_disposition.
                "Content-Disposition": calendar_ics.content_disposition(filename),
                # Safe to cache: a screening's time, cinema and film do not
                # change, and if the screening is cancelled the card stops
                # offering it.
                "Cache-Control": "public, max-age=3600",
            },
        )
    finally:
        db.close()
