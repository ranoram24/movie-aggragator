# Two stages: Node builds the React app, then a slim Python image runs the API
# and serves that build. The Node toolchain never ships to production -- it
# would roughly triple the image for no runtime benefit.

# ---------------------------------------------------------------- frontend
FROM node:22-slim AS frontend

WORKDIR /build
# Copy manifests first so this layer is cached unless dependencies change.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# Deliberately empty: with no base URL the app calls whatever origin serves it,
# so the deployed hostname never gets baked into the bundle. Set explicitly
# here in case a local .env with a localhost URL is ever present.
ENV VITE_API_BASE_URL=""
RUN npm run build

# ---------------------------------------------------------------- backend
FROM python:3.11-slim

# Keeps Python from writing .pyc files and makes logs appear immediately
# instead of sitting in a buffer, which matters when reading `fly logs`.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY scrapers/ ./scrapers/
COPY --from=frontend /build/dist ./frontend/dist

# The database lives on a mounted volume, not in the image: a container's own
# filesystem is discarded on every restart and redeploy.
ENV DATABASE_URL="sqlite:////data/movie_aggregator.db" \
    API_HOST="0.0.0.0" \
    API_PORT="8080"

EXPOSE 8080

# One worker on purpose. The background scraper lives inside the app process,
# so N workers would mean N copies of every scrape loop all writing to one
# SQLite file.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
