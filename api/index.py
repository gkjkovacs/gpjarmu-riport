"""
FastAPI wrapper around the V1 gpjarmu-riport pipeline.

This is a pure additive shim — it does NOT modify any V1 source. The V1
LangGraph pipeline (`gpjarmu_riport.graph.run_pipeline`) is invoked
synchronously inside a POST handler via `asyncio.run(...)` so the response
body carries the full result in a single round-trip.

When deployed to Vercel (env `VERCEL=1`), the state DB / output / log file
are redirected to `/tmp/*` because the deployment filesystem is read-only
outside `/tmp`. See pitfalls 1-10 in `/tmp/specs/web-gui-spec.md`.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Step 0: Vercel-specific path overrides. MUST happen BEFORE any gpjarmu_riport
# import, because the Settings object is memoized at import time.
# ---------------------------------------------------------------------------
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC = _PROJECT_ROOT / "src"

# Pitfall #1: Vercel does NOT add `src/` to sys.path. Prepend it explicitly.
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Pitfall #2: read-only fs. Override BEFORE any Settings() instantiation.
if os.environ.get("VERCEL") == "1":
    os.environ.setdefault("STATE_DB_PATH", "/tmp/state.db")
    os.environ.setdefault("OUTPUT_DIR", "/tmp/output")
    os.environ.setdefault("LOG_FILE", "/tmp/run.log")

# Also ensure the project root is on sys.path for `gpjarmu_riport` package
# discovery (some layouts need it alongside src/).
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Now safe to import V1 code.
# ---------------------------------------------------------------------------
import asyncio  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import traceback  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import Any  # noqa: E402

from fastapi import FastAPI, HTTPException, Query, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from gpjarmu_riport.config import Settings, get_settings, reload_settings  # noqa: E402
from gpjarmu_riport.state.db import StateDB  # noqa: E402
from gpjarmu_riport.utils.logging import setup_logging  # noqa: E402


WEB_DIR = _PROJECT_ROOT / "web"
APP_VERSION = "1.0.0"

logger = logging.getLogger("api")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Céges Gépjármű Magyar Közlöny Riport — Web API",
    version=APP_VERSION,
    description=(
        "Stateless demo mode wrapper around the V1 `gpjarmu-riport` pipeline. "
        "POST /api/run triggers the full pipeline synchronously; the response "
        "carries the rendered report body in JSON."
    ),
    docs_url="/docs",
    redoc_url=None,
)


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------
class RunRequest(BaseModel):
    """Body for POST /api/run."""
    seed: bool = False
    lookback_days: int | None = None
    dry_run: bool = False
    # --- SMTP-testing overrides (do NOT modify V1 source; use these to force
    # a non-empty pipeline result for email send verification) ---
    relevance_threshold: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="Override V1 .env relevance_threshold at runtime.",
    )
    disable_keyword_filter: bool = Field(
        default=False,
        description="Disable V1 keyword pre-filter (use only for SMTP tests).",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _redact_value(v: str) -> str:
    """Mask a secret: first 4 + '...' + last 4 (or REDACTED placeholder)."""
    if not v:
        return ""
    if len(v) <= 12:
        return "REDACTED"
    return f"{v[:4]}...{v[-4:]}"


def _settings_dict() -> dict[str, Any]:
    """Return a JSON-safe dict of the current Settings, with secrets redacted."""
    settings = get_settings()
    data = settings.model_dump(mode="json")
    for k in ("llm_api_key", "smtp_password"):
        if data.get(k):
            data[k] = _redact_value(str(data[k]))
    # Paths are already strings when mode="json"
    return data


# ---------------------------------------------------------------------------
# Static file routes (web/*)
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def serve_index() -> FileResponse:
    """Serve the single-page UI."""
    return FileResponse(WEB_DIR / "index.html", media_type="text/html")


@app.get("/style.css", include_in_schema=False)
def serve_css() -> FileResponse:
    return FileResponse(WEB_DIR / "style.css", media_type="text/css")


@app.get("/app.js", include_in_schema=False)
def serve_js() -> FileResponse:
    return FileResponse(WEB_DIR / "app.js", media_type="application/javascript")


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict[str, Any]:
    """Liveness probe + Vercel flag."""
    return {
        "status": "ok",
        "vercel": os.environ.get("VERCEL") == "1",
        "ver": APP_VERSION,
    }


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    """Return the current (redacted) configuration."""
    return _settings_dict()


@app.get("/api/state")
def get_state() -> dict[str, Any]:
    """
    Return run_meta + reported-items count from the current state DB.

    May be empty if /tmp was wiped (cold start) or the DB has never been
    initialised.
    """
    settings = get_settings()
    db_path = str(settings.state_db_path)
    out: dict[str, Any] = {"db_path": db_path, "exists": False, "meta": {}, "total_reported": 0}
    if Path(db_path).exists():
        out["exists"] = True
        try:
            db = StateDB(db_path)
            meta = db.get_run_meta()
            out["meta"] = meta
            out["total_reported"] = int(meta.get("total_reported", 0) or 0)
            out["last_run"] = meta.get("last_run")
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"
    return out


@app.post("/api/init-db")
def init_db(force: bool = Query(False, description="Reset all data first")) -> dict[str, Any]:
    """Initialise (or reset) the SQLite state DB."""
    settings = get_settings()
    settings.ensure_dirs()
    db = StateDB(settings.state_db_path)
    if force:
        db.reset()
    return {"ok": True, "path": str(settings.state_db_path), "force": force}


@app.post("/api/run")
def run_pipeline_endpoint(req: RunRequest) -> JSONResponse:
    """
    Trigger the V1 pipeline synchronously. Returns the full result + the
    rendered report body in the response (stateless demo mode).
    """
    started_at = datetime.now(timezone.utc)
    started_iso = started_at.isoformat()

    # Build a Settings override. We reload from env so lookback_days / dry_run
    # in the request body take effect, then mutate the live instance.
    settings = get_settings()

    # Apply per-request overrides (must be done BEFORE validate_for_run + run).
    if req.lookback_days is not None:
        settings.lookback_days = max(1, min(365, int(req.lookback_days)))
    if req.dry_run:
        settings.dry_run = True
    if req.relevance_threshold is not None:
        settings.relevance_threshold = float(req.relevance_threshold)
    if req.disable_keyword_filter:
        settings.keyword_filter_enabled = False

    # Configure logging (idempotent — uses force=True in setup_logging).
    setup_logging(settings)
    logger.info(
        "API run started: seed=%s lookback_days=%s dry_run=%s",
        req.seed, settings.lookback_days, settings.dry_run,
    )

    try:
        settings.validate_for_run()
    except ValueError as e:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": f"ConfigurationError: {e}",
                "traceback": "",
            },
        )

    settings.ensure_dirs()
    db = StateDB(settings.state_db_path)

    try:
        # Pitfall #8: bridge async -> sync via asyncio.run.
        from gpjarmu_riport.graph import run_pipeline
        result = asyncio.run(run_pipeline(settings, db, seed=req.seed))
    except Exception as e:
        tb = traceback.format_exc()
        logger.exception("Pipeline failed")
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "traceback": tb,
            },
        )
    # NB: pitfall #9 — do NOT call db.close(); StateDB has no close().

    finished_at = datetime.now(timezone.utc)
    duration_s = round((finished_at - started_at).total_seconds(), 2)

    # Build the response.
    report_path = result.get("report_path", "") or ""
    report_filename = Path(report_path).name if report_path else ""
    report_content = ""
    report_html_content = ""
    if report_path and Path(report_path).exists():
        try:
            report_content = Path(report_path).read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("Could not read report file %s: %s", report_path, e)
        # Try to also produce an HTML rendering for in-browser display.
        try:
            from gpjarmu_riport.email import render_html
            report_html_content = render_html(
                run_date=result.get("run_date", started_at.date().isoformat()),
                lookback_start=result.get("lookback_start", ""),
                lookback_end=result.get("lookback_end", ""),
                issues_scanned=result.get("issues_scanned", 0),
                new_items_count=result.get("new_items_count", 0),
                grouped_issues=result.get("grouped_issues", []),
                relevance_threshold=settings.relevance_threshold,
            )
        except Exception as e:
            logger.debug("HTML render failed (non-fatal): %s", e)

    new_items_count = int(result.get("new_items_count", 0) or 0)
    issues_scanned = int(result.get("issues_scanned", 0) or 0)
    warnings = list(result.get("warnings", []) or [])
    errors = list(result.get("errors", []) or [])
    email_sent = bool(result.get("email_sent", False))

    if email_sent:
        email_status = "sent"
    elif settings.smtp_enabled and errors:
        email_status = "FAILED (report file is still saved)"
    elif settings.smtp_enabled:
        email_status = "skipped (no new items)"
    else:
        email_status = "disabled (SMTP_ENABLED=false)"

    body: dict[str, Any] = {
        "ok": True,
        "started_at": started_iso,
        "finished_at": finished_at.isoformat(),
        "duration_s": duration_s,
        "new_items_count": new_items_count,
        "issues_scanned": issues_scanned,
        "report_filename": report_filename,
        "report_content": report_content,
        "report_html_content": report_html_content,
        "email_sent": email_sent,
        "email_status": email_status,
        "warnings": warnings,
        "errors": errors,
    }
    return JSONResponse(status_code=200, content=body)


@app.get("/api/report", response_class=PlainTextResponse)
def get_report(file: str = Query(..., description="Report filename, e.g. gpjarmu-2026-07-23.txt")):
    """
    Download a report. Reads from settings.output_dir (which is /tmp/output on
    Vercel, ./output locally). 404 if the file doesn't exist.
    """
    settings = get_settings()
    # Sanitise: refuse path traversal.
    if "/" in file or "\\" in file or ".." in file:
        raise HTTPException(status_code=400, detail="Invalid filename")
    candidate = settings.output_dir / file
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"Report not found: {file}")
    return PlainTextResponse(
        candidate.read_text(encoding="utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{file}"'},
    )


# ---------------------------------------------------------------------------
# Mangum handler for Vercel (pitfall #5).
# ---------------------------------------------------------------------------
try:
    from mangum import Mangum
    handler = Mangum(app, lifespan="off")
except ImportError:  # pragma: no cover — local dev without mangum
    handler = None  # type: ignore[assignment]


__all__ = ["app", "handler", "APP_VERSION"]
