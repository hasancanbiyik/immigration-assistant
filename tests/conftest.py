"""
Shared test fixtures for the Immigration Assistant test suite.

Strategy
--------
All heavy ML services (VectorStoreService, GeminiService, TranslationService)
are replaced with lightweight MagicMock / AsyncMock objects so the full test
suite runs without downloading any ML models and finishes in seconds.

The FastAPI lifespan still executes — it just calls the mocked classes.

Import-chain problem and solution
----------------------------------
app.main imports app.services.vector_store, which imports chromadb and
sentence_transformers at module level. app.services.translation imports
transformers at module level. None of these are in requirements-test.txt.

If Python can't satisfy those imports, app.main never attaches to the app
package, and patch("app.main.VectorStoreService", ...) raises:
    AttributeError: module 'app' has no attribute 'main'

Fix: install lightweight MagicMock stubs into sys.modules for every heavy
dependency *before* any app package is imported. This happens at conftest
module-load time (i.e. before any test or fixture runs), which is early
enough to intercept the import chain.
"""

import os
import sys
import tempfile
from unittest.mock import MagicMock, AsyncMock, patch
import pytest
from fastapi.testclient import TestClient


# ── Test SQLite path (must be set BEFORE any app.* import) ────────────────────
# Both rfe_db and timeline_db read APP_DB_PATH at module-load time. Point them
# at a throwaway temp file so tests don't write to ./data/ in the repo root.
_TEST_DB_FD, _TEST_DB_PATH = tempfile.mkstemp(prefix="immigration_test_", suffix=".db")
os.close(_TEST_DB_FD)
os.environ["APP_DB_PATH"] = _TEST_DB_PATH


# ── Stub heavy ML deps so app.main can be imported without the full ML stack ──
# These libraries are imported at module level (not lazily) in the service
# files, so they must be present in sys.modules before app.main loads.
_HEAVY_DEPS = [
    "chromadb",
    "chromadb.config",
    "chromadb.utils",
    "chromadb.utils.embedding_functions",
    "sentence_transformers",
    "transformers",
    "torch",
    "torch.nn",
    "torch.nn.functional",
]
for _mod in _HEAVY_DEPS:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

# chromadb.config.Settings must be callable (it's used as Settings(...) in
# vector_store.py). MagicMock() is already callable by default, but being
# explicit avoids surprises if the Settings constructor is called with kwargs.
sys.modules["chromadb.config"].Settings = MagicMock(return_value=MagicMock())


# ─── Mock factory helpers ─────────────────────────────────────────────────────

def make_mock_vector_store():
    vs = MagicMock()
    vs.initialize = AsyncMock()
    vs.is_available = True
    vs.add_chunks.return_value = 5
    vs.query.return_value = [
        {
            "text": "Receipt Number EAC2390012345. Your I-485 petition has been received.",
            "score": 0.87,
            "metadata": {
                "source_filename": "i797_notice.pdf",
                "page_number": 1,
                "chunk_index": 0,
                "client_name": "test_client",
                "case_type": "Asylum",
                "document_type": "receipt_notice",
            },
        }
    ]
    vs.list_documents_by_client.return_value = ["i797_notice.pdf", "i485_petition.pdf"]
    vs.delete_document.return_value = 3
    vs.get_collection_stats.return_value = {"total_chunks": 42, "model": "bge-m3"}
    return vs


def make_mock_gemini():
    gem = MagicMock()
    gem.is_available = True
    gem.generate_answer = AsyncMock(return_value={
        "answer": "Based on the documents, your I-485 receipt number is EAC2390012345 "
                  "and the case is currently pending.",
        "confidence": 0.87,
    })
    gem.translate_text = AsyncMock(return_value={
        "translated_text": "This document was issued by the Department of Homeland Security.",
        "confidence": 88,
        "model_used": "gemini-2.5-flash",
    })
    # OCR fallback path in documents.py awaits this; without AsyncMock it
    # returns a non-awaitable MagicMock and uploads of sparse-text PDFs fail.
    gem.extract_text_from_document = AsyncMock(return_value=None)
    gem.extract_rfe_issues = AsyncMock(return_value=[])
    return gem


def make_mock_translation():
    ts = MagicMock()
    ts.translate_text.return_value = {
        "translated_text": "Fallback OPUS-MT translation result.",
        "model": "Helsinki-NLP/opus-mt-tc-big-tr-en",
        "word_count": 6,
    }
    ts.translate_pages.return_value = [
        {"page_number": 1, "translated_text": "Translated page one content."}
    ]
    ts.get_supported_languages.return_value = {
        "tr-en": "Turkish → English",
        "es-en": "Spanish → English",
    }
    ts._generate_certification.return_value = (
        "I, the undersigned, certify that the above is a true and accurate translation."
    )
    return ts


# ─── Main test client fixture ─────────────────────────────────────────────────

@pytest.fixture()
def client():
    """
    FastAPI TestClient with all ML services mocked.

    Each test gets a fresh lifespan cycle (startup + shutdown) so app.state
    is clean. SQLite tables (timeline_events, rfe_cases, rfe_issues) are
    wiped between tests by the autouse `clear_sqlite_state` fixture.
    """
    with (
        patch("app.main.VectorStoreService", return_value=make_mock_vector_store()),
        patch("app.main.GeminiService", return_value=make_mock_gemini()),
        patch("app.main.TranslationService", return_value=make_mock_translation()),
    ):
        from app.main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


# ─── SQLite state cleanup ─────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_sqlite_state():
    """
    Wipe SQLite tables before and after each test so events/cases from one
    test don't bleed into the next.

    Calls init_db() on each module first because the fixture may run before
    any test invokes the `client` fixture (which triggers the lifespan that
    normally creates the tables).
    """
    from app.services import timeline_db, rfe_db
    timeline_db.init_db()
    rfe_db.init_db()

    def _wipe():
        # Order matters: rfe_issues FK-cascades from rfe_cases, but explicit
        # is clearer than implicit (and faster than relying on cascade).
        timeline_db.clear_all_events()
        with rfe_db._get_conn() as conn:
            conn.execute("DELETE FROM rfe_issues")
            conn.execute("DELETE FROM rfe_cases")

    _wipe()
    yield
    _wipe()
