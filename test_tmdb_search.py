import os
import requests
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("TMDB_TOKEN")

def search_movie(query: str, language: str = "he-IL"):
    url = "https://api.themoviedb.org/3/search/movie"
    headers = {"Authorization": f"Bearer {token}", "accept": "application/json"}
    params = {"query": query, "language": language}
    response = requests.get(url, headers=headers, params=params)
    return response.json()

if __name__ == "__main__":
    for query in ["גבעה 338", "פיוז", "בוסית בהפרעה"]:
        print(f"\nSearching: {query}")
        results = search_movie(query)
        for r in results.get("results", [])[:3]:
            print(r["id"], r.get("title"), r.get("release_date"))