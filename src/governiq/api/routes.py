"""API Routes — FastAPI endpoints for evaluation management."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..core.engine import EvaluationEngine
from ..core.llm_config import load_llm_config
from ..core.manifest import Manifest
from ..core.manifest_validator import validate_manifest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["evaluation"])

DATA_DIR = Path("data")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ManifestValidationRequest(BaseModel):
    manifest: dict[str, Any]


class EvaluationRequest(BaseModel):
    manifest: dict[str, Any]
    bot_export: dict[str, Any]
    candidate_id: str = ""
    webhook_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "claude-haiku-4-5-20251001"
    cbm_only: bool = False


class AnalyticsRefreshResponse(BaseModel):
    session_id: str
    analytics_status: str
    analytics_last_checked_at: str | None
    tasks_with_data: int = 0
    total_tasks: int = 0
    message: str = ""


class EvaluationResponse(BaseModel):
    session_id: str
    overall_score: float
    has_critical_failures: bool
    state_seeded: bool
    scorecard: dict[str, Any]


class ResumeResponse(BaseModel):
    session_id: str
    overall_score: float
    has_critical_failures: bool
    completed_tasks: list[str]
    scorecard: dict[str, Any]


class TestAIRequest(BaseModel):
    provider: str = "lmstudio"
    url: str = "http://localhost:1234/v1"
    api_key: str = ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/manifest/validate")
async def validate_manifest_endpoint(request: ManifestValidationRequest):
    """Validate a manifest against MD rules before evaluation."""
    try:
        manifest = Manifest(**request.manifest)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid manifest schema: {e}")

    result = validate_manifest(manifest)
    return {
        "valid": result.valid,
        "errors": [
            {"rule_id": d.rule_id, "message": d.message, "task_id": d.task_id}
            for d in result.errors
        ],
        "warnings": [
            {"rule_id": d.rule_id, "message": d.message, "task_id": d.task_id}
            for d in result.warnings
        ],
    }


@router.post("/evaluate", response_model=EvaluationResponse)
async def run_evaluation(request: EvaluationRequest):
    """Run a full evaluation (or CBM-only) against a bot export."""
    try:
        manifest_data = request.manifest
        if request.webhook_url:
            manifest_data["webhook_url"] = request.webhook_url
        manifest = Manifest(**manifest_data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid manifest: {e}")

    engine = EvaluationEngine(
        manifest=manifest,
        llm_api_key=request.llm_api_key,
    )

    try:
        if request.cbm_only:
            scorecard = await engine.run_cbm_only(
                bot_export=request.bot_export,
                candidate_id=request.candidate_id,
            )
        else:
            scorecard = await engine.run_full_evaluation(
                bot_export=request.bot_export,
                candidate_id=request.candidate_id,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Evaluation failed")
        raise HTTPException(status_code=500, detail=f"Evaluation error: {e}")

    return EvaluationResponse(
        session_id=scorecard.session_id,
        overall_score=scorecard.overall_score,
        has_critical_failures=scorecard.has_critical_failures,
        state_seeded=scorecard.state_seeded,
        scorecard=scorecard.to_dict(),
    )


@router.post("/evaluate/upload")
async def run_evaluation_upload(
    manifest_file: UploadFile = File(...),
    bot_export_file: UploadFile = File(...),
    candidate_id: str = "",
    cbm_only: bool = True,
):
    """Run evaluation from uploaded files."""
    try:
        manifest_data = json.loads(await manifest_file.read())
        manifest = Manifest(**manifest_data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid manifest file: {e}")

    try:
        bot_export_data = json.loads(await bot_export_file.read())
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid bot export file: {e}")

    engine = EvaluationEngine(manifest=manifest)

    try:
        if cbm_only:
            scorecard = await engine.run_cbm_only(
                bot_export=bot_export_data,
                candidate_id=candidate_id,
            )
        else:
            scorecard = await engine.run_full_evaluation(
                bot_export=bot_export_data,
                candidate_id=candidate_id,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "session_id": scorecard.session_id,
        "overall_score": scorecard.overall_score,
        "scorecard": scorecard.to_dict(),
    }


@router.get("/results/{session_id}")
async def get_results(session_id: str):
    """Retrieve a previously generated scorecard."""
    results_dir = Path("./data/results")
    path = results_dir / f"scorecard_{session_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Scorecard not found.")
    with path.open("r") as f:
        return json.load(f)


@router.get("/results")
async def list_results():
    """List all available evaluation results."""
    results_dir = Path("./data/results")
    if not results_dir.exists():
        return {"results": []}
    files = sorted(results_dir.glob("scorecard_*.json"), reverse=True)
    results = []
    for f in files[:50]:
        with f.open("r") as fh:
            data = json.load(fh)
            results.append({
                "session_id": data.get("session_id"),
                "candidate_id": data.get("candidate_id"),
                "assessment_name": data.get("assessment_name"),
                "overall_score": data.get("overall_score"),
                "analytics_status": data.get("analytics_status", "pending"),
                "analytics_last_checked_at": data.get("analytics_last_checked_at"),
                "completed_tasks": data.get("completed_tasks", []),
            })
    return {"results": results}


@router.post("/evaluations/{session_id}/resume", response_model=ResumeResponse)
async def resume_evaluation(
    session_id: str,
    webhook_url: str = "",
    llm_api_key: str = "",
):
    """Resume an interrupted evaluation from its last checkpoint.

    Re-runs only the webhook tasks that had not yet completed when the
    original evaluation was interrupted (network failure, process kill, bot crash).
    CBM and compliance results from the original run are preserved unchanged.
    Cross-task entity values are restored from the saved RuntimeContext.

    The manifest originally used must be passed via query params or body.
    For now, the endpoint re-loads the manifest from the saved scorecard metadata.

    Args:
        session_id: Session ID of the interrupted run (from the original response).
        webhook_url: Optional webhook URL override (uses saved value if not provided).
        llm_api_key: Optional LLM API key for the conversation driver.
    """
    results_dir = Path("./data/results")
    scorecard_path = results_dir / f"scorecard_{session_id}.json"
    if not scorecard_path.exists():
        raise HTTPException(status_code=404, detail=f"Scorecard '{session_id}' not found.")

    with scorecard_path.open("r") as f:
        saved_data = json.load(f)

    completed = saved_data.get("completed_tasks", [])
    total_tasks = len(saved_data.get("task_scores", []))
    if len(completed) >= total_tasks and total_tasks > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Evaluation '{session_id}' already has all {total_tasks} tasks completed. "
                "Nothing to resume."
            ),
        )

    # We need the original manifest to reconstruct the engine.
    # The manifest_id is stored; look for a manifest file matching it.
    manifest_id = saved_data.get("manifest_id", "")
    manifest_obj = None
    manifests_dir = Path("./manifests")
    for mf in manifests_dir.glob("*.json"):
        try:
            with mf.open("r") as f:
                mdata = json.load(f)
            if mdata.get("manifest_id") == manifest_id:
                from ..core.manifest import Manifest
                manifest_obj = Manifest(**mdata)
                break
        except Exception:
            continue

    if manifest_obj is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Could not locate manifest '{manifest_id}' in ./manifests/. "
                "Provide the original manifest file to use resume."
            ),
        )

    if webhook_url:
        manifest_obj = manifest_obj.model_copy(update={"webhook_url": webhook_url})

    engine = EvaluationEngine(manifest=manifest_obj, llm_api_key=llm_api_key)

    try:
        scorecard = await engine.resume_evaluation(source_session_id=session_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Resume failed for session '%s'", session_id)
        raise HTTPException(status_code=500, detail=f"Resume error: {e}")

    return ResumeResponse(
        session_id=scorecard.session_id,
        overall_score=scorecard.overall_score,
        has_critical_failures=scorecard.has_critical_failures,
        completed_tasks=scorecard.completed_tasks,
        scorecard=scorecard.to_dict(),
    )


@router.post("/evaluations/{session_id}/refresh-analytics", response_model=AnalyticsRefreshResponse)
async def refresh_analytics(session_id: str):
    """Re-fetch Kore.ai analytics for a completed evaluation session.

    Safe to call multiple times. Kore.ai analytics data can take up to 10 hours
    to appear after a session ends. Each call overwrites the previous analytics
    data with the latest results and updates analytics_status and
    analytics_last_checked_at on the saved scorecard.

    Status values:
      - pending:   No data returned from Kore.ai yet.
      - partial:   Some tasks have data, others are still processing.
      - available: All tasks have analytics data.
    """
    # Build a minimal engine — no manifest/bot needed, just persist_dir + credentials
    from ..core.manifest import Manifest
    from ..webhook.jwt_auth import KoreCredentials
    import os

    kore_bot_id     = os.environ.get("KORE_BOT_ID", "")
    kore_client_id  = os.environ.get("KORE_CLIENT_ID", "")
    kore_client_secret = os.environ.get("KORE_CLIENT_SECRET", "")
    kore_platform_url  = os.environ.get("KORE_PLATFORM_URL", "https://bots.kore.ai")

    kore_credentials: KoreCredentials | None = None
    if kore_bot_id and kore_client_id and kore_client_secret:
        kore_credentials = KoreCredentials(
            bot_id=kore_bot_id,
            client_id=kore_client_id,
            client_secret=kore_client_secret,
            platform_url=kore_platform_url,
        )

    # Minimal manifest needed only to satisfy EvaluationEngine.__init__
    try:
        _dummy_manifest = Manifest(
            manifest_id="_refresh",
            assessment_name="_refresh",
            webhook_url="",
            tasks=[],
        )
    except Exception:
        _dummy_manifest = None

    if _dummy_manifest is None:
        raise HTTPException(status_code=500, detail="Could not construct engine for refresh.")

    engine = EvaluationEngine(
        manifest=_dummy_manifest,
        kore_credentials=kore_credentials,
    )

    try:
        result = await engine.run_analytics_refresh(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Scorecard '{session_id}' not found.")
    except Exception as e:
        logger.exception("Analytics refresh failed for session '%s'", session_id)
        raise HTTPException(status_code=500, detail=f"Refresh error: {e}")

    return AnalyticsRefreshResponse(
        session_id=result["session_id"],
        analytics_status=result["analytics_status"],
        analytics_last_checked_at=result.get("analytics_last_checked_at"),
        tasks_with_data=result.get("tasks_with_data", 0),
        total_tasks=result.get("total_tasks", 0),
        message=result.get("message", ""),
    )


# ---------------------------------------------------------------------------
# Log streaming
# ---------------------------------------------------------------------------

def read_log_entries(
    session_id: str,
    offset: int = 0,
    logs_dir: Path | None = None,
) -> dict:
    """Read log entries from the JSONL file starting at offset."""
    logs_dir = logs_dir or (DATA_DIR / "logs")
    log_file = logs_dir / f"eval_{session_id}.jsonl"

    entries = []
    if log_file.exists():
        try:
            lines = log_file.read_text(encoding="utf-8").strip().split("\n")
            lines = [l for l in lines if l.strip()]
            for line in lines[offset:]:
                try:
                    entries.append(json.loads(line))
                except Exception:
                    pass
        except Exception:
            pass

    next_offset = offset + len(entries)

    # Check if evaluation is in terminal state
    stub_path = DATA_DIR / "results" / f"scorecard_{session_id}.json"
    done = False
    if stub_path.exists():
        try:
            stub = json.loads(stub_path.read_text())
            done = stub.get("status") in ("completed", "error", "halted")
        except Exception:
            pass

    return {"entries": entries, "next_offset": next_offset, "done": done}


@router.get("/logs/{session_id}")
async def get_evaluation_log(session_id: str, offset: int = 0):
    """Stream evaluation log entries for the live log panel."""
    return JSONResponse(read_log_entries(session_id=session_id, offset=offset))


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------

from ..core.health import check_ai_model as _check_ai_model_impl

_health_cache: dict = {}
_HEALTH_LLM_TTL = timedelta(seconds=25)


def _probe_llm_provider(config=None) -> dict:
    """Make a live call to the LLM provider. No caching. Testable."""
    return _check_ai_model_impl(config=config)


def _check_ai_model(url: str = "", api_key: str = "") -> dict:
    """Check AI provider with TTL caching to avoid burning rate-limit quota."""
    # url/api_key overrides bypass cache (used by live test-ai endpoint)
    if url or api_key:
        return _check_ai_model_impl(url=url, api_key=api_key)

    config = load_llm_config()
    cache_key = f"{config.api_format}:{config.base_url}:{config.model}"

    cached = _health_cache.get(cache_key)
    if cached:
        age = datetime.now(timezone.utc) - cached["cached_at"]
        if age < _HEALTH_LLM_TTL:
            return cached["result"]

    result = _probe_llm_provider(config)
    _health_cache[cache_key] = {"result": result, "cached_at": datetime.now(timezone.utc)}
    return result


def _check_storage() -> dict:
    """Check if the results directory is writable."""
    results_dir = Path("./data/results")
    try:
        results_dir.mkdir(parents=True, exist_ok=True)
        test_file = results_dir / ".health_check"
        test_file.write_text("ok")
        test_file.unlink()
        return {
            "status": "ok",
            "message": "Storage is working correctly.",
            "detail": str(results_dir.resolve()),
        }
    except Exception as exc:
        return {
            "status": "failing",
            "message": "Results cannot be saved. Check that you have write permission to the data folder.",
            "detail": str(exc)[:120],
        }


def _check_manifests() -> dict:
    """Check that at least one manifest file exists."""
    manifests_dir = Path("./manifests")
    if not manifests_dir.exists():
        return {
            "status": "failing",
            "message": "No assessment is configured. Go to Manifests to load one.",
            "detail": "manifests/ directory not found",
        }
    manifests = list(manifests_dir.glob("*.json"))
    if not manifests:
        return {
            "status": "failing",
            "message": "No assessment is configured. Go to Manifests to upload one.",
            "detail": "No .json files in manifests/",
        }
    return {
        "status": "ok",
        "message": f"{len(manifests)} assessment(s) available.",
        "detail": f"{len(manifests)} manifest(s) found",
    }


@router.get("/health")
async def system_health():
    """Live subsystem health check. Called by the health bar on every page load."""
    ai = _check_ai_model()
    storage = _check_storage()
    manifests = _check_manifests()
    app_sub = {
        "status": "ok",
        "message": "GovernIQ is running correctly.",
        "detail": "process alive",
    }

    subsystems = {
        "ai_model": ai,
        "storage": storage,
        "manifests": manifests,
        "app": app_sub,
    }

    advisories: list[str] = []
    if any(s["status"] == "failing" for s in subsystems.values()):
        overall = "error"
    else:
        overall = "ok"

    return {"status": overall, "subsystems": subsystems, "advisories": advisories}


@router.post("/health/test-ai")
async def test_ai_connection(request: TestAIRequest):
    """Test an AI provider connection without saving the config."""
    result = _check_ai_model(url=request.url, api_key=request.api_key)
    return {"status": result["status"], "message": result["message"]}
