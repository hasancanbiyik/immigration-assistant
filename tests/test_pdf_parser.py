"""
Tests for the PDF parsing pipeline.
"""

import pytest
from app.utils.pdf_parser import PDFParser, RECEIPT_NUMBER_PATTERN, FORM_NUMBER_PATTERN


@pytest.fixture
def parser():
    return PDFParser(max_chunk_size=500, chunk_overlap=50)


class TestMetadataExtraction:
    """Test immigration-specific metadata extraction."""

    def test_receipt_number_pattern(self):
        """USCIS receipt numbers: 3 letters + 10 digits."""
        text = "Your receipt number is EAC2390012345."
        matches = RECEIPT_NUMBER_PATTERN.findall(text)
        assert matches == ["EAC2390012345"]

    def test_multiple_receipt_numbers(self):
        text = "Cases EAC2390012345 and MSC2190067890 are pending."
        matches = RECEIPT_NUMBER_PATTERN.findall(text)
        assert set(matches) == {"EAC2390012345", "MSC2190067890"}

    def test_form_number_pattern(self):
        """Common USCIS form numbers."""
        text = "Please file Form I-485 and I-765 together."
        matches = FORM_NUMBER_PATTERN.findall(text)
        assert "I-485" in [m.upper() for m in matches]
        assert "I-765" in [m.upper() for m in matches]

    def test_case_type_detection(self, parser):
        text = (
            "This is a petition for H-1B specialty occupation visa. "
            "The labor condition application has been filed."
        )
        metadata = parser._extract_metadata(text)
        assert metadata.detected_case_type == "H-1B"

    def test_document_type_detection(self, parser):
        text = (
            "Department of Homeland Security\n"
            "U.S. Citizenship and Immigration Services\n"
            "Receipt Number: EAC2390012345\n"
            "Notice Date: January 15, 2025\n"
            "We have received your case."
        )
        metadata = parser._extract_metadata(text)
        assert metadata.detected_document_type == "receipt_notice"
        assert "EAC2390012345" in metadata.receipt_numbers

    def test_approval_notice_detection(self, parser):
        text = (
            "Department of Homeland Security\n"
            "U.S. Citizenship and Immigration Services\n"
            "Approval Notice\n"
            "Your petition has been approved."
        )
        metadata = parser._extract_metadata(text)
        assert metadata.detected_document_type == "approval_notice"

    def test_rfe_detection(self, parser):
        text = (
            "Department of Homeland Security\n"
            "U.S. Citizenship and Immigration Services\n"
            "Request for Evidence\n"
            "We need additional evidence to process your case."
        )
        metadata = parser._extract_metadata(text)
        assert metadata.detected_document_type == "rfe_response"


class TestChunking:
    """Test document chunking logic."""

    def test_basic_chunking(self, parser):
        from app.utils.pdf_parser import ParsedPage

        pages = [
            ParsedPage(
                page_number=1,
                text="First paragraph about H-1B visa.\n\nSecond paragraph about employment.",
                word_count=10,
            )
        ]
        chunks = parser._create_chunks(pages, "test.pdf")
        assert len(chunks) >= 1
        assert chunks[0].source_filename == "test.pdf"
        assert chunks[0].page_number == 1

    def test_long_text_creates_multiple_chunks(self, parser):
        from app.utils.pdf_parser import ParsedPage

        long_text = "\n\n".join(
            [f"This is paragraph {i} with enough text to fill a chunk. " * 5
             for i in range(20)]
        )
        pages = [
            ParsedPage(page_number=1, text=long_text, word_count=500)
        ]
        chunks = parser._create_chunks(pages, "test.pdf")
        assert len(chunks) > 1

    def test_minimum_chunk_size_filter(self, parser):
        from app.utils.pdf_parser import ParsedPage

        pages = [
            ParsedPage(page_number=1, text="Too short.", word_count=2)
        ]
        chunks = parser._create_chunks(pages, "test.pdf")
        assert len(chunks) == 0  # Below min_chunk_size


class TestTextCleaning:
    """Test text cleaning utilities."""

    def test_whitespace_normalization(self, parser):
        text = "Too   many     spaces   here"
        cleaned = parser._clean_text(text)
        assert "   " not in cleaned

    def test_preserves_paragraph_breaks(self, parser):
        text = "First paragraph.\n\nSecond paragraph."
        cleaned = parser._clean_text(text)
        assert "\n\n" in cleaned

    def test_collapses_excessive_newlines(self, parser):
        text = "First.\n\n\n\n\nSecond."
        cleaned = parser._clean_text(text)
        assert "\n\n\n" not in cleaned
