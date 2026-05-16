---
title: Immigration Assistant
emoji: 📄
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 8000
pinned: false
short_description: AI Immigration Assistant — Q&A, translation, RFE tracker
---

# Immigration Assistant

A RAG-powered immigration law assistant with document Q&A, USCIS-compliant translation, case timeline tracking, and RFE deadline management.

> **Public demo note.** This Space runs on HuggingFace's free CPU tier. First load after inactivity may take 30–60 seconds while the container warms up. Uploaded documents and RFE cases reset between container restarts — this is intentional for an ephemeral demo. The full production deployment uses persistent storage.

## Live Demo

**[hasancanbiyik-immigration-assistant.hf.space](https://hasancanbiyik-immigration-assistant.hf.space)** — public HuggingFace Space, free CPU tier.

The demo includes a one-click **"Try with sample document"** button on the Q&A panel so reviewers can hit a working RAG flow without supplying their own USCIS notice. A loading overlay polls `/api/health` and dismisses itself once the embedding model is ready, so the first click after a cold-start doesn't look like a broken page.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                       React Frontend (SPA)                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ Doc Q&A  │  │Translate │  │ Case Timeline│  │ RFE Tracker  │  │
│  └────┬─────┘  └────┬─────┘  └──────┬───────┘  └──────┬───────┘  │
└───────┼─────────────┼────────────────┼──────────────────┼────────┘
        │             │                │                  │
┌───────┼─────────────┼────────────────┼──────────────────┼────────┐
│       ▼             ▼                ▼                  ▼        │
│                       FastAPI Backend                            │
│ ┌──────────────┐ ┌─────────────┐ ┌──────────────┐ ┌────────────┐ │
│ │/api/documents│ │/api/transl. │ │/api/timeline │ │/api/rfe    │ │
│ └──────┬───────┘ └──────┬──────┘ └──────┬───────┘ └─────┬──────┘ │
│        │                │               │                │       │
│ ┌──────▼──────┐ ┌───────▼──────┐ ┌──────▼───────┐ ┌─────▼──────┐ │
│ │ ChromaDB    │ │ Gemini 2.5   │ │ Regex event  │ │ SQLite     │ │
│ │ + BGE-M3    │ │ Flash (1st)  │ │ extractor    │ │ (cases +   │ │
│ │ (vector RAG)│ │ → OPUS-MT    │ │ + NOID/RFE   │ │ checklist) │ │
│ │             │ │   fallback   │ │ deadlines    │ │            │ │
│ └──────┬──────┘ └──────────────┘ └──────────────┘ └────────────┘ │
│        │                                                         │
│ ┌──────▼──────────────┐                                          │
│ │ Gemini 2.5 Flash    │ ← LLM reasoning over retrieved chunks    │
│ │ (RAG synthesizer)   │   + Gemini vision OCR for scanned PDFs   │
│ └─────────────────────┘                                          │
└──────────────────────────────────────────────────────────────────┘
```

## Tech Stack

| Component        | Technology                                                | License        |
|------------------|-----------------------------------------------------------|----------------|
| Backend          | FastAPI + Uvicorn                                         | MIT            |
| Embeddings       | BAAI/bge-m3 (568M params) — MiniLM swap on free tier       | MIT            |
| Vector Store     | ChromaDB (persistent client, cosine similarity)            | Apache 2.0     |
| LLM (Q&A + OCR)  | Gemini 2.5 Flash                                          | Google ToS     |
| Translation      | Gemini 2.5 Flash → Helsinki-NLP OPUS-MT fallback           | Google + Apache|
| Document parsing | PyMuPDF (PDF), python-docx (DOCX), regex (immigration meta)| AGPL / MIT     |
| Persistence      | SQLite (RFE cases + checklist, WAL mode, FK enforced)      | Public domain  |
| PDF export       | fpdf2 + DejaVu Sans (Unicode-safe, bundled in image)      | LGPL / Bitstream |
| Frontend         | React 19, single-file SPA, inline styles (no UI framework) | MIT            |
| Build / CI       | Vite, Docker (multi-stage), GitHub Actions                | MIT / Apache   |

## Quick Start

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# 2. Install backend dependencies
pip install -r requirements.txt

# 3. (Optional) Enable Gemini for higher-quality Q&A + translation + OCR fallback.
#    Without this, the app uses the OPUS-MT local fallback for translation
#    and returns retrieved chunks (no LLM reasoning) for Q&A.
export GEMINI_API_KEY="your_api_key_here"

# 4. Run the API
uvicorn app.main:app --reload --port 8000

# 5. (In another terminal) run the React frontend in dev mode
cd frontend
npm install
npm run dev   # opens http://localhost:5173 with /api proxied to :8000

# Or, for production: build the frontend and let FastAPI serve it
# from the same origin (Docker does this automatically):
#   cd frontend && npm run build
#   uvicorn app.main:app --port 8000
#   open http://localhost:8000

# API docs (Swagger UI)
open http://localhost:8000/docs
```

## API Endpoints

### Document Q&A
- `POST /api/documents/upload` — Upload and process a PDF / TXT / DOCX (with optional `client_name`)
- `POST /api/documents/ask` — Ask questions about uploaded documents
- `GET /api/documents/stats` — Collection statistics
- `GET /api/documents/client/{client_name}` — List documents stored for a client
- `DELETE /api/documents/client/{client_name}` — Delete all of a client's documents
- `DELETE /api/documents/client/{client_name}/{filename}` — Delete one document for a client
- `DELETE /api/documents/{filename}` — Delete a document (all clients)

### Translation
- `POST /api/translation/text` — Translate text (Gemini → OPUS-MT fallback) with optional USCIS certification
- `POST /api/translation/document` — Translate an uploaded PDF / TXT / DOCX page-by-page
- `POST /api/translation/export` — Export translation as `.docx` or `.pdf`
- `GET /api/translation/languages` — Supported language pairs and loaded models

### Case Timeline
- `POST /api/timeline/extract` — Extract timeline from a single document
- `POST /api/timeline/extract-multiple` — Merge timelines from multiple documents
- `POST /api/timeline/events/add` — Manually add a timeline event for a client
- `GET /api/timeline/events/{client_name}` — Get the saved timeline for a client

### RFE Tracker
- `GET /api/rfe/cases` — List all RFE cases (sorted by deadline urgency)
- `POST /api/rfe/cases` — Create a case (auto-calculates +87-day deadline)
- `GET /api/rfe/cases/{case_id}` — Get a case + its issues checklist
- `PUT /api/rfe/cases/{case_id}` — Update case fields
- `DELETE /api/rfe/cases/{case_id}` — Delete case (cascades issues)
- `POST /api/rfe/cases/{case_id}/issues` — Add a checklist item
- `PUT /api/rfe/cases/{case_id}/issues/{issue_id}` — Update an issue
- `DELETE /api/rfe/cases/{case_id}/issues/{issue_id}` — Remove an issue
- `POST /api/rfe/cases/{case_id}/extract-issues?mode=quick|ai` — Auto-populate checklist from an RFE notice (regex or Gemini vision)

### System
- `GET /api/health` — Returns `{ ready: bool, embedding_model: str, modules: {...} }`. Resilient to partial startup (uses `getattr` for `app.state.*`) so HF Space wake-from-sleep gets a 200 even while the embedder is still loading. The frontend polls this endpoint to dismiss the loading overlay.

## Running Tests

```bash
pytest tests/ -v
```

The full suite (114 tests across the parser, schemas, and every router) runs in under a second because `tests/conftest.py` installs `MagicMock` stubs for heavy ML deps (`chromadb`, `sentence_transformers`, `transformers`, `torch`) into `sys.modules` before `app.main` is imported. This means CI doesn't have to download multi-gigabyte ML models on every push.

## Deployment

See **[DEPLOY.md](./DEPLOY.md)** for the full HuggingFace Spaces deployment procedure: creating the Space, configuring `GEMINI_API_KEY` and `EMBEDDING_MODEL` as Space secrets, pushing via git remote, watching the build, and troubleshooting common issues (port mismatches, cold-start times, missing secrets, etc.).

Updates after the initial deploy are a single `git push hf main` — HF rebuilds the Docker image automatically.

## Models

### Embedding: BGE-M3 (default) / MiniLM (public demo)
- **`BAAI/bge-m3`** is the default retriever in code — 568M parameters, multilingual (EN/TR/ES/ZH/AR), supports dense + sparse hybrid retrieval, runs on CPU or Apple Silicon, MIT license.
- **`sentence-transformers/all-MiniLM-L6-v2`** is swapped in for the public HuggingFace Space demo (~150 MB RAM, ~15s cold start vs. BGE-M3's ~90s) to keep first-load fast on the free CPU tier. Selected at runtime via the `EMBEDDING_MODEL` environment variable — no code change required.
- The fallback path is built into `VectorStoreService.initialize()`: if BGE-M3 fails to load (OOM, network hiccup), it automatically degrades to MiniLM.

### Translation: Gemini 2.5 Flash (primary) / OPUS-MT (fallback)

The translation router tries Gemini first, falls back to OPUS-MT only if Gemini is unavailable, rate-limited, or returns an empty response (safety filters etc.). This gives the demo LLM-quality output without depending on the LLM being up.

- **Gemini 2.5 Flash** — used via a dedicated `GenerativeModel` instance with no system prompt and `max_output_tokens=8192` (the QA model is configured separately for retrieval). Returns translation + a model-reported confidence score (`CONFIDENCE: NN` parsed from the response). Also handles document-level translation page-by-page with confidence averaging.

- **Helsinki-NLP OPUS-MT** (Apache 2.0) — local fallback, lazy-loaded per language pair so RAM isn't wasted on unused pairs. Sentence splitter guards Turkish abbreviations (`T.C.`, `vb.`, etc.) and DD.MM.YYYY dates from being mis-split.
  - Turkish: `opus-mt-tc-big-tr-en` / `opus-mt-tc-big-en-tr`
  - Spanish: `opus-mt-es-en` / `opus-mt-en-es`
  - Chinese: `opus-mt-zh-en` / `opus-mt-en-zh`
  - Arabic: `opus-mt-ar-en` / `opus-mt-en-ar`

USCIS certification statements (per 8 CFR 103.2(b)(3)) are generated by the app and bundled with the translation download. The PDF export uses the bundled DejaVu Sans font (installed via `fonts-dejavu-core` in the Docker image) so Turkish, Spanish, Arabic characters render correctly — falls back to Helvetica + Latin-1 substitution on machines without DejaVu installed.

## Project Status

- [x] Backend scaffolding (FastAPI + 4 routers: documents, translation, timeline, RFE)
- [x] PDF / DOCX / TXT parsing pipeline with immigration metadata extraction
- [x] Vector store service (ChromaDB + BGE-M3, with MiniLM swap for free-tier demo)
- [x] Translation service (Gemini 2.5 Flash primary, OPUS-MT fallback) + USCIS certification
- [x] Case timeline extraction (regex auto-detect + manual entry, incl. NOID 30-day window)
- [x] RFE Tracker (SQLite-backed cases + checklist, regex & Gemini-vision extraction modes)
- [x] Pydantic schemas for all modules
- [x] **114 backend tests** with mocked ML services — full suite runs in <1 second
- [x] CI: backend tests on Python 3.11 + 3.12, frontend ESLint, Docker build smoke test
- [x] Dockerfile (multi-stage: React build → FastAPI backend, single image)
- [x] Gemini integration for LLM reasoning + vision OCR + RFE issue extraction
- [x] React 19 frontend with cold-start loading overlay, public-demo banner, sample-doc one-click loader
- [x] PDF export with Unicode-safe rendering (DejaVu Sans, fpdf2)
- [x] HuggingFace Spaces deployment (Docker SDK, free CPU tier)
- [ ] Persistent storage upgrade path (HF Pro paid tier, mounted at `/data`)
- [ ] Hybrid retrieval (BGE-M3 sparse + dense reranking)
- [ ] Gemini-vision timeline extraction (mirroring the RFE Tracker's two-mode pattern)

## Author

Hasan Can Biyik — [Portfolio](http://hasancanbiyik.github.io/) | [LinkedIn](https://www.linkedin.com/in/hasancanbyk/)
