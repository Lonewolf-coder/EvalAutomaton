"""API Routes — FastAPI endpoints for evaluation management."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from ..core.engine import EvaluationEngine
from ..core.manifest import Manifest
from ..core.manifest_validator import validate_manifest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["evaluation"])


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
    cbm_only: bool = False


class EvaluationResponse(BaseModel):
    session_id: str
    overall_score: float
    has_critical_failures: bool
    state_seeded: bool
    scorecard: dict[str, Any]


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
            })
    return {"results": results}
