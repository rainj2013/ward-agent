"""Static page routes."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse


router = APIRouter()
STATIC_DIR = Path(__file__).resolve().parents[3] / "static"


@router.get("/", response_class=HTMLResponse)
async def home():
    return FileResponse(str(STATIC_DIR / "index.html"))


@router.get("/runtime", response_class=HTMLResponse)
async def runtime_page():
    return FileResponse(str(STATIC_DIR / "runtime.html"))
