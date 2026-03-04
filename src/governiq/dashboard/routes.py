"""Dashboard Routes — Serves the admin evaluation dashboard.

Designed for non-technical evaluators. Every finding expressed in plain English.
No raw JSON. No gate IDs. The CBM Evaluator Reference Panel is always visible
alongside webhook results for every task.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["dashboard"])

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


@router.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    """Dashboard home — list all evaluations."""
    results_dir = Path("./data/results")
    evaluations = []
    if results_dir.exists():
        for f in sorted(results_dir.glob("scorecard_*.json"), reverse=True)[:50]:
            with f.open("r") as fh:
                data = json.load(fh)
                evaluations.append(data)

    return templates.TemplateResponse("home.html", {
        "request": request,
        "evaluations": evaluations,
    })


@router.get("/evaluation/{session_id}", response_class=HTMLResponse)
async def evaluation_detail(request: Request, session_id: str):
    """Evaluation detail page — full scorecard with CBM Map and evidence."""
    results_dir = Path("./data/results")
    path = results_dir / f"scorecard_{session_id}.json"
    if not path.exists():
        return HTMLResponse("<h1>Evaluation not found</h1>", status_code=404)

    with path.open("r") as f:
        scorecard = json.load(f)

    return templates.TemplateResponse("scorecard.html", {
        "request": request,
        "scorecard": scorecard,
    })
