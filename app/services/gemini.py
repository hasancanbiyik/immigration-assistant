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
            response = self.model.generate_content(prompt)
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
