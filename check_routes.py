import json, sys
sys.stdout.reconfigure(encoding='utf-8')
with open('data/document_type_registry.json', encoding='utf-8') as f:
    reg = json.load(f)
for dt in reg['document_types']:
    route = dt.get('ocr_route', 'NOT_SET')
    doc_type = dt['type'][:38]
    print(f"{doc_type:38s}  {route}")
