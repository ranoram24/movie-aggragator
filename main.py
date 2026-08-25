import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import func

import scheduler
from api_movies import router as movies_router
from database import SessionLocal
from models import CinemaSource, Theatre, SourceMovieListing, Screening
from scrapers import SCRAPERS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

# Port 8000 is deliberately left alone -- it is reserved for something else.
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", 8010))
FRONTEND_PORT = int(os.getenv("FRONTEND_PORT", 5173))

# Handles to the background scrape loops, so shutdown can cancel them.
_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: begin scraping in the background. This returns immediately --
    # the first scrape runs concurrently, so the API is up right away.
    scheduler.start(_tasks)
    yield
    # Shutdown: stop the loops so uvicorn can exit cleanly instead of hanging
    # on a scrape that is mid-flight.
    await scheduler.stop(_tasks)


app = FastAPI(title="Movie Screenings Aggregator", lifespan=lifespan)

# Only needed if the frontend ends up as a separate dev server on its own port
# (React/Vite and friends). A server-rendered frontend is same-origin and does
# not need this. Scoped to localhost only -- do not widen this to "*".
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://localhost:{FRONTEND_PORT}",
        f"http://127.0.0.1:{FRONTEND_PORT}",
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Product API (what's playing / showtimes) lives in its own module; this file
# stays the scraper control plane.
app.include_router(movies_router)


# Response models. Without these FastAPI has no idea what a route returns -- it
# reads the return annotation, never the function body -- so /docs would show a
# meaningless "string" placeholder for every 200. Declaring them also makes
# FastAPI validate and serialise the response on the way out.

class RootResponse(BaseModel):
    status: str
    chains: list[str]


class ChainResult(BaseModel):
    theatres: int
    listings: int
    new_screenings: int
    skipped_unknown: int
    duplicates: int


class ChainStatus(BaseModel):
    state: str                      # pending | running | idle | error | cancelled
    last_run: str | None = None
    last_success: str | None = None
    last_error: str | None = None
    last_result: ChainResult | None = None
    runs: int
    failures: int


class ScrapeStatusResponse(BaseModel):
    window_days: int
    intervals_seconds: dict[str, int]
    chains: dict[str, ChainStatus]


class ScrapeStartedResponse(BaseModel):
    started: str
    note: str


class SourceStats(BaseModel):
    key: str | None = None
    name: str | None = None
    theatres: int
    listings: int
    screenings: int


class StatsResponse(BaseModel):
    sources: list[SourceStats]
    total_screenings: int


@app.get("/")
def read_root() -> RootResponse:
    return {"status": "ok", "chains": list(SCRAPERS)}


@app.get("/scrape/status")
def scrape_status() -> ScrapeStatusResponse:
    """What each background scraper is doing and when it last succeeded."""
    return {
        "window_days": scheduler.SCRAPE_DAYS,
        "intervals_seconds": scheduler.INTERVALS,
        "chains": scheduler.STATUS,
    }


@app.post("/scrape/{chain}")
async def scrape_now(chain: str) -> ScrapeStartedResponse:
    """Force one chain to scrape immediately, without waiting for its interval."""
    if chain not in SCRAPERS:
        raise HTTPException(404, f"Unknown chain '{chain}'. Options: {', '.join(SCRAPERS)}")
    if scheduler.STATUS[chain]["state"] == "running":
        raise HTTPException(409, f"'{chain}' is already running")

    # Fire and forget: Lev takes ~12 minutes, far too long to hold a request open.
    asyncio.create_task(scheduler.trigger(chain), name=f"scrape:{chain}:manual")
    return {"started": chain, "note": "runs in the background; poll /scrape/status"}


@app.get("/stats")
def stats() -> StatsResponse:
    """Row counts per chain, straight from the database."""
    db = SessionLocal()
    try:
        out = []
        for source in db.query(CinemaSource).order_by(CinemaSource.id):
            theatres = db.query(func.count(Theatre.id)).filter_by(
                cinema_source_id=source.id).scalar()
            listings = db.query(func.count(SourceMovieListing.id)).filter_by(
                cinema_source_id=source.id).scalar()
            screenings = db.query(func.count(Screening.id)).join(
                Theatre, Theatre.id == Screening.theatre_id).filter(
                Theatre.cinema_source_id == source.id).scalar()
            out.append({
                "key": source.key,
                "name": source.name,
                "theatres": theatres,
                "listings": listings,
                "screenings": screenings,
            })
        return {"sources": out, "total_screenings": sum(s["screenings"] for s in out)}
    finally:
        db.close()


if __name__ == "__main__":
    # Entry point so `python main.py` binds the project's port instead of
    # uvicorn's CLI default of 8000, which is reserved for something else.
    import uvicorn

    uvicorn.run("main:app", host=API_HOST, port=API_PORT, reload=True)
