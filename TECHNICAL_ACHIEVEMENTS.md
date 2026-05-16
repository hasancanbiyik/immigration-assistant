# Technical Achievements — Immigration Assistant

> This document is intended for LLM-assisted resume generation and technical portfolio review.
> It describes what was designed, built, and improved across the full development arc of this project.

---

## Project Overview

**Immigration Assistant** is a full-stack AI application designed to assist immigration attorneys with document analysis, legal translation, and case timeline management. The system is built to run entirely on-premise — all client data stays on the attorney's machine, which is a meaningful differentiator from cloud-based legal SaaS tools (Clio, Filevine, MyCase).

**Live stack:** FastAPI (Python) backend · React 19 + Vite frontend · ChromaDB vector database · BGE-M3 / MiniLM embeddings · Gemini 2.5 Flash LLM · Helsinki-NLP OPUS-MT translation models · PyMuPDF document parsing · Docker

---

## Core System Architecture

### Retrieval-Augmented Generation (RAG) Pipeline

Designed and implemented a full RAG pipeline for immigration document Q&A:

1. **Ingestion layer** — Documents (PDF, DOCX, TXT) are parsed by a custom `DocumentParser` built on PyMuPDF. Text is extracted page-by-page with block-level sorting to preserve reading order in complex layouts (e.g., Turkish civil registry tables).

2. **Chunking** — A paragraph-aware overlapping chunker splits documents into 800-character segments with 100-character overlap to avoid information loss at chunk boundaries.

3. **Embedding** — Chunks are embedded using `BGE-M3` (568M parameter multilingual model) with automatic fallback to `MiniLM-L6` if GPU memory is insufficient.

4. **Vector store** — Embeddings are stored in ChromaDB with per-chunk metadata: `client_name`, `case_type`, `document_type`, `source_filename`, `page_number`. This enables precise filtering at query time.

5. **Retrieval** — Cosine similarity search retrieves the top-k most relevant chunks, filtered by `client_name` to enforce client isolation.

6. **Generation** — Retrieved chunks are injected into a Gemini 2.5 Flash prompt alongside the user's question. The LLM returns a structured answer with a confidence score.

### Client Data Isolation

A critical design decision was enforcing strict client isolation in the shared ChromaDB collection. Each document chunk is tagged with `client_name` at upload time, and every query is filtered to that client's namespace. This prevents cross-client data leakage — a requirement for attorney-client confidentiality. Added a client management UI (per-client localStorage persistence, client selector dropdown, per-client chat history) to enforce this at the application layer as well.

---

## Features Built

### 1. Document Q&A with RAG

- Upload immigration documents (PDF, DOCX, TXT up to 50MB) and query them in natural language
- Automatic metadata extraction: USCIS receipt numbers (`[A-Z]{3}\d{10}`), form numbers (I-485, N-400, etc.), case type (H-1B, Asylum, I-130, etc.), document type (receipt notice, approval, RFE, etc.)
- Per-client document management: list all stored documents, delete individual files by client scope
- Response confidence scoring and source attribution (which page, which file)
- Sticky notes sidebar per client (auto-saved to localStorage)

### 2. Multi-Language Legal Translation

- **Two-tier translation architecture:** Gemini 2.5 Flash as primary translator (superior quality, uses pre-extracted text), Helsinki-NLP OPUS-MT as offline fallback (no API required)
- Separate PDF text extraction path for translation: uses `page.get_text("text")` (natural reading order) rather than the block-sorted extraction used for Q&A (optimised for complex tables)
- Per-document confidence scoring parsed from LLM output (`CONFIDENCE: [0-100]` sentinel pattern)
- Optional USCIS-compliant certification statement generation (8 CFR 103.2(b)(3))
- Export to `.txt` and `.docx` formats with attorney-warning header, formatted using python-docx
- Loading indicators, success/failure badges, model attribution in UI

### 3. Case Timeline Tracker

- Auto-extract case events from uploaded USCIS documents using pattern matching across 8 event types: filing, receipt notice, biometrics, RFE issued, RFE response, interview, approval, denial, transfer
- Manual event entry with date picker, receipt number, and form type fields
- In-memory timeline storage per client (session-scoped)
- Events sorted chronologically; automatic de-duplication on multi-document upload
- **USCIS Deadline Calculator** — built-in hard-deadline reference tool (no server calls):
  - RFE response: 87 days
  - NOID response: 30 days
  - NOIR response: 33 days
  - Appeal / Motion to Reopen: 30 days
  - Color-coded urgency output (green → yellow → red → "OVERDUE")
- Per-event automatic response deadline calculation for RFE and NOID events
- Cross-tab "Client Profile" sidebar: access uploaded docs and notes from within the timeline tab without switching

### 4. Frontend (React 19 + Vite)

- Custom `MarkdownText` component for rendering LLM responses — handles `**bold**`, paragraph breaks, and line breaks without an external library
- Client isolation enforced at the UI layer (client must be selected before upload; uploads always tagged with `client_name`)
- `StatusBadge` component for confidence scores, model attribution, urgency indicators
- Indeterminate progress bar during translation/upload
- All client state persisted to `localStorage` (`imm_clients`, `imm_msgs_{id}`, `imm_notes_{id}`, `imm_selected_client`)

