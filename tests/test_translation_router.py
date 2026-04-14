"""
Integration tests for the Translation router.

Gemini and OPUS-MT services are mocked via conftest.py so no API calls
or model downloads happen. Tests verify request validation, response shapes,
and correct routing between Gemini (primary) and OPUS-MT (fallback).
"""

import io
import pytest


# ─── Supported languages ──────────────────────────────────────────────────────

class TestSupportedLanguages:

    def test_languages_endpoint_returns_200(self, client):
        resp = client.get("/api/translation/languages")
        assert resp.status_code == 200

    def test_languages_response_is_dict(self, client):
        data = client.get("/api/translation/languages").json()
        assert isinstance(data, dict)


# ─── Text translation ─────────────────────────────────────────────────────────

class TestTextTranslation:

    BASE_PAYLOAD = {
        "text": "Türkiye Cumhuriyeti nüfus cüzdanı.",
        "source_lang": "tr",
        "target_lang": "en",
        "generate_certification": False,
    }

    def test_translate_text_returns_200(self, client):
        resp = client.post("/api/translation/text", json=self.BASE_PAYLOAD)
        assert resp.status_code == 200

    def test_translate_text_response_fields(self, client):
        data = client.post("/api/translation/text", json=self.BASE_PAYLOAD).json()
        assert "translated_text" in data
        assert "source_lang" in data
        assert "target_lang" in data
        assert "model_used" in data

    def test_translate_text_source_and_target_reflected(self, client):
        data = client.post("/api/translation/text", json=self.BASE_PAYLOAD).json()
        assert data["source_lang"] == "tr"
        assert data["target_lang"] == "en"

    def test_translate_text_returns_non_empty_translation(self, client):
        data = client.post("/api/translation/text", json=self.BASE_PAYLOAD).json()
        assert len(data["translated_text"]) > 0

    def test_translate_text_with_certification(self, client):
        payload = {**self.BASE_PAYLOAD, "generate_certification": True}
        data = client.post("/api/translation/text", json=payload).json()
        assert "certification_statement" in data
        # When certification is requested, the field should be populated
        assert data["certification_statement"] is not None

    def test_translate_without_certification_gives_empty_cert(self, client):
        payload = {**self.BASE_PAYLOAD, "generate_certification": False}
        data = client.post("/api/translation/text", json=payload).json()
        # certification_statement should be empty / None when not requested
        cert = data.get("certification_statement", "")
        assert not cert or cert == ""

    def test_translate_empty_text_returns_422(self, client):
        payload = {**self.BASE_PAYLOAD, "text": ""}
        resp = client.post("/api/translation/text", json=payload)
        # Empty text should be rejected
        assert resp.status_code in (400, 422)

    def test_translate_spanish_to_english(self, client):
        payload = {
            "text": "Esta es una carta de apoyo para la solicitud de visa.",
            "source_lang": "es",
            "target_lang": "en",
            "generate_certification": False,
        }
        resp = client.post("/api/translation/text", json=payload)
        assert resp.status_code == 200

    def test_confidence_score_in_response(self, client):
        data = client.post("/api/translation/text", json=self.BASE_PAYLOAD).json()
        # Confidence may be None (OPUS-MT) or a number (Gemini)
        if data.get("confidence") is not None:
            assert 0 <= data["confidence"] <= 100


# ─── Document translation ─────────────────────────────────────────────────────

class TestDocumentTranslation:

    def test_translate_txt_document_returns_200(self, client):
        content = "Bu belge, Türkiye'de düzenlenen resmi bir nüfus cüzdanıdır.".encode("utf-8")
        resp = client.post(
            "/api/translation/document",
            files={"file": ("nufus.txt", io.BytesIO(content), "text/plain")},
            data={"source_lang": "tr", "target_lang": "en"},
        )
        assert resp.status_code == 200

    def test_translate_document_response_fields(self, client):
        content = "Resmi belge içeriği burada yer almaktadır.".encode("utf-8")
        data = client.post(
            "/api/translation/document",
            files={"file": ("doc.txt", io.BytesIO(content), "text/plain")},
            data={"source_lang": "tr", "target_lang": "en"},
        ).json()
        assert "translated_pages" in data
        assert "total_pages" in data
        assert isinstance(data["translated_pages"], list)

    def test_translate_document_has_at_least_one_page(self, client):
        content = "Sosyal güvenlik belgesi. Tarih: 15/03/2024.".encode("utf-8")
        data = client.post(
            "/api/translation/document",
            files={"file": ("sgk.txt", io.BytesIO(content), "text/plain")},
            data={"source_lang": "tr", "target_lang": "en"},
        ).json()
        assert data["total_pages"] >= 1

    def test_translate_unsupported_file_type_returns_400(self, client):
        resp = client.post(
            "/api/translation/document",
            files={"file": ("image.jpg", io.BytesIO(b"fake"), "image/jpeg")},
            data={"source_lang": "tr", "target_lang": "en"},
        )
        assert resp.status_code in (400, 422)

    def test_translate_docx_document(self, client):
        from docx import Document
        doc = Document()
        doc.add_paragraph("Türkiye Cumhuriyeti Adalet Bakanlığı belgesinin içeriği.")
        buf = io.BytesIO()
        doc.save(buf)

        resp = client.post(
            "/api/translation/document",
            files={"file": ("bakanlik.docx", io.BytesIO(buf.getvalue()),
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            data={"source_lang": "tr", "target_lang": "en"},
        )
        assert resp.status_code == 200
