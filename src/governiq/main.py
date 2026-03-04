"""GovernIQ Universal Evaluation Platform — FastAPI Application Entry Point."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api.routes import router as api_router
from .dashboard.routes import router as dashboard_router

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
        "The engine knows six execution patterns; manifests provide all domain knowledge."
    ),
    version="0.1.0",
)

# Static files for the dashboard
static_dir = Path(__file__).parent / "dashboard" / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# API routes
app.include_router(api_router)

# Dashboard routes
app.include_router(dashboard_router)


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
