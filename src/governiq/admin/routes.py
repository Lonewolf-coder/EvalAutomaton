"""Admin / Evaluator Portal Routes — Dashboard, review, manifest management, LLM config."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..core.llm_config import (
    LLMConfig,
    get_provider_info,
    load_llm_config,
    save_llm_config,
    PROVIDER_DEFAULTS,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

MANIFESTS_DIR = Path("manifests")
ARCHIVED_DIR = MANIFESTS_DIR / "archived"
SCHEMA_DIR = MANIFESTS_DIR / "schema"
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


def _load_manifests_summary(include_archived: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load manifest summaries. Returns (active, archived)."""
    active: list[dict[str, Any]] = []
    archived: list[dict[str, Any]] = []
    if MANIFESTS_DIR.exists():
        for f in sorted(MANIFESTS_DIR.glob("*.json")):
            try:
                with f.open("r") as fh:
                    data = json.load(fh)
                active.append({
                    "id": data.get("manifest_id", f.stem),
                    "name": data.get("assessment_name", f.stem),
                    "type": data.get("assessment_type", "unknown"),
                    "version": data.get("manifest_version", "1.0"),
                    "task_count": len(data.get("tasks", [])),
                    "faq_count": len(data.get("faq_config", {}).get("required_faqs", [])),
                    "compliance_count": len(data.get("compliance_checks", [])),
                    "created_by": data.get("created_by", ""),
                })
            except Exception:
                pass
    if include_archived and ARCHIVED_DIR.exists():
        for f in sorted(ARCHIVED_DIR.glob("*.json")):
            try:
                with f.open("r") as fh:
                    data = json.load(fh)
                archived.append({
                    "id": data.get("manifest_id", f.stem),
                    "name": data.get("assessment_name", f.stem),
                    "type": data.get("assessment_type", "unknown"),
                })
            except Exception:
                pass
    return active, archived


def _load_manifest(manifest_id: str) -> dict[str, Any] | None:
    """Load a single manifest by ID. Checks both active and archived."""
    for directory in [MANIFESTS_DIR, ARCHIVED_DIR]:
        if not directory.exists():
            continue
        for f in directory.glob("*.json"):
            try:
                with f.open("r") as fh:
                    data = json.load(fh)
                if data.get("manifest_id") == manifest_id or f.stem == manifest_id:
                    return data
            except Exception:
                pass
    return None


def _save_manifest(data: dict[str, Any]) -> Path:
    """Save manifest to disk. Returns the file path."""
    MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
    manifest_id = data.get("manifest_id", "untitled")
    path = MANIFESTS_DIR / f"{manifest_id}.json"
    with path.open("w") as f:
        json.dump(data, f, indent=2)
    return path


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
    manifests, _ = _load_manifests_summary()
    stats = _build_stats(evaluations)
    llm_config = load_llm_config()
    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "portal": "admin",
        "evaluations": evaluations,
        "manifests": manifests,
        "stats": stats,
        "llm_config": llm_config,
        "providers": get_provider_info(),
    })


@router.post("/llm-config")
async def save_llm_settings(
    request: Request,
    provider: str = Form("anthropic"),
    api_key: str = Form(""),
    model: str = Form(""),
    base_url: str = Form(""),
    temperature: str = Form("0.3"),
):
    """Save LLM provider configuration from admin dashboard."""
    defaults = PROVIDER_DEFAULTS.get(provider, {})

    config = LLMConfig(
        provider=provider,
        api_key=api_key,
        model=model or defaults.get("default_model", ""),
        base_url=base_url or defaults.get("base_url", ""),
        api_format=defaults.get("api_format", "openai"),
        temperature=float(temperature),
    )
    save_llm_config(config)
    return RedirectResponse(url="/admin/", status_code=303)


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


# ---------------------------------------------------------------------------
# Manifest Management Routes
# ---------------------------------------------------------------------------

@router.get("/manifests", response_class=HTMLResponse)
async def manifest_list(request: Request):
    """List all active and archived manifests."""
    active, archived = _load_manifests_summary(include_archived=True)
    message = request.query_params.get("message", "")
    return templates.TemplateResponse("admin_manifest_list.html", {
        "request": request,
        "portal": "admin",
        "manifests": active,
        "archived": archived,
        "message": message,
    })


