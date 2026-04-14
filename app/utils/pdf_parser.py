"""
PDF Parsing Pipeline
====================
Extracts text from immigration PDFs, chunks them intelligently
by document section, and extracts metadata (receipt numbers, dates,
case types, form numbers).

Uses PyMuPDF (fitz) for fast, accurate PDF text extraction.
"""

import fitz  # PyMuPDF
import re
import hashlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
import logging

logger = logging.getLogger(__name__)


# ─── Immigration-specific regex patterns ──────────────────────────────

# USCIS receipt numbers: 3 letters + 10 digits (e.g., EAC2390012345)
RECEIPT_NUMBER_PATTERN = re.compile(
    r"\b([A-Z]{3}\d{10})\b"
)

# Common USCIS form numbers
FORM_NUMBER_PATTERN = re.compile(
    r"\b(I-\d{3}[A-Z]?|N-\d{3}|G-\d{3}|EAD)\b", re.IGNORECASE
)

# Date patterns (MM/DD/YYYY, Month DD, YYYY, YYYY-MM-DD)
DATE_PATTERNS = [
    re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b"),
    re.compile(
        r"\b((?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+\d{1,2},?\s+\d{4})\b"
    ),
    re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
]

# Case type indicators
CASE_TYPE_INDICATORS = {
    "H-1B": ["h-1b", "h1b", "specialty occupation", "labor condition"],
    "I-130": ["i-130", "petition for alien relative", "immediate relative"],
    "I-140": ["i-140", "immigrant petition", "employment-based"],
    "I-485": ["i-485", "adjustment of status", "permanent residence"],
    "I-765": ["i-765", "employment authorization", "ead", "work permit"],
    "N-400": ["n-400", "naturalization", "citizenship application"],
    "Asylum": ["asylum", "persecution", "refugee", "credible fear"],
    "OPT": ["opt", "optional practical training", "f-1 student"],
}


@dataclass
class ParsedPage:
    """Represents a single parsed page from a PDF."""
    page_number: int
    text: str
    word_count: int


@dataclass
class DocumentChunk:
    """A chunk of text ready for embedding."""
    text: str
    page_number: int
    chunk_index: int
    source_filename: str
    char_start: int
    char_end: int


@dataclass
class ExtractedMetadata:
    """Metadata extracted from document content."""
    receipt_numbers: list[str] = field(default_factory=list)
    form_numbers: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    detected_case_type: Optional[str] = None
    detected_document_type: Optional[str] = None


@dataclass
class ParsedDocument:
    """Complete parsed document with pages, chunks, and metadata."""
    document_id: str
    filename: str
    total_pages: int
    pages: list[ParsedPage]
    chunks: list[DocumentChunk]
    metadata: ExtractedMetadata
    full_text: str


