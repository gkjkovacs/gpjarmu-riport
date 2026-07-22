# Céges Gépjármű Magyar Közlöny Havi Riport

> Havi automatikus monitor, amely a **Magyar Közlöny** friss számait átfésüli, és kiszűri a **céges gépjárműveket** érintő jogszabályváltozásokat — egyetlen `.txt` riportfájlba rendezve.

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/orchestration-LangGraph-orange)](https://langchain-ai.github.io/langgraph/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## Mi ez?

A `magyarkozlony.hu` oldalról gyűjti az elmúlt **30 nap** Magyar Közlöny számait, minden számból kiemeli a bekezdés-szintű egységeket, majd egy LLM-mel **szemantikusan** eldönti, hogy melyek érintik a céges gépjárművek adózását, üzemeltetését, biztosítását, flottakezelését stb. Az újdonságokról egyetlen `.txt` riport készül, amit megnyithatsz bármely szövegszerkesztőben (Notepad, VS Code, Notepad++). A Windows Task Scheduler csatolhatja e-mailhez, de a pipeline maga nem küld levelet.

**Főbb jellemzők:**

- **LangGraph pipeline** — 6 node-os állapotgép, checkpoint-elhető, újrafuttatható.
- **Duplikáció-védelem** — SQLite-alapú state DB, `(issue_number, anchor)` kompozit kulccsal. Soha nem kapsz ugyanarról a bekezdésről kétszer riportot.
- **30 napos rolling ablak** — az első futás egy 30 napos seed, utána mindig az előző futás óta újat dolgozza fel.
- **Szemantikus relevancia** — az LLM 0,00–1,00 score-t ad minden bekezdésre, és a téma-taxonomia alapján 15 altémakörbe sorolja. A küszöb (alapból 0,50) egyszerűen átállítható.
- **Magyar nyelvű kimenet** — subject, törzs, action item-ek mind magyarul.
- **Nincs e-mail küldés** — egyszerű UTF-8 `.txt` fájlba ír; a Windows Task Scheduler küldi tovább e-mailben, ha kell.
- **Platform-független** — Windows / macOS / Linux. A Windows Task Scheduler-be (vagy a Linux cron-ba) egyetlen parancsot kell ütemezni.

---

## Gyors telepítés (Windows)

### 1. Python 3.11+ telepítése

Töltsd le a [python.org/downloads](https://www.python.org/downloads/) oldalról. A telepítőben pip-pel együtt tedd fel. **Fontos:** a telepítés első képernyőjén pipáld be a **„Add Python to PATH"** opciót.

### 2. Projekt letöltése

```powershell
git clone https://github.com/<your-username>/gpjarmu-riport.git
cd gpjarmu-riport
```

### 3. Virtuális környezet

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Ha a PowerShell szkript-tilalmat dob:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### 4. Függőségek

```powershell
pip install -r requirements.txt
```

### 5. `.env` beállítása

```powershell
copy .env.example .env
notepad .env
```

A `.env`-ben két dolgot kell kitöltened:

- **`LLM_API_KEY`** — az Ollama Cloud API key (https://ollama.com/settings → API keys). Vagy ha más LLM-et használsz (OpenAI, Anthropic, lokális Ollama), a `LLM_BASE_URL` + `LLM_API_KEY` + `LLM_MODEL` sorokat.
- **`EMAIL_FROM`** / **`EMAIL_TO`** — feladó / címzett cím. Csak akkor kell, ha SMTP-t is bekapcsolsz.

### 6. Első futtatás (seed)

```powershell
python run.py seed
```

Ez feldolgozza az elmúlt 30 napot, és a kimenet az `output/gpjarmu-<dátum>.txt` fájlba kerül.

### 7. Megnézés

```powershell
# Megnyitás az alapértelmezett levelezőkliensben
start output\gpjarmu-2026-07-02.txt

# Vagy PowerShell-ben szövegesen
Get-Content output\gpjarmu-2026-07-02.txt
```

### 8. E-mail küldés (freemail.hu)

Ha szeretnéd, hogy a pipeline a `.txt` riportot **automatikusan e-mailben is elküldje**, a freemail.hu SMTP-jét használhatod. A beállítás a `.env` fájlban:

```bash
# .env — a freemail-es szekció
SMTP_ENABLED=true
SMTP_HOST=smtp.freemail.hu
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=gergely.kovacs@freemail.hu
SMTP_PASSWORD=a_freemail_jelszavad
SMTP_ATTACHMENT=true

EMAIL_FROM=gergely.kovacs@freemail.hu
EMAIL_TO=akos@ceged.hu
```

**A freemail.hu SMTP beállításai** (a freemail hivatalos súgójából, https://accounts.freemail.hu/a/help/faq/clients):

| Mező | Érték |
|---|---|
| SMTP host | `smtp.freemail.hu` |
| Port | `587` (STARTTLS, ajánlott) vagy `465` (SSL) |
| Felhasználónév | A teljes e-mail cím (nem csak a helyi rész!) |
| Jelszó | A webes felületen (https://accounts.freemail.hu) használt jelszó |
| Titkosítás | STARTTLS (port 587) vagy SSL (port 465) |

**Fontos árnyalatok:**

1. **A `SMTP_USERNAME` mezőbe a teljes e-mail cím kell** (pl. `gergely.kovacs@freemail.hu`), nem csak `gergely.kovacs`. A freemail ezt várja.
2. **Az `EMAIL_FROM` értéke a freemail-es címed legyen** — egyes SMTP szerverek (köztük a freemail) visszautasítják a levelet, ha a `From:` fejléc nem egyezik a hitelesített felhasználóval.
3. **Ha a jelszó speciális karaktereket tartalmaz** (pl. `!`, `#`, `&`), idézőjelbe kell tenni a `.env`-ben: `SMTP_PASSWORD="Titok!123"`.
4. **A 2-faktoros auth (2FA) nem érintett** — a freemail.hu jelenlegi szabályzata szerint a normál jelszóval is működik a SMTP, nem kell app-password (szemben a Gmaillel).

**E-mail formátum:**

- Ha `SMTP_ATTACHMENT=true` (alapértelmezett): rövid cover üzenet + `gpjarmu-<dátum>.txt` mellékletként.
- Ha `SMTP_ATTACHMENT=false`: a teljes riport szövege a levelező törzsében, nincs melléklet.

**Hibakezelés:** ha a küldés nem sikerül (rossz jelszó, hálózati hiba), a `.txt` fájl akkor is mentődik — a futás nem abortál, csak a `Run complete` panelen látod, hogy `Email: FAILED (report file is still saved)`.

### 9. Havi ütemezés (Windows Task Scheduler)

```powershell
# Feladat regisztrálása: minden hónap 1. napján 08:00-kor
$action = New-ScheduledTaskAction `
  -Execute "C:\path\to\gpjarmu-riport\.venv\Scripts\python.exe" `
  -Argument "C:\path\to\gpjarmu-riport\run.py run" `
  -WorkingDirectory "C:\path\to\gpjarmu-riport"

$trigger = New-ScheduledTaskTrigger -Monthly -DaysOfMonth 1 -At 08:00

Register-ScheduledTask `
  -TaskName "Céges Gépjármű Havi Riport" `
  -Action $action `
  -Trigger $trigger `
  -RunLevel Highest `
  -Description "Havonta futtatja a Magyar Közlöny céges-gépjármű monitort."
```

*(A fenti PowerShell parancsot a `gpjarmu-riport` mappában futtatva, az útvonalak automatikusan kitöltődnek.)*

---

## Projekt struktúra

```
gpjarmu-riport/
├── .env.example                # Konfigurációs sablon (SOHA ne commitolj .env-t!)
├── requirements.txt            # Pin-elt Python függőségek
├── pyproject.toml              # Csomag metaadatok
├── run.py                      # CLI entrypoint: `python run.py run|seed|init-db|show-config`
├── README.md
├── data/                       # SQLite state.db (git-ignored)
├── output/                     # Generált .txt riportok (git-ignored)
├── src/
│   └── gpjarmu_riport/
│       ├── __init__.py
│       ├── config.py           # Pydantic Settings: .env betöltés + validáció
│       ├── llm_factory.py      # ChatModel factory (OpenAI / Anthropic / Ollama)
│       ├── cli.py              # Typer CLI: run, seed, init-db, show-config
│       ├── graph/
│       │   ├── state.py        # StateGraph state schema
│       │   ├── graph.py        # StateGraph összeállítás
│       │   └── nodes/
│       │       ├── discover.py
│       │       ├── fetch.py
│       │       ├── classify.py
│       │       ├── dedupe.py
│       │       ├── expand.py
│       │       └── render.py
│       ├── scraper/
│       │   └── magyarkozlony.py
│       ├── state/
│       │   └── db.py
│       ├── email/
│       │   ├── eml_builder.py
│       │   └── smtp.py
│       ├── prompts/
│       │   ├── relevance-classifier.system.md
│       │   ├── report-writer.system.md
│       │   └── topic-taxonomy.md
│       ├── templates/
│       │   └── eml-template.html.j2
│       └── utils/
│           ├── logging.py
│           └── html_parser.py
└── tests/
    ├── test_state.py
    ├── test_eml_builder.py
    ├── test_scraper.py
    └── fixtures/
```

---

## Hogyan működik (a pipeline)

```
START ──► discover_issues ──► fetch_content ──► classify (LLM) ──►
            │                    │                │
            │                    │                └─► score < 0.50 → KIHAGYÁS
            │                    │
            └────────────────────┴──► dedupe ──► expand (LLM) ──► render_email ──► END
                                       │
                                       └─► (issue, anchor) már riportolva → KIHAGYÁS
```

Minden node:

1. **`discover_issues`** — listázza a Magyar Közlöny számait a lookback ablakban. Kiszűri a `Hivatalos Értesítő`-t.
2. **`fetch_content`** — minden számhoz letölti a `megtekintes` HTML-t, bekezdésekre bontja, opcionálisan az `indokolás`-szöveget is csatolja. PDF fallback ha a HTML nem elérhető.
3. **`classify`** — az LLM minden bekezdésre pontoz (0,00–1,00) és 15 altémakör egyikébe sorolja. Csak a `>= RELEVANCE_THRESHOLD` (alapból 0,50) score-júak maradnak.
4. **`dedupe`** — a state DB-ben ellenőrzi, hogy az `(issue_number, anchor)` már riportolva volt-e.
5. **`expand`** — a fennmaradt bekezdésekből az LLM 2-4 mondatos bővítést, kulcs-dátumokat és action item-eket generál.
6. **`render_email`** — strukturált adatokból plain text riportot épít, és kiírja `gpjarmu-<dátum>.txt` néven.

---

## Konfiguráció (`.env`)

Minden konfigurációs érték a `.env` fájlban van, Pydantic-kal validálva. A teljes lista: [`.env.example`](.env.example).

**Legfontosabbak:**

| Változó | Alapértelmezett | Leírás |
|---|---|---|
| `LLM_BASE_URL` | `https://ollama.com/v1` | OpenAI-kompatibilis endpoint |
| `LLM_API_KEY` | _(kötelező)_ | API kulcs |
| `LLM_MODEL` | `minimax-m3:cloud` | Modell neve |
| `LOOKBACK_DAYS` | `30` | Hány napra visszamenőleg dolgozzon |
| `RELEVANCE_THRESHOLD` | `0.50` | Relevancia küszöb (0–1) |
| `STATE_DB_PATH` | `./data/state.db` | SQLite state DB helye |
| `OUTPUT_DIR` | `./output` | .txt riportok célmappája |
| `SMTP_ENABLED` | `false` | `true` esetén a riport a `.txt` fájlba mentés után e-mailben is elküldésre kerül |
| `SMTP_HOST` | `smtp.freemail.hu` | SMTP szerver (freemail/Gmail/Outlook/custom) |
| `SMTP_PORT` | `587` | `587` (STARTTLS) vagy `465` (SSL) |
| `SMTP_SECURITY` | `starttls` | `starttls` / `ssl` / `none` |
| `SMTP_USERNAME` | _(kötelező SMTP-nél)_ | Freemail esetén a **teljes e-mail cím** (pl. `gergely.kovacs@freemail.hu`) |
| `SMTP_PASSWORD` | _(kötelező SMTP-nél)_ | A freemail webes jelszó (https://accounts.freemail.hu) |
| `SMTP_ATTACHMENT` | `true` | `true`: `.txt` melléklet + rövid cover; `false`: teljes riport a törzsben |
| `EMAIL_FROM` | `gpjarmu-riport@localhost` | Feladó (a freemail-es felhasználónak meg kell egyeznie a `SMTP_USERNAME` címmel) |
| `EMAIL_TO` | `you@example.com` | Címzett |

---

## Fejlesztés

### Tesztek futtatása

```powershell
pytest
```

### Új LLM provider hozzáadása

A `src/gpjarmu_riport/llm_factory.py` egy factory patternt használ. Új provider:

1. `pip install langchain-<provider>`
2. Adj hozzá egy új ágat az `LLM_PROVIDER` enum-hoz
3. Implementáld a factory függvényt

### A state DB újrainicializálása

```powershell
python run.py init-db --force
```

**Figyelem:** ez törli az összes korábbi riportot, és a következő futás az **összes** 30 napos ablakból fog mindent riportolni (mint az első seed).

---

## Licenc

MIT. Lásd [LICENSE](LICENSE).

## Mintaripport

Egy tipikus .eml kimenet a `gpjarmu-2026-07-02.eml` formátumban (subject: `[Céges Gépjármű riport] 2026-07-02 – 1 új változás`):

```
From: gpjarmu-riport@localhost
To: you@example.com
Subject: =?utf-8?b?W0PDqWdlcyBHw6lwasOhcm3FsSByaXBvcnRdIDIwMjYtMDctMDIg4oCTIDEgw7pqIHbDoWx0b3rDoXM=?=
Content-Type: multipart/alternative; boundary="…"

--…
Content-Type: text/plain; charset="utf-8"
Content-Transfer-Encoding: 7bit

Céges Gépjármű — Magyar Közlöny Havi Riport
Futtatás dátuma: 2026-07-02  ·  Lookback: 2026-06-02 → 2026-07-02  ·  …

Magyar Közlöny 2026. évi 83. szám (2026-07-01)
  § 12. § (3)  A cégautóadó mértéke 2026. január 1-jétől emelkedik.
    Relevancia: 0.82 · cégautóadó
    A bekezdés a cégautóadóról szóló törvény 3. §-át módosítja: a havi fix adó 18 000 Ft-ról 19 500 Ft-ra emelkedik. …
    Határidők: 2026. január 1.
    • Frissíteni a havi költségvetési tervet az új adómértékkel.
    📄 Indokolás megnyitása

--…
Content-Type: text/html; charset="utf-8"
Content-Transfer-Encoding: 7bit

<!doctype html>
<html lang="hu">
… (színes, topic-badget tartalmazó HTML — megnyitható böngészőben)
```

A teljes HTML body inline CSS-t használ (mail-kliens kompatibilis), és tartalmazza a téma-badge-eket, anchorokat, határidőket, action item-eket és az indokolás linket.

---

## Vercel deployment (SaaS runtime)

A v3 projekt deployolható Vercel-re mint FastAPI runtime, amelyet a [`magyar_kozlony`](https://github.com/gkjkovacs/Magyar-kozlony) SaaS HTTP-n hív. A Vercel-detected entry point: `api/index.py` (FastAPI `app` symbol).

### Endpointok (SaaS contract)

| Method | Path | Auth | Leírás |
|---|---|---|---|
| `GET`  | `/health`              | – | Liveness + regisztrált scope-ok száma |
| `GET`  | `/scopes`              | – | Regisztrált scope nevek listája |
| `GET`  | `/scopes/{name}`       | – | Egy scope részletes metaadata |
| `POST` | `/scopes`              | bearer | Új scope modul írása + live-regisztráció (v3 service) |
| `POST` | `/scopes/create`       | bearer | Alias (501) — használd a `/scopes` POST-ot |
| `DELETE` | `/scopes/{name}`    | bearer | Scope unregister (fájl marad) |
| `POST` | `/run`                 | bearer | Async dispatch (202 Accepted) — v3 service |
| `POST` | `/runs`                | bearer | **Szinkron futtatás**, visszaadja a teljes `RunResult`-ot |
| `GET`  | `/runs/{run_id}`       | bearer | Stub (nincs perzisztens run state) |

### Auth

A wrapper minden védett endpointra `Authorization: Bearer <RUNTIME_TOKEN>` fejlécet vár. A token a Vercel UI env var-okban (`RUNTIME_TOKEN`) és a SaaS-ban (`RUNTIME_TOKEN`) is azonos érték kell legyen.

### Vercel env var-ok (Production)

| Key | Required | Default | Leírás |
|---|---|---|---|
| `RUNTIME_TOKEN`       | ✓ | – | Bearer token (a SaaS küldi) |
| `OLLAMA_API_KEY`      | ✓ | – | LLM provider API kulcs |
| `OLLAMA_MODEL`        | – | `minimax-m3:cloud` | Modell név |
| `OLLAMA_BASE_URL`     | – | `https://ollama.com/v1` | OpenAI-kompatibilis endpoint |
| `SCOPE`               | – | `konyveles` | Alap scope |
| `LOOKBACK_DAYS`       | – | `30` | Alap lookback |
| `RELEVANCE_THRESHOLD` | – | `0.50` | Alap küszöb |
| `SMTP_ENABLED`        | – | `false` | Ha `true`, a pipeline emailt küld |

### Lokális fejlesztés

```bash
.venv/bin/uvicorn api.index:app --host 127.0.0.1 --port 5329 --reload
# Health check:
curl http://127.0.0.1:5329/health
# {"status":"ok","scopes_count":3}
```

A Vercel-en `VERCEL=1` automatikusan be van állítva — a wrapper ilyenkor `/tmp` alá írja a `state.db`-t és az `output_dir`-t (a Vercel projekt fs read-only).

### Vercel UI deploy lépések

1. Push-old a v3-at egy GitHub repoba:
   ```bash
   git init -b main
   git add api/ vercel.json .vercelignore runtime.txt requirements.vercel.txt
   git commit -m "v3: Vercel FastAPI runtime wrapper"
   git remote add origin https://github.com/<user>/gpjarmu-riport-v3.git
   git push -u origin main
   ```
2. Vercel UI → **Add New Project** → válaszd a `gpjarmu-riport-v3` repót
3. **Root Directory**: `.` (a v3 gyökere, nem almappa)
4. **Framework Preset**: Other
5. **Build Command**: üres (a `@vercel/python` auto-detect-eli)
6. A **Settings → Environment Variables**-ban add hozzá a fenti env var-okat
7. **Deploy** — 1-2 perc a függőségek telepítésére
8. A kapott URL (`https://gpjarmu-riport-v3-xxx.vercel.app`) menjen a SaaS-ba mint `RUNTIME_URL`

### SaaS-oldali összekötés

A [`magyar_kozlony`](https://github.com/gkjkovacs/Magyar-kozlony) Vercel project Settings → Environment Variables:

| Key | Value |
|---|---|
| `RUNTIME_URL`   | `https://gpjarmu-riport-v3-xxx.vercel.app` |
| `RUNTIME_TOKEN` | (ugyanaz, mint a v3 `RUNTIME_TOKEN`) |

A SaaS auto-redeployolódik, és a `/scopes`, `/runs`, `/api/runs` hívások a v3 wrapper felé mennek.

