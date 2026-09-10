"""English/Hindi operations templates for the nine finding codes.

Owned by ``ws-f-accuracy-ops-api``. Every user-facing string in
``GET /ops/applications/{id}`` comes from these templates — no rule IDs,
no OCR text, no internal stage names.
"""

from __future__ import annotations

# Priority order follows contracts §11.
CODE_ORDER: list[str] = [
    "NAME_MISMATCH",
    "ID_MISMATCH",
    "ADDRESS_MISMATCH",
    "MISSING_DOCUMENT",
    "BANK_STATEMENT_OLD",
    "PAGE_UNREADABLE",
    "OCR_FAILED",
    "DATA_MISSING",
    "PROCESSING_ERROR",
    "REVIEW_REQUIRED",
]

SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

# Placeholders: {expected}, {found}, {document}, {pages}, {months}.
TEMPLATES: dict[str, dict[str, dict[str, str]]] = {
    "REVIEW_REQUIRED": {
        "title": {"en": "Additional evidence needs review", "hi": "अतिरिक्त प्रमाण की जाँच आवश्यक है"},
        "detail": {"en": "Check the highlighted pages for unresolved document or field checks ({pages}).",
                   "hi": "दस्तावेज़ या जानकारी की अनसुलझी जाँच के लिए चिह्नित पृष्ठ देखें ({pages})।"},
    },
    "NAME_MISMATCH": {
        "title": {
            "en": "Applicant name does not match",
            "hi": "आवेदक का नाम मेल नहीं खाता",
        },
        "detail": {
            "en": "Expected “{expected}” but found “{found}” on {document} ({pages}).",
            "hi": "{document} ({pages}) में “{expected}” अपेक्षित था, लेकिन “{found}” मिला।",
        },
    },
    "ID_MISMATCH": {
        "title": {
            "en": "PAN / Aadhaar does not match",
            "hi": "पैन / आधार मेल नहीं खाता",
        },
        "detail": {
            "en": "Expected “{expected}” but found “{found}” on {document} ({pages}).",
            "hi": "{document} ({pages}) में “{expected}” अपेक्षित था, लेकिन “{found}” मिला।",
        },
    },
    "ADDRESS_MISMATCH": {
        "title": {
            "en": "Address does not match",
            "hi": "पता मेल नहीं खाता",
        },
        "detail": {
            "en": "Expected “{expected}” but found “{found}” on {document} ({pages}).",
            "hi": "{document} ({pages}) में “{expected}” अपेक्षित था, लेकिन “{found}” मिला।",
        },
    },
    "MISSING_DOCUMENT": {
        "title": {
            "en": "Required document not found",
            "hi": "आवश्यक दस्तावेज़ नहीं मिला",
        },
        "detail": {
            "en": "{document} was not found in the uploaded file. Please upload it.",
            "hi": "अपलोड की गई फ़ाइल में {document} नहीं मिला। कृपया इसे अपलोड करें।",
        },
    },
    "BANK_STATEMENT_OLD": {
        "title": {
            "en": "Bank statement older than three months",
            "hi": "बैंक स्टेटमेंट तीन महीने से पुराना है",
        },
        "detail": {
            "en": "The latest statement on {document} ({pages}) is {months} old. A statement from the last 3 months is needed.",
            "hi": "{document} ({pages}) का नवीनतम स्टेटमेंट {months} पुराना है। पिछले 3 महीनों का स्टेटमेंट चाहिए।",
        },
    },
    "PAGE_UNREADABLE": {
        "title": {
            "en": "Page too blurry to read",
            "hi": "पृष्ठ पढ़ने के लिए बहुत धुंधला है",
        },
        "detail": {
            "en": "{document} ({pages}) is too blurry to read. Please re-upload a clearer scan.",
            "hi": "{document} ({pages}) पढ़ने के लिए बहुत धुंधला है। कृपया साफ़ स्कैन पुनः अपलोड करें।",
        },
    },
    "OCR_FAILED": {
        "title": {
            "en": "Could not read this page reliably",
            "hi": "यह पृष्ठ ठीक से पढ़ा नहीं जा सका",
        },
        "detail": {
            "en": "{document} ({pages}) could not be read reliably. Please verify it manually.",
            "hi": "{document} ({pages}) ठीक से पढ़ा नहीं जा सका। कृपया इसकी स्वयं जाँच करें।",
        },
    },
    "DATA_MISSING": {
        "title": {
            "en": "Expected information missing",
            "hi": "अपेक्षित जानकारी नहीं मिली",
        },
        "detail": {
            "en": "“{expected}” was not found on {document} ({pages}). Please check the document.",
            "hi": "{document} ({pages}) में “{expected}” नहीं मिला। कृपया दस्तावेज़ जाँचें।",
        },
    },
    "PROCESSING_ERROR": {
        "title": {
            "en": "File could not be processed",
            "hi": "फ़ाइल संसाधित नहीं हो सकी",
        },
        "detail": {
            "en": "{document} ({pages}) could not be processed: {found}",
            "hi": "{document} ({pages}) संसाधित नहीं हो सका: {found}",
        },
    },
}

