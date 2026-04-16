"""
Immigration Assistance ChatBot — Main FastAPI Application
=========================================================
A RAG-powered immigration law assistant with document Q&A,
USCIS-compliant translation, and case timeline tracking.

Tech Stack:
- FastAPI (backend)
- ChromaDB + BGE-M3 (vector store + embeddings)
- Helsinki-NLP OPUS-MT (translation)
- Gemini Free Tier (LLM reasoning)
- PyMuPDF (PDF parsing)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import logging
import os

from app.services.vector_store import VectorStoreService
from app.services.translation import TranslationService
from app.services.gemini import GeminiService
from app.services import rfe_db
from app.routers import documents, translation, timeline
from app.routers import rfe

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup, cleanup on shutdown."""
    logger.info("🚀 Starting Immigration Assistance ChatBot...")

    # Initialize RFE tracker SQLite database
    rfe_db.init_db()
    logger.info("✅ RFE tracker database ready (SQLite)")

    # Initialize vector store
    app.state.vector_store = VectorStoreService()
    await app.state.vector_store.initialize()
    logger.info("✅ Vector store initialized (ChromaDB + BGE-M3)")

    # Initialize translation service (lazy-loads models on first use)
    app.state.translation = TranslationService()
    logger.info("✅ Translation service ready (OPUS-MT)")

    # Initialize Gemini LLM service
    app.state.gemini = GeminiService()
    app.state.gemini.initialize()
    if app.state.gemini.is_available:
        logger.info("✅ Gemini LLM ready (gemini-2.0-flash)")
    else:
        logger.warning("⚠️  Gemini unavailable — Q&A will use fallback mode")

    yield

    # Cleanup
    logger.info("🛑 Shutting down services...")


app = FastAPI(
    title="Immigration Assistance ChatBot",
    description=(
        "RAG-powered immigration law assistant with document Q&A, "
        "USCIS-compliant translation, and case timeline tracking."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow React frontend (local dev only; production uses same origin)
_extra_origins = os.getenv("ALLOWED_ORIGINS", "").split(",")
_cors_origins = ["http://localhost:3000", "http://localhost:5173"] + [
    o.strip() for o in _extra_origins if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
app.include_router(documents.router, prefix="/api/documents", tags=["Documents & Q&A"])
app.include_router(translation.router, prefix="/api/translation", tags=["Translation"])
app.include_router(timeline.router, prefix="/api/timeline", tags=["Case Timeline"])
app.include_router(rfe.router, prefix="/api/rfe", tags=["RFE Tracker"])


# ── Static frontend (production) ──────────────────────────────────────────────
# When running in Docker/Fly.io the built React app lives at frontend/dist.
# In local dev the directory won't exist, so this block is safely skipped.
_FRONTEND_DIST = os.path.join(os.getcwd(), "frontend", "dist")
if os.path.isdir(_FRONTEND_DIST):
    # Serve compiled JS/CSS assets
    _assets_dir = os.path.join(_FRONTEND_DIST, "assets")
    if os.path.isdir(_assets_dir):
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

    # Serve any other static files at the dist root (favicon, icons, etc.)
    @app.get("/favicon.svg", include_in_schema=False)
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        for name in ("favicon.svg", "favicon.ico"):
            path = os.path.join(_FRONTEND_DIST, name)
            if os.path.exists(path):
                return FileResponse(path)

    # SPA catch-all — return index.html for every non-API route so that
    # client-side routing (React Router, etc.) works on hard refresh.
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        return FileResponse(os.path.join(_FRONTEND_DIST, "index.html"))


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "Immigration Assistance ChatBot",
        "version": "1.0.0",
        "modules": {
            "document_qa": "active",
            "translation": "active",
            "timeline": "active",
            "rfe_tracker": "active",
            "gemini_llm": "active" if app.state.gemini.is_available else "fallback",
        },
    }
