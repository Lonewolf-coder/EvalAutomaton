"""Candidate Portal Routes — Submission, history, and detailed report."""

from __future__ import annotations

import io
import json
import logging
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..core.engine import EvaluationEngine
from ..core.manifest import Manifest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/candidate", tags=["candidate"])

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

MANIFESTS_DIR = Path("manifests")
DATA_DIR = Path("data")


def _load_available_manifests() -> list[dict[str, Any]]:
    """Scan manifests/ directory and return summary info."""
    results = []
    if not MANIFESTS_DIR.exists():
        return results
    for f in sorted(MANIFESTS_DIR.glob("*.json")):
        try:
            with f.open("r") as fh:
                data = json.load(fh)
            results.append({
                "id": f.stem,
                "name": data.get("assessment_name", f.stem),
                "file": f.name,
            })
        except Exception:
            pass
    return results


def _load_submissions(candidate_id: str | None = None) -> list[dict[str, Any]]:
    """Load all scorecards, optionally filtered by candidate."""
    results_dir = DATA_DIR / "results"
    if not results_dir.exists():
        return []
    submissions = []
    for f in sorted(results_dir.glob("scorecard_*.json"), reverse=True):
        try:
            with f.open("r") as fh:
                data = json.load(fh)
            if candidate_id and data.get("candidate_id") != candidate_id:
                continue
            submissions.append(data)
        except Exception:
            pass
    return submissions


def _build_task_summary(scorecard: dict[str, Any]) -> dict[str, Any]:
    """Build task-level summary stats for the report."""
    tasks = scorecard.get("task_scores", [])
    total = len(tasks)
    passed = sum(1 for t in tasks if t.get("all_passed"))
    checks_total = 0
    checks_passed = 0
    for t in tasks:
        for c in t.get("cbm_checks", []) + t.get("webhook_checks", []):
            checks_total += 1
            if c.get("status") == "pass":
                checks_passed += 1
    return {"total": total, "passed": passed, "checks_total": checks_total, "checks_passed": checks_passed}


def _build_compliance_summary(scorecard: dict[str, Any]) -> dict[str, Any]:
    cr = scorecard.get("compliance_results", [])
    total = len(cr)
    passed = sum(1 for c in cr if c.get("status") == "pass")
    return {"total": total, "passed": passed, "all_passed": passed == total}


def _build_recommendations(scorecard: dict[str, Any]) -> list[dict[str, str]]:
    """Generate plain-English recommendations from scorecard failures and CBM insights."""
    recs = []
    # Compliance failures
    for cr in scorecard.get("compliance_results", []):
        if cr.get("status") == "fail":
            priority = "high" if cr.get("critical") else "medium"
            recs.append({
                "title": f"Fix compliance: {cr.get('label', 'Unknown')}",
                "description": f"The check requires '{cr.get('required_state')}' but found '{cr.get('actual_value', 'not found')}'. "
                               f"Go to your bot settings and update this configuration before re-exporting.",
                "priority": priority,
            })

    # Task failures
    for ts in scorecard.get("task_scores", []):
        failed_checks = [
            c for c in ts.get("cbm_checks", []) + ts.get("webhook_checks", [])
            if c.get("status") == "fail"
        ]
        for fc in failed_checks:
            recs.append({
                "title": f"{ts.get('task_name', 'Task')}: {fc.get('label', 'Check failed')}",
                "description": fc.get("details", "Review this check and fix the underlying issue."),
                "priority": "high" if "required" in fc.get("details", "").lower() or "not found" in fc.get("details", "").lower() else "medium",
            })

        # CBM insight-based recommendations (from warning-level checks)
        warning_checks = [
            c for c in ts.get("cbm_checks", [])
            if c.get("status") == "warning"
        ]
        for wc in warning_checks:
            check_id = wc.get("check_id", "")
            details = wc.get("details", "")
            if "validation" in check_id and "no validation" in details:
                entity = wc.get("label", "").replace("Entity '", "").replace("' validation rules", "")
                recs.append({
                    "title": f"Add validation rules to '{entity}'",
                    "description": (
                        f"Entity '{entity}' has no validation rules. Adding validation "
                        "(regex, min/max length) prevents invalid input from reaching your API."
                    ),
                    "priority": "high",
                })
            elif "not_found_handling" in check_id:
                recs.append({
                    "title": "Add error handling message",
                    "description": (
                        "No error/not-found message node detected. Add a message node "
                        "that handles API errors or invalid lookups for better user experience."
                    ),
                    "priority": "medium",
                })
            elif "summary_display" in check_id:
                recs.append({
                    "title": "Add booking summary display",
                    "description": (
                        "No prompt or message node for displaying a booking summary "
                        "before confirmation. A summary step improves transparency."
                    ),
                    "priority": "medium",
                })

        # Service nodes without error handling (from INFO checks)
        info_checks = [
            c for c in ts.get("cbm_checks", [])
            if c.get("status") == "info" and "service_design" in c.get("check_id", "")
            and "no explicit error handling" in c.get("details", "")
        ]
        for ic in info_checks:
            service_name = ic.get("label", "").replace("Service '", "").replace("' integration", "")
            recs.append({
                "title": f"Add error handling for '{service_name}'",
                "description": (
                    f"Service node '{service_name}' has no error handling branch. "
                    "Add a message node to handle API failures gracefully."
                ),
                "priority": "medium",
            })

    # Deduplicate and limit
    seen = set()
    unique = []
    for r in recs:
        key = r["title"]
        if key not in seen:
            seen.add(key)
            unique.append(r)
    # Sort: high first
    unique.sort(key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x["priority"], 3))
    return unique[:20]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def candidate_submit_page(request: Request):
    """Candidate submission form."""
    available = _load_available_manifests()
    return templates.TemplateResponse("candidate_submit.html", {
        "request": request,
        "portal": "candidate",
        "available_manifests": available,
        "error": None,
    })