@router.get("/manifest/new", response_class=HTMLResponse)
async def manifest_new(request: Request):
    """Create a new manifest."""
    return templates.TemplateResponse("admin_manifest_editor.html", {
        "request": request,
        "portal": "admin",
        "manifest_data": None,
        "tasks_json": "[]",
        "compliance_json": "[]",
        "faq_json": "{}",
        "full_json": json.dumps({
            "manifest_id": "",
            "manifest_version": "1.0",
            "assessment_name": "",
            "assessment_type": "",
            "description": "",
            "conversation_starter": "Hi",
            "tasks": [],
            "compliance_checks": [],
            "faq_config": {},
            "scoring_config": {
                "cbm_structural_weight": 0.40,
                "webhook_functional_weight": 0.40,
                "compliance_weight": 0.10,
                "faq_weight": 0.10,
                "pass_threshold": 0.70,
            },
        }, indent=2),
        "error": None,
        "success": None,
    })


@router.get("/manifest/edit/{manifest_id}", response_class=HTMLResponse)
async def manifest_edit(request: Request, manifest_id: str):
    """Edit an existing manifest."""
    data = _load_manifest(manifest_id)
    if not data:
        return HTMLResponse("<h1>Manifest not found</h1>", status_code=404)

    # Convert to SimpleNamespace-like dict for template dot access
    class _D(dict):
        def __getattr__(self, key: str) -> Any:
            val = self.get(key)
            if isinstance(val, dict):
                return _D(val)
            return val

    manifest_data = _D(data)
    return templates.TemplateResponse("admin_manifest_editor.html", {
        "request": request,
        "portal": "admin",
        "manifest_data": manifest_data,
        "tasks_json": json.dumps(data.get("tasks", []), indent=2),
        "compliance_json": json.dumps(data.get("compliance_checks", []), indent=2),
        "faq_json": json.dumps(data.get("faq_config", {}), indent=2),
        "full_json": json.dumps(data, indent=2),
        "error": None,
        "success": None,
    })


@router.post("/manifest/save")
async def manifest_save_form(
    request: Request,
    manifest_id: str = Form(""),
    original_id: str = Form(""),
    assessment_name: str = Form(""),
    assessment_type: str = Form(""),
    manifest_version: str = Form("1.0"),
    description: str = Form(""),
    conversation_starter: str = Form("Hi"),
    created_by: str = Form(""),
    notes: str = Form(""),
    cbm_weight: str = Form("0.40"),
    webhook_weight: str = Form("0.40"),
    compliance_weight: str = Form("0.10"),
    faq_weight: str = Form("0.10"),
    pass_threshold: str = Form("0.70"),
    tasks_json: str = Form("[]"),
    compliance_json: str = Form("[]"),
    faq_json: str = Form("{}"),
):
    """Save manifest from form editor."""
    if not manifest_id or not assessment_name:
        return RedirectResponse(url="/admin/manifest/new?error=manifest_id+and+assessment_name+required", status_code=303)

    try:
        tasks = json.loads(tasks_json)
        compliance = json.loads(compliance_json)
        faq = json.loads(faq_json)
    except json.JSONDecodeError as e:
        return RedirectResponse(url=f"/admin/manifest/edit/{manifest_id}?error=Invalid+JSON:+{e}", status_code=303)

    data = {
        "manifest_id": manifest_id,
        "manifest_version": manifest_version,
        "assessment_name": assessment_name,
        "assessment_type": assessment_type,
        "description": description,
        "conversation_starter": conversation_starter,
        "created_by": created_by,
        "notes": notes,
        "scoring_config": {
            "cbm_structural_weight": float(cbm_weight),
            "webhook_functional_weight": float(webhook_weight),
            "compliance_weight": float(compliance_weight),
            "faq_weight": float(faq_weight),
            "pass_threshold": float(pass_threshold),
        },
        "tasks": tasks,
        "compliance_checks": compliance,
        "faq_config": faq,
    }

    # If ID changed, remove old file
    if original_id and original_id != manifest_id:
        old_path = MANIFESTS_DIR / f"{original_id}.json"
        if old_path.exists():
            old_path.unlink()

    _save_manifest(data)
    return RedirectResponse(url=f"/admin/manifests?message=Manifest+'{manifest_id}'+saved+successfully", status_code=303)


