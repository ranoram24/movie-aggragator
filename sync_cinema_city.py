import time
from datetime import datetime
from database import SessionLocal
from models import CinemaSource, Theatre, SourceMovieListing, Screening
from scrape_cinema_city import (
    fetch_movies_page, extract_theaters, extract_movies,
    get_movies_for_theater, get_dates_for_movie_at_theater,
    clean_date, get_showtimes
)

# Only the 8 physical locations, not the VIP/ONYX/Prime/Lounge sub-variants.
# These are the theater "ID"s (not TixTheatreId) from theatersAll, one per building.
PHYSICAL_THEATER_IDS = [1, 2, 3, 4, 5, 13, 17, 25]

def get_or_create_cinema_source(db):
    source = db.query(CinemaSource).filter_by(name="Cinema City").first()
    if not source:
        source = CinemaSource(name="Cinema City")
        db.add(source)
        db.commit()
        db.refresh(source)
    return source

def get_or_create_theatre(db, cinema_source_id, theater_data):
    tix_id = str(theater_data["TixTheatreId"])
    theatre = db.query(Theatre).filter_by(source_theatre_id=tix_id).first()
    if not theatre:
        theatre = Theatre(
            cinema_source_id=cinema_source_id,
            name=theater_data["Name"],
            source_theatre_id=tix_id,
            latitude=None,   # we'll fill this in later via geocoding
            longitude=None,
        )
        db.add(theatre)
        db.commit()
        db.refresh(theatre)
    return theatre

def get_or_create_listing(db, cinema_source_id, movie_id, raw_title):
    listing = db.query(SourceMovieListing).filter_by(
        cinema_source_id=cinema_source_id, source_movie_id=str(movie_id)
    ).first()
    if not listing:
        listing = SourceMovieListing(
            cinema_source_id=cinema_source_id,
            source_movie_id=str(movie_id),
            raw_title=raw_title,
            movie_id=None,       # unmatched for now, per our Phase 2 rule
            match_confidence=None,
        )
        db.add(listing)
        db.commit()
        db.refresh(listing)
    return listing

def sync():
    db = SessionLocal()
    cinema_source = get_or_create_cinema_source(db)

    html = fetch_movies_page()
    all_theaters = extract_theaters(html)
    # Build a lookup: theater's local ID -> its full data (name, TixTheatreId, etc.)
    theaters_by_id = {t["ID"]: t for t in all_theaters}

    screenings_saved = 0

    for theater_id in PHYSICAL_THEATER_IDS:
        theater_data = theaters_by_id.get(theater_id)
        if not theater_data:
            print(f"Skipping unknown theater id {theater_id}")
            continue

        theatre = get_or_create_theatre(db, cinema_source.id, theater_data)
        tix_id = theater_data["TixTheatreId"]

        print(f"\n== {theater_data['Name']} (local id {theater_id}, TixTheatreId {tix_id}) ==")

        movies_here = get_movies_for_theater(theater_id)
        time.sleep(0.5)

        for movie in movies_here:
            movie_id = movie["MovieId"]
            listing = get_or_create_listing(db, cinema_source.id, movie_id, movie["Name"])

            dates = get_dates_for_movie_at_theater(theater_id, movie_id)
            time.sleep(0.5)

            for raw_date in dates:
                date_str = clean_date(raw_date)
                showtimes_response = get_showtimes(tix_id, movie_id, date_str)
                time.sleep(0.5)

                if not showtimes_response:
                    continue

                for movie_entry in showtimes_response:
                    for slot in movie_entry.get("Dates", []):
                        event_id = slot["EventId"]

                        existing = db.query(Screening).filter_by(
                            source_movie_listing_id=listing.id,
                            theatre_id=theatre.id,
                            showtime=slot["Date"],
                        ).first()
                        if existing:
                            continue  # already saved, skip

                        screening = Screening(
                            source_movie_listing_id=listing.id,
                            theatre_id=theatre.id,
                            showtime=slot["Date"],
                            venue_type="regular",
                            ticket_url=f"https://tickets.cinema-city.co.il/order/{event_id}",
                            last_verified_at=datetime.now().isoformat(),
                        )
                        db.add(screening)
                        screenings_saved += 1

            db.commit()  # commit after each movie, so partial progress survives if something fails later

    db.close()
    print(f"\nDone. Saved {screenings_saved} new screenings.")

if __name__ == "__main__":
    sync()