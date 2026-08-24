import os
import requests
from dotenv import load_dotenv

load_dotenv()  # reads the .env file and loads it into the environment

token = os.getenv("TMDB_TOKEN")

url = "https://api.themoviedb.org/3/movie/550"  # 550 = Fight Club, just a known test ID
headers = {
    "Authorization": f"Bearer {token}",
    "accept": "application/json"
}

response = requests.get(url, headers=headers)
print(response.status_code)
print(response.json())