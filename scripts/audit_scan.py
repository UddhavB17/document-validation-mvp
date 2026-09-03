"""Heuristic scan for obvious label-vs-content mismatches (read-only).

Usage: .venv/bin/python scripts/audit_scan.py <application_id>
"""

import json
import re
import sqlite3
import sys

# Strong content markers -> the type they imply.
MARKERS = [
    (
        "Aadhaar",
        re.compile(
            r"unique identification authority|uidai|आधार|aadhaar\s*(?:no|number|card)|मेरा\s*आधार",
            re.I,
        ),
    ),
    (
        "PAN Card",
        re.compile(
            r"income\s*tax\s*department.{0,80}permanent\s*account\s*number|permanent\s*account\s*number\s*card",
            re.I | re.S,
        ),
    ),
    ("CIBIL Report", re.compile(r"transunion\s*cibil|cibil\s*score|consumer\s*cir\b", re.I)),
    ("CRIF Report", re.compile(r"crif\s*high\s*mark|equifax|experian", re.I)),
    (
        "Voter ID",
        re.compile(r"election\s*commission\s*of\s*india|elector('|)s?\s*photo\s*identity", re.I),
    ),
    (
        "Driving License",
        re.compile(r"driving\s*licen[cs]e|transport\s*department.{0,40}licen[cs]e", re.I | re.S),
    ),
    (
        "Bank Statement",
        re.compile(
            r"statement\s*of\s*account|account\s*statement\s*for|txn\s*date.{0,40}(withdrawal|deposit)",
            re.I | re.S,
        ),
    ),
]

GARBAGE_NAME = re.compile(
    r"^(date of birth|dob|s/o|d/o|w/o|c/o|a/c|a/c number|account number|name|father|mother|address|signature|india|male|female|yes|no)\b[:.]?\s*$",
    re.I,
)
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
AADHAAR_RE = re.compile(r"^\d{12}$")


def main() -> None:
    app_id = int(sys.argv[1])
    con = sqlite3.connect("data/dmef.db")
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT page_number, document_type, classification_confidence, detection_method,"
        " ocr_text, extracted_fields FROM pages WHERE application_id=? ORDER BY page_number",
        (app_id,),
    ).fetchall()

    print(f"### app {app_id}: marker/label conflicts")
    for r in rows:
        text = r["ocr_text"] or ""
        label = r["document_type"] or "?"
        hits = [name for name, rx in MARKERS if rx.search(text)]
        for h in hits:
            # skip when label already matches or is a close family member
            fam_ok = (
                h == label
                or (h == "PAN Card" and label in ("PAN", "PAN Card", "KYC Card Photo"))
                or (h == "Aadhaar" and label in ("Aadhaar", "KYC Card Photo"))
                or (
                    h in ("CIBIL Report", "CRIF Report")
                    and label in ("CIBIL Report", "CRIF Report")
                )
            )
            if not fam_ok:
                snippet = re.sub(r"\s+", " ", text)[:140]
                print(
                    f"p{r['page_number']:>4} label={label!r} conf={r['classification_confidence']} "
                    f"method={r['detection_method']} marker={h}\n      {snippet}"
                )

    print(f"\n### app {app_id}: suspicious extracted fields")
    for r in rows:
        if not r["extracted_fields"]:
            continue
        try:
            f = json.loads(r["extracted_fields"])
        except Exception:
            continue
        if not isinstance(f, dict):
            continue
        name = f.get("applicant_name")
        pan = f.get("pan_number")
        aad = f.get("aadhaar_number")
        problems = []
        if isinstance(name, str):
            n = name.strip()
            if GARBAGE_NAME.match(n) or len(n) < 3 or n.isdigit():
                problems.append(f"garbage name={name!r}")
        if isinstance(pan, str) and not PAN_RE.match(pan.strip().upper().replace(" ", "")):
            problems.append(f"bad pan={pan!r}")
        if isinstance(aad, str) and not AADHAAR_RE.match(re.sub(r"\D", "", aad)):
            problems.append(f"bad aadhaar={aad!r}")
        if problems:
            print(f"p{r['page_number']:>4} type={r['document_type']!r}: " + "; ".join(problems))


if __name__ == "__main__":
    main()
