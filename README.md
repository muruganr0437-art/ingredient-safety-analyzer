# AI Ingredient Safety Analyzer

An educational Streamlit app that reads a packaged-food ingredient label (OCR or typed), matches ingredients to a
**curated, source-linked database**, and explains what is known, what is uncertain and what is missing. It separates
*hazard* from *risk*, estimates exposure only from validated inputs, and exports TXT/PDF reports.

**It is not a medical tool.** It never diagnoses, never predicts illness/death/lifespan, and never labels a product
"safe". See *Limitations*.

## Features
Image upload (JPG/PNG/WEBP, validated, EXIF-rotated) - Tesseract OCR with editable text - label parsing (serving size,
allergens, manufacturer, expiry, nutrition) - deterministic ingredient matching (exact > synonym > E/INS number >
**flagged** fuzzy that needs your confirmation) - evidence cards with sources - exposure calculator
(intake, mg/kg bw/day, %ADI) that refuses to run on missing data - missing-data section - TXT/PDF report - local
redacted history with delete - admin page (edit, review status, import/export) - emergency guidance - optional AI
explanation behind guardrails.

## Limitations (read this)
* **The seed database is a starter, not an authority.** All 9 seed records (and every ADI in them) are marked
  `unverified`. They cite real EFSA/WHO/IARC documents, but the build process could not open those documents, so
  numbers and URLs **must be checked by a person** before you mark anything `reviewed`. Unreviewed ADIs are *never*
  used for %ADI comparisons.
* No live connection to WHO/FAO/JECFA/EFSA/FDA/FSSAI exists. Barcode / Open Food Facts lookup is **not implemented**
  (see Future improvements).
* OCR misreads text; always edit the extracted ingredients.
* An ADI is a chronic reference value, not an acute poison threshold; exceeding it does not prove harm.
* Only one food and one ingredient are counted per calculation; other dietary sources are ignored.
* Emergency numbers are **not shipped**; configure verified ones (below).

## Architecture
```
Upload -> ocr_service (validate, orient, OCR, parse) -> editable text
       -> ingredient_service (split, match, flag uncertain) -> database/db.py (SQLite, curated data)
       -> report_service (risk category, missing data) + exposure_service (validated inputs only)
       -> evidence_service (provenance checks) -> TXT / PDF
       -> ai_service (optional; sees only curated facts; output validated)
```
Curated science (`ingredients`, `health_effects`, `safety_limits`, `evidence_sources`) is separate from sessions
and from AI text (`ai_summaries`). Schema: `database/schema.sql`.

## Setup on Windows (PowerShell + VS Code)
```powershell
# 1. Install Python 3.11+ from python.org (tick "Add to PATH"), then in the VS Code terminal:
cd path\to\ingredient-safety-analyzer
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
pip install -r requirements.txt

# 2. Install Tesseract OCR: download the Windows installer from the UB Mannheim build linked on
#    https://github.com/tesseract-ocr/tesseract  (docs: "Installing Tesseract"), install to the default folder.
#    Then either add C:\Program Files\Tesseract-OCR to PATH, or set it in .env (next step).

# 3. Configuration
Copy-Item .env.example .env
notepad .env        # set TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe if not on PATH

# 4. Initialise the database (also happens automatically on first launch)
python -m database.db

# 5. Run
streamlit run app.py
```
macOS/Linux: `python3 -m venv .venv && source .venv/bin/activate`, install Tesseract with `brew install tesseract` or
`sudo apt install tesseract-ocr`.

**Versions the test suite passed on:** Python 3.12.3, streamlit 1.65.0, pillow 12.1.1, pytesseract 0.3.13,
pydantic 2.14.0, pandas 3.0.2, plotly 7.1.0, requests 2.33.1, reportlab 4.4.10, python-dotenv 1.2.2, pytest 9.1.1.
Python 3.11 was not tested.

## Run the tests
```powershell
python -m pytest -q
```
Covers: ingredient matching (case, synonyms, identifiers, typos, unknowns), OCR/invalid images/EXIF, exposure maths
and missing/invalid inputs, report + PDF links, invalid sources, redaction, toxic-exposure warnings, import/export
rules, AI guardrails, and a headless run of every Streamlit page. Example: `500 mg/kg x 0.33 kg = 165 mg/day;
/60 kg = 2.75 mg/kg bw/day; /40 = 6.875 % of ADI`.

## Adding reviewed ingredient records
1. Set `ADMIN_PASSWORD` in `.env`, restart, open **Ingredient Database > Administrator**.
2. Choose *New record* (or edit one). Fill the JSON: synonyms, `e_number`/`ins_number`, `sources` (title, publisher,
   URL, publication date, claim supported), `health_effects` (each cites a listed source URL), `safety_limits`.
3. Open each source yourself and confirm it supports the claim and number. Put today's date in `retrieval_date`.
4. Use **Quick review actions**: status `reviewed` + date (optionally apply to its safety limits). The model refuses
   `reviewed` without a source and date. Imports are forced to `unverified` unless you tick the keep-status box.

## Emergency resources
Copy `data/emergency_resources.example.json` to `data/emergency_resources.json` and add only contacts you verified from
an official source (with source URL and date). Without it the app tells users to look up their local number.

## Optional AI explanation
Off by default. To enable, set `AI_ENABLED=true`, `AI_API_URL` (OpenAI-compatible chat-completions endpoint),
`AI_API_KEY`, `AI_MODEL` in `.env` / host secrets. The model only receives curated findings, and its output is rejected
if it adds links, numbers not in the facts, or outcome predictions. `evidence_service.retrieve_evidence` is a
keyword retriever over approved records; swap in sentence-transformers + FAISS if you want semantic retrieval.

## Deployment
* **Streamlit Community Cloud:** push to GitHub; `packages.txt` installs Tesseract; add secrets in the app settings
  (same names as `.env`). **Local SQLite does not persist there** (the filesystem is ephemeral): the curated seed is
  re-created on restart, but admin edits and saved history are lost. For real use choose a container host or add a
  managed database (migration path: replace `database/db.py` with a PostgreSQL implementation; the schema is portable
  apart from `AUTOINCREMENT`/`PRAGMA`).
* **Docker:** `docker build -t isa . && docker run -p 8501:8501 -v isa-data:/data -e ADMIN_PASSWORD=... isa`. The volume
  keeps the DB. Put it behind an HTTPS reverse proxy (Caddy/nginx/cloud load balancer); never expose plain HTTP.
* Uploads: 8 MB cap (`MAX_UPLOAD_MB` + `.streamlit/config.toml`), type + decode validation, pixel limit, processed in memory,
  never written to disk. Back up `data/analyzer.db` regularly and set a retention period for saved reports.
* Do not commit `.env` or `secrets.toml`. Use a long unique `ADMIN_PASSWORD`; the admin check uses constant-time
  comparison and a 5-attempt session limit, but it is a single shared password, not a user-account system.

## Troubleshooting
* *"Tesseract OCR is not installed"* - install it and set `TESSERACT_CMD`.
* *PowerShell blocks activation* - `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
* *`ModuleNotFoundError`* - run commands from the project root with the venv active.
* *Empty/garbled OCR* - use a sharper, well-lit, flat photo, or type the ingredients.
* *Admin tab says disabled* - `ADMIN_PASSWORD` is empty.

## Future improvements
Open Food Facts barcode lookup (check its current terms, attribution and data-quality caveats first; a barcode match
must not mark a composition as verified), country-specific permitted-use data, semantic RAG over an approved document
set, per-user accounts, PostgreSQL, group-ADI unit conversion helpers (e.g. sodium benzoate -> benzoic acid).
