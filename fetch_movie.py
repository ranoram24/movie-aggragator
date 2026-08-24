import os
import requests
from dotenv import load_dotenv
from database import SessionLocal
from models import Movie

load_dotenv()  # reads the .env file and loads it into the environment

token = os.getenv("TMDB_TOKEN")

def fetch_movie_from_tmdb(tmdb_id):
    url=f"https://api.themoviedb.org/3/movie/{tmdb_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "accept": "application/json"
    }
    response=requests.get(url, headers=headers)
    return response.json()  # returns a dict with the movie data

def save_movie_to_db(movie_data):
    db=SessionLocal()
    movie=Movie(
        tmdb_id=movie_data["id"],
        title_en=movie_data["title"],
        title_he=movie_data.get("title_he", None),  # optional field
        poster_url=f"https://image.tmdb.org/t/p/w500{movie_data['poster_path']}" if movie_data.get("poster_path") else None,
        release_date=movie_data.get("release_date", None),
        runtime_minutes=movie_data.get("runtime", None),
        overview=movie_data.get("overview", None)
    )
    db.add(movie)
    db.commit()
    db.refresh(movie)
    db.close()
    print(f"Saved movie {movie.title_en} (TMDB ID: {movie.tmdb_id}) to the database.")

if __name__ == "__main__":
    data=fetch_movie_from_tmdb(550)  # 550 = Fight Club, just a known test ID
    save_movie_to_db(data)