@router.post("/submit")
async def candidate_submit(
    request: Request,
    candidate_name: str = Form(""),
    candidate_email: str = Form(""),
    assessment_type: str = Form(""),
    mock_api_url: str = Form(""),
    mock_api_schema: str = Form(""),
    webhook_url: str = Form(""),
    bot_id: str = Form(""),
    bot_name: str = Form(""),
    client_id: str = Form(""),
    client_secret: str = Form(""),
    bot_export: UploadFile = File(...),
):
    """Handle candidate submission — run evaluation and redirect to report."""
    from ..webhook.jwt_auth import KoreCredentials, get_kore_bearer_token
    from ..core.llm_config import load_llm_config

    available = _load_available_manifests()
    candidate_id = candidate_email  # Email is the primary identifier

    # Validate assessment selection
    if not assessment_type:
        return templates.TemplateResponse("candidate_submit.html", {
            "request": request,
            "portal": "candidate",
            "available_manifests": available,
            "error": "Please select an assessment type.",
        })

    # Load manifest
    manifest_path = MANIFESTS_DIR / f"{assessment_type}.json"
    if not manifest_path.exists():
        return templates.TemplateResponse("candidate_submit.html", {
            "request": request,
            "portal": "candidate",
            "available_manifests": available,
            "error": f"Assessment manifest '{assessment_type}' not found.",
        })

    try:
        with manifest_path.open("r") as f:
            manifest_data = json.load(f)
        if webhook_url:
            manifest_data["webhook_url"] = webhook_url
        if mock_api_url:
            manifest_data["mock_api_base_url"] = mock_api_url
        manifest = Manifest(**manifest_data)
    except Exception as e:
        return templates.TemplateResponse("candidate_submit.html", {
            "request": request,
            "portal": "candidate",
            "available_manifests": available,
            "error": f"Manifest error: {e}",
        })

    # Parse bot export — supports JSON file or ZIP archive containing JSON
    try:
        content = await bot_export.read()
        filename = (bot_export.filename or "").lower()

        # Detect ZIP by filename extension or magic bytes (PK\x03\x04)
        if filename.endswith(".zip") or content[:4] == b"PK\x03\x04":
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    # Find JSON files, skip macOS/system junk
                    json_files = [
                        n for n in zf.namelist()
                        if n.endswith(".json")
                        and not n.startswith("__MACOSX")
                        and not n.startswith(".")
                    ]
                    if not json_files:
                        raise ValueError("No JSON file found inside the ZIP archive.")
                    # Prefer the largest JSON file (most likely the bot export)
                    json_files.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
                    with zf.open(json_files[0]) as jf:
                        bot_export_data = json.loads(jf.read())
            except zipfile.BadZipFile:
                raise ValueError("The uploaded file is not a valid ZIP archive.")
        else:
            bot_export_data = json.loads(content)
    except Exception as e:
        return templates.TemplateResponse("candidate_submit.html", {
            "request": request,
            "portal": "candidate",
            "available_manifests": available,
            "error": f"Invalid bot export file: {e}. Please upload a valid JSON file or ZIP archive.",
        })

    # JWT Authentication
    # - App-scope JWT: Used directly as bearer for webhook calls (no exchange needed)
    # - Admin-scope JWT: Exchanged for bearer token via /oAuth/token/jwtgrant (for public APIs)
    kore_bearer_token = ""  # Admin bearer for Kore public APIs only
    kore_creds = None
    if bot_id and client_id and client_secret:
        kore_creds = KoreCredentials(
            bot_id=bot_id,
            client_id=client_id,
            client_secret=client_secret,
            bot_name=bot_name,
        )
        # Try to get admin bearer token for Kore public APIs (non-fatal if fails)
        try:
            kore_bearer_token = await get_kore_bearer_token(kore_creds)
            logger.info("Kore.ai admin bearer token obtained for bot %s", bot_id)
        except Exception as e:
            logger.warning("Admin JWT grant failed: %s — public API insights unavailable", e)

    # Load LLM config from admin settings
    llm_config = load_llm_config()

    # Run evaluation
    engine = EvaluationEngine(
        manifest=manifest,
        llm_api_key=llm_config.api_key,
        llm_model=llm_config.model,
        llm_base_url=llm_config.base_url,
        llm_api_format=llm_config.api_format,
        kore_bearer_token=kore_bearer_token,
        kore_credentials=kore_creds,
    )
    try:
        # Run full evaluation if webhook URL or Kore credentials are available
        if webhook_url or kore_creds:
            scorecard = await engine.run_full_evaluation(
                bot_export=bot_export_data,
                candidate_id=candidate_id,
            )
        else:
            scorecard = await engine.run_cbm_only(
                bot_export=bot_export_data,
                candidate_id=candidate_id,
            )
    except ValueError as e:
        return templates.TemplateResponse("candidate_submit.html", {
            "request": request,
            "portal": "candidate",
            "available_manifests": available,
            "error": f"Evaluation error: {e}",
        })
    except Exception as e:
        logger.exception("Evaluation failed for candidate %s", candidate_id)
        return templates.TemplateResponse("candidate_submit.html", {
            "request": request,
            "portal": "candidate",
            "available_manifests": available,
            "error": f"Unexpected evaluation error: {e}",
        })

    # Redirect to report
    return RedirectResponse(
        url=f"/candidate/report/{scorecard.session_id}",
        status_code=303,
    )


@router.get("/history", response_class=HTMLResponse)
async def candidate_history(request: Request):
    """Show submission history."""
    submissions = _load_submissions()
    return templates.TemplateResponse("candidate_history.html", {
        "request": request,
        "portal": "candidate",
        "submissions": submissions,
    })


@router.get("/report/{session_id}", response_class=HTMLResponse)
async def candidate_report(request: Request, session_id: str):
    """Detailed evaluation report for a specific submission."""
    results_dir = DATA_DIR / "results"
    path = results_dir / f"scorecard_{session_id}.json"
    if not path.exists():
        return HTMLResponse(
            "<h1>Report not found</h1><p>This evaluation session does not exist.</p>",
            status_code=404,
        )

    with path.open("r") as f:
        scorecard = json.load(f)

    task_summary = _build_task_summary(scorecard)
    compliance_summary = _build_compliance_summary(scorecard)
    recommendations = _build_recommendations(scorecard)

    return templates.TemplateResponse("candidate_report.html", {
        "request": request,
        "portal": "candidate",
        "sc": scorecard,
        "task_summary": task_summary,
        "compliance_summary": compliance_summary,
        "recommendations": recommendations,
    })
