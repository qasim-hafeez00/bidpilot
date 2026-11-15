"""BidPilot API (FastAPI). Graph runs happen in the worker; the API reads checkpoints, enqueues work and streams events."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from apps.api import streaming
from apps.api.auth import upwork_oauth
from apps.api.routers import analytics, auth, jobs, messages, proposals, runs, settings
from common import db
from common.pii import setup_logging

WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    await db.init_schema()
    if os.environ.get("SEED_DEMO") == "1":  # hosted demo: make sure the reviewer account exists
        try:
            from scripts.seed_demo import main as seed

            await seed()
        except Exception as e:  # never block start-up on the demo seed
            print("demo seed skipped:", type(e).__name__, e)
    worker_task = None
    if os.environ.get("WORKER_MODE") == "inline":  # single-container free hosting: the Arq worker runs as a sibling task
        from arq.worker import Worker

        from worker.tasks import WorkerSettings

        w = Worker(**{k: getattr(WorkerSettings, k) for k in ("functions", "cron_jobs", "on_startup", "redis_settings", "max_jobs",
                                                             "job_timeout", "keep_result", "max_tries")}, handle_signals=False)
        worker_task = asyncio.create_task(w.async_run())
    yield
    if worker_task:
        worker_task.cancel()


app = FastAPI(title="BidPilot API", version="1.0.0", lifespan=lifespan,
              description="GigBid multi-agent freelancer copilot: jobs, proposals, approvals, messages, runs, analytics.")
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:15173").split(","),
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok", "service": "bidpilot-api"}


for r in (auth.router, jobs.router, proposals.router, messages.router, runs.router, streaming.router, analytics.router,
          settings.router, upwork_oauth.router):
    app.include_router(r)

if WEB_DIST.exists():  # production: serve the built React app from the same origin
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        f = WEB_DIST / path
        return FileResponse(f if path and f.is_file() else WEB_DIST / "index.html")