# Document-type labels for the classifier's main labels (EN/HI). Unknown
# labels fall back to the raw EN label with a generic Hindi word.
DOCUMENT_LABELS: dict[str, dict[str, str]] = {
    "aadhaar": {"en": "Aadhaar", "hi": "आधार"},
    "pan": {"en": "PAN card", "hi": "पैन कार्ड"},
    "pan card": {"en": "PAN card", "hi": "पैन कार्ड"},
    "voter id": {"en": "Voter ID", "hi": "मतदाता पहचान पत्र"},
    "driving license": {"en": "Driving licence", "hi": "ड्राइविंग लाइसेंस"},
    "passport": {"en": "Passport", "hi": "पासपोर्ट"},
    "ration card": {"en": "Ration card", "hi": "राशन कार्ड"},
    "bank statement": {"en": "Bank statement", "hi": "बैंक स्टेटमेंट"},
    "salary slip": {"en": "Salary slip", "hi": "वेतन पर्ची"},
    "form 16": {"en": "Form 16", "hi": "फ़ॉर्म 16"},
    "income tax return": {"en": "Income tax return", "hi": "आयकर रिटर्न"},
    "application form": {"en": "Application form", "hi": "आवेदन पत्र"},
    "sanction letter": {"en": "Sanction letter", "hi": "स्वीकृति पत्र"},
    "loan agreement": {"en": "Loan agreement", "hi": "ऋण समझौता"},
    "facility agreement": {"en": "Facility agreement", "hi": "सुविधा समझौता"},
    "passbook": {"en": "Passbook", "hi": "पासबुक"},
    "cheque": {"en": "Cheque", "hi": "चेक"},
    "utility bill": {"en": "Utility bill", "hi": "बिजली/पानी का बिल"},
    "rent agreement": {"en": "Rent agreement", "hi": "किराया समझौता"},
    "cam": {"en": "Credit appraisal memo", "hi": "ऋण मूल्यांकन ज्ञापन"},
    "cibil report": {"en": "CIBIL report", "hi": "सिबिल रिपोर्ट"},
    "crif report": {"en": "CRIF report", "hi": "क्रिफ़ रिपोर्ट"},
    "kfs": {"en": "Key fact statement", "hi": "मुख्य तथ्य विवरण"},
    "key fact statement": {"en": "Key fact statement", "hi": "मुख्य तथ्य विवरण"},
    "nach form": {"en": "NACH form", "hi": "नैच फ़ॉर्म"},
    "affidavit": {"en": "Affidavit", "hi": "शपथ-पत्र"},
    "unknown": {"en": "Document", "hi": "दस्तावेज़"},
}


def document_label(document_type: str | None, lang: str = "en") -> str:
    """User-facing document label in EN or HI (falls back gracefully)."""
    raw = str(document_type or "").strip()
    key = raw.strip().casefold()
    entry = DOCUMENT_LABELS.get(key)
    if entry:
        return entry.get(lang, entry["en"])
    if lang == "hi":
        return "दस्तावेज़"
    return raw or "Document"


def render(code: str, part: str, lang: str, **values: object) -> str:
    """Render a title/detail template; missing values become empty strings."""
    template = TEMPLATES[code][part][lang]
    safe = {key: ("" if value is None else str(value)) for key, value in values.items()}
    # Unused placeholders collapse quietly.
    import string

    fields = [field for _, field, _, _ in string.Formatter().parse(template) if field]
    for field in fields:
        safe.setdefault(field, "")
    return template.format(**safe)
