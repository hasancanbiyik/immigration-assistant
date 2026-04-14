"""
Tests for Pydantic schemas and data models.

Validates enum values, default fields, and validation behaviour
without requiring any services or the FastAPI app.
"""

import pytest
from pydantic import ValidationError

from app.models.schemas import (
    CaseType,
    DocumentType,
    SupportedLanguage,
    TimelineEventType,
    TranslationRequest,
    QuestionRequest,
    TimelineEvent,
    CaseTimeline,
)


# ─── Enum validation ──────────────────────────────────────────────────────────

class TestCaseTypeEnum:

    def test_h1b_is_valid(self):
        assert CaseType("H-1B") == CaseType.H1B

    def test_i485_is_valid(self):
        assert CaseType("I-485") == CaseType.I485

    def test_asylum_is_valid(self):
        assert CaseType("Asylum") == CaseType.ASYLUM

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            CaseType("NOT_A_CASE")

    def test_all_expected_values_exist(self):
        expected = {"H-1B", "I-130", "I-140", "I-485", "I-765", "N-400", "Asylum", "OPT", "Other"}
        actual = {ct.value for ct in CaseType}
        assert expected.issubset(actual)


class TestDocumentTypeEnum:

    def test_receipt_notice_is_valid(self):
        assert DocumentType("receipt_notice") == DocumentType.RECEIPT_NOTICE

    def test_approval_notice_is_valid(self):
        assert DocumentType("approval_notice") == DocumentType.APPROVAL_NOTICE

    def test_rfe_response_is_valid(self):
        assert DocumentType("rfe_response") == DocumentType.RFE_RESPONSE

    def test_birth_certificate_is_valid(self):
        assert DocumentType("birth_certificate") == DocumentType.BIRTH_CERTIFICATE


class TestSupportedLanguageEnum:

    def test_turkish_is_supported(self):
        assert SupportedLanguage("tr") == SupportedLanguage.TURKISH

    def test_english_is_supported(self):
        assert SupportedLanguage("en") == SupportedLanguage.ENGLISH

    def test_spanish_is_supported(self):
        assert SupportedLanguage("es") == SupportedLanguage.SPANISH


class TestTimelineEventTypeEnum:

    def test_filing_is_valid(self):
        assert TimelineEventType("filing") == TimelineEventType.FILING

    def test_rfe_issued_is_valid(self):
        assert TimelineEventType("rfe_issued") == TimelineEventType.RFE_ISSUED

    def test_approval_is_valid(self):
        assert TimelineEventType("approval") == TimelineEventType.APPROVAL

    def test_all_expected_types_exist(self):
        expected = {"filing", "receipt", "biometrics", "rfe_issued", "rfe_response",
                    "interview", "approval", "denial", "transfer", "other"}
        actual = {t.value for t in TimelineEventType}
        assert expected.issubset(actual)


# ─── TranslationRequest ───────────────────────────────────────────────────────

class TestTranslationRequest:

    def test_valid_request(self):
        req = TranslationRequest(text="Belge içeriği.", source_lang="tr", target_lang="en")
        assert req.text == "Belge içeriği."
        assert req.source_lang == "tr"
        assert req.target_lang == "en"

    def test_certification_has_a_boolean_default(self):
        req = TranslationRequest(text="Test", source_lang="tr", target_lang="en")
        assert isinstance(req.generate_certification, bool)

    def test_certification_can_be_set_true(self):
        req = TranslationRequest(
            text="Test", source_lang="tr", target_lang="en",
            generate_certification=True,
        )
        assert req.generate_certification is True

    def test_missing_text_raises_validation_error(self):
        with pytest.raises(ValidationError):
            TranslationRequest(source_lang="tr", target_lang="en")  # no text


# ─── QuestionRequest ──────────────────────────────────────────────────────────

class TestQuestionRequest:

    def test_valid_question(self):
        req = QuestionRequest(question="What is the receipt number?")
        assert req.question == "What is the receipt number?"

    def test_top_k_default(self):
        req = QuestionRequest(question="Test?")
        assert req.top_k == 5  # default

    def test_top_k_can_be_set(self):
        req = QuestionRequest(question="Test?", top_k=3)
        assert req.top_k == 3

    def test_client_name_is_optional(self):
        req = QuestionRequest(question="Test?")
        assert req.client_name is None

    def test_missing_question_raises_validation_error(self):
        with pytest.raises(ValidationError):
            QuestionRequest()  # no question


# ─── TimelineEvent ────────────────────────────────────────────────────────────

class TestTimelineEvent:

    def test_valid_event(self):
        evt = TimelineEvent(
            event_type=TimelineEventType.FILING,
            description="Filed I-485 on March 15, 2024.",
        )
        assert evt.event_type == TimelineEventType.FILING

    def test_optional_fields_default_to_none(self):
        evt = TimelineEvent(
            event_type=TimelineEventType.RECEIPT,
            description="Receipt notice received.",
        )
        assert evt.date is None
        assert evt.receipt_number is None
        assert evt.form_type is None


# ─── CaseTimeline ─────────────────────────────────────────────────────────────

class TestCaseTimeline:

    def test_empty_timeline(self):
        tl = CaseTimeline(events=[], extracted_from=[])
        assert tl.events == []
        assert tl.client_name is None

    def test_timeline_with_events(self):
        evt = TimelineEvent(
            event_type=TimelineEventType.APPROVAL,
            description="Petition approved.",
        )
        tl = CaseTimeline(client_name="john_doe", events=[evt], extracted_from=["approval.pdf"])
        assert tl.client_name == "john_doe"
        assert len(tl.events) == 1
