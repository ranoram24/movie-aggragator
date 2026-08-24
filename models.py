from sqlalchemy import Column, Integer, String, Float, ForeignKey
from database import Base

class Movie(Base):
    __tablename__ = "movies"
    id=Column(Integer, primary_key=True, index=True)
    tmdb_id=Column(Integer, unique=True, index=True)
    title_en=Column(String)
    title_he=Column(String)
    poster_url=Column(String)
    release_date=Column(String)
    runtime_minutes=Column(Integer)
    overview=Column(String)

class CinemaSource(Base):
    __tablename__ = "cinema_sources"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)  # e.g. "Cinema City"

class Theatre(Base):
    __tablename__ = "theatres"

    id = Column(Integer, primary_key=True, index=True)
    cinema_source_id = Column(Integer, ForeignKey("cinema_sources.id"))
    name = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    source_theatre_id = Column(String)  # the ID this cinema chain uses internally (e.g. TheatreId=1173)

class SourceMovieListing(Base):
    __tablename__ = "source_movie_listings"

    id = Column(Integer, primary_key=True, index=True)
    movie_id = Column(Integer, ForeignKey("movies.id"), nullable=True)  # nullable: unmatched listings have no movie yet
    cinema_source_id = Column(Integer, ForeignKey("cinema_sources.id"))
    source_movie_id = Column(String)  # e.g. Cinema City's MovieId=6271
    raw_title = Column(String)  # the title as scraped, before matching
    match_confidence = Column(Float, nullable=True)

class Screening(Base):
    __tablename__ = "screenings"

    id = Column(Integer, primary_key=True, index=True)
    source_movie_listing_id = Column(Integer, ForeignKey("source_movie_listings.id"))
    theatre_id = Column(Integer, ForeignKey("theatres.id"))
    showtime = Column(String)  # simple string for now, refine later
    venue_type = Column(String, nullable=True)  # e.g. "regular", "VIP"
    ticket_url = Column(String, nullable=True)
    last_verified_at = Column(String, nullable=True)