@router.post("/manifest/save-json")
async def manifest_save_json(
    request: Request,
    manifest_json: str = Form("{}"),
):
    """Save manifest from JSON editor."""
    try:
        data = json.loads(manifest_json)
    except json.JSONDecodeError as e:
        return RedirectResponse(url=f"/admin/manifest/new?error=Invalid+JSON:+{e}", status_code=303)

    manifest_id = data.get("manifest_id", "")
    if not manifest_id:
        return RedirectResponse(url="/admin/manifest/new?error=manifest_id+is+required", status_code=303)

    _save_manifest(data)
    return RedirectResponse(url=f"/admin/manifests?message=Manifest+'{manifest_id}'+saved+from+JSON", status_code=303)


@router.get("/manifest/archive/{manifest_id}")
async def manifest_archive(request: Request, manifest_id: str):
    """Archive a manifest (move to archived/ directory)."""
    src = MANIFESTS_DIR / f"{manifest_id}.json"
    if not src.exists():
        return HTMLResponse("<h1>Manifest not found</h1>", status_code=404)
    ARCHIVED_DIR.mkdir(parents=True, exist_ok=True)
    dst = ARCHIVED_DIR / f"{manifest_id}.json"
    shutil.move(str(src), str(dst))
    return RedirectResponse(url=f"/admin/manifests?message=Manifest+'{manifest_id}'+archived", status_code=303)


@router.get("/manifest/restore/{manifest_id}")
async def manifest_restore(request: Request, manifest_id: str):
    """Restore an archived manifest."""
    src = ARCHIVED_DIR / f"{manifest_id}.json"
    if not src.exists():
        return HTMLResponse("<h1>Archived manifest not found</h1>", status_code=404)
    dst = MANIFESTS_DIR / f"{manifest_id}.json"
    shutil.move(str(src), str(dst))
    return RedirectResponse(url=f"/admin/manifests?message=Manifest+'{manifest_id}'+restored", status_code=303)


@router.get("/manifest/schema", response_class=HTMLResponse)
async def manifest_schema_reference(request: Request):
    """Render the manifest JSON schema as a human-readable reference page."""
    schema_path = SCHEMA_DIR / "manifest_schema.json"
    schema_data: dict[str, Any] = {}
    if schema_path.exists():
        with schema_path.open("r") as f:
            schema_data = json.load(f)
    return templates.TemplateResponse("admin_manifest_schema.html", {
        "request": request,
        "portal": "admin",
        "schema": schema_data,
        "schema_json": json.dumps(schema_data, indent=2),
    })


# ---------------------------------------------------------------------------
# Evaluation Comparison Routes
# ---------------------------------------------------------------------------

@router.get("/compare", response_class=HTMLResponse)
async def compare_evaluations(request: Request):
    """Compare evaluations — detect duplicates and compare submissions."""
    evaluations = _load_all_evaluations()

    # Build comparison data: group by candidate + assessment
    comparisons: dict[str, list[dict[str, Any]]] = {}
    for ev in evaluations:
        key = f"{ev.get('candidate_id', 'unknown')}|{ev.get('manifest_id', '')}"
        comparisons.setdefault(key, []).append(ev)

    # Detect duplicates (same candidate, same assessment, multiple submissions)
    duplicates = {k: v for k, v in comparisons.items() if len(v) > 1}

    # Compute similarity scores between submissions
    similarity_groups: list[dict[str, Any]] = []
    for key, group in duplicates.items():
        candidate_id, manifest_id = key.split("|", 1)
        # Sort by score descending
        group.sort(key=lambda x: x.get("overall_score", 0), reverse=True)
        similarity_groups.append({
            "candidate_id": candidate_id,
            "manifest_id": manifest_id,
            "assessment_name": group[0].get("assessment_name", "Unknown"),
            "count": len(group),
            "submissions": group,
            "score_range": {
                "min": min(e.get("overall_score", 0) for e in group),
                "max": max(e.get("overall_score", 0) for e in group),
            },
        })

    # Selected pair for detailed comparison (from query params)
    left_id = request.query_params.get("left", "")
    right_id = request.query_params.get("right", "")
    left_sc: dict[str, Any] | None = None
    right_sc: dict[str, Any] | None = None
    if left_id and right_id:
        for ev in evaluations:
            if ev.get("session_id") == left_id:
                left_sc = ev
            if ev.get("session_id") == right_id:
                right_sc = ev

    return templates.TemplateResponse("admin_compare.html", {
        "request": request,
        "portal": "admin",
        "evaluations": evaluations,
        "similarity_groups": similarity_groups,
        "left": left_sc,
        "right": right_sc,
        "left_id": left_id,
        "right_id": right_id,
    })
