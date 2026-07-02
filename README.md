# Céges Gépjármű Magyar Közlöny Havi Riport

> Havi automatikus monitor, amely a **Magyar Közlöny** friss számait átfésüli, és kiszűri a **céges gépjárműveket** érintő jogszabályváltozásokat — egyetlen `.eml` fájlba rendezve.

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/orchestration-LangGraph-orange)](https://langchain-ai.github.io/langgraph/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## Mi ez?

A `magyarkozlony.hu` oldalról gyűjti az elmúlt **30 nap** Magyar Közlöny számait, minden számból kiemeli a bekezdés-szintű egységeket, majd egy LLM-mel **szemantikusan** eldönti, hogy melyek érintik a céges gépjárművek adózását, üzemeltetését, biztosítását, flottakezelését stb. Az újdonságokról egyetlen `.eml` fájl készül, amit megnyithatsz bármely levelezőkliensben (Thunderbird, Outlook, Apple Mail, mutt).

**Főbb jellemzők:**

- **LangGraph pipeline** — 6 node-os állapotgép, checkpoint-elhető, újrafuttatható.
- **Duplikáció-védelem** — SQLite-alapú state DB, `(issue_number, anchor)` kompozit kulccsal. Soha nem kapsz ugyanarról a bekezdésről kétszer riportot.
- **30 napos rolling ablak** — az első futás egy 30 napos seed, utána mindig az előző futás óta újat dolgozza fel.
- **Szemantikus relevancia** — az LLM 0,00–1,00 score-t ad minden bekezdésre, és a téma-taxonomia alapján 15 altémakörbe sorolja. A küszöb (alapból 0,50) egyszerűen átállítható.
- **Magyar nyelvű kimenet** — subject, törzs, action item-ek mind magyarul.
- **SMTP opcionális** — alapértelmezetten `.eml` fájlba ment, de a `.env`-ben `SMTP_ENABLED=true`-val azonnal küldi is.
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

Ez feldolgozza az elmúlt 30 napot, és a kimenet az `output/gpjarmu-<dátum>.eml` fájlba kerül.

### 7. Megnézés

```powershell
# Megnyitás az alapértelmezett levelezőkliensben
start output\gpjarmu-2026-07-02.eml

# Vagy PowerShell-ben szövegesen
Get-Content output\gpjarmu-2026-07-02.eml
```

### 8. Havi ütemezés (Windows Task Scheduler)

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
├── output/                     # Generált .eml fájlok (git-ignored)
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
6. **`render_email`** — Jinja2 template + email.message.EmailMessage → `.eml` fájl. Opcionálisan SMTP-n is elküldi.

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
| `OUTPUT_DIR` | `./output` | .eml fájlok célmappája |
| `SMTP_ENABLED` | `false` | Ha `true`, a `.eml` mellett SMTP-n is küld |

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
