"""
Integration tests for the Documents & Q&A router.

All ML services (vector store, Gemini) are mocked via conftest.py.
The document parsing pipeline (PyMuPDF, python-docx) runs for real
so upload tests validate actual file handling behaviour.
"""

import io
import pytest


# ─── Health check ─────────────────────────────────────────────────────────────

class TestHealthCheck:

    def test_health_returns_200(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200

    def test_health_response_structure(self, client):
        data = client.get("/api/health").json()
        assert data["status"] == "healthy"
        assert "modules" in data
        assert "document_qa" in data["modules"]
        assert "translation" in data["modules"]
        assert "timeline" in data["modules"]

    def test_health_reports_gemini_active(self, client):
        data = client.get("/api/health").json()
        # Mock gemini has is_available = True
        assert data["modules"]["gemini_llm"] == "active"


# ─── Document upload ──────────────────────────────────────────────────────────

class TestDocumentUpload:

    def _upload(self, client, content: bytes, filename: str,
                content_type: str = "text/plain", client_name: str = "test_client"):
        return client.post(
            "/api/documents/upload",
            files={"file": (filename, io.BytesIO(content), content_type)},
            data={"client_name": client_name},
        )

    def test_upload_txt_returns_200(self, client):
        resp = self._upload(client, b"I-485 petition. EAC2390012345.", "petition.txt")
        assert resp.status_code == 200

    def test_upload_response_fields(self, client):
        resp = self._upload(client, b"H-1B specialty occupation petition.", "h1b.txt")
        data = resp.json()
        assert "filename" in data
        assert "pages_processed" in data
        assert "chunks_created" in data
        assert data["filename"] == "h1b.txt"
        assert data["pages_processed"] == 1
        # chunks_created comes from mocked add_chunks which returns 5
        assert data["chunks_created"] == 5

    def test_upload_detects_receipt_number(self, client):
        content = b"Receipt Number: EAC2390012345\nYour case has been received."
        resp = self._upload(client, content, "receipt.txt")
        data = resp.json()
        meta = data.get("extracted_metadata", {})
        assert meta.get("receipt_number") == "EAC2390012345"

    def test_upload_unsupported_type_returns_400(self, client):
        resp = self._upload(client, b"fake image bytes", "photo.jpg", "image/jpeg")
        assert resp.status_code == 400
        assert "Supported file types" in resp.json()["detail"]

    def test_upload_without_client_name_succeeds(self, client):
        """Client name is optional — upload still works without it."""
        resp = client.post(
            "/api/documents/upload",
            files={"file": ("doc.txt", io.BytesIO(b"Test document content."), "text/plain")},
        )
        assert resp.status_code == 200

    def test_upload_docx_succeeds(self, client):
        from docx import Document
        doc = Document()
        doc.add_paragraph("This is a support letter for an I-130 petition.")
        buf = io.BytesIO()
        doc.save(buf)
        docx_bytes = buf.getvalue()

        resp = client.post(
            "/api/documents/upload",
            files={"file": ("support_letter.docx", io.BytesIO(docx_bytes),
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            data={"client_name": "alice"},
        )
        assert resp.status_code == 200
        assert resp.json()["filename"] == "support_letter.docx"


# ─── Document Q&A ─────────────────────────────────────────────────────────────

class TestDocumentQA:

    def test_ask_returns_200(self, client):
        resp = client.post(
            "/api/documents/ask",
            json={"question": "What is the receipt number?", "client_name": "test_client"},
        )
        assert resp.status_code == 200

    def test_ask_response_has_answer(self, client):
        resp = client.post(
            "/api/documents/ask",
            json={"question": "What is the case status?", "client_name": "test_client"},
        )
        data = resp.json()
        assert "answer" in data
        assert len(data["answer"]) > 0

    def test_ask_response_has_confidence(self, client):
        resp = client.post(
            "/api/documents/ask",
            json={"question": "What form was filed?", "client_name": "test_client"},
        )
        data = resp.json()
        assert "confidence" in data
        assert 0.0 <= data["confidence"] <= 1.0

    def test_ask_response_has_sources(self, client):
        resp = client.post(
            "/api/documents/ask",
            json={"question": "What documents are there?", "client_name": "test_client"},
        )
        data = resp.json()
        assert "sources" in data
        assert isinstance(data["sources"], list)

    def test_ask_when_no_docs_returns_fallback_message(self, client):
        """When query returns empty results, endpoint returns a helpful message."""
        from unittest.mock import patch, MagicMock
        # Override vector store to return empty results for this test
        from app.main import app
        empty_vs = MagicMock()
        empty_vs.query.return_value = []
        app.state.vector_store = empty_vs

        resp = client.post(
            "/api/documents/ask",
            json={"question": "Anything?", "client_name": "no_docs_client"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        # Should contain a helpful message, not an error
        assert len(data["answer"]) > 0


# ─── Client document management ───────────────────────────────────────────────

class TestClientDocuments:

    def test_list_client_documents(self, client):
        resp = client.get("/api/documents/client/test_client")
        assert resp.status_code == 200
        data = resp.json()
        assert data["client_name"] == "test_client"
        assert isinstance(data["documents"], list)
        # Mock returns ["i797_notice.pdf", "i485_petition.pdf"]
        assert len(data["documents"]) == 2

    def test_delete_client_document(self, client):
        resp = client.delete("/api/documents/client/test_client/i797_notice.pdf")
        assert resp.status_code == 200
        data = resp.json()
        assert "chunks_deleted" in data
        assert data["chunks_deleted"] == 3  # matches mock return value

    def test_delete_nonexistent_document_returns_404(self, client):
        from unittest.mock import MagicMock
        from app.main import app
        # Override to return 0 deleted chunks (document not found)
        zero_vs = MagicMock()
        zero_vs.delete_document.return_value = 0
        app.state.vector_store = zero_vs

        resp = client.delete("/api/documents/client/ghost_client/missing.pdf")
        assert resp.status_code == 404

    def test_get_document_stats(self, client):
        resp = client.get("/api/documents/stats")
        assert resp.status_code == 200
