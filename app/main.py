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
from contextlib import asynccontextmanager
import logging

from app.services.vector_store import VectorStoreService
from app.services.translation import TranslationService
from app.services.gemini import GeminiService
from app.routers import documents, translation, timeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup, cleanup on shutdown."""
    logger.info("🚀 Starting Immigration Assistance ChatBot...")

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

# CORS — allow React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
app.include_router(documents.router, prefix="/api/documents", tags=["Documents & Q&A"])
app.include_router(translation.router, prefix="/api/translation", tags=["Translation"])
app.include_router(timeline.router, prefix="/api/timeline", tags=["Case Timeline"])


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
            "gemini_llm": "active" if app.state.gemini.is_available else "fallback",
        },
    }
