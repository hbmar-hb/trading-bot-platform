"""
Admin System Routes — Health checks, logs, and system diagnostics.
Only accessible by admin users.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.dependencies import get_current_admin_user
from app.services.system_health_service import (
    check_infra,
    check_logs,
    check_database,
    check_models,
    check_celery,
    check_exchange,
    check_shadow_mode,
    run_full_check,
    generate_shareable_log,
)
from app.services.shadow_monitor_service import (
    run_shadow_monitor_check,
    get_shadow_monitor_history,
)

router = APIRouter(prefix="/admin/system", tags=["admin"])


class RunCheckRequest(BaseModel):
    check: str  # infra | logs | database | ml_models | celery | exchange | full


class ShareLogRequest(BaseModel):
    report: dict


@router.get("/health", summary="Quick health status")
async def admin_health(current_user=Depends(get_current_admin_user)):
    """Returns a quick OK if the admin is authenticated."""
    return {"status": "ok", "admin": str(current_user.id)}


@router.post("/run-check", summary="Run a specific health check")
async def run_check(req: RunCheckRequest, _=Depends(get_current_admin_user)):
    """Run a single health check or full report."""
    check_name = req.check

    if check_name == "infra":
        result = check_infra()
    elif check_name == "logs":
        result = check_logs()
    elif check_name == "database":
        result = await check_database()
    elif check_name == "ml_models":
        result = check_models()
    elif check_name == "celery":
        result = check_celery()
    elif check_name == "exchange":
        result = await check_exchange()
    elif check_name == "shadow_mode":
        result = check_shadow_mode()
    elif check_name == "full":
        return await run_full_check()
    else:
        raise HTTPException(status_code=400, detail=f"Unknown check: {check_name}")

    return {
        "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "status": "healthy" if result.healthy else ("critical" if any(i.startswith("🔴") for i in result.issues) else "warning"),
        "checks": {check_name: result.to_dict()},
        "summary": {
            "total_issues": len(result.issues),
            "criticals": sum(1 for i in result.issues if i.startswith("🔴")),
            "warnings": sum(1 for i in result.issues if i.startswith("🟡")),
            "issues_list": result.issues,
        },
    }


@router.get("/checks", summary="List available checks")
async def list_checks(_=Depends(get_current_admin_user)):
    """List all available health check names."""
    return {
        "checks": [
            {"id": "full", "label": "Full System Report", "description": "Runs all checks at once"},
            {"id": "infra", "label": "Infrastructure", "description": "RAM, disk, load average"},
            {"id": "logs", "label": "Logs", "description": "Recent errors in log files"},
            {"id": "database", "label": "Database", "description": "Signals, positions, bot status"},
            {"id": "ml_models", "label": "ML Models", "description": "Adaptive weights, bot models, drift"},
            {"id": "celery", "label": "Celery", "description": "Workers, tasks, queues"},
            {"id": "exchange", "label": "Exchange", "description": "Equity, connectivity"},
            {"id": "shadow_mode", "label": "Shadow Mode (Fase D)", "description": "Candidate model shadow evaluation"},
        ]
    }


@router.post("/share-log", summary="Generate a shareable text log")
async def share_log(req: ShareLogRequest, _=Depends(get_current_admin_user)):
    """Generate a plain-text log from a report for sharing."""
    try:
        text = generate_shareable_log(req.report)
        return {"log": text}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate log: {exc}")


@router.get("/shadow-history", summary="Shadow mode monitor history")
async def shadow_history(limit: int = 20, _=Depends(get_current_admin_user)):
    """Return recent shadow-mode check reports."""
    return {"history": get_shadow_monitor_history(limit=limit)}


@router.post("/run-shadow-check", summary="Run shadow mode check on demand")
async def run_shadow_check(_=Depends(get_current_admin_user)):
    """Run the shadow-mode monitor immediately and store the report."""
    try:
        report = run_shadow_monitor_check(save_history=True)
        return report
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Shadow monitor failed: {exc}")
