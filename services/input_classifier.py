"""Fast first-pass input relevance checks."""

from __future__ import annotations

LOAN_TERMS = {
    "loan",
    "borrower",
    "co-applicant",
    "coapplicant",
    "applicant",
    "sanction",
    "emi",
    "disbursement",
    "aadhaar",
    "aadhar",
    "pan",
    "crif",
    "cibil",
    "nach",
}

NON_LOAN_TERMS = {
    "assignment",
    "homework",
    "semester",
    "question",
    "dbms",
    "database management",
    "university",
    "college",
    "experiment",
    "lab manual",
    "answer",
}


def classify_input_text(text_by_page: dict[int, str]) -> dict[str, object]:
    text = " ".join(text_by_page.values()).lower()
    if len(text.strip()) < 120:
        return {"input_type": "unknown", "reason": "Not enough digital text for early classification"}

    loan_hits = sorted(term for term in LOAN_TERMS if term in text)
    non_loan_hits = sorted(term for term in NON_LOAN_TERMS if term in text)
    if non_loan_hits and len(non_loan_hits) >= max(2, len(loan_hits) + 1):
        return {
            "input_type": "unsupported",
            "reason": f"Digital text looks unrelated to loan processing: {', '.join(non_loan_hits[:5])}",
            "loan_hits": loan_hits,
            "non_loan_hits": non_loan_hits,
        }

    if loan_hits:
        return {"input_type": "loan_packet", "reason": f"Loan terms detected: {', '.join(loan_hits[:5])}"}

    return {"input_type": "unknown", "reason": "No strong loan or non-loan signal detected"}
