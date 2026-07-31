"""
Patch data/document_type_registry.json to set correct ocr_route for all document types.

Rules:
- "structured": Documents with tabular/multi-column layout (CAM, Bank Statement, CIBIL, etc.)
- "fast": Everything else (form-style, certificates, letters, ID documents, etc.)
"""
import json, sys

sys.stdout.reconfigure(encoding='utf-8')

STRUCTURED_TYPES = {
    "CAM",
    "KFS",
    "CERSAI Report",
    "CIBIL Report",
    "CRIF Report",
    "Passbook",
    "Bank Statement",
    "Salary Slip",
}

with open('data/document_type_registry.json', encoding='utf-8') as f:
    reg = json.load(f)

changed = 0
for dt in reg['document_types']:
    doc_type = dt['type']
    current = dt.get('ocr_route')
    if doc_type in STRUCTURED_TYPES:
        desired = 'structured'
    else:
        desired = 'fast'
    if current != desired:
        dt['ocr_route'] = desired
        print(f"  CHANGED {doc_type}: {current} -> {desired}")
        changed += 1
    else:
        print(f"  OK      {doc_type}: {current}")

with open('data/document_type_registry.json', 'w', encoding='utf-8') as f:
    json.dump(reg, f, ensure_ascii=False, indent=2)

print(f"\nDone. {changed} types updated.")
