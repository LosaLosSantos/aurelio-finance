"""FinTheAdvisor FastAPI application — Phase 1 / MVP.

Exposes the healthcheck and the resource routers. DB tables are created at
startup (lifespan). CORS is open toward the development frontend.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import logging
import pathlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.database import StartRefused, init_db
from app.routers import (
    accumulation_plans,
    cash_anchors,
    chain,
    chat,
    dashboard,
    expenses,
    goals,
    holdings,
    instruments,
    income_sources,
    institutions,
    liabilities,
    prices,
    real_assets,
    settings,
    snapshots,
    survey,
    transactions,
    transfers,
    watchlist,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # On startup: bring the database up to date, never without a copy of it.
    try:
        init_db()
    except StartRefused as refused:
        say_why_not(refused)
        raise
    yield
    # (no shutdown cleanup needed for now)


def say_why_not(refused: StartRefused) -> None:
    """Say why the app will not start in its own sentence, and only that.

    uvicorn follows a failed startup with the traceback Starlette formats for
    it, and FastAPI wraps this lifespan once for every router included below,
    so the sentence would arrive at the bottom of a long run of frames that add
    nothing to it. It is logged on its own, and the traceback that would repeat
    it is dropped; uvicorn's "Application startup failed. Exiting." follows.
    """
    console = logging.getLogger("uvicorn.error")
    console.error("%s", refused)
    console.addFilter(lambda record: "StartRefused" not in record.getMessage())


app = FastAPI(
    title="Aurelio API",
    version=__version__,
    lifespan=lifespan,
)

# CORS: the browser blocks calls between different "origins". The Vite frontend
# runs on :5173, the backend on :8000 -> different origins. Here we declare
# which origins are allowed to call the API from the browser.
FRONTEND_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],   # GET, POST, PUT, DELETE, OPTIONS...
    allow_headers=["*"],
)

# Attach the resource routers to the main app.
app.include_router(institutions.router)
app.include_router(accumulation_plans.router)
app.include_router(transactions.router)
app.include_router(snapshots.router)
app.include_router(holdings.router)
app.include_router(real_assets.router)
app.include_router(liabilities.router)
app.include_router(prices.router)
app.include_router(instruments.router)
app.include_router(income_sources.router)
app.include_router(expenses.router)
app.include_router(cash_anchors.router)
app.include_router(transfers.router)
app.include_router(dashboard.router)
app.include_router(settings.router)
app.include_router(survey.router)
app.include_router(goals.router)
app.include_router(chain.router)
app.include_router(chat.router)
app.include_router(watchlist.router)


@app.get("/api/health")
def health() -> dict:
    """Healthcheck: confirms the backend is up."""
    return {
        "status": "ok",
        "service": "aurelio-backend",
        "version": __version__,
    }


# --- Serving the built frontend -------------------------------------------
# When `frontend/dist` exists (after `npm run build`), the API also serves the
# app itself: one process, one URL, no Node running and no CORS in the picture.
# In development the folder is usually absent and Vite serves the frontend on
# :5173, proxying /api here — the same relative paths work in both cases.
_DIST = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "dist"

if _DIST.is_dir():
    # `html=True` makes unknown paths fall back to index.html, so the app keeps
    # working if it ever grows client-side routes. Mounted LAST so it can never
    # shadow an /api route.
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="frontend")
