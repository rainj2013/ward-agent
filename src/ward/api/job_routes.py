"""Analysis job creation, status, trace, and event routes."""

import asyncio

from fastapi import APIRouter, Depends

from ward.api.dependencies import RuntimeServices, get_services
from ward.api.sse import sse_data, sse_response
from ward.schemas.models import AnalysisJobCreateResponse, AnalysisJobResponse


router = APIRouter(prefix="/api", tags=["analysis-jobs"])
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


async def job_event_stream(job_id: str, services: RuntimeServices):
    last_event_id = 0
    while True:
        job = services.jobs.get_job(job_id)
        if not job:
            yield sse_data({"ok": False, "error": "Job not found", "done": True})
            return
        events = services.jobs.get_events(job_id, last_event_id)
        for event in events:
            last_event_id = event["id"]
            payload = {"ok": True, **event, "job": job, "done": False}
            if job.get("status") in TERMINAL_STATUSES and event["event"] in {"succeeded", "failed"}:
                payload["job"] = services.jobs.get_job(job_id)
                payload["done"] = True
            yield sse_data(payload)
        if job.get("status") in TERMINAL_STATUSES:
            if not events:
                yield sse_data({"ok": True, "event": "done", "job": job, "done": True})
            return
        await asyncio.sleep(0.5)


async def _create_job(services: RuntimeServices, job_type: str, payload: dict) -> AnalysisJobCreateResponse:
    try:
        return AnalysisJobCreateResponse(ok=True, job=await services.jobs.create_job(job_type, payload))
    except Exception as exc:
        return AnalysisJobCreateResponse(ok=False, error=str(exc))


@router.post("/analysis-jobs/index/{prefix}", response_model=AnalysisJobCreateResponse)
async def create_index_job(prefix: str, services: RuntimeServices = Depends(get_services)):
    return await _create_job(services, "index_analysis", {"prefix": prefix})


@router.post("/analysis-jobs/stock/{symbol}", response_model=AnalysisJobCreateResponse)
async def create_stock_job(symbol: str, services: RuntimeServices = Depends(get_services)):
    return await _create_job(services, "stock_analysis", {"symbol": symbol.upper()})


@router.post("/analysis-jobs/report", response_model=AnalysisJobCreateResponse)
async def create_report_job(services: RuntimeServices = Depends(get_services)):
    return await _create_job(services, "market_report", {})


@router.get("/analysis-jobs/{job_id}", response_model=AnalysisJobResponse)
def get_job(job_id: str, services: RuntimeServices = Depends(get_services)):
    job = services.jobs.get_job(job_id)
    return AnalysisJobResponse(ok=bool(job), job=job, error=None if job else "Job not found")


@router.get("/analysis-jobs/{job_id}/trace")
def get_job_trace(job_id: str, services: RuntimeServices = Depends(get_services)):
    trace = services.jobs.get_trace(job_id)
    return {"ok": bool(trace), **(trace or {"error": "Job not found"})}


@router.get("/analysis-jobs/{job_id}/events")
async def stream_job_events(job_id: str, services: RuntimeServices = Depends(get_services)):
    return sse_response(job_event_stream(job_id, services))


@router.get("/runtime/stats")
def runtime_stats(range: str = "1d", services: RuntimeServices = Depends(get_services)):
    return {"ok": True, "stats": services.jobs.get_stats(range)}
