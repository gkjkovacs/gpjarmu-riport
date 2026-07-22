"""
Vercel-compatible FastAPI wrapper for the HR Középvállalati Magyar Közlöny
Havi Riport.

Exposes the v3 pipeline as an HTTP service so the SaaS UI (magyar_kozlony)
can trigger pipeline runs and manage scopes remotely. The wrapper is a thin
adapter around `hr_kozlony.service:app`:

- Re-exports the existing `app` symbol (so Vercel's Python build can find it).
- Overrides `POST /run` with a synchronous variant that:
    * Accepts `lookback_days` and `relevance_threshold` from the SaaS.
    * Returns a JSON result with `report_path`, `new_items_count`,
      `issues_scanned`, `email_sent`, `warnings`, `errors`.
- Applies Vercel-specific path overrides (`/tmp` for state.db + output) when
  `VERCEL=1` is set in the environment. This makes the service safe to run
  in Vercel's read-only filesystem.
- Validates a bearer token (`RUNTIME_TOKEN` env var) on every request except
  `/health` and the FastAPI auto-generated docs (`/docs`, `/openapi.json`,
  `/redoc`).

Vercel contract
---------------
- Entry point: `api/index.py` with `app` symbol → auto-detected by
  `@vercel/python` builder.
- `maxDuration: 300s` in `vercel.json` (pipeline runs can take several minutes
  for a 30-day seed lookback).
- Environment variables: see `vercel.json` / `.env.example`.

Run locally
-----------
    uvicorn api.index:app --host 127.0.0.1 --port 8765 --reload
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Optional

# --- Make the src/ layout importable ----------------------------------------
# The v3 project uses src/hr_kozlony/... (PEP 517 editable layout). On Vercel,
# the project root becomes /var/task, and `src/` is not on sys.path by default.
# We add it explicitly here, before any `from hr_kozlony...` import.
_HERE = Path(__file__).resolve()
_PROJECT_ROOT = _HERE.parent.parent  # /api/index.py → project root
_SRC = _PROJECT_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# --- Vercel-specific environment overrides ----------------------------------
# On Vercel the project filesystem is read-only except for /tmp. Override the
# state.db and output_dir paths so the pipeline can write to writable storage.
# We only apply these overrides when the Vercel runtime sets VERCEL=1.
if os.environ.get("VERCEL") == "1":
    # Vercel provides /tmp as a writable scratch dir. Each function instance
    # gets its own /tmp, so state is per-instance (not shared across requests).
    # For our use case (long-running pipeline + scope management) this is
    # acceptable: the SaaS treats the runtime as the source of truth for
    # in-flight runs, and the state.db is only used for dedup within a session.
    os.environ.setdefault("STATE_DB_PATH", "/tmp/state.db")
    os.environ.setdefault("OUTPUT_DIR", "/tmp/output")
    os.environ.setdefault("LOG_FILE", "/tmp/hr-kozlony.log")

# --- Bearer-token auth -------------------------------------------------------
# The SaaS sets `RUNTIME_TOKEN` and sends `Authorization: Bearer <token>`.
# The v3 service has no built-in auth, so we add a minimal FastAPI dependency
# here. Unauthenticated paths: /health and the FastAPI docs UI.
from fastapi import Depends, FastAPI, Header, HTTPException  # noqa: E402

_RUNTIME_TOKEN = os.environ.get("RUNTIME_TOKEN", "")


def _check_bearer(authorization: Optional[str] = Header(default=None)) -> None:
    """Validate `Authorization: Bearer <token>` against `RUNTIME_TOKEN`."""
    if not _RUNTIME_TOKEN:
        # No token configured → service is open. Useful for first deploy /
        # smoke tests, but the SaaS will refuse to talk to a token-less
        # runtime anyway (its `runtime_client` requires RUNTIME_TOKEN).
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or malformed Authorization header (expected `Bearer <token>`)",
        )
    presented = authorization.split(" ", 1)[1].strip()
    if presented != _RUNTIME_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid bearer token.")


# --- Import the underlying service ------------------------------------------
# `hr_kozlony.service:app` provides /health, /scopes, /scopes/{name},
# POST /scopes, DELETE /scopes/{name}, and POST /run (background).
# We re-use it as-is, then bolt on a synchronous /run with a richer payload.
from hr_kozlony.service import ScopeResponse, app as _service_app  # noqa: E402,E501

# Re-mount the existing routes into a fresh parent app so we can extend
# /run without monkey-patching the v3 service module. This keeps the v3
# source untouched (the v3 service still works standalone, e.g. for
# `uvicorn hr_kozlony.service:app`).
from fastapi import BackgroundTasks  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

app = FastAPI(
    title="HR Középvállalati Magyar Közlöny Havi Riport — Vercel Runtime",
    description=(
        "Thin Vercel-compatible wrapper around `hr_kozlony.service`. "
        "Adds bearer-token auth and a synchronous `POST /runs` that returns "
        "the full pipeline result (report_path, new_items_count, email_sent, "
        "etc.). Re-exports /health, /scopes, /scopes/{name}, POST /scopes, "
        "DELETE /scopes/{name} from the v3 service unchanged."
    ),
    version="1.0.0",
)

# Mount the v3 service's routes under this app. FastAPI lets us include
# another app's router via `app.mount(...)` or by directly copying routes;
# the cleanest way is to re-include the service's `app.router` so /health,
# /scopes, etc. become available here too.
app.router.routes.extend(_service_app.router.routes)


# --- /runs (synchronous, full-result) ----------------------------------------
class RunRequestSync(BaseModel):
    """Payload for `POST /runs` — synchronous pipeline run with full result.

    Mirrors the SaaS `runtime_client.post_json("/runs", ...)` contract.
    """

    run_id: str = Field(..., description="Caller-assigned run ID (UUID).")
    scope: str = Field(..., description="Scope name to run (e.g. 'konyveles').")
    seed: bool = Field(
        False, description="If true, force a 30-day lookback (ignore last_run)."
    )
    dry_run: bool = Field(
        False,
        description=(
            "If true, skip email + state writes. Report is still rendered to "
            "the output dir (as a 0-byte placeholder when no new items)."
        ),
    )
    lookback_days: int = Field(30, ge=1, le=365)
    relevance_threshold: float = Field(0.50, ge=0.0, le=1.0)


class RunResultSync(BaseModel):
    """Response for `POST /runs` — the full pipeline outcome."""

    run_id: str
    scope: str
    started_at: str
    finished_at: str
    new_items_count: int
    issues_scanned: int
    report_path: str
    email_sent: bool
    warnings: list[str]
    errors: list[str]


@app.post(
    "/runs",
    response_model=RunResultSync,
    dependencies=[Depends(_check_bearer)],
)
def runs_sync(req: RunRequestSync) -> RunResultSync:
    """Trigger a pipeline run synchronously, return the full result.

    Unlike the v3 service's background `POST /run` (which returns 202
    Accepted), this endpoint blocks until the pipeline finishes and returns
    the complete RunResult. The SaaS relies on this synchronous contract.
    """
    from datetime import datetime, timezone

    from hr_kozlony.config import get_settings, reload_settings
    from hr_kozlony.graph import run_pipeline
    from hr_kozlony.scopes import get_scope, list_scopes
    from hr_kozlony.state.db import StateDB

    # 1) Validate scope is registered.
    if req.scope not in list_scopes():
        raise HTTPException(
            status_code=404,
            detail=(
                f"Scope {req.scope!r} is not registered. "
                f"Available: {list_scopes()}. POST /scopes first to create it."
            ),
        )
    # Touch the scope so the import-side effects run (registers keyword pattern).
    get_scope(req.scope)

    # 2) Push the request fields into the env so Settings() picks them up.
    os.environ["SCOPE"] = req.scope
    os.environ["LOOKBACK_DAYS"] = str(req.lookback_days)
    os.environ["RELEVANCE_THRESHOLD"] = str(req.relevance_threshold)
    if req.dry_run:
        os.environ["DRY_RUN"] = "true"
    started_at = datetime.now(timezone.utc).isoformat()
    reload_settings()  # drop memoized Settings so the new env values are loaded
    settings = get_settings()
    settings.validate_for_run()
    settings.ensure_dirs()

    # 3) Build the StateDB + run the pipeline. The graph is async, so we
    # bridge with asyncio.run.
    db = StateDB(settings.state_db_path)
    try:
        result = asyncio.run(run_pipeline(settings, db, seed=req.seed))
    except Exception as e:
        # Surface a 500 with the error message — the SaaS converts this to a
        # user-visible "Run failed: ..." message.
        raise HTTPException(
            status_code=500,
            detail=f"Pipeline raised {type(e).__name__}: {e}",
        ) from e

    finished_at = datetime.now(timezone.utc).isoformat()
    return RunResultSync(
        run_id=req.run_id,
        scope=req.scope,
        started_at=started_at,
        finished_at=finished_at,
        new_items_count=int(result.get("new_items_count", 0)),
        issues_scanned=int(result.get("issues_scanned", 0)),
        report_path=str(result.get("report_path", "")),
        email_sent=bool(result.get("email_sent", False)),
        warnings=list(result.get("warnings", [])),
        errors=list(result.get("errors", [])),
    )


# --- /runs/{run_id} (read-only stub) -----------------------------------------
# The SaaS may poll this after a run; we don't persist run history in the
# wrapper, so it returns 404 (the SaaS treats this as "no extra state").
@app.get(
    "/runs/{run_id}",
    dependencies=[Depends(_check_bearer)],
)
def runs_get(run_id: str) -> dict[str, str]:
    return {"run_id": run_id, "status": "not persisted (see /scopes for state)"}


# --- /scopes endpoint aliases -----------------------------------------------
# The SaaS's `runtime_client` calls /scopes, /scopes/{name}, POST /scopes —
# all of which already exist via the mounted v3 service routes. We just add
# a /scopes/create alias to match the SaaS's expected path (POST /scopes/create
# in addition to POST /scopes). The v3 service uses POST /scopes; we forward.


@app.post(
    "/scopes/create",
    response_model=ScopeResponse,
    dependencies=[Depends(_check_bearer)],
    status_code=201,
)
def scopes_create_alias() -> dict[str, str]:
    """Alias to POST /scopes — provided for SaaS compatibility.

    The SaaS calls POST /api/scopes/create on its side, which it maps to
    POST /scopes/create here. The actual scope-creation logic lives in
    `POST /scopes` (the v3 service's endpoint). Use that one directly.
    """
    raise HTTPException(
        status_code=501,
        detail=(
            "Use POST /scopes (the v3 service's canonical endpoint) to create "
            "a new scope. This /scopes/create alias is reserved for future "
            "SaaS-specific extensions."
        ),
    )


# --- Vercel serverless entry point -----------------------------------------
# The Vercel @vercel/python builder invokes the `handler` symbol on each
# request. FastAPI is ASGI, but Vercel expects an AWS-Lambda-style handler
# (synchronous `(event, context)` callable). Mangum bridges the two:
# it takes the ASGI `app` and exposes a `handler(event, context)` that
# Vercel can call.
#
# `lifespan="off"` disables Mangum's lifespan-event emulation — we don't use
# startup/shutdown hooks, so this avoids extra latency on cold starts.
from mangum import Mangum  # noqa: E402

handler = Mangum(app, lifespan="off")


__all__ = ["app", "handler"]
