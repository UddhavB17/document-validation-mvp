"""Consistency-check submodule."""

from __future__ import annotations

from typing import Any

from services.language_detection import analyze_text_languages, normalize_language_code


def _application_language_checks(pages: list[dict], trusted: dict | None = None) -> list[dict]:
    """Verify that a digital application form contains a second language.

    Scanned application forms are excluded because OCR is not reliable enough
    for this checklist rule. Hindi is a valid second language.
    """
    anomalies: list[dict] = []
    app_pages = [
        page
        for page in pages
        if page.get("document_type") == "Application Form"
        and str(page.get("page_type") or "").strip().casefold() == "digital"
    ]
    if not app_pages:
        return anomalies

    configured_languages = _configured_application_languages(trusted or {})
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

        text = str(page.get("ocr_text") or "")
        scripts = set(analyze_text_languages(text)["scripts"])
        if "latin" in scripts and scripts.difference({"latin"}):
            return []

    all_scripts = {
        script
        for app_page in app_pages
        for script in analyze_text_languages(str(app_page.get("ocr_text") or ""))["scripts"]
    }
    if "latin" in all_scripts and all_scripts.difference({"latin"}):
        return []

    page = app_pages[0]
    anomalies.append(
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
    )
    return anomalies


def _is_second_application_language(value: Any) -> bool:
    """Return true for a recognized language other than English, including Hindi."""
    code = normalize_language_code(value)
    return bool(code and code != "en")


def _configured_application_languages(trusted: dict) -> list[Any]:
    """Read optional case/template language declarations from trusted input."""
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
