"""Create the database tables.

Safe to re-run: create_all() only creates tables that don't exist yet, so it
will NOT add columns to a table that already exists. After changing models.py,
rebuild instead:

    python create_table.py --rebuild

Everything in here is re-derivable by running sync.py and match_movies.py, so
dropping is cheap.
"""

import argparse

from database import Base, engine
from models import Movie, CinemaSource, Theatre, SourceMovieListing, Screening

parser = argparse.ArgumentParser()
parser.add_argument("--rebuild", action="store_true",
                    help="drop every table first (destroys all scraped data)")
args = parser.parse_args()

if args.rebuild:
    Base.metadata.drop_all(bind=engine)
    print("Dropped all tables.")

Base.metadata.create_all(bind=engine)
print("Tables created:", ", ".join(sorted(Base.metadata.tables)))
