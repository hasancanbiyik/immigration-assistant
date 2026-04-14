"""
Tests for DocumentParser — the layer that routes .pdf / .txt / .docx files
to a shared ParsedDocument format before embedding.
"""

import io
import pytest

from app.utils.document_parser import (
    DocumentParser,
    is_supported_document,
    SUPPORTED_DOCUMENT_EXTENSIONS,
)


@pytest.fixture(scope="module")
def parser():
    return DocumentParser()


# ─── Extension detection ──────────────────────────────────────────────────────

class TestSupportedExtensions:

    def test_pdf_is_supported(self):
        assert is_supported_document("petition.pdf") is True

    def test_txt_is_supported(self):
        assert is_supported_document("notes.txt") is True

    def test_docx_is_supported(self):
        assert is_supported_document("application.docx") is True

    def test_jpg_is_not_supported(self):
        assert is_supported_document("scan.jpg") is False

    def test_doc_old_format_is_not_supported(self):
        assert is_supported_document("old_form.doc") is False

    def test_empty_filename_is_not_supported(self):
        assert is_supported_document("") is False

    def test_no_extension_is_not_supported(self):
        assert is_supported_document("noextension") is False

    def test_supported_extensions_constant(self):
        assert ".pdf" in SUPPORTED_DOCUMENT_EXTENSIONS
        assert ".txt" in SUPPORTED_DOCUMENT_EXTENSIONS
        assert ".docx" in SUPPORTED_DOCUMENT_EXTENSIONS


# ─── TXT parsing ──────────────────────────────────────────────────────────────

class TestTxtParsing:

    def test_basic_text_produces_one_page(self, parser):
        text = b"This is a simple immigration petition.\n\nFiled under I-485."
        result = parser.parse_document(text, "petition.txt")
        assert result.total_pages == 1

    def test_text_content_preserved(self, parser):
        content = "This petition concerns an H-1B specialty occupation visa application."
        result = parser.parse_document(content.encode(), "h1b.txt")
        assert "H-1B" in result.full_text

    def test_immigration_keywords_trigger_case_type(self, parser):
        text = b"This is a petition for H-1B specialty occupation. Labor condition filed."
        result = parser.parse_document(text, "h1b.txt")
        assert result.metadata.detected_case_type == "H-1B"

    def test_receipt_number_extracted_from_txt(self, parser):
        text = b"Receipt Number: EAC2390012345\nYour case has been received."
        result = parser.parse_document(text, "receipt.txt")
        assert "EAC2390012345" in result.metadata.receipt_numbers

    def test_empty_text_produces_no_pages(self, parser):
        result = parser.parse_document(b"   \n\n   ", "empty.txt")
        assert result.total_pages == 0
        assert len(result.chunks) == 0

    def test_utf8_characters_decoded(self, parser):
        text = "Türkiye Cumhuriyeti nüfus cüzdanı belgesi.".encode("utf-8")
        result = parser.parse_document(text, "turkish_doc.txt")
        assert result.total_pages == 1

    def test_chunks_created_from_long_text(self, parser):
        # Enough paragraphs to force at least 2 chunks
        paragraphs = "\n\n".join(
            [f"Paragraph {i}: " + "This is supporting evidence for the petition. " * 8
             for i in range(10)]
        )
        result = parser.parse_document(paragraphs.encode(), "long_doc.txt")
        assert len(result.chunks) >= 2


# ─── DOCX parsing ─────────────────────────────────────────────────────────────

class TestDocxParsing:

    def _make_docx_bytes(self, paragraphs: list[str]) -> bytes:
        """Build a minimal in-memory .docx with the given paragraphs."""
        from docx import Document
        doc = Document()
        for para in paragraphs:
            doc.add_paragraph(para)
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()

    def test_docx_paragraphs_extracted(self, parser):
        content = ["This is paragraph one.", "This is paragraph two about I-485."]
        docx_bytes = self._make_docx_bytes(content)
        result = parser.parse_document(docx_bytes, "test.docx")
        assert result.total_pages == 1
        assert "paragraph one" in result.full_text

    def test_docx_with_receipt_number(self, parser):
        content = [
            "U.S. Citizenship and Immigration Services",
            "Receipt Number: MSC2190067890",
            "We have received your application.",
        ]
        docx_bytes = self._make_docx_bytes(content)
        result = parser.parse_document(docx_bytes, "receipt_notice.docx")
        assert "MSC2190067890" in result.metadata.receipt_numbers

    def test_docx_approval_notice_detected(self, parser):
        content = [
            "Department of Homeland Security",
            "Approval Notice",
            "Your petition has been approved.",
        ]
        docx_bytes = self._make_docx_bytes(content)
        result = parser.parse_document(docx_bytes, "approval.docx")
        assert result.metadata.detected_document_type == "approval_notice"


# ─── Unsupported formats ──────────────────────────────────────────────────────

class TestUnsupportedFormats:

    def test_unsupported_extension_raises_value_error(self, parser):
        with pytest.raises(ValueError, match="Unsupported file type"):
            parser.parse_document(b"some bytes", "image.jpg")

    def test_xls_raises_value_error(self, parser):
        with pytest.raises(ValueError):
            parser.parse_document(b"data", "spreadsheet.xls")
