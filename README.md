---
title: Immigration Assistant ChatBot
emoji: 📄
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 8000
pinned: false
short_description: RAG-powered immigration law assistant — Q&A, translation, timeline, RFE tracker
---

# Immigration Assistant ChatBot

A RAG-powered immigration law assistant with document Q&A, USCIS-compliant translation, case timeline tracking, and RFE deadline management.

> **Public demo note.** This Space runs on HuggingFace's free CPU tier. First load after inactivity may take 30–60 seconds while the container warms up. Uploaded documents and RFE cases reset between container restarts — this is intentional for an ephemeral demo. The full production deployment uses persistent storage.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  React Frontend                      │
│   ┌──────────┐  ┌──────────┐  ┌──────────────────┐ │
│   │ Doc Q&A  │  │Translate │  │ Case Timeline    │ │
│   └────┬─────┘  └────┬─────┘  └────────┬─────────┘ │
└────────┼──────────────┼─────────────────┼───────────┘
         │              │                 │
┌────────┼──────────────┼─────────────────┼───────────┐
│        ▼              ▼                 ▼           │
│              FastAPI Backend                         │
│  ┌────────────┐ ┌────────────┐ ┌──────────────────┐│
│  │/api/docs   │ │/api/trans  │ │/api/timeline     ││
│  └─────┬──────┘ └─────┬──────┘ └────────┬─────────┘│
│        │              │                 │           │
│  ┌─────▼──────┐ ┌─────▼──────┐ ┌───────▼─────────┐│
│  │ ChromaDB   │ │ OPUS-MT    │ │ Regex + NLP     ││
│  │ + BGE-M3   │ │ (TR/ES/ZH/ │ │ Event Extractor ││
│  │ (RAG)      │ │  AR ↔ EN)  │ │                 ││
│  └─────┬──────┘ └────────────┘ └─────────────────┘│
│        │                                            │
│  ┌─────▼──────┐                                     │
│  │ Gemini     │                                     │
│  │ Free Tier  │                                     │
│  │ (Reasoning)│                                     │
│  └────────────┘                                     │
└─────────────────────────────────────────────────────┘
```

## Tech Stack

| Component       | Technology                          | License     |
|-----------------|-------------------------------------|-------------|
| Backend         | FastAPI                             | MIT         |
| Embeddings      | BAAI/bge-m3 (568M params)           | MIT         |
| Vector Store    | ChromaDB                            | Apache 2.0  |
| Translation     | Helsinki-NLP OPUS-MT (big variants) | Apache 2.0  |
| LLM Reasoning   | Gemini Free Tier                   | Google ToS  |
| PDF Parsing     | PyMuPDF                             | AGPL        |
| Frontend        | React 19 (inline styles, no UI framework) | MIT         |
| Containerization| Docker                              | Apache 2.0  |

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
- `GET /api/health` — Health check

## Running Tests

```bash
pytest tests/ -v
```

## Models

### Embedding: BGE-M3 (default) / MiniLM (public demo)
- **`BAAI/bge-m3`** is the default retriever in code — 568M parameters, multilingual (EN/TR/ES/ZH/AR), supports dense + sparse hybrid retrieval, runs on CPU or Apple Silicon, MIT license.
- **`sentence-transformers/all-MiniLM-L6-v2`** is swapped in for the public HuggingFace Space demo (~150 MB RAM, ~15s cold start vs. BGE-M3's ~90s) to keep first-load fast on the free CPU tier. Selected at runtime via the `EMBEDDING_MODEL` environment variable — no code change required.
- The fallback path is built into `VectorStoreService.initialize()`: if BGE-M3 fails to load (OOM, network hiccup), it automatically degrades to MiniLM.

### Translation: OPUS-MT
- Separate models per language pair (lazy-loaded)
- Turkish: `opus-mt-tc-big-tr-en` / `opus-mt-tc-big-en-tr`
- Spanish: `opus-mt-es-en` / `opus-mt-en-es`
- Chinese: `opus-mt-zh-en` / `opus-mt-en-zh`
- Arabic: `opus-mt-ar-en` / `opus-mt-en-ar`
- Apache 2.0 license

## Project Status

- [x] Backend scaffolding (FastAPI + 4 routers: documents, translation, timeline, RFE)
- [x] PDF / DOCX / TXT parsing pipeline with immigration metadata extraction
- [x] Vector store service (ChromaDB + BGE-M3, with MiniLM fallback)
- [x] Translation service (Gemini 2.5 Flash primary, OPUS-MT fallback) + USCIS certification
- [x] Case timeline extraction (regex + manual entry)
- [x] RFE Tracker (SQLite-backed cases + checklist + Gemini issue extraction)
- [x] Pydantic schemas for all modules
- [x] Tests for PDF parser
- [x] Dockerfile (multi-stage: frontend build + backend)
- [x] Gemini integration for LLM reasoning
- [x] React frontend (single-file App.jsx, 4 panels)
- [x] HuggingFace Spaces deployment (Docker SDK, free CPU tier)
- [ ] Synthetic demo data
- [ ] Persistent storage upgrade path (HF Pro / Fly.io with volumes)

## Author

Hasan Can Biyik — [Portfolio](https://hasancanbiyik.com) | [LinkedIn](https://linkedin.com/in/hasancanbiyik)
