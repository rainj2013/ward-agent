"""Local settings page and API routes."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from ward.api.dependencies import RuntimeServices, get_services
from ward.api.page_routes import STATIC_DIR
from ward.schemas.models import LLMSettingsUpdateRequest


router = APIRouter()


def require_local_request(request: Request) -> None:
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=403, detail="Settings are only available from localhost")


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    require_local_request(request)
    return FileResponse(str(STATIC_DIR / "settings.html"))


@router.get("/api/settings/llm")
def get_llm_settings(request: Request, services: RuntimeServices = Depends(get_services)):
    require_local_request(request)
    return {"ok": True, "settings": services.settings.get_llm_settings()}


@router.put("/api/settings/llm")
def update_llm_settings(
    request: Request,
    payload: LLMSettingsUpdateRequest,
    services: RuntimeServices = Depends(get_services),
):
    require_local_request(request)
    try:
        settings = services.settings.save_llm_settings(payload.base_url, payload.model, payload.api_key)
        return {"ok": True, "settings": settings}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
