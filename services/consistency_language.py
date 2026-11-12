"""Language/script checks for digital application-form evidence."""

from __future__ import annotations

from typing import Any

from services.language_detection import analyze_text_languages, normalize_language_code


def application_language_checks(pages: list[dict], trusted: dict | None = None) -> list[dict]:
    """Require a second script/language on digital application forms."""
    app_pages = [
        page
        for page in pages
        if page.get("document_type") == "Application Form"
        and str(page.get("page_type") or "").strip().casefold() == "digital"
    ]
    if not app_pages:
        return []

    configured_languages = _configured_application_languages(trusted or {})
    language_profiles = {
        id(page): analyze_text_languages(str(page.get("ocr_text") or "")) for page in app_pages
    }
    for page in app_pages:
        fields = page.get("extracted_fields") or {}
        declared_language = fields.get("second_language")
        if _is_second_application_language(declared_language):
            return []
        if any(_is_second_application_language(value) for value in configured_languages):
            return []
        language_metadata = (
            fields.get("_language") if isinstance(fields.get("_language"), dict) else {}
        )
        provider_languages = language_metadata.get("provider_languages") or []
        if any(_is_second_application_language(value) for value in provider_languages):
            return []
        scripts = set(language_profiles[id(page)]["scripts"])
        if "latin" in scripts and scripts.difference({"latin"}):
            return []

    all_scripts = {
        script for page in app_pages for script in language_profiles[id(page)]["scripts"]
    }
    if "latin" in all_scripts and all_scripts.difference({"latin"}):
        return []

    page = app_pages[0]
    return [
        {
            "rule_id": "APPLICATION_SECOND_LANGUAGE_MISSING",
            "s_no": 10,
            "severity": "MEDIUM",
            "document_type": "Application Form",
            "expected_value": "Second language (Hindi accepted)",
            "found_value": "Not found",
            "page_number": page.get("page_number"),
            "person_id": None,
            "reason": "Verify that the digital application form includes a second language; Hindi is accepted.",
        }
    ]


def _is_second_application_language(value: Any) -> bool:
    code = normalize_language_code(value)
    return bool(code and code != "en")


def _configured_application_languages(trusted: dict) -> list[Any]:
    values: list[Any] = []
    for key in ("application_form_languages", "required_application_languages"):
        value = trusted.get(key)
        if isinstance(value, list):
            values.extend(value)
        elif value not in (None, ""):
            values.append(value)
    document_languages = trusted.get("document_languages")
    if isinstance(document_languages, dict):
        value = document_languages.get("Application Form") or document_languages.get(
            "application_form"
        )
        if isinstance(value, list):
            values.extend(value)
        elif value not in (None, ""):
            values.append(value)
    return values
