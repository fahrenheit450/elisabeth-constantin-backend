import json
import logging
import os
from typing import Dict, Iterable, Optional
import requests

logger = logging.getLogger(__name__)

DEEPL_API_KEY = os.getenv("DEEPL_API_KEY")
DEEPL_API_URL = "https://api-free.deepl.com/v2/translate"

def _translate_with_deepl(text: str, target_lang: str = "EN") -> Optional[str]:
    """
    Translate text using DeepL API.
    Returns the translated text or None on failure.
    """
    if not text or not DEEPL_API_KEY:
        return None
    
    try:
        response = requests.post(
            DEEPL_API_URL,
            data={
                "auth_key": DEEPL_API_KEY,
                "text": text,
                "target_lang": target_lang.upper(),
                "source_lang": "FR"
            },
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get("translations") and len(result["translations"]) > 0:
                return result["translations"][0]["text"]
        else:
            logger.error(f"DeepL API error: {response.status_code} - {response.text}")
    except Exception as exc:
        logger.error(f"DeepL translation failed: {exc}")
    
    return None


def _translate_payload(payload: Dict[str, str], target_language: str) -> Dict[str, str]:
    """
    Translate a dictionary of strings using DeepL API.
    Note: For manual translation workflow, this is kept for backward compatibility
    but won't auto-translate descriptions (handled by manual endpoint).
    """
    if not payload:
        return {}

    translated = {}
    target_lang_code = "EN" if target_language == "en" else target_language.upper()
    
    for key, value in payload.items():
        if not value or not isinstance(value, str):
            continue
        
        # Skip description and status fields - description is handled manually, status is an enum
        # Also skip `type` because artwork types are managed separately in the
        # artwork_types collection and should not be auto-translated here.
        if key in ["description", "status", "type"]:
            continue
            
        result = _translate_with_deepl(value, target_lang_code)
        if result:
            translated[key] = result
    
    return translated


def apply_dynamic_translations(
    document: dict,
    fields: Iterable[str],
    target_language: str,
    collection=None,
) -> dict:
    """
    Ensure the requested language exists for the given fields and update the database if needed.
    Returns a copy of the document with the translated values applied.
    """
    if not document or target_language == "fr":
        return dict(document) if document else document

    translations = document.get("translations", {})
    lang_translations = translations.get(target_language, {}) or {}
    fields_to_translate: Dict[str, str] = {}

    for field in fields:
        existing_value = lang_translations.get(field)
        source_value = document.get(field)
        if existing_value is None and source_value:
            fields_to_translate[field] = source_value

    if fields_to_translate:
        new_values = _translate_payload(fields_to_translate, target_language)
        if new_values:
            lang_translations.update(new_values)
            translations[target_language] = lang_translations
            if collection is not None and document.get("_id"):
                try:
                    collection.update_one(
                        {"_id": document["_id"]},
                        {"$set": {"translations": translations}},
                    )
                except Exception as exc:
                    logger.error("Failed to persist translations: %s", exc)

    updated_document = dict(document)
    for field in fields:
        translated_value = lang_translations.get(field)
        if translated_value:
            updated_document[field] = translated_value
    return updated_document
