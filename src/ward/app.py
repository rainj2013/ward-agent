"""FastAPI app entry point."""

from __future__ import annotations

import uvicorn
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from ward.api.routes import router as api_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Nasdaq Agent",
        description="Nasdaq market analysis with AI",
        version="0.1.0",
    )
    app.include_router(api_router)

    # Mount static files
    static_dir = Path(__file__).parent.parent.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("ward.app:app", host="0.0.0.0", port=8000, reload=True)
