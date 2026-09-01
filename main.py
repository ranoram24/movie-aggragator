import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func

import auth
import migrate
import scheduler
from api_ingest import router as ingest_router
from api_movies import router as movies_router
from database import Base, SessionLocal, engine
from models import CinemaSource, Theatre, SourceMovieListing, Screening
from scrapers import SCRAPERS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

# Port 8000 is deliberately left alone -- it is reserved for something else.
# In a container the host must be 0.0.0.0, or the process is unreachable from
# outside it; locally 127.0.0.1 keeps the dev server off the network.
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", 8010))
FRONTEND_PORT = int(os.getenv("FRONTEND_PORT", 5173))

# When the built React app is present, FastAPI serves it too. That means one
# deploy, one URL, and no CORS at all in production -- the app and the API are
# the same origin.
FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist" 

# Handles to the background scrape loops, so shutdown can cancel them.
_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    # A fresh deploy starts with an empty volume, so the tables have to exist
    # before anything queries them. create_all only creates what is missing.
    Base.metadata.create_all(bind=engine)

    # ...and only whole tables: it will not add a column to a table that
    # already exists. Without this, adding a field to a model would leave the
    # deployed database a column short and every query touching it would fail.
    added = migrate.run()
    if added:
        logging.getLogger("scraper").info("schema: added %s missing column(s)", added)

    # Startup: begin scraping in the background. This returns immediately --
    # the first scrape runs concurrently, so the API is up right away.
    if os.getenv("RUN_SCHEDULER", "1") != "0":
        scheduler.start(_tasks)
    else:
        logging.getLogger("scraper").info("scheduler disabled via RUN_SCHEDULER=0")
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

# Accepts pushes for chains this host cannot scrape itself (see api_ingest).
app.include_router(ingest_router)


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
    # The second freshness layer. Kept in its own block rather than merged into
    # `chains`, because a chain can be scraping happily while having no cheap
    # way to be validated -- Lev, for one -- and flattening the two would make
    # that look like a failure.
    validation_horizon_hours: int
    validation_intervals_seconds: dict[str, int]
    validation: dict[str, dict]


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


@app.get("/health")
def health() -> RootResponse:
    """Liveness check. Not on "/" -- that path belongs to the React app in
    production, and a JSON body there would shadow the whole frontend."""
    return {"status": "ok", "chains": list(SCRAPERS)}


@app.get("/scrape/status")
def scrape_status() -> ScrapeStatusResponse:
    """What each background scraper is doing and when it last succeeded."""
    return {
        "window_days": scheduler.SCRAPE_DAYS,
        "intervals_seconds": scheduler.INTERVALS,
        "chains": scheduler.STATUS,
        "validation_horizon_hours": scheduler.VALIDATION_HORIZON_HOURS,
        "validation_intervals_seconds": {
            key: scheduler.VALIDATION_INTERVALS.get(
                key, scheduler.VALIDATION_INTERVAL_DEFAULT
            )
            for key in scheduler.VALIDATION_STATUS
        },
        "validation": scheduler.VALIDATION_STATUS,
    }


@app.post("/scrape/{chain}", dependencies=[Depends(auth.require_token)])
async def scrape_now(chain: str) -> ScrapeStartedResponse:
    """Force one chain to scrape immediately, without waiting for its interval.

    Behind the shared token. It was open, which let anyone start real scrapes on
    demand -- a Lev run takes about twelve minutes, so a handful of calls in a
    loop would keep the machine busy indefinitely at no cost to the caller.
    """
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


# ---------------------------------------------------------------- frontend
# Registered after every API route: matching is sequential, so /api/... and
# /docs resolve to their handlers and only genuine app paths fall through here.
if FRONTEND_DIST.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        """Hand every unmatched path to the React app.

        React Router owns routes like /movie/m17, which exist only in the
        browser -- there is no such file on disk, so without this a refresh or
        a shared link would 404.
        """
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")

else:
    @app.get("/", include_in_schema=False)
    def no_frontend():
        """Backend running without a built frontend -- the normal dev setup,
        where Vite serves the app separately on port 5173."""
        return {
            "status": "ok",
            "note": "API only; no built frontend here. Run the Vite dev server, "
                    "or `npm run build` in frontend/ to have this serve it.",
            "docs": "/docs",
        }


if __name__ == "__main__":
    # Entry point so `python main.py` binds the project's port instead of
    # uvicorn's CLI default of 8000, which is reserved for something else.
    import uvicorn

    uvicorn.run("main:app", host=API_HOST, port=API_PORT, reload=True)
