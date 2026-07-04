"""Shared Hindi + English keyword helpers for document classification."""

from __future__ import annotations


def contains_term(text: str, *terms: str) -> bool:
    """Return True if any term appears in text (case-insensitive for ASCII)."""
    lowered = text.lower()
    return any(term.lower() in lowered or term in text for term in terms)


# Common Hindi terms seen in MSFC loan files
HI = {
    "aadhaar": ("आधार", "यूआईडीएआई"),
    "passbook": ("पासबुक", "पास बुक"),
    "bank_statement": ("खाता विवरण", "बैंक विवरण", "खाता स्टेटमेंट"),
    "sanction": ("स्वीकृति पत्र", "ऋण स्वीकृति"),
    "loan_agreement": ("ऋण समझौता", "ऋण अनुबंध"),
    "consent": ("सहमति पत्र", "सहमति"),
    "stamp": ("स्टाम्प", "स्टाम्प शुल्क", "मुद्रांक"),
    "application": ("आवेदन पत्र", "ऋण आवेदन"),
    "property": ("संपत्ति", "बैनामा", "सेल डीड"),
    "guarantee": ("गारंटी", "प्रत्याभूति"),
    "insurance": ("बीमा", "बीमा पत्र"),
    "disbursement": ("वितरण", "वितरण अनुरोध"),
    "technical": ("तकनीकी", "तकनीकी रिपोर्ट", "मूल्यांकन"),
    "legal": ("कानूनी", "कानूनी रिपोर्ट"),
    "voter": ("मतदाता", "मतदाता पहचान"),
    "utility": ("बिजली बill", "बिजली का बill"),
}
