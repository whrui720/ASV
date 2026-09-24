"""FastAPI app factory — docs/FRONTEND_PLAN.md §10/§11.

Run with:
    uvicorn api.main:app --reload --port 8000

In dev, the Vite frontend (``web/``) proxies ``/api`` to this process
(``web/vite.config.ts``) and runs on :5173 separately. In production,
``scripts/run_webapp.py`` builds the frontend once and this app serves the
static bundle directly, so the whole thing is one process on one port.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from apps.api.routers import benchmark, claims, config, paper, runs, sources

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_FRONTEND_DIST = _PROJECT_ROOT / "web" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(title="ASV", version="0.1.0")

    # Dev-mode CORS: Vite runs on a different origin (5173) than uvicorn (8000).
    # Harmless once the built frontend is served from this same origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in (
        runs.router, claims.router, sources.router, paper.router, config.router,
        benchmark.router,
    ):
        app.include_router(router)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    # Serve the built frontend (scripts/run_webapp.py builds web/ into web/dist
    # first) so `uvicorn api.main:app` alone is the whole app in production.
    # StaticFiles(html=True) only serves index.html at the exact root — a
    # client-side route like /runs/{id}/claims has no matching file on disk,
    # so it needs an explicit SPA-fallback catch-all rather than the mount
    # handling it. /assets/* (Vite's hashed bundle) is served directly.
    if _FRONTEND_DIST.exists():
        app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="assets")

        index_path = _FRONTEND_DIST / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404)
            candidate = _FRONTEND_DIST / full_path
            if full_path and candidate.is_file():
                return FileResponse(str(candidate))
            return FileResponse(str(index_path))

    return app


app = create_app()
