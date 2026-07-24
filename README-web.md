# gpjarmu-riport — Web GUI (Vercel-deployable)

A pure-additive FastAPI wrapper around the V1 `gpjarmu-riport` pipeline.
**No V1 source file is modified.**

```
gpjarmu-riport-v4/
├── api/
│   ├── __init__.py             # empty
│   └── index.py                # FastAPI app + Mangum handler
├── web/
│   ├── index.html              # single-page UI (vanilla HTML/JS)
│   ├── style.css               # dark-mode-friendly minimal styles
│   └── app.js                  # fetch() wrappers + DOM manipulation
├── vercel.json                 # routes + functions config
├── runtime.txt                 # python-3.11.15
├── requirements-vercel.txt     # V1 deps + fastapi + mangum + python-multipart
├── requirements-dev.txt        # local-only: uvicorn + httpx
├── .vercelignore               # exclude data/, output/, .venv/, .env, tests/
└── README-web.md               # this file
```

## Endpoints

| Method | Path                | Purpose                                                  |
|--------|---------------------|----------------------------------------------------------|
| GET    | `/`                 | Single-page UI                                           |
| GET    | `/style.css`        | Stylesheet                                               |
| GET    | `/app.js`           | Frontend JS                                              |
| GET    | `/api/health`       | Liveness + Vercel flag                                   |
| GET    | `/api/config`       | Redacted Settings                                        |
| GET    | `/api/state`        | run_meta + reported-items count                          |
| POST   | `/api/init-db`      | `?force=true|false` — initialise/reset the state DB       |
| POST   | `/api/run`          | Body `{seed, lookback_days, dry_run}` — runs the pipeline|
| GET    | `/api/report?file=` | Download a rendered `.txt` report                        |
| GET    | `/docs`             | Auto-generated Swagger UI                                |

## Local development

```bash
cd /home/ger/projects/gpjarmu-riport-v4
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -r requirements-vercel.txt     # or: fastapi mangum python-multipart

# Run the wrapper on http://127.0.0.1:5329/
uvicorn api.index:app --host 127.0.0.1 --port 5329
```

Open the browser at <http://127.0.0.1:5329/> and click **▶ Pipeline futtatása**.
The first run calls the LLM (Ollama Cloud or whatever `LLM_BASE_URL` points to)
and the report appears in the result panel. The `.txt` file is also saved
to `./output/` (or `/tmp/output/` when `VERCEL=1`).

## Vercel deployment

```bash
# 1. Set the secrets in the Vercel dashboard (Project → Settings → Environment Variables):
#    LLM_API_KEY             (your Ollama Cloud / OpenAI key)
#    LLM_BASE_URL            (e.g. https://ollama.com/v1)
#    LLM_MODEL               (e.g. minimax-m3:cloud)
#    SMTP_USERNAME / SMTP_PASSWORD / etc.  (only if SMTP_ENABLED=true)
#
# 2. Deploy:
npx vercel@latest deploy --prod --yes --token <vcp_...>
```

State lives in `/tmp/` on Vercel (ephemeral — wiped between cold starts).
That is the trade-off for **Stateless demo mode** (no Vercel KV / Postgres).

## Production hardening — adding auth

For a real deployment, gate `POST /api/run` behind a Bearer token:

```python
# In api/index.py, change the run endpoint to:
@app.post("/api/run")
def run_pipeline_endpoint(
    req: RunRequest,
    request: Request,
):
    expected = os.environ.get("RUNTIME_TOKEN")
    if expected:
        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {expected}":
            raise HTTPException(status_code=401, detail="Unauthorized")
    ...
```

Set `RUNTIME_TOKEN` in the Vercel dashboard, then have the JS frontend
include it in the `fetch()` call. Alternatively, enable Vercel's
[Password Protection](https://vercel.com/docs/security/vercel-password-protection)
on the project — simpler, no code change needed.

## Verifying the deployment

1. `curl https://<your-app>.vercel.app/api/health` — should return
   `{"status":"ok","vercel":true,"ver":"1.0.0"}`.
2. Open `https://<your-app>.vercel.app/` in a browser.
3. Tick "Dry run" + click **▶ Pipeline futtatása** — the response comes
   back with the report body in JSON and the panel renders it.

## Notes / pitfalls (learned during dev)

- Vercel's Python runtime does NOT add `src/` to `sys.path` — `api/index.py`
  prepends it before importing the V1 package.
- The deployment filesystem is read-only outside `/tmp/`. We override
  `STATE_DB_PATH`, `OUTPUT_DIR`, `LOG_FILE` to `/tmp/*` when `VERCEL=1`.
- `vercel.json` uses **either** `functions` **or** `builds`, not both. We use
  `functions` only.
- The V1 `StateDB` class has no `close()` method — do NOT add a
  `finally: db.close()` in your handler.
- The Vercel Python function cold start is 1-3s and the function timeout
  is set to 300s (`maxDuration` in `vercel.json`). A full seed run with
  LLM calls typically takes 1-3 min — within the limit.