---

## Engineering & Quality Improvements

### Debugging and Bug Fixes

- **Cross-client storage contamination** — Root-caused and fixed: ChromaDB shared collection was returning documents from other clients. Fix: enforced `client_name` tagging on every upload and scoped all queries with ChromaDB `where` filter.

- **fpdf2 `multi_cell(0, h, text)` width bug** — Diagnosed `FPDFException: Not enough horizontal space to render a single character` in fpdf2 v2.8.7. Root cause: `set_margins()` called after `add_page()`, causing `epw` to compute as 0. Fix: reorder to set margins before page creation, use `pdf.epw` explicitly as the cell width.

- **PDF translation text ordering** — Documents translated via Gemini were "cut off at the beginning" because block-sorted extraction (designed for tabular civil registry forms) produced incorrect reading order for linear documents. Fix: added a separate `_extract_pages_for_translation()` function that uses `fitz.page.get_text("text")` for direct natural-order extraction for the translation pipeline.

### CI/CD Pipeline (GitHub Actions)

Designed a three-job CI pipeline that runs on every push and pull request:

**Job 1: Backend Tests** (Python 3.11 and 3.12 matrix)
- Uses a lightweight `requirements-test.txt` that excludes `torch`, `sentence-transformers`, and `chromadb` (together ~4GB of downloads). Total install time: ~25 seconds.
- All ML services (`VectorStoreService`, `GeminiService`, `TranslationService`) are replaced with `MagicMock` / `AsyncMock` objects in `conftest.py`, allowing the full FastAPI lifespan to execute without any model downloads.
- Coverage report generated via `pytest-cov` and uploaded to Codecov.
- **62 tests** covering: PDF parsing, document parser, documents router, translation router, timeline router, Pydantic schemas.

**Job 2: Frontend Lint**
- Node 20 with npm cache
- ESLint run against the React codebase

**Job 3: Docker Build** (main branch only, after tests pass)
- Validates the production Dockerfile builds successfully
- GitHub Actions cache (`type=gha`) reuses unchanged Docker layers between runs

### Test Suite Design

Wrote 62 tests across 6 test modules:

| Module | Tests | What it covers |
|---|---|---|
| `test_pdf_parser.py` | 12 | Regex patterns, chunking, text cleaning |
| `test_document_parser.py` | 18 | Extension routing, TXT/DOCX parsing, metadata extraction |
| `test_documents_router.py` | 14 | Upload, Q&A, client document management API |
| `test_translation_router.py` | 13 | Text translation, document translation, certification |
| `test_timeline_router.py` | 14 | Manual events, timeline extraction, client isolation |
| `test_schemas.py` | 22 | Pydantic schema validation, enum coverage |

Key testing decisions:
- **No ML models in CI** — mocked at the class level so the FastAPI lifespan runs for real but services return deterministic outputs
- **Timeline state isolation** — the module-level `_timelines` dict is cleared before each test via an `autouse` fixture to prevent inter-test state bleed
- **Real document parsing in router tests** — PyMuPDF and python-docx run for real; only the embedding/LLM layer is mocked. This catches regressions in the parsing pipeline.

---

## Technologies Used

| Category | Technology | Role |
|---|---|---|
| Backend framework | FastAPI | REST API, dependency injection, lifespan management |
| Language | Python 3.11+ | Core backend |
| Vector database | ChromaDB | Persistent embedding storage and semantic search |
| Embeddings | BGE-M3 (BAAI) | Multilingual dense retrieval |
| LLM | Gemini 2.5 Flash | Q&A generation, legal translation |
| Translation (offline) | Helsinki-NLP OPUS-MT | MarianMT fallback translation |
| PDF parsing | PyMuPDF (fitz) | Block-level PDF text extraction |
| Document parsing | python-docx | DOCX paragraph and table extraction |
| PDF export | fpdf2 | Translation export to PDF |
| Frontend | React 19 + Vite 8 | Single-page application |
| Styling | Inline CSS (no framework) | Custom design system |
| Testing | pytest + httpx | Backend unit and integration tests |
| CI/CD | GitHub Actions | Automated testing and Docker validation |
| Containerisation | Docker | Production deployment |

---

## Differentiating Design Decisions

1. **Local-first architecture** — No client data leaves the attorney's machine. ChromaDB runs embedded (no server), models are downloaded once and cached locally. This is a direct response to attorney-client privilege requirements.

2. **Gemini used only for text** — PyMuPDF extracts text locally (free, fast) before sending to Gemini. Gemini never sees the raw PDF bytes — only extracted text. This minimises API token consumption and keeps sensitive document content from being transmitted unnecessarily.

3. **Graceful degradation** — If `GEMINI_API_KEY` is not set, the system falls back to OPUS-MT for translation and returns top-k retrieved chunks directly for Q&A. The application is usable offline.

4. **Hard deadline awareness** — The USCIS Deadline Calculator is not a calendar integration but a pure calculation tool built into the Case Timeline tab. It implements the actual statutory response windows (87/30/33 days) so attorneys always have the correct deadline on screen without switching to another tool.
