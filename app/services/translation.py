"""
Translation Service
===================
USCIS-compliant translation using Helsinki-NLP OPUS-MT models.

Supports: Turkish, Spanish, Chinese, Arabic ↔ English

Key features:
- Lazy-loads models on first use per language pair (saves RAM)
- Auto-generates USCIS certification statements
- Handles both text and document-level translation

OPUS-MT models are Apache 2.0 licensed — safe for commercial use.
"""

from transformers import MarianMTModel, MarianTokenizer
from typing import Optional
from datetime import datetime
import time
import logging

logger = logging.getLogger(__name__)


# Model mapping: (source_lang, target_lang) -> HuggingFace model ID
# Using the "big" variants where available for better quality
OPUS_MT_MODELS = {
    # To English
    ("tr", "en"): "Helsinki-NLP/opus-mt-tc-big-tr-en",
    ("es", "en"): "Helsinki-NLP/opus-mt-es-en",
    ("zh", "en"): "Helsinki-NLP/opus-mt-zh-en",
    ("ar", "en"): "Helsinki-NLP/opus-mt-ar-en",
    # From English
    ("en", "tr"): "Helsinki-NLP/opus-mt-tc-big-en-tr",
    ("en", "es"): "Helsinki-NLP/opus-mt-en-es",
    ("en", "zh"): "Helsinki-NLP/opus-mt-en-zh",
    ("en", "ar"): "Helsinki-NLP/opus-mt-en-ar",
}

LANGUAGE_NAMES = {
    "tr": "Turkish",
    "es": "Spanish",
    "zh": "Chinese",
    "ar": "Arabic",
    "en": "English",
}

# USCIS certification template per 8 CFR 103.2(b)(3)
USCIS_CERTIFICATION_TEMPLATE = """CERTIFICATION OF TRANSLATION

I, Immigration Assistant (AI-Assisted Translation Tool), hereby certify that:

1. The attached translation from {source_language} to {target_language} is complete and accurate to the best of my ability.

2. This translation was generated using the Helsinki-NLP OPUS-MT neural machine translation model and should be reviewed by a qualified human translator before submission to USCIS.

3. IMPORTANT NOTICE: Per 8 CFR 103.2(b)(3), USCIS requires that translations be certified by a translator who is competent to translate from the foreign language into English. This AI-generated translation is provided as a DRAFT for professional review. A qualified human translator must review, verify, and certify this translation before it is submitted to USCIS or any government agency.

Date: {date}
Document: {document_description}
Source Language: {source_language}
Target Language: {target_language}
Word Count (Original): {word_count}
Translation Model: {model_id}

---
REVIEWER SIGNATURE (Required for USCIS submission):

I, _________________________, certify that I am competent to translate from {source_language} to {target_language}, and that the above translation is complete and accurate.

Signature: _________________________
Printed Name: _________________________
Date: _________________________
Contact: _________________________
"""


