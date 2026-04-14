"""
Pydantic models for request/response schemas.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


# ─── Document Q&A Models ─────────────────────────────────────────────

class CaseType(str, Enum):
    H1B = "H-1B"
    I130 = "I-130"
    I140 = "I-140"
    I485 = "I-485"
    I765 = "I-765"
    N400 = "N-400"
    ASYLUM = "Asylum"
    OPT = "OPT"
    OTHER = "Other"


class DocumentType(str, Enum):
    PETITION = "petition"
    SUPPORT_LETTER = "support_letter"
    USCIS_NOTICE = "uscis_notice"
    RFE_RESPONSE = "rfe_response"
    APPROVAL_NOTICE = "approval_notice"
    RECEIPT_NOTICE = "receipt_notice"
    BIRTH_CERTIFICATE = "birth_certificate"
    MARRIAGE_CERTIFICATE = "marriage_certificate"
    ACADEMIC_RECORD = "academic_record"
    OTHER = "other"


class DocumentMetadata(BaseModel):
    """Metadata attached to each document chunk in the vector store."""
    client_name: Optional[str] = None
    case_type: Optional[CaseType] = None
    document_type: Optional[DocumentType] = None
    filing_date: Optional[str] = None
    receipt_number: Optional[str] = None
    source_filename: str
    page_number: int
    chunk_index: int


class DocumentUploadResponse(BaseModel):
    """Response after uploading and processing a document."""
    document_id: str
    filename: str
    pages_processed: int
    chunks_created: int
    extracted_metadata: DocumentMetadata
    message: str


class QuestionRequest(BaseModel):
    """Request for document Q&A."""
    question: str = Field(..., min_length=3, max_length=1000)
    client_name: Optional[str] = None
    case_type: Optional[CaseType] = None
    top_k: int = Field(default=5, ge=1, le=20)


class SourceChunk(BaseModel):
    """A retrieved source chunk with relevance score."""
    text: str
    score: float
    metadata: DocumentMetadata


class QuestionResponse(BaseModel):
    """Response from document Q&A."""
    answer: str
    sources: list[SourceChunk]
    confidence: float = Field(ge=0.0, le=1.0)
    disclaimer: str = (
        "This information is for general reference only. "
        "For official guidance, consult USCIS or an immigration attorney."
    )


# ─── Translation Models ──────────────────────────────────────────────

class SupportedLanguage(str, Enum):
    TURKISH = "tr"
    SPANISH = "es"
    CHINESE = "zh"
    ARABIC = "ar"
    ENGLISH = "en"


class TranslationRequest(BaseModel):
    """Request for text translation."""
    text: str = Field(..., min_length=1, max_length=50000)
    source_lang: SupportedLanguage
    target_lang: SupportedLanguage = SupportedLanguage.ENGLISH
    generate_certification: bool = Field(
        default=True,
        description="Generate USCIS-compliant certification statement",
    )


class TranslationResponse(BaseModel):
    """Response from translation service."""
    original_text: str
    translated_text: str
    source_lang: str
    target_lang: str
    model_used: str
    certification_statement: Optional[str] = None
    word_count: int
    processing_time_ms: float
    confidence: Optional[float] = None


class DocumentTranslationResponse(BaseModel):
    """Response from document (PDF) translation."""
    original_filename: str
    translated_pages: list[dict]
    total_pages: int
    certification_statement: Optional[str] = None
    processing_time_ms: float
    confidence: Optional[float] = None


# ─── Case Timeline Models ────────────────────────────────────────────

class TimelineEventType(str, Enum):
    FILING = "filing"
    RECEIPT = "receipt"
    BIOMETRICS = "biometrics"
    RFE_ISSUED = "rfe_issued"
    RFE_RESPONSE = "rfe_response"
    INTERVIEW = "interview"
    APPROVAL = "approval"
    DENIAL = "denial"
    TRANSFER = "transfer"
    OTHER = "other"


class TimelineEvent(BaseModel):
    """A single event in a case timeline."""
    event_type: TimelineEventType
    date: Optional[str] = None
    description: str
    receipt_number: Optional[str] = None
    form_type: Optional[str] = None
    source_document: Optional[str] = None


class CaseTimeline(BaseModel):
    """Complete case timeline for a client."""
    client_name: Optional[str] = None
    case_type: Optional[CaseType] = None
    receipt_number: Optional[str] = None
    events: list[TimelineEvent]
    extracted_from: list[str]
    last_updated: datetime = Field(default_factory=datetime.now)
