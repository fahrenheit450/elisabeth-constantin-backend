import json
import logging
import os
from typing import Dict, Iterable, Optional
import requests

logger = logging.getLogger(__name__)


def _get_deepl_api_key() -> Optional[str]:
    return os.getenv("DEEPL_API_KEY") or os.getenv("DEEPL_AUTH_KEY")


def _build_deepl_translate_url() -> str:
    """Resolve DeepL translate URL.

    Priority:
    1) DEEPL_API_URL (full URL or base URL)
    2) DEEPL_PLAN in {free, pro}
    3) infer from key suffix ':fx' (free)
    """
    override = os.getenv("DEEPL_API_URL")
    if override:
        override = override.strip()
        if override.endswith("/v2/translate"):
            return override
        return override.rstrip("/") + "/v2/translate"

    plan = (os.getenv("DEEPL_PLAN") or "").strip().lower()
    if plan == "pro":
        return "https://api.deepl.com/v2/translate"
    if plan == "free":
        return "https://api-free.deepl.com/v2/translate"

    key = _get_deepl_api_key() or ""
    if key.endswith(":fx"):
        return "https://api-free.deepl.com/v2/translate"
    return "https://api.deepl.com/v2/translate"


def _alternate_deepl_translate_url(url: str) -> str:
    if "api-free.deepl.com" in url:
        return url.replace("api-free.deepl.com", "api.deepl.com")
    if "api.deepl.com" in url:
        return url.replace("api.deepl.com", "api-free.deepl.com")
    return url


def _suggested_deepl_translate_url_from_response(response_text: str) -> Optional[str]:
    """Extract the correct DeepL endpoint from DeepL's 'Wrong endpoint' message."""
    if not response_text:
        return None

    lower = response_text.lower()
    if "wrong endpoint" not in lower or "use https://" not in lower:
        return None

    if "use https://api-free.deepl.com" in lower:
        return "https://api-free.deepl.com/v2/translate"
    if "use https://api.deepl.com" in lower:
        return "https://api.deepl.com/v2/translate"

    return None

def _translate_with_deepl(text: str, target_lang: str = "EN") -> Optional[str]:
    """
    Translate text using DeepL API.
    Returns the translated text or None on failure.
    """
    api_key = _get_deepl_api_key()
    if not text:
        return None
    if not api_key:
        logger.warning("DeepL translation skipped: DEEPL_API_KEY is missing")
        return None
    
    try:
        url = _build_deepl_translate_url()

        def _attempt(post_url: str) -> requests.Response:
            return requests.post(
                post_url,
                data={
                    "auth_key": api_key,
                    "text": text,
                    "target_lang": target_lang.upper(),
                    "source_lang": "FR",
                },
                timeout=10,
            )

        response = _attempt(url)

        # DeepL sometimes returns a very explicit hint when the endpoint is wrong.
        # In that case, prefer the suggested endpoint even if DEEPL_API_URL was set.
        if response.status_code == 403:
            suggested = _suggested_deepl_translate_url_from_response(response.text)
            if suggested and suggested != url:
                logger.warning("DeepL suggests endpoint %s; retrying", suggested)
                response = _attempt(suggested)

        # Common misconfig: using a Pro key against the Free endpoint (or vice-versa).
        # If user didn't override the URL, try the alternate endpoint on 403.
        if (
            response.status_code == 403
            and not os.getenv("DEEPL_API_URL")
            and ("api-free.deepl.com" in url or "api.deepl.com" in url)
        ):
            alt = _alternate_deepl_translate_url(url)
            if alt != url:
                logger.warning("DeepL 403 on %s; retrying on %s", url, alt)
                response = _attempt(alt)

        if response.status_code == 200:
            result = response.json()
            if result.get("translations") and len(result["translations"]) > 0:
                return result["translations"][0]["text"]

        logger.error(
            "DeepL API error on %s: %s - %s",
            url,
            response.status_code,
            response.text[:500],
        )
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
