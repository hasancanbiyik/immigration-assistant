"""
Gemini LLM Service
==================
Handles RAG-based question answering using Google's Gemini API (free tier).

The API key is loaded from the GEMINI_API_KEY environment variable.
Never hardcode API keys.
"""

import os
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Will be lazily imported to avoid startup failures if not installed
_genai = None


def _get_genai():
    """Lazy import google.generativeai."""
    global _genai
    if _genai is None:
        try:
            import google.generativeai as genai
            _genai = genai
        except ImportError:
            raise ImportError(
                "google-generativeai is required for Gemini integration. "
                "Install it with: pip install google-generativeai"
            )
    return _genai


def _extract_json_array(raw: str) -> Optional[list]:
    """
    Pull the first balanced top-level JSON array out of a string.

    Walks the text from the first '[' and matches brackets while
    correctly skipping over '[' / ']' that appear inside JSON strings
    (including escaped quotes). Returns the parsed list, or None if
    no valid array is found.
    """
    start = raw.find("[")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(raw[start : i + 1])
                    return parsed if isinstance(parsed, list) else None
                except json.JSONDecodeError:
                    return None
    return None


# System prompt for immigration law Q&A
_LANGUAGE_NAMES = {
    "tr": "Turkish", "es": "Spanish", "zh": "Chinese",
    "ar": "Arabic", "en": "English",
}

TRANSLATION_PROMPT_TEMPLATE = """You are a certified legal translator specializing in immigration documents for USCIS submissions.

Translate the following {source_language} text to {target_language}.

REQUIREMENTS:
- Preserve all proper names, dates, case numbers, receipt numbers, and legal terminology exactly as written
- Maintain the document's structure and paragraph breaks
- Use formal, professional language appropriate for US immigration submissions
- For ambiguous legal terms, choose the more conservative/formal translation
- Do NOT add commentary, explanations, or notes inside the translation itself

After the complete translation, on a new line write EXACTLY:
CONFIDENCE: [0-100]

Where the confidence score reflects how accurately the legal/technical content was translated (consider term clarity, specialized vocabulary, and any ambiguous passages).

TEXT TO TRANSLATE:
{text}"""

IMMIGRATION_QA_SYSTEM_PROMPT = """You are an immigration law research assistant built for law firms and paralegals. Your role is to answer questions about immigration cases based ONLY on the provided document excerpts.

CRITICAL RULES:
1. ONLY use information from the provided document excerpts to answer questions.
2. If the documents don't contain enough information to answer, say so clearly.
3. Always cite which source document and page number your answer comes from.
4. Include a disclaimer that this is for informational purposes only and not legal advice.
5. Use clear, professional language appropriate for a legal setting.
6. If you detect dates, receipt numbers, or case milestones, highlight them.
7. Never fabricate information. If uncertain, say "Based on the available documents, I cannot confirm..."

RESPONSE FORMAT:
- Lead with a direct answer to the question
- Support with specific references to the source documents
- Note any gaps in the available information
- End with relevant follow-up suggestions if applicable
"""


