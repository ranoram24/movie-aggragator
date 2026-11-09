from sqlalchemy import Boolean, Column, Index, Integer, String, Float, ForeignKey
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
    # ISO-639-1 of the language the film was actually made in, from TMDb.
    # Distinct from a screening's dub: "שפת מקור" is a property of the film,
    # while dubbed_language is a property of the individual showing.
    original_language=Column(String)

    # Digital release date according to TMDb. A FALLBACK for films the
    # Telegram channel does not carry, never an override -- see
    # digital_dates.py for why the channel wins where both have an opinion.
    #
    # Separate column rather than merged into digital_releases on purpose:
    # that table is the channel's data as the channel has it, and mixing a
    # second source into it would make "what did the channel say" unanswerable.
    digital_date_tmdb=Column(String)
    # When TMDb was last asked. Needed because the common answer is "no digital
    # date yet", which is indistinguishable from "never asked" without it --
    # and re-asking every film on every pass would be ~200 requests a cycle.
    digital_tmdb_checked_at=Column(String)

class CinemaSource(Base):
    __tablename__ = "cinema_sources"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True)  # stable slug, e.g. "cinema_city" -> maps to a scraper class
    name = Column(String)  # e.g. "Cinema City"

class Theatre(Base):
    __tablename__ = "theatres"

    id = Column(Integer, primary_key=True, index=True)
    cinema_source_id = Column(Integer, ForeignKey("cinema_sources.id"))
    name = Column(String)
    address = Column(String, nullable=True)
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

    # Metadata as the chain itself reports it, kept separate from the TMDb-matched
    # Movie record so we can still show something for listings TMDb can't match
    # (opera broadcasts, concerts, live stage shows).
    poster_url = Column(String, nullable=True)

    # Perceptual hash of the poster, and the cluster of listings sharing it.
    # The chains spell and word titles differently but publish the same
    # artwork, so this is the only identity they all agree on. See posters.py.
    poster_hash = Column(String, nullable=True)
    poster_group = Column(String, nullable=True)

    # Plot description as the chain publishes it, used when TMDb has none.
    synopsis = Column(String, nullable=True)
    genre = Column(String, nullable=True)
    runtime_minutes = Column(Integer, nullable=True)
    premiere_date = Column(String, nullable=True)
    age_rating = Column(String, nullable=True)

class Screening(Base):
    __tablename__ = "screenings"

    # Without these the table has only its primary key, and it is by far the
    # biggest: 84k rows, of which 87% are in the past and no query ever wants.
    #
    # Every API request filters on showtime, and every upsert during a scrape
    # looks a row up by the identity triple below. Unindexed, both were full
    # scans -- so a scrape storing 3,300 screenings scanned 84,000 rows 3,300
    # times, which is what kept a one-CPU machine busy and made the site slow
    # for everyone else while it ran.
    __table_args__ = (
        Index("ix_screenings_showtime", "showtime"),
        Index(
            "ix_screenings_identity",
            "source_movie_listing_id", "theatre_id", "showtime",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    source_movie_listing_id = Column(Integer, ForeignKey("source_movie_listings.id"))
    theatre_id = Column(Integer, ForeignKey("theatres.id"))
    showtime = Column(String)  # simple string for now, refine later
    venue_type = Column(String, nullable=True)  # e.g. "regular", "VIP"

    # Language of the audio and of the subtitles, as ISO-639-1 codes ("he", "en").
    # These belong on the screening rather than the listing because a cinema can
    # run the dubbed and the original version of one film at the same venue on
    # the same day -- Planet serves both under a single film id. Two separately
    # bookable showings, so they must not collapse into one row.
    dubbed_language = Column(String, nullable=True)      # None = not dubbed
    original_language = Column(String, nullable=True)    # the spoken language when not dubbed
    subtitled_language = Column(String, nullable=True)

    ticket_url = Column(String, nullable=True)  # deep link straight to this showtime's checkout
    last_verified_at = Column(String, nullable=True)   # last seen by a FULL scrape

    # Whether a ticket can still be bought for this screening. Deliberately
    # tri-state:
    #   True  -- the chain still lists it, or it has never been questioned
    #   False -- the chain has stopped listing it, or says it is sold out
    #   NULL  -- never validated (a chain we cannot poll cheaply, e.g. Lev)
    #
    # NULL and True both display. Only an explicit False hides a screening, so a
    # chain the validator cannot reach never silently empties out.
    is_available = Column(Boolean, nullable=True, default=True)
    last_validated_at = Column(String, nullable=True)   # last checked by validate.py


class DigitalRelease(Base):
    """When a film reaches digital, per the MoviesOnlineDates Telegram channel.

    Keyed by tmdb_id rather than joined to movies.id with a foreign key, and
    deliberately so: the channel posts a film when its date is announced, which
    is often before any chain lists it and long after the last one drops it.
    Storing only the films we currently carry would mean re-scraping the whole
    history every time a new film appeared. This table is the channel's data as
    the channel has it, and api_movies joins it to whatever we happen to be
    showing today.

    Dates are stored ISO (YYYY-MM-DD) though the channel writes DD/MM/YYYY, so
    they sort and compare like every other date in this schema. NULL means the
    channel has not given one -- usually because it says "יפורסם בהמשך".
    """
    __tablename__ = "digital_releases"

    id = Column(Integer, primary_key=True, index=True)
    # The join key, straight out of the themoviedb.org link in each post.
    tmdb_id = Column(Integer, unique=True, index=True, nullable=False)

    # Kept for debugging and for the backfill report. Not used for matching --
    # the whole point of the tmdb id is that titles never have to be compared.
    title_he = Column(String, nullable=True)
    title_en = Column(String, nullable=True)

    digital_date = Column(String, nullable=True)        # the field the app shows
    bluray_date = Column(String, nullable=True)
    cinema_il_date = Column(String, nullable=True)

    # Which post this came from, and when we last saw it. source_post_id is how
    # a correction is attributed: the channel edits the original post in place,
    # so the id stays the same while the dates change under it.
    source_post_id = Column(Integer, nullable=True)
    first_seen_at = Column(String, nullable=True)
    updated_at = Column(String, nullable=True)
