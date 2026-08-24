from database import Base, engine
from models import Movie, CinemaSource, Theatre, SourceMovieListing, Screening

Base.metadata.create_all(bind=engine)