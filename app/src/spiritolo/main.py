"""``create_app`` wires settings, the database, the executor, the routers and
the static web build into one FastAPI application."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from ingredients.worker import runner

from .auth import Sessions
from .db import Database
from .deps import AppState
from .executor import Executor
from .routers import auth as auth_router
from .routers import ops as ops_router
from .routers import public as public_router
from .settings import Settings, from_env

log = logging.getLogger("spiritolo")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or from_env()
    db = Database(settings.db_path)
    executor = Executor(db, poll_seconds=settings.executor_poll_seconds) if settings.run_executor else None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        boot = db.new_connection(actor=("system", None, "boot"))
        try:
            runner.requeue_interrupted(boot)
        finally:
            boot.close()
        if executor is not None:
            executor.start()
        log.info("spiritolo up: db=%s origin=%s executor=%s", settings.db_path, settings.public_origin,
                 executor is not None)
        try:
            yield
        finally:
            if executor is not None:
                executor.stop()
            db.close_all()

    app = FastAPI(title="Spiritolo", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.spiritolo = AppState(settings=settings, db=db, sessions=Sessions(settings), executor=executor)

    if settings.extra_origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=list(settings.extra_origins), allow_credentials=True,
            allow_methods=["*"], allow_headers=["*"],
        )

    app.include_router(public_router.router)
    app.include_router(auth_router.router)
    app.include_router(ops_router.router)

    @app.get("/api/health")
    def health() -> dict:
        c = db.connection()
        c.execute("select 1").fetchone()
        return {"ok": True, "executor": executor.health() if executor is not None else {"alive": False}}

    @app.exception_handler(404)
    async def not_found(request: Request, exc):  # noqa: ANN001
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": getattr(exc, "detail", "not found")}, status_code=404)
        return _spa(settings, request.url.path)

    if settings.static_dir:
        static = Path(settings.static_dir)

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):  # noqa: ANN202
            if path.startswith("api/"):
                return JSONResponse({"detail": "not found"}, status_code=404)
            candidate = (static / path).resolve() if path else None
            if candidate and candidate.is_file() and str(candidate).startswith(str(static.resolve())):
                return FileResponse(candidate)
            return _spa(settings, path)

    return app


def _spa(settings: Settings, path: str):  # noqa: ANN202
    if settings.static_dir:
        index = Path(settings.static_dir) / "index.html"
        if index.is_file():
            return FileResponse(index, headers={"cache-control": "no-cache"})
    return JSONResponse({"detail": "not found"}, status_code=404)


def app() -> FastAPI:
    """The uvicorn factory target: ``uvicorn spiritolo.main:app --factory``."""
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app()