class TranslationService:
    """
    Manages OPUS-MT translation models with lazy loading.
    """

    def __init__(self):
        # Cache loaded models: key = (src, tgt), value = (model, tokenizer)
        self._loaded_models: dict[tuple[str, str], tuple] = {}

    def _get_model(
        self, source_lang: str, target_lang: str
    ) -> tuple[MarianMTModel, MarianTokenizer]:
        """Load or retrieve cached model for a language pair."""
        pair = (source_lang, target_lang)

        if pair in self._loaded_models:
            return self._loaded_models[pair]

        model_id = OPUS_MT_MODELS.get(pair)
        if not model_id:
            raise ValueError(
                f"Unsupported language pair: {source_lang} → {target_lang}. "
                f"Supported pairs: {list(OPUS_MT_MODELS.keys())}"
            )

        logger.info(f"Loading translation model: {model_id}")
        tokenizer = MarianTokenizer.from_pretrained(model_id)
        model = MarianMTModel.from_pretrained(model_id)
        logger.info(f"✅ Loaded {model_id}")

        self._loaded_models[pair] = (model, tokenizer)
        return model, tokenizer

    def translate_text(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        generate_certification: bool = True,
    ) -> dict:
        """
        Translate text between supported language pairs.
        
        Args:
            text: Source text to translate.
            source_lang: ISO 639-1 source language code.
            target_lang: ISO 639-1 target language code.
            generate_certification: Include USCIS certification statement.
            
        Returns:
            Dict with translated text, metadata, and optional certification.
        """
        start_time = time.time()

        model, tokenizer = self._get_model(source_lang, target_lang)
        model_id = OPUS_MT_MODELS[(source_lang, target_lang)]

        # Split long text into sentence-level chunks for better quality
        # OPUS-MT works best with individual sentences or short paragraphs
        sentences = self._split_into_sentences(text)

        translated_parts = []
        for batch_start in range(0, len(sentences), 8):
            batch = sentences[batch_start : batch_start + 8]
            encoded = tokenizer(
                batch, return_tensors="pt", padding=True, truncation=True,
                max_length=512,
            )
            translated_tokens = model.generate(
                **encoded,
                max_length=512,
                num_beams=4,
                no_repeat_ngram_size=4,
                repetition_penalty=1.5,
                length_penalty=1.0,
            )
            decoded = tokenizer.batch_decode(
                translated_tokens, skip_special_tokens=True
            )
            translated_parts.extend(decoded)

        translated_text = " ".join(translated_parts)
        word_count = len(text.split())

        processing_time = (time.time() - start_time) * 1000

        result = {
            "original_text": text,
            "translated_text": translated_text,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "model_used": model_id,
            "word_count": word_count,
            "processing_time_ms": round(processing_time, 2),
            "certification_statement": None,
        }

        if generate_certification:
            result["certification_statement"] = self._generate_certification(
                source_lang=source_lang,
                target_lang=target_lang,
                word_count=word_count,
                model_id=model_id,
            )

        return result

    def translate_pages(
        self,
        pages: list[dict],
        source_lang: str,
        target_lang: str,
    ) -> list[dict]:
        """
        Translate multiple pages (from PDF extraction).
        
        Args:
            pages: List of dicts with 'page_number' and 'text' keys.
            source_lang: Source language code.
            target_lang: Target language code.
            
        Returns:
            List of dicts with original and translated text per page.
        """
        translated_pages = []
        for page in pages:
            result = self.translate_text(
                text=page["text"],
                source_lang=source_lang,
                target_lang=target_lang,
                generate_certification=False,
            )
            translated_pages.append(
                {
                    "page_number": page["page_number"],
                    "original_text": page["text"],
                    "translated_text": result["translated_text"],
                }
            )
        return translated_pages

    def get_supported_languages(self) -> dict:
        """Return supported language pairs and their model IDs."""
        return {
            f"{src}→{tgt}": model_id
            for (src, tgt), model_id in OPUS_MT_MODELS.items()
        }

    def get_loaded_models(self) -> list[str]:
        """Return list of currently loaded model IDs."""
        return [
            OPUS_MT_MODELS[pair]
            for pair in self._loaded_models
        ]

    def _split_into_sentences(self, text: str) -> list[str]:
        """
        Sentence splitting that handles Turkish legal documents.
        
        Avoids breaking on:
        - Dates like 18.03.2025
        - Numbered lists like 1-) or 2.)
        - Abbreviations like T.C., vb., vs.
        """
        import re

        # Protect dates (DD.MM.YYYY) from being split
        text = re.sub(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", r"\1<DOT>\2<DOT>\3", text)

        # Protect common Turkish abbreviations
        for abbr in ["T.C.", "vb.", "vs.", "vd.", "Dr.", "Prof.", "No.", "Md."]:
            text = text.replace(abbr, abbr.replace(".", "<DOT>"))

        # Protect numbered lists like 1-) 2-) or 1.) 2.)
        text = re.sub(r"(\d+)[\-\.]\)", r"\1<NUM>)", text)

        # Now split on actual sentence boundaries
        # Sentence ends with . ! ? followed by whitespace and uppercase or newline
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-ZÇĞİÖŞÜa-z0-9])", text)

        # Restore protected tokens
        restored = []
        for s in sentences:
            s = s.replace("<DOT>", ".").replace("<NUM>", "-")
            s = s.strip()
            if not s:
                continue
            restored.append(s)

        # Merge very short fragments
        result = []
        buffer = ""
        for s in restored:
            if len(s) < 20 and buffer:
                buffer += " " + s
            else:
                if buffer:
                    result.append(buffer)
                buffer = s
        if buffer:
            result.append(buffer)

        return result if result else [text.replace("<DOT>", ".").replace("<NUM>", "-")]

    def _generate_certification(
        self,
        source_lang: str,
        target_lang: str,
        word_count: int,
        model_id: str,
        document_description: str = "Immigration Document",
    ) -> str:
        """Generate USCIS-compliant certification statement."""
        return USCIS_CERTIFICATION_TEMPLATE.format(
            source_language=LANGUAGE_NAMES.get(source_lang, source_lang),
            target_language=LANGUAGE_NAMES.get(target_lang, target_lang),
            date=datetime.now().strftime("%B %d, %Y"),
            document_description=document_description,
            word_count=word_count,
            model_id=model_id,
        )
