import requests

url = "https://cinema-city.co.il/movies"
response = requests.get(url)
print(response.status_code)

with open("cinema_city_movies.html", "w", encoding="utf-8") as f:
    f.write(response.text)