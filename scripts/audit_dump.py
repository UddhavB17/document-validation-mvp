"""Read-only audit dump of per-page classification and extraction data.

Usage: .venv/bin/python scripts/audit_dump.py <application_id> [--full]
Writes tmp/audit_app_<id>.txt with one block per page.
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

FIELD_KEYS = (
    "applicant_name", "pan_number", "aadhaar_number", "address",
    "date_of_birth", "account_number", "ifsc_code", "phone_number",
    "person_id", "loan_id",
)


def main() -> None:
    app_id = int(sys.argv[1])
    con = sqlite3.connect("data/dmef.db")
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT page_number, page_type, ocr_route, document_type,
               classification_confidence, detection_method,
               detected_page_number, ocr_text, extracted_fields
        FROM pages WHERE application_id = ? ORDER BY page_number
        """,
        (app_id,),
    ).fetchall()

    out = Path(f"tmp/audit_app_{app_id}.txt")
    out.parent.mkdir(exist_ok=True)
    with out.open("w") as fh:
        for r in rows:
            text = (r["ocr_text"] or "").strip()
            snippet = re.sub(r"\s+", " ", text)[:220]
            fields = {}
            if r["extracted_fields"]:
                try:
                    raw = json.loads(r["extracted_fields"])
                    if isinstance(raw, dict):
                        fields = {k: raw.get(k) for k in FIELD_KEYS if raw.get(k)}
                        extra = {k: v for k, v in raw.items() if k not in FIELD_KEYS and v and not isinstance(v, (list, dict))}
                        fields.update(extra)
                except Exception:
                    fields = {"_raw": r["extracted_fields"][:150]}
            fh.write(
                f"p{r['page_number']:>4} | {r['page_type']:>7} | route={r['ocr_route']} | "
                f"type={r['document_type']} | conf={r['classification_confidence']} | "
                f"method={r['detection_method']} | detpg={r['detected_page_number']}\n"
            )
            fh.write(f"      text: {snippet}\n")
            if fields:
                fh.write(f"      fields: {json.dumps(fields, ensure_ascii=False)[:400]}\n")
    print(f"wrote {out} ({len(rows)} pages)")


if __name__ == "__main__":
    main()