class GeminiService:
    """
    Gemini API integration for RAG-based Q&A.
    Uses Gemini 2.0 Flash (free tier: 15 RPM, 1M TPM).
    """

    def __init__(self):
        self.model = None
        self._initialized = False

    def initialize(self):
        """Initialize the Gemini client with API key from environment."""
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            logger.warning(
                "GEMINI_API_KEY not set. Q&A will use fallback mode "
                "(returns retrieved chunks without LLM reasoning)."
            )
            return

        genai = _get_genai()
        genai.configure(api_key=api_key)

        self.model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=IMMIGRATION_QA_SYSTEM_PROMPT,
            generation_config={
                "temperature": 0.3,
                "top_p": 0.8,
                "max_output_tokens": 1500,
            },
        )

        self._initialized = True
        logger.info("✅ Gemini service initialized (gemini-2.5-flash)")

    @property
    def is_available(self) -> bool:
        return self._initialized and self.model is not None

    async def generate_answer(
        self,
        question: str,
        retrieved_chunks: list[dict],
        client_name: Optional[str] = None,
        case_type: Optional[str] = None,
    ) -> dict:
        """
        Generate an answer using retrieved document chunks as context.

        Args:
            question: The user's question.
            retrieved_chunks: List of dicts with 'text', 'score', 'metadata'.
            client_name: Optional client name for context.
            case_type: Optional case type filter.

        Returns:
            Dict with 'answer', 'confidence', and 'model_used'.
        """
        if not self.is_available:
            return self._fallback_answer(question, retrieved_chunks)

        # Build context from retrieved chunks
        context_parts = []
        for i, chunk in enumerate(retrieved_chunks):
            meta = chunk.get("metadata", {})
            source = meta.get("source_filename", "unknown")
            page = meta.get("page_number", "?")
            score = chunk.get("score", 0)
            context_parts.append(
                f"[Source {i+1}: {source}, Page {page}, "
                f"Relevance: {score:.2f}]\n{chunk['text']}"
            )

        context = "\n\n---\n\n".join(context_parts)

        # Build the prompt
        prompt_parts = [f"QUESTION: {question}\n"]
        if client_name:
            prompt_parts.append(f"CLIENT: {client_name}")
        if case_type:
            prompt_parts.append(f"CASE TYPE: {case_type}")
        prompt_parts.append(
            f"\nDOCUMENT EXCERPTS:\n{context}\n\n"
            f"Please answer the question based on the document excerpts above."
        )

        prompt = "\n".join(prompt_parts)

        try:
            response = self.model.generate_content(prompt)
            answer = response.text

            # Calculate confidence from retrieval scores
            avg_score = (
                sum(c.get("score", 0) for c in retrieved_chunks)
                / len(retrieved_chunks)
                if retrieved_chunks
                else 0
            )

            return {
                "answer": answer,
                "confidence": round(min(avg_score + 0.1, 1.0), 2),
                "model_used": "gemini-2.5-flash",
            }

        except Exception as e:
            import traceback
            logger.error(f"Gemini API error: {type(e).__name__}: {e}")
            logger.error(traceback.format_exc())
            # Surface the actual error so we can debug
            fallback = self._fallback_answer(question, retrieved_chunks)
            fallback["answer"] = (
                f"⚠️ Gemini API error: {type(e).__name__}: {str(e)[:200]}\n\n"
                f"Falling back to document excerpts:\n\n{fallback['answer']}"
            )
            return fallback

    async def translate_text(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> Optional[dict]:
        """
        Translate text using Gemini with confidence scoring.

        Returns a dict with 'translated_text', 'confidence', and 'model_used',
        or None if Gemini is unavailable (caller should fall back to OPUS-MT).

        Uses a dedicated GenerativeModel instance with NO system prompt and a
        much larger output token limit. The shared `self.model` is configured
        for Q&A (system_instruction = IMMIGRATION_QA_SYSTEM_PROMPT, max_output_tokens=1500),
        which both conflicts with translation intent and truncates non-trivial
        legal documents mid-sentence. Mirrors the pattern used by
        extract_text_from_document and extract_rfe_issues.
        """
        if not self.is_available:
            return None

        source_name = _LANGUAGE_NAMES.get(source_lang, source_lang)
        target_name = _LANGUAGE_NAMES.get(target_lang, target_lang)

        prompt = TRANSLATION_PROMPT_TEMPLATE.format(
            source_language=source_name,
            target_language=target_name,
            text=text,
        )

        try:
            genai = _get_genai()
            translation_model = genai.GenerativeModel(
                model_name="gemini-2.5-flash",
                # No system_instruction — the translation prompt already
                # carries the "you are a certified legal translator" framing.
                # Mixing in the QA system prompt makes Gemini hedge and cite.
                generation_config={
                    "temperature": 0.2,
                    "top_p": 0.9,
                    # 8192 is the Gemini 2.5 Flash output ceiling. The 1500-token
                    # cap on the shared QA model was the primary cause of the
                    # "translation cuts off mid-sentence" bug for longer inputs.
                    "max_output_tokens": 8192,
                },
            )
            response = translation_model.generate_content(prompt)

            # Defensive: Gemini can return an empty response if blocked by a
            # safety filter or if the candidate has no content. response.text
            # raises ValueError in that case. Surface a clean failure so the
            # caller can fall back to OPUS-MT instead of crashing.
            if not response.candidates or not response.candidates[0].content.parts:
                finish_reason = (
                    response.candidates[0].finish_reason
                    if response.candidates else "no_candidates"
                )
                logger.warning(
                    f"Gemini translation returned empty response (finish_reason={finish_reason}). "
                    f"Falling back to OPUS-MT."
                )
                return None

            raw = response.text.strip()

            # Parse confidence score from the last line
            confidence = 0.80  # sensible default
            lines = raw.splitlines()
            translation_lines = []
            confidence_found = False

            for line in reversed(lines):
                stripped = line.strip()
                if not confidence_found and stripped.upper().startswith("CONFIDENCE:"):
                    try:
                        conf_val = stripped.split(":", 1)[1].strip().rstrip("%")
                        confidence = int(conf_val) / 100.0
                        confidence_found = True
                    except (ValueError, IndexError):
                        pass
                else:
                    translation_lines.insert(0, line)

            translation = "\n".join(translation_lines).strip()
            if not translation:
                translation = raw  # fallback if parsing fails

            return {
                "translated_text": translation,
                "confidence": round(min(max(confidence, 0.0), 1.0), 2),
                "model_used": "gemini-2.5-flash",
            }

        except Exception as e:
            logger.error(f"Gemini translation error: {e}")
            return None  # Caller falls back to OPUS-MT

    async def extract_text_from_document(
        self,
        file_bytes: bytes,
        filename: str,
    ) -> Optional[str]:
        """
        Use Gemini's vision to OCR a scanned / image-based PDF.

        Called automatically by the document upload endpoint when extracted
        text is suspiciously sparse (< 150 chars/page on average), which
        reliably indicates a scanned document rather than a text-based one.

        Returns the full extracted text, or None if Gemini is unavailable or fails.
        """
        if not self.is_available:
            return None

        # Only PDFs need OCR — TXT/DOCX already yield usable text
        if not filename.lower().endswith(".pdf"):
            return None

        import base64

        ocr_prompt = (
            "Extract ALL text from this document exactly as it appears on the page. "
            "Preserve paragraph breaks, dates, numbers, names, addresses, "
            "case numbers, receipt numbers, and all legal terminology precisely. "
            "Do not summarize, interpret, add commentary, or skip any text. "
            "Return only the raw extracted text — nothing else."
        )

        try:
            genai = _get_genai()
            ocr_model = genai.GenerativeModel(
                model_name="gemini-2.5-flash",
                generation_config={
                    "temperature": 0.0,       # deterministic OCR
                    "max_output_tokens": 8192,
                },
            )
            content = [
                {
                    "inline_data": {
                        "mime_type": "application/pdf",
                        "data": base64.b64encode(file_bytes).decode("utf-8"),
                    }
                },
                ocr_prompt,
            ]
            response = ocr_model.generate_content(content)
            extracted = response.text.strip()
            return extracted if extracted else None

        except Exception as e:
            logger.error(f"Gemini OCR error for '{filename}': {type(e).__name__}: {e}")
            return None

    async def extract_rfe_issues(
        self,
        file_bytes: bytes,
        filename: str,
        text_fallback: str = "",
    ) -> list[str]:
        """
        Extract specific RFE issues from a document using Gemini's vision.

        For PDFs (including scanned/image-only ones), the raw bytes are sent
        directly as inline multimodal data — Gemini can read pages it can "see",
        not just pages with extractable text.

        For TXT / DOCX (no binary vision needed), the pre-extracted text is
        sent as plain text in the prompt.

        Returns a list of issue strings, or [] if Gemini is unavailable / fails.
        """
        if not self.is_available:
            return []

        import base64

        # ── Determine how to send the document ───────────────────────
        fname_lower = filename.lower()
        if fname_lower.endswith(".pdf"):
            mime_type = "application/pdf"
        elif fname_lower.endswith(".png"):
            mime_type = "image/png"
        elif fname_lower.endswith((".jpg", ".jpeg")):
            mime_type = "image/jpeg"
        else:
            mime_type = None  # TXT / DOCX — use extracted text instead

        extraction_prompt = (
            "You are analyzing a USCIS Request for Evidence (RFE) notice issued to an immigration attorney.\n\n"
            "Your task: extract ALL specific issues and evidence requests raised in this RFE.\n\n"
            "Return ONLY a valid JSON array of strings. Each string should be one concise, "
            "specific, and actionable issue or evidence item (1–2 sentences max).\n\n"
            "Good example output:\n"
            '["Provide evidence that the proffered position qualifies as a specialty occupation", '
            '"Submit a NACES-approved credential evaluation confirming the beneficiary\'s degree", '
            '"Include a detailed employer support letter on company letterhead listing specific job duties", '
            '"Provide the LCA certified by the Department of Labor"]\n\n'
            "Rules:\n"
            "- Be specific and actionable — the attorney must know exactly what to gather\n"
            "- Only include concrete evidence/documentation requests, not general commentary\n"
            "- If no specific RFE issues can be identified, return an empty array: []\n\n"
            "JSON array:"
        )

        try:
            # Build a lightweight extraction model (no immigration QA system prompt)
            genai = _get_genai()
            extraction_model = genai.GenerativeModel(
                model_name="gemini-2.5-flash",
                generation_config={
                    "temperature": 0.1,   # low temp for structured extraction
                    "max_output_tokens": 1000,
                },
            )

            if mime_type:
                # Multimodal: send raw bytes — works for scanned/image PDFs
                content = [
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": base64.b64encode(file_bytes).decode("utf-8"),
                        }
                    },
                    extraction_prompt,
                ]
            else:
                # Text-only fallback for TXT / DOCX
                text_snippet = text_fallback[:8000]
                content = f"{extraction_prompt}\n\nDOCUMENT TEXT:\n{text_snippet}"

            response = extraction_model.generate_content(content)
            raw = response.text.strip()

            # Extract the JSON array from the response. Gemini sometimes wraps
            # it in markdown fences or adds prose. We can't use a non-greedy
            # regex because issue strings may contain "]" — instead we walk
            # the string and balance brackets, ignoring brackets inside strings.
            parsed = _extract_json_array(raw)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]

            logger.warning(f"Gemini RFE extraction: unexpected response format — {raw[:200]}")
            return []

        except Exception as e:
            logger.error(f"Gemini RFE extraction error: {type(e).__name__}: {e}")
            return []

    def _fallback_answer(
        self, question: str, retrieved_chunks: list[dict]
    ) -> dict:
        """
        Fallback when Gemini is unavailable — returns structured
        chunk summaries without LLM reasoning.
        """
        if not retrieved_chunks:
            return {
                "answer": (
                    "I couldn't find any relevant information in the uploaded "
                    "documents. Please upload the relevant case files or "
                    "rephrase your question."
                ),
                "confidence": 0.0,
                "model_used": "fallback (no LLM)",
            }

        parts = ["Based on the uploaded documents:\n"]
        for i, chunk in enumerate(retrieved_chunks[:3]):
            meta = chunk.get("metadata", {})
            source = meta.get("source_filename", "unknown")
            page = meta.get("page_number", "?")
            text = chunk["text"][:400]
            parts.append(f"**Source: {source}, Page {page}**\n{text}\n")

        parts.append(
            "\n---\n*Note: Full AI-powered reasoning requires the Gemini "
            "API key to be configured. Set the GEMINI_API_KEY environment "
            "variable to enable enhanced answers.*"
        )

        avg_score = (
            sum(c.get("score", 0) for c in retrieved_chunks)
            / len(retrieved_chunks)
            if retrieved_chunks
            else 0
        )

        return {
            "answer": "\n".join(parts),
            "confidence": round(avg_score, 2),
            "model_used": "fallback (no LLM)",
        }
