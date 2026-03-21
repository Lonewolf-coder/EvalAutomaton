"""Admin / Evaluator Portal Routes - Dashboard, review, manifest management, LLM config."""

from __future__ import annotations

import json
import re
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
import logging
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..core.llm_config import (
    LLMConfig,
    get_provider_info,
    load_llm_config,
    save_llm_config,
    PROVIDER_DEFAULTS,
)
from ..core.health import check_ai_model

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

MANIFESTS_DIR = Path("manifests")
ARCHIVED_DIR = MANIFESTS_DIR / "archived"
SCHEMA_DIR = MANIFESTS_DIR / "schema"
DATA_DIR = Path("data")
DATA_MANIFESTS_DIR = DATA_DIR / "manifests"


def _is_lock_stale_admin(session_id: str, stale_minutes: int = 60) -> bool:
    """Admin-side stale lock check (mirrors candidate/routes.py version)."""
    lock_path = DATA_DIR / "locks" / f"{session_id}.lock"
    if not lock_path.exists():
        return True
    try:
        data = json.loads(lock_path.read_text())
        started_at = datetime.fromisoformat(data["started_at"])
        return (datetime.now(timezone.utc) - started_at) > timedelta(minutes=stale_minutes)
    except Exception:
        return True


def _enrich_submission(data: dict[str, Any]) -> dict[str, Any]:
    """Add computed display fields to a raw scorecard/stub dict."""
    from datetime import datetime, timezone, timedelta

    session_id = data.get("session_id", "")
    status = data.get("status", "error")

    # Stale detection -- running submissions older than 15 minutes
    display_status = status
    if status == "running":
        submitted_at_str = data.get("submitted_at")
        if not submitted_at_str:
            display_status = "stale"  # Legacy stub without submitted_at
        else:
            try:
                submitted_at = datetime.fromisoformat(submitted_at_str)
                age = datetime.now(timezone.utc) - submitted_at
                if age > timedelta(minutes=15):
                    display_status = "stale"
            except Exception:
                display_status = "stale"

    # Lock check
    lock_path = DATA_DIR / "locks" / f"{session_id}.lock"
    has_active_lock = lock_path.exists() and not _is_lock_stale_admin(session_id)

    # ZIP availability
    upload_dir = DATA_DIR / "uploads" / session_id
    try:
        zip_available = upload_dir.exists() and any(upload_dir.iterdir())
    except OSError:
        zip_available = False

    # Resume check -- RuntimeContext must exist, be valid JSON, and have session_id
    can_resume = False
    if status in ("halted", "error") and not has_active_lock:
        ctx_path = DATA_DIR / "runtime_contexts" / f"context_{session_id}.json"
        if ctx_path.exists():
            try:
                ctx_data = json.loads(ctx_path.read_text())
                can_resume = bool(ctx_data.get("session_id"))
            except Exception:
                pass

    return {
        **data,
        "overall_score": data.get("overall_score"),
        "candidate_id": data.get("candidate_id", "unknown"),
        "manifest_id": data.get("manifest_id", "unknown"),
        "assessment_name": data.get("assessment_name", "Unknown Assessment"),
        "submitted_at": data.get("submitted_at"),
        "halt_reason": data.get("halt_reason"),
        "display_status": display_status,
        "has_active_lock": has_active_lock,
        "zip_available": zip_available,
        "can_resume": can_resume,
        "can_start_fresh": status not in ("running",) and not has_active_lock,
    }


def _load_all_evaluations() -> list[dict[str, Any]]:
    results_dir = DATA_DIR / "results"
    if not results_dir.exists():
        return []
    evals = []
    for f in sorted(results_dir.glob("scorecard_*.json"), reverse=True):
        try:
            with f.open("r") as fh:
                data = json.load(fh)
            evals.append(_enrich_submission(data))
        except Exception as exc:
            logger.warning("Failed to load scorecard %s: %s", f.name, exc)
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