class PDFParser:
    """
    Parses immigration PDFs with intelligent chunking and metadata extraction.
    
    Chunking strategy:
    - Split by paragraphs first (double newline boundaries)
    - Merge small paragraphs up to max_chunk_size
    - Never split mid-sentence if avoidable
    - Overlap between chunks for context continuity
    """

    def __init__(
        self,
        max_chunk_size: int = 800,
        chunk_overlap: int = 100,
        min_chunk_size: int = 50,
    ):
        self.max_chunk_size = max_chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size

    def parse_pdf(self, file_path: str | Path) -> ParsedDocument:
        """
        Parse a PDF file and return structured document with chunks.
        
        Args:
            file_path: Path to the PDF file.
            
        Returns:
            ParsedDocument with pages, chunks, and extracted metadata.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"PDF not found: {file_path}")

        logger.info(f"Parsing PDF: {file_path.name}")

        doc = fitz.open(str(file_path))
        pages: list[ParsedPage] = []
        full_text_parts: list[str] = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            raw_text = self._extract_page_text(page)
            clean_text = self._clean_text(raw_text)

            if clean_text.strip():
                pages.append(
                    ParsedPage(
                        page_number=page_num + 1,
                        text=clean_text,
                        word_count=len(clean_text.split()),
                    )
                )
                full_text_parts.append(clean_text)

        doc.close()

        full_text = "\n\n".join(full_text_parts)

        # Generate document ID from content hash
        doc_id = hashlib.sha256(
            f"{file_path.name}:{full_text[:500]}".encode()
        ).hexdigest()[:12]

        # Extract metadata from full text
        metadata = self._extract_metadata(full_text)

        # Create chunks
        chunks = self._create_chunks(pages, file_path.name)

        parsed = ParsedDocument(
            document_id=doc_id,
            filename=file_path.name,
            total_pages=len(pages),
            pages=pages,
            chunks=chunks,
            metadata=metadata,
            full_text=full_text,
        )

        logger.info(
            f"Parsed {file_path.name}: {len(pages)} pages, "
            f"{len(chunks)} chunks, "
            f"receipt numbers: {metadata.receipt_numbers}, "
            f"case type: {metadata.detected_case_type}"
        )

        return parsed

    def parse_pdf_bytes(self, pdf_bytes: bytes, filename: str) -> ParsedDocument:
        """Parse PDF from bytes (for file upload handling)."""
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages: list[ParsedPage] = []
        full_text_parts: list[str] = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            raw_text = self._extract_page_text(page)
            clean_text = self._clean_text(raw_text)

            if clean_text.strip():
                pages.append(
                    ParsedPage(
                        page_number=page_num + 1,
                        text=clean_text,
                        word_count=len(clean_text.split()),
                    )
                )
                full_text_parts.append(clean_text)

        doc.close()

        full_text = "\n\n".join(full_text_parts)
        doc_id = hashlib.sha256(
            f"{filename}:{full_text[:500]}".encode()
        ).hexdigest()[:12]

        metadata = self._extract_metadata(full_text)
        chunks = self._create_chunks(pages, filename)

        return ParsedDocument(
            document_id=doc_id,
            filename=filename,
            total_pages=len(pages),
            pages=pages,
            chunks=chunks,
            metadata=metadata,
            full_text=full_text,
        )

    def _extract_page_text(self, page) -> str:
        """
        Extract text from a PDF page using block-level sorting.
        
        Uses PyMuPDF's 'blocks' mode which groups text by visual blocks,
        then sorts by vertical position first, horizontal second.
        This preserves the left-to-right reading order for tabular
        documents (like Turkish nufus kayit ornegi) where the default
        'text' mode reads column-by-column.
        """
        blocks = page.get_text("blocks")
        # Each block: (x0, y0, x1, y1, text, block_no, block_type)
        # block_type: 0 = text, 1 = image
        text_blocks = [b for b in blocks if b[6] == 0]
        
        # Sort by vertical position (y0), then horizontal (x0)
        # Using a tolerance band for y-position to group items on the same line
        text_blocks.sort(key=lambda b: (round(b[1] / 8) * 8, b[0]))
        
        lines = []
        prev_y = None
        current_line_parts = []
        
        for block in text_blocks:
            y0 = round(block[1] / 8) * 8  # Snap to grid
            text = block[4].strip()
            if not text:
                continue
                
            if prev_y is not None and y0 != prev_y:
                # New line — flush current
                if current_line_parts:
                    lines.append(" | ".join(current_line_parts))
                current_line_parts = [text]
            else:
                current_line_parts.append(text)
            
            prev_y = y0
        
        if current_line_parts:
            lines.append(" | ".join(current_line_parts))
        
        return "\n".join(lines)

    def _clean_text(self, text: str) -> str:
        """Clean extracted text while preserving structure."""
        # Normalize whitespace but preserve paragraph breaks
        text = re.sub(r"[ \t]+", " ", text)
        # Normalize line breaks: collapse 3+ newlines to 2
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Remove leading/trailing whitespace per line
        lines = [line.strip() for line in text.split("\n")]
        text = "\n".join(lines)
        return text.strip()

    def _create_chunks(
        self, pages: list[ParsedPage], filename: str
    ) -> list[DocumentChunk]:
        """
        Create overlapping chunks from pages using paragraph-aware splitting.
        """
        chunks: list[DocumentChunk] = []
        chunk_index = 0

        for page in pages:
            # Split page into paragraphs
            paragraphs = re.split(r"\n\n+", page.text)
            paragraphs = [p.strip() for p in paragraphs if p.strip()]

            current_chunk = ""
            char_offset = 0

            for para in paragraphs:
                # If adding this paragraph exceeds max size, finalize current chunk
                if (
                    current_chunk
                    and len(current_chunk) + len(para) + 2 > self.max_chunk_size
                ):
                    if len(current_chunk) >= self.min_chunk_size:
                        chunks.append(
                            DocumentChunk(
                                text=current_chunk.strip(),
                                page_number=page.page_number,
                                chunk_index=chunk_index,
                                source_filename=filename,
                                char_start=char_offset,
                                char_end=char_offset + len(current_chunk),
                            )
                        )
                        chunk_index += 1

                    # Start new chunk with overlap from end of previous
                    overlap_text = current_chunk[-self.chunk_overlap :]
                    # Find sentence boundary in overlap
                    sentence_break = overlap_text.rfind(". ")
                    if sentence_break > 0:
                        overlap_text = overlap_text[sentence_break + 2 :]

                    char_offset += len(current_chunk) - len(overlap_text)
                    current_chunk = overlap_text + "\n\n" + para
                else:
                    if current_chunk:
                        current_chunk += "\n\n" + para
                    else:
                        current_chunk = para

            # Don't forget the last chunk on this page
            if current_chunk and len(current_chunk) >= self.min_chunk_size:
                chunks.append(
                    DocumentChunk(
                        text=current_chunk.strip(),
                        page_number=page.page_number,
                        chunk_index=chunk_index,
                        source_filename=filename,
                        char_start=char_offset,
                        char_end=char_offset + len(current_chunk),
                    )
                )
                chunk_index += 1

        return chunks

    def _extract_metadata(self, text: str) -> ExtractedMetadata:
        """Extract immigration-specific metadata from document text."""
        text_lower = text.lower()

        # Receipt numbers
        receipt_numbers = list(set(RECEIPT_NUMBER_PATTERN.findall(text)))

        # Form numbers
        form_numbers = list(
            set(m.upper() for m in FORM_NUMBER_PATTERN.findall(text))
        )

        # Dates
        dates: list[str] = []
        for pattern in DATE_PATTERNS:
            dates.extend(pattern.findall(text))
        dates = list(set(dates))[:10]  # Cap at 10 most relevant

        # Detect case type
        detected_case_type = None
        max_hits = 0
        for case_type, indicators in CASE_TYPE_INDICATORS.items():
            hits = sum(1 for ind in indicators if ind in text_lower)
            if hits > max_hits:
                max_hits = hits
                detected_case_type = case_type

        # Detect document type
        detected_doc_type = self._detect_document_type(text_lower)

        return ExtractedMetadata(
            receipt_numbers=receipt_numbers,
            form_numbers=form_numbers,
            dates=dates,
            detected_case_type=detected_case_type,
            detected_document_type=detected_doc_type,
        )

    def _detect_document_type(self, text_lower: str) -> Optional[str]:
        """Detect the type of immigration document."""
        # Order matters: check specific types BEFORE generic uscis_notice
        # so that "Department of Homeland Security" doesn't swallow everything
        type_indicators = {
            "rfe_response": [
                "request for evidence",
                "request for additional evidence",
                "rfe",
            ],
            "approval_notice": [
                "approval notice",
                "petition has been approved",
                "application has been approved",
            ],
            "receipt_notice": [
                "receipt notice",
                "we have received your",
                "case was received",
            ],
            "support_letter": [
                "to whom it may concern",
                "letter of support",
                "i am writing in support",
                "employment verification",
            ],
            "petition": [
                "petition for",
                "application for",
                "form i-",
            ],
            "birth_certificate": [
                "certificate of birth",
                "birth certificate",
                "born on",
                "date of birth",
            ],
            "marriage_certificate": [
                "certificate of marriage",
                "marriage certificate",
                "solemnized",
            ],
        }

        # First pass: look for types with 2+ indicator hits
        best_type = None
        best_hits = 0
        for doc_type, indicators in type_indicators.items():
            hits = sum(1 for ind in indicators if ind in text_lower)
            if hits >= 2 and hits > best_hits:
                best_hits = hits
                best_type = doc_type

        if best_type:
            return best_type

        # Second pass: high-specificity single indicators that are
        # strong enough to classify on their own
        high_specificity = {
            "receipt_notice": [
                "receipt notice", "we have received your",
                "case was received",
            ],
            "rfe_response": [
                "request for evidence",
                "request for additional evidence",
            ],
            "approval_notice": [
                "approval notice",
                "petition has been approved",
                "application has been approved",
            ],
        }
        for doc_type, indicators in high_specificity.items():
            if any(ind in text_lower for ind in indicators):
                return doc_type

        return "other"
