"""Admin / Evaluator Portal Routes — Dashboard, review, manifest management."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

MANIFESTS_DIR = Path("manifests")
DATA_DIR = Path("data")


def _load_all_evaluations() -> list[dict[str, Any]]:
    results_dir = DATA_DIR / "results"
    if not results_dir.exists():
        return []
    evals = []
    for f in sorted(results_dir.glob("scorecard_*.json"), reverse=True):
        try:
            with f.open("r") as fh:
                evals.append(json.load(fh))
        except Exception:
            pass
    return evals


def _load_manifests_summary() -> list[dict[str, Any]]:
    results = []
    if not MANIFESTS_DIR.exists():
        return results
    for f in sorted(MANIFESTS_DIR.glob("*.json")):
        try:
            with f.open("r") as fh:
                data = json.load(fh)
            results.append({
                "name": data.get("assessment_name", f.stem),
                "type": data.get("assessment_type", "unknown"),
                "task_count": len(data.get("tasks", [])),
                "faq_count": len(data.get("faq_config", {}).get("required_faqs", [])),
                "compliance_count": len(data.get("compliance_checks", [])),
            })
        except Exception:
            pass
    return results


def _build_stats(evaluations: list[dict[str, Any]]) -> dict[str, int]:
    total = len(evaluations)
    passed = sum(1 for e in evaluations if e.get("overall_score", 0) >= 0.7 and not e.get("has_critical_failures"))
    critical = sum(1 for e in evaluations if e.get("has_critical_failures"))
    failed = total - passed
    return {"total": total, "passed": passed, "failed": failed, "critical": critical}


def _build_task_summary(scorecard: dict[str, Any]) -> dict[str, Any]:
    tasks = scorecard.get("task_scores", [])
    total = len(tasks)
    passed = sum(1 for t in tasks if t.get("all_passed"))
    return {"total": total, "passed": passed}


def _build_compliance_summary(scorecard: dict[str, Any]) -> dict[str, Any]:
    cr = scorecard.get("compliance_results", [])
    total = len(cr)
    passed = sum(1 for c in cr if c.get("status") == "pass")
    return {"total": total, "passed": passed, "all_passed": passed == total}


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    evaluations = _load_all_evaluations()
    manifests = _load_manifests_summary()
    stats = _build_stats(evaluations)
    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "portal": "admin",
        "evaluations": evaluations,
        "manifests": manifests,
        "stats": stats,
    })


@router.get("/review/{session_id}", response_class=HTMLResponse)
async def admin_review(request: Request, session_id: str):
    path = DATA_DIR / "results" / f"scorecard_{session_id}.json"
    if not path.exists():
        return HTMLResponse("<h1>Evaluation not found</h1>", status_code=404)

    with path.open("r") as f:
        scorecard = json.load(f)

    task_summary = _build_task_summary(scorecard)
    compliance_summary = _build_compliance_summary(scorecard)

    return templates.TemplateResponse("admin_review.html", {
        "request": request,
        "portal": "admin",
        "sc": scorecard,
        "task_summary": task_summary,
        "compliance_summary": compliance_summary,
    })