def validate_manifest_data(data: dict) -> dict:
    """Pre-flight validation of a raw manifest dict.

    Returns {"valid": bool, "errors": [...], "warnings": [...]}.
    Errors block save. Warnings are shown but do not block.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Required fields
    for field in ("manifest_id", "tasks", "scoring_config"):
        if field not in data:
            errors.append(f"Missing required field: '{field}'")

    # pass_threshold range
    sc = data.get("scoring_config", {})
    pt = sc.get("pass_threshold")
    if pt is not None and not (0.5 <= pt <= 1.0):
        errors.append(f"pass_threshold must be between 0.5 and 1.0 (got {pt})")

    # Weight sum
    if sc:
        w_sum = (
            sc.get("webhook_functional_weight", 0)
            + sc.get("compliance_weight", 0)
            + sc.get("faq_weight", 0)
        )
        if abs(w_sum - 1.0) > 0.01:
            warnings.append(
                f"scoring_config weights sum to {w_sum:.3f} instead of 1.0 -- will be normalised at evaluation time"
            )

    # value_pool type check
    for task in data.get("tasks", []):
        for entity in task.get("required_entities", []):
            vp = entity.get("value_pool")
            if isinstance(vp, dict) and "strategy" not in vp:
                warnings.append(
                    f"Task '{task.get('task_id')}' entity '{entity.get('entity_key')}': "
                    f"value_pool is a JSON object -- convert to array in manifest editor"
                )

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def _save_manifest(data: dict[str, Any]) -> Path:
    """Save manifest to both manifests/ and data/manifests/. Returns the manifests/ path."""
    result = validate_manifest_data(data)
    if not result["valid"]:
        raise ValueError(f"Manifest validation failed: {result['errors']}")
    MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
    manifest_id = data.get("manifest_id", "untitled")
    payload = json.dumps(data, indent=2)
    path = MANIFESTS_DIR / f"{manifest_id}.json"
    path.write_text(payload)
    (DATA_MANIFESTS_DIR / f"{manifest_id}.json").write_text(payload)
    return path


def _build_stats(evaluations: list[dict[str, Any]]) -> dict[str, int]:
    total = len(evaluations)
    passed = sum(
        1 for e in evaluations
        if e.get("overall_score") is not None
        and (pt := e.get("pass_threshold") or e.get("scoring_config", {}).get("pass_threshold"))
        and e.get("overall_score", 0) >= pt
        and not e.get("has_critical_failures")
    )
    critical = sum(1 for e in evaluations if e.get("has_critical_failures"))
    failed = total - passed
    return {"total": total, "passed": passed, "failed": failed, "critical": critical}


def _build_task_summary(scorecard: dict[str, Any]) -> dict[str, Any]:
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


@router.get("/settings", response_class=HTMLResponse)
async def admin_settings_page(request: Request):
    """Multi-provider AI settings page."""
    llm_config = load_llm_config()
    return templates.TemplateResponse("admin_settings.html", {
        "request": request,
        "portal": "admin",
        "llm_config": llm_config,
        "providers": get_provider_info(),
        "provider_defaults": PROVIDER_DEFAULTS,
    })


@router.post("/settings")
async def save_admin_settings(
    request: Request,
    provider: str = Form("anthropic"),
    api_key: str = Form(""),
    model: str = Form(""),
    base_url: str = Form(""),
    temperature: str = Form("0.3"),
    azure_deployment: str = Form(""),
):
    """Save AI provider settings, then probe the provider and embed result in redirect."""
    defaults = PROVIDER_DEFAULTS.get(provider, {})
    config = LLMConfig(
        provider=provider,
        api_key=api_key,
        model=model or defaults.get("default_model", ""),
        base_url=base_url or defaults.get("base_url", ""),
        api_format=defaults.get("api_format", "openai"),
        temperature=float(temperature),
        azure_deployment=azure_deployment,
    )
    save_llm_config(config)
    probe_result = check_ai_model(config=config)
    verified = "1" if probe_result.get("status") == "ok" else "0"
    reason = probe_result.get("message", "")
    return RedirectResponse(
        url=f"/admin/settings?saved=1&verified={verified}&reason={urllib.parse.quote(reason)}",
        status_code=303,
    )


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
        raw = json.load(f)

    # Merge safe defaults so the template never crashes on minimal stubs (error/running)
    scorecard: dict[str, Any] = {
        "overall_score": 0.0,
        "pass_threshold": None,
        "has_critical_failures": False,
        "any_webhook_tested": False,
        "state_seeded": False,
        "task_scores": [],
        "compliance_results": [],
        "faq_score": None,
        "plagiarism_flag": False,
        "plagiarism_message": "",
        "kore_api_insights": {},
        "analytics_by_task": {},
        "tooltips": [],
        "completed_tasks": [],
        "task_sessions": {},
        "eval_window": {},
        "analytics_status": "pending",
        "analytics_last_checked_at": None,
        "candidate_id": "Unknown",
        "manifest_id": "Unknown",
        "assessment_name": "Unknown Assessment",
        "submitted_at": None,
        "halt_reason": None,
        "halted_on_task": None,
        "error": None,
        "status": "unknown",
        **raw,
    }

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


_SAMPLE_MANIFEST: dict = {
    "manifest_id": "my_bot_assessment_v1",
    "manifest_version": "1.0",
    "assessment_name": "My Bot Assessment - Basic",
    "assessment_type": "custom",
    "description": "Evaluates a bot for Create, Retrieve, Modify, Delete, and FAQ capabilities.",
    "webhook_url": "",
    "mock_api_base_url": "",
    "conversation_starter": "Hi",
    "created_by": "",
    "notes": "",
    "scoring_config": {
        "cbm_structural_weight": 0.0,
        "webhook_functional_weight": 0.80,
        "compliance_weight": 0.10,
        "faq_weight": 0.10,
        "pass_threshold": 0.70,
    },
    "compliance_checks": [
        {
            "check_id": "compliance_dialoggpt",
            "label": "DialogGPT is enabled",
            "cbm_field": "dialogGPTSettings[0].dialogGPTLLMConfig.enable",
            "required_state": "enabled",
            "critical": True,
            "tooltip": "DialogGPT must be enabled for the Agent Node to function correctly.",
        }
    ],
    "faq_config": {
        "required_faqs": [
            {
                "primary_question": "What are your working hours?",
                "ground_truth_answer": "We are open Monday to Friday from 9 AM to 6 PM.",
                "required_keywords": ["Monday", "Friday", "9 AM", "6 PM"],
                "alternate_questions": [
                    "When are you open?",
                    "What time do you close?",
                ],
            }
        ],
        "min_alternate_questions": 2,
        "semantic_similarity_threshold": 0.80,
    },
    "tasks": [
        {
            "task_id": "task_create",
            "task_name": "Create Record - Happy Path",
            "pattern": "CREATE",
            "dialog_name": "Create Record",
            "dialog_name_policy": "contains",
            "required_entities": [
                {
                    "entity_key": "customerName",
                    "semantic_hint": "customer full name",
                    "value_pool": ["Alice Smith", "Bob Johnson"],
                    "validation_required": True,
                    "validation_description": "Must contain first and last name",
                },
                {
                    "entity_key": "phoneNumber",
                    "semantic_hint": "contact phone number",
                    "value_pool": ["9876543210", "8765432109"],
                    "validation_required": True,
                    "validation_description": "Must be 10-digit phone number",
                },
            ],
            "required_nodes": [
                {"node_type": "aiassist", "label": "Agent Node for entity handling", "required": True},
                {"node_type": "service", "label": "POST service node", "service_method": "POST", "required": True},
                {"node_type": "entity", "label": "Entity collection nodes", "required": True},
            ],
            "state_assertion": {
                "enabled": True,
                "verify_endpoint": "",
                "filter_field": "phoneNumber",
                "field_assertions": {"customerName": "customerName", "phoneNumber": "phoneNumber"},
            },
            "record_alias": "Record1",
            "weight": 1.0,
        },
        {
            "task_id": "task_create_amend",
            "task_name": "Create Record - Amendment Test",
            "pattern": "CREATE_WITH_AMENDMENT",
            "dialog_name": "Create Record",
            "dialog_name_policy": "contains",
            "required_entities": [
                {"entity_key": "customerName", "semantic_hint": "customer full name", "value_pool": ["Carol White", "Dave Brown"]},
                {"entity_key": "phoneNumber", "semantic_hint": "contact phone number", "value_pool": ["7654321098", "6543210987"]},
            ],
            "required_nodes": [
                {"node_type": "aiassist", "label": "Agent Node for amendment", "required": True},
            ],
            "amendment_config": {
                "target_entity": "phoneNumber",
                "amendment_utterance_template": "Actually, change the phone number to {amended_value}",
                "amended_value_pool": ["1111111111", "2222222222"],
            },
            "state_assertion": {
                "enabled": True,
                "verify_endpoint": "",
                "filter_field": "phoneNumber",
                "field_assertions": {"phoneNumber": "phoneNumber"},
            },
            "record_alias": "Record2",
            "co_reference_test": True,
            "weight": 1.0,
        },
        {
            "task_id": "task_retrieve",
            "task_name": "Retrieve Record",
            "pattern": "RETRIEVE",
            "dialog_name": "Get Record",
            "dialog_name_policy": "contains",
            "required_entities": [
                {"entity_key": "phoneNumber", "semantic_hint": "phone number for lookup", "value_pool": []}
            ],
            "required_nodes": [
                {"node_type": "service", "label": "GET service node", "service_method": "GET", "required": True},
            ],
            "cross_task_refs": {
                "lookup": {"source_task_id": "task_create", "source_record_alias": "Record1", "source_field": "phoneNumber"}
            },
            "state_assertion": {
                "enabled": True,
                "verify_endpoint": "",
                "filter_field": "phoneNumber",
                "field_assertions": {"phoneNumber": "phoneNumber"},
            },
            "weight": 1.0,
        },
        {
            "task_id": "task_edge_case",
            "task_name": "Retrieve - Invalid Input Edge Case",
            "pattern": "EDGE_CASE",
            "dialog_name": "Get Record",
            "dialog_name_policy": "contains",
            "required_entities": [],
            "required_nodes": [],
            "negative_tests": [
                {
                    "invalid_value_pool": ["0000000000", "invalid"],
                    "expected_error_pattern": "not found|no record|does not exist",
                    "requires_re_entry_prompt": True,
                }
            ],
            "weight": 0.5,
        },
        {
            "task_id": "task_modify",
            "task_name": "Modify Record",
            "pattern": "MODIFY",
            "dialog_name": "Modify Record",
            "dialog_name_policy": "contains",
            "required_entities": [
                {"entity_key": "phoneNumber", "semantic_hint": "phone number for lookup", "value_pool": []}
            ],
            "required_nodes": [
                {"node_type": "service", "label": "GET service node", "service_method": "GET", "required": True},
                {"node_type": "service", "label": "PUT service node", "service_method": "PUT", "required": True},
            ],
            "cross_task_refs": {
                "lookup": {"source_task_id": "task_create", "source_record_alias": "Record1", "source_field": "phoneNumber"}
            },
            "modifiable_fields": ["customerName"],
            "modified_value_pool": {"customerName": ["Updated Name One", "Updated Name Two"]},
            "state_assertion": {
                "enabled": True,
                "verify_endpoint": "",
                "filter_field": "phoneNumber",
                "field_assertions": {"phoneNumber": "phoneNumber"},
            },
            "weight": 1.0,
        },
        {
            "task_id": "task_delete",
            "task_name": "Delete Record",
            "pattern": "DELETE",
            "dialog_name": "Delete Record",
            "dialog_name_policy": "contains",
            "required_entities": [],
            "required_nodes": [
                {"node_type": "service", "label": "DELETE service node", "service_method": "DELETE", "required": True},
            ],
            "cross_task_refs": {
                "lookup": {"source_task_id": "task_create_amend", "source_record_alias": "Record2", "source_field": "phoneNumber"}
            },
            "state_assertion": {
                "enabled": True,
                "verify_endpoint": "",
                "filter_field": "phoneNumber",
                "field_assertions": {},
                "expect_deletion": True,
            },
            "weight": 1.0,
        },
    ],
    "state_seeding_config": {"enabled": True, "schema_validation": True, "seed_endpoint": ""},
    "tooltips": [
        {"node_type": "aiassist", "text": "Agent Node - enables LLM-powered entity handling and amendment support."},
        {"node_type": "service", "text": "Service Node - makes API calls (GET, POST, PUT, DELETE)."},
        {"node_type": "entity", "text": "Entity Node - collects a specific piece of information from the user."},
        {"node_type": "message", "text": "Message Node - displays a message to the user."},
        {"node_type": "form", "text": "Form Node - collects multiple fields in a structured form."},
        {"node_type": "script", "text": "Script Node - runs a JavaScript function for custom logic."},
    ],
    "assignment_brief": {
        "scenario_title": "My Bot Assessment",
        "scenario_description": "Build a Kore.ai XO Platform chatbot that handles Create, Retrieve, Modify, and Delete operations via a REST API.",
        "what_to_build": [
            "Welcome dialog with main menu",
            "Create Record dialog (entities + POST API + Agent Node)",
            "Retrieve Record dialog (GET API + entity lookup)",
            "Modify Record dialog (GET + PUT APIs)",
            "Delete Record dialog (DELETE API)",
            "At least 2 FAQs",
        ],
        "entities_to_collect": [
            {"name": "customerName", "description": "Customer full name (first + last)"},
            {"name": "phoneNumber", "description": "10-digit phone number"},
        ],
        "api_endpoints": [
            {"name": "Create Record", "method": "POST", "description": "Creates a new record"},
            {"name": "Get Record", "method": "GET", "description": "Retrieves record by phone number"},
            {"name": "Update Record", "method": "PUT", "description": "Updates an existing record"},
            {"name": "Delete Record", "method": "DELETE", "description": "Removes a record"},
        ],
        "validation_rules": [
            {"entity": "customerName", "rule": "must contain first and last name", "description": "First + Last name required"},
            {"entity": "phoneNumber", "rule": "must be 10 digits", "description": "Numeric only, exactly 10 digits"},
        ],
        "faq_topics": ["working hours", "refund policy"],
        "mock_api_setup_instructions": "Deploy the provided MockAPI collection. The evaluator will provide the base URL.",
        "submission_instructions": "Export your bot as a ZIP from Kore.ai XO Platform and submit along with your webhook URL and mock API base URL.",
    },
    "submission_config": {
        "max_attempts": 6,
        "require_evaluator_confirmation": True,
        "allow_evaluator_exception": True,
        "feedback_mode": "immediate",
    },
}


@router.get("/manifest/new", response_class=HTMLResponse)
async def manifest_new(request: Request):
    """Create a new manifest - pre-populated with a comprehensive sample."""
    error = request.query_params.get("error", "")
    sample = _SAMPLE_MANIFEST
    return templates.TemplateResponse("admin_manifest_editor.html", {
        "request": request,
        "portal": "admin",
        "manifest_data": None,
        "tasks_json": json.dumps(sample["tasks"], indent=2),
        "compliance_json": json.dumps(sample["compliance_checks"], indent=2),
        "faq_json": json.dumps(sample["faq_config"], indent=2),
        "assignment_brief_json": json.dumps(sample.get("assignment_brief", {}), indent=2),
        "submission_config_json": json.dumps(sample.get("submission_config", {}), indent=2),
        "tooltips_json": json.dumps(sample.get("tooltips", []), indent=2),
        "full_json": json.dumps(sample, indent=2),
        "error": error or None,
        "success": None,
    })


@router.get("/manifest/edit/{manifest_id}", response_class=HTMLResponse)
async def manifest_edit(request: Request, manifest_id: str):
    """Edit an existing manifest."""
    data = _load_manifest(manifest_id)
    if not data:
        return HTMLResponse(
            "<h1>Manifest not found</h1><p>The manifest may have been archived or deleted.</p>",
            status_code=404,
        )

    error = request.query_params.get("error", "")
    success = request.query_params.get("success", "")

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
        "assignment_brief_json": json.dumps(data.get("assignment_brief", {}), indent=2),
        "submission_config_json": json.dumps(data.get("submission_config", {}), indent=2),
        "tooltips_json": json.dumps(data.get("tooltips", []), indent=2),
        "full_json": json.dumps(data, indent=2),
        "error": error or None,
        "success": success or None,
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
    cbm_weight: str = Form("0.0"),
    webhook_weight: str = Form("0.80"),
    compliance_weight: str = Form("0.10"),
    faq_weight: str = Form("0.10"),
    pass_threshold: str = Form("0.70"),
    tasks_json: str = Form("[]"),
    compliance_json: str = Form("[]"),
    faq_json: str = Form("{}"),
    assignment_brief_json: str = Form("{}"),
    submission_config_json: str = Form("{}"),
    tooltips_json: str = Form("[]"),
    state_seeding_json: str = Form("{}"),
):
    """Save manifest from form editor."""
    if not manifest_id or not assessment_name:
        return RedirectResponse(url="/admin/manifest/new?error=manifest_id+and+assessment_name+required", status_code=303)

    try:
        tasks = json.loads(tasks_json)
        compliance = json.loads(compliance_json)
        faq = json.loads(faq_json)
        assignment_brief = json.loads(assignment_brief_json)
        submission_config = json.loads(submission_config_json)
        tooltips = json.loads(tooltips_json)
        state_seeding = json.loads(state_seeding_json) if state_seeding_json else {}
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
        "assignment_brief": assignment_brief,
        "submission_config": submission_config,
        "tooltips": tooltips,
    }
    if state_seeding:
        data["state_seeding_config"] = state_seeding

    # If ID changed, remove old file
    if original_id and original_id != manifest_id:
        old_path = MANIFESTS_DIR / f"{original_id}.json"
        if old_path.exists():
            old_path.unlink()
        old_data_path = DATA_MANIFESTS_DIR / f"{original_id}.json"
        if old_data_path.exists():
            old_data_path.unlink()

    try:
        _save_manifest(data)
    except ValueError as e:
        return RedirectResponse(
            url=f"/admin/manifest/edit/{manifest_id}?error={e}",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/admin/manifest/edit/{manifest_id}?success=Manifest+saved+successfully",
        status_code=303,
    )


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

    try:
        _save_manifest(data)
    except ValueError as e:
        return RedirectResponse(
            url=f"/admin/manifest/edit/{manifest_id}?error={e}",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/admin/manifest/edit/{manifest_id}?success=Manifest+saved+from+JSON+editor",
        status_code=303,
    )


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


@router.post("/manifest/validate", response_class=HTMLResponse)
async def manifest_validate(request: Request, manifest_json: str = Form("{}")):
    """Validate manifest JSON against MD-01-MD-12 rules. Returns an HTML fragment."""
    from ..core.manifest import Manifest
    from ..core.manifest_validator import Severity, validate_manifest

    try:
        data = json.loads(manifest_json)
        manifest = Manifest(**data)
        result = validate_manifest(manifest)
    except Exception as e:
        return HTMLResponse(
            f'<div class="alert alert-danger"><strong>Parse error:</strong> {e}</div>'
        )

    if result.valid:
        html = '<div class="alert alert-success"><strong>Valid manifest</strong> - no defects found.</div>'
    else:
        rows = ""
        for d in result.defects:
            color = "danger" if d.severity == Severity.ERROR else "warning"
            rows += (
                f'<div class="alert alert-{color}" style="margin-bottom:.4rem;">'
                f'<strong>[{d.rule_id}] {d.severity.value.upper()}</strong>: {d.message}'
                f"</div>"
            )
        html = f'<div>{rows}</div>'

    return HTMLResponse(html)


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


def _compute_task_diff(left_sc: dict | None, right_sc: dict | None) -> list[dict]:
    """Align tasks from two scorecards by task_id and compute score deltas."""
    if not left_sc or not right_sc:
        return []
    left_tasks = {t["task_id"]: t for t in left_sc.get("task_scores", [])}
    right_tasks = {t["task_id"]: t for t in right_sc.get("task_scores", [])}
    seen = set()
    ordered_ids = []
    for tid in list(left_tasks.keys()) + list(right_tasks.keys()):
        if tid not in seen:
            seen.add(tid)
            ordered_ids.append(tid)
    diff = []
    for tid in ordered_ids:
        lt = left_tasks.get(tid)
        rt = right_tasks.get(tid)
        left_score = lt["combined_score"] if lt else None
        right_score = rt["combined_score"] if rt else None
        if left_score is not None and right_score is not None:
            delta = left_score - right_score
        elif left_score is not None:
            delta = left_score
        else:
            delta = -(right_score or 0)
        diff.append({
            "task_id": tid,
            "task_name": (lt or rt or {}).get("task_name", tid),
            "left_score": left_score,
            "right_score": right_score,
            "delta": round(delta, 4),
            "significant": abs(delta) > 0.20,
        })
    return diff


@router.get("/compare", response_class=HTMLResponse)
async def compare_evaluations(request: Request):
    """Compare evaluations - detect duplicates and compare submissions."""
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
        group.sort(key=lambda x: (x.get("overall_score") or 0), reverse=True)
        similarity_groups.append({
            "candidate_id": candidate_id,
            "manifest_id": manifest_id,
            "assessment_name": group[0].get("assessment_name", "Unknown"),
            "count": len(group),
            "submissions": group,
            "score_range": {
                "min": min((e.get("overall_score") or 0) for e in group),
                "max": max((e.get("overall_score") or 0) for e in group),
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

    task_diff = _compute_task_diff(left_sc, right_sc)

    return templates.TemplateResponse("admin_compare.html", {
        "request": request,
        "portal": "admin",
        "evaluations": evaluations,
        "similarity_groups": similarity_groups,
        "left": left_sc,
        "right": right_sc,
        "left_id": left_id,
        "right_id": right_id,
        "task_diff": task_diff,
    })


# ---------------------------------------------------------------------------
# Restart Endpoint
# ---------------------------------------------------------------------------


@router.post("/evaluation/{session_id}/restart")
async def restart_evaluation(
    request: Request,
    session_id: str,
    background_tasks: BackgroundTasks,
    mode: str = Form(...),
):
    """Restart an evaluation.

    mode='fresh'  — create a new session from the original upload.
    mode='resume' — continue from the last saved RuntimeContext checkpoint.
    """
    # Validate session_id is a UUID to prevent path traversal
    if not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', session_id):
        return JSONResponse({"error": "Invalid session ID format"}, status_code=400)

    from ..candidate.routes import _run_evaluation_background

    results_dir = DATA_DIR / "results"
    stub_path = results_dir / f"scorecard_{session_id}.json"

    if not stub_path.exists():
        return JSONResponse({"error": "Submission not found"}, status_code=404)
    try:
        original_stub = json.loads(stub_path.read_text())
    except Exception:
        return JSONResponse({"error": "Cannot read submission data"}, status_code=500)

    # Guard: active lock
    if not _is_lock_stale_admin(session_id):
        return JSONResponse(
            {"error": "Evaluation is currently running. Please wait before re-running."},
            status_code=409,
        )

    if mode == "fresh":
        upload_dir = DATA_DIR / "uploads" / session_id
        try:
            zip_available = upload_dir.exists() and any(upload_dir.iterdir())
        except OSError:
            zip_available = False
        if not zip_available:
            return JSONResponse(
                {"error": "Original upload not found — re-upload required via candidate portal"},
                status_code=400,
            )

        new_session_id = str(uuid.uuid4())
        new_stub_path = results_dir / f"scorecard_{new_session_id}.json"
        new_stub = {
            **original_stub,
            "session_id": new_session_id,
            "status": "running",
            "completed_tasks": [],
            "halt_reason": None,
            "halted_on_task": None,
            "halted_at": None,
            "parent_session_id": session_id,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "log_file": f"data/logs/eval_{new_session_id}.jsonl",
            "error": None,
        }
        with new_stub_path.open("w") as f:
            json.dump(new_stub, f, indent=2)

        manifest_id = original_stub.get("manifest_id", "")
        manifest_obj = None
        for mf in MANIFESTS_DIR.glob("*.json"):
            try:
                mdata = json.loads(mf.read_text())
                if mdata.get("manifest_id") == manifest_id:
                    from ..core.manifest import Manifest
                    manifest_obj = Manifest(**mdata)
                    break
            except Exception:
                continue
        if manifest_obj is None:
            return JSONResponse(
                {"error": f"Manifest '{manifest_id}' not found — cannot re-run"},
                status_code=422,
            )

        from ..core.llm_config import load_llm_config as _load_llm_config
        llm_config = _load_llm_config()

        import io as _io_mod
        import zipfile as _zf_mod
        _upload_files = list(upload_dir.iterdir())
        _upload_file = _upload_files[0]
        _raw_bytes = _upload_file.read_bytes()
        if _upload_file.suffix == ".zip" or _raw_bytes[:4] == b"PK\x03\x04":
            try:
                with _zf_mod.ZipFile(_io_mod.BytesIO(_raw_bytes)) as zf:
                    _json_files = [
                        n for n in zf.namelist()
                        if n.endswith(".json") and not n.startswith("__MACOSX")
                    ]
                    if not _json_files:
                        return JSONResponse({"error": "No JSON file found in saved ZIP"}, status_code=422)
                    _json_files.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
                    with zf.open(_json_files[0]) as jf:
                        _bot_export_data = json.loads(jf.read())
            except Exception:
                _bot_export_data = json.loads(_raw_bytes)
        else:
            _bot_export_data = json.loads(_raw_bytes)

        background_tasks.add_task(
            _run_evaluation_background,
            session_id=new_session_id,
            manifest=manifest_obj,
            bot_export_data=_bot_export_data,
            candidate_id=original_stub.get("candidate_id", ""),
            webhook_url=original_stub.get("webhook_url", ""),
            kore_creds=None,
            llm_config=llm_config,
            kore_bearer_token="",
            plag_report=None,
        )
        return RedirectResponse(
            url=f"/admin/?restarted={new_session_id}", status_code=303
        )

    elif mode == "resume":
        ctx_path = DATA_DIR / "runtime_contexts" / f"context_{session_id}.json"
        if not ctx_path.exists():
            return JSONResponse(
                {"error": "Checkpoint not found — use Start Fresh instead"},
                status_code=400,
            )
        try:
            ctx_data = json.loads(ctx_path.read_text())
            if not ctx_data.get("session_id"):
                raise ValueError("Empty context")
        except Exception:
            return JSONResponse(
                {"error": "Checkpoint is corrupt — use Start Fresh instead"},
                status_code=400,
            )

        new_session_id = str(uuid.uuid4())
        new_stub_path = results_dir / f"scorecard_{new_session_id}.json"
        new_stub = {
            **original_stub,
            "session_id": new_session_id,
            "status": "running",
            "completed_tasks": original_stub.get("completed_tasks", []),
            "halt_reason": None,
            "halted_on_task": None,
            "halted_at": None,
            "parent_session_id": session_id,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "log_file": f"data/logs/eval_{new_session_id}.jsonl",
            "error": None,
        }
        with new_stub_path.open("w") as f:
            json.dump(new_stub, f, indent=2)

        manifest_id = original_stub.get("manifest_id", "")
        manifest_obj = None
        for mf in MANIFESTS_DIR.glob("*.json"):
            try:
                mdata = json.loads(mf.read_text())
                if mdata.get("manifest_id") == manifest_id:
                    from ..core.manifest import Manifest
                    manifest_obj = Manifest(**mdata)
                    break
            except Exception:
                continue
        if manifest_obj is None:
            return JSONResponse(
                {"error": f"Manifest '{manifest_id}' not found — cannot resume"},
                status_code=422,
            )

        from ..core.llm_config import load_llm_config as _load_llm_config
        llm_config = _load_llm_config()

        async def _do_resume():
            from ..core.engine import EvaluationEngine
            from ..core.eval_logger import EvalLogger
            _log_dir = DATA_DIR / "logs"
            _eval_logger = EvalLogger(session_id=new_session_id, log_dir=_log_dir)
            engine = EvaluationEngine(
                manifest=manifest_obj,
                llm_api_key=llm_config.api_key,
                llm_model=llm_config.model,
                llm_base_url=llm_config.base_url,
                llm_api_format=llm_config.api_format,
                eval_logger=_eval_logger,
            )
            try:
                scorecard = await engine.resume_evaluation(
                    source_session_id=session_id,
                    new_session_id=new_session_id,
                )
                with new_stub_path.open("w") as f:
                    json.dump(scorecard.to_dict(), f, indent=2)
            except Exception as exc:
                logger.exception("Resume failed for new session %s", new_session_id)
                existing = json.loads(new_stub_path.read_text()) if new_stub_path.exists() else {}
                existing.update({"status": "error", "error": str(exc)})
                with new_stub_path.open("w") as f:
                    json.dump(existing, f, indent=2)

        background_tasks.add_task(_do_resume)
        return RedirectResponse(
            url=f"/admin/?restarted={new_session_id}", status_code=303
        )

    return JSONResponse({"error": f"Unknown mode: {mode}"}, status_code=400)
