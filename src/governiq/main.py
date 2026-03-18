"""GovernIQ Universal Evaluation Platform — FastAPI Application Entry Point.

Serves two portals from a single server:
  /candidate/  — Candidate submission, history, and detailed report
  /admin/      — Evaluator dashboard, review, and manifest management
  /api/v1/     — REST API for programmatic access
  /            — Landing page with links to both portals
  /how-it-works — Explanation of the evaluation methodology
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .api.routes import router as api_router
from .candidate.routes import router as candidate_router
from .admin.routes import router as admin_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="GovernIQ Universal Evaluation Platform",
    description=(
        "Domain-agnostic assessment evaluation engine that automates "
        "evaluation of candidate bot submissions for certification. "
        "Two portals: Candidate (submit & view reports) and Admin (review & manage)."
    ),
    version="0.1.0",
)

# Static files
static_dir = Path(__file__).parent / "dashboard" / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Templates (shared across portals)
TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

# Register routers
app.include_router(api_router)
app.include_router(candidate_router)
app.include_router(admin_router)


# ---------------------------------------------------------------------------
# Landing page and shared routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def landing_page(request: Request):
    """Landing page with links to both portals."""
    return templates.TemplateResponse("landing.html", {
        "request": request,
        "portal": None,
    })


@app.get("/how-it-works", response_class=HTMLResponse)
async def how_it_works(request: Request):
    """Explanation of how the evaluation engine works."""
    return templates.TemplateResponse("how_it_works.html", {
        "request": request,
        "portal": None,
    })


@app.get("/health")
async def health():
    return {"status": "ok", "service": "governiq", "version": "0.1.0"}


def main():
    """CLI entry point."""
    import uvicorn
    uvicorn.run(
        "governiq.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
