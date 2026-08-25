import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Tells SQLAlchemy where the database lives.
# "sqlite:///./movie_aggregator.db" means: create a SQLite file called
# movie_aggregator.db right here in the project folder.
# That file will appear automatically the first time we actually use it.
#
# In production this is overridden by the DATABASE_URL environment variable so
# the file can live on a mounted volume instead of inside the container. A
# container's own filesystem is thrown away on every restart and redeploy, so
# a database written there would silently reset to empty.
# Note the four slashes for an absolute path: sqlite:////data/movie_aggregator.db
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./movie_aggregator.db")

# The engine is SQLAlchemy's core connection object — the thing that
# actually talks to the database.
# connect_args is a SQLite-specific quirk: it allows the connection to be
# used safely across different parts of the app. Not needed if we switch
# to Postgres later.
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

# A "session" is like a conversation with the database — you open one,
# do some work (read/write data), then close it.
# SessionLocal is a factory that creates new sessions whenever we need one.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base is a special class that all our table definitions (Movie, Screening,
# etc.) will inherit from. It's how SQLAlchemy knows "this Python class
# represents a database table."
Base = declarative_base()