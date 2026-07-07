"""FastAPI app entry point."""

from __future__ import annotations

import uvicorn
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from ward.api.dependencies import create_runtime_services
from ward.api.page_routes import router as page_router
from ward.api.market_routes import router as market_router
from ward.api.job_routes import router as job_router
from ward.api.routes import router as api_router
from ward.api.settings_routes import router as settings_router
from ward.api.stock_routes import router as stock_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.services = create_runtime_services()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Nasdaq Agent",
        description="Nasdaq market analysis with AI",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(api_router)
    app.include_router(page_router)
    app.include_router(settings_router)
    app.include_router(stock_router)
    app.include_router(market_router)
    app.include_router(job_router)

    # Mount static files
    static_dir = Path(__file__).parent.parent.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app


app = create_app()


if __name__ == "__main__":
    from ward.core.config import get_config
    cfg = get_config()
    uvicorn.run("ward.app:app", host=cfg.web_host, port=cfg.web_port, reload=True)
