"""
End-to-end proof: Voter ID spatial extraction using correct OCR route.
"""
import json, sys, sqlite3
sys.stdout.reconfigure(encoding='utf-8')

# Clear lru_cache so registry reload picks up the patched file
from services.document_classifier import load_document_type_registry
load_document_type_registry.cache_clear()

from services.ocr_router import OCRRouter
from services.generic_kv_extractor import extract_kv_deterministic

conn = sqlite3.connect('data/dmef.db')
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT image_path FROM pages WHERE document_type = 'Voter ID' AND image_path IS NOT NULL LIMIT 3"
).fetchall()

registry = load_document_type_registry()
doc_config = next(
    (c for c in registry.get('document_types', []) if c.get('type') == 'Voter ID'), None
)

router = OCRRouter()

for i, row in enumerate(rows):
    image_path = row['image_path']
    print(f"\n--- Voter ID sample {i+1}: {image_path} ---")
    ocr_result = router.process_page(image_path, 'Voter ID', i + 1)
    
    print(f"  Route used: {ocr_result.route_used}")
    print(f"  Bounding boxes: {len(ocr_result.bounding_boxes)}")
    if ocr_result.bounding_boxes:
        print(f"  Sample blocks:")
        for b in ocr_result.bounding_boxes[:5]:
            print(f"    '{b['text']}' bbox={b['bbox']}")
    
    res = extract_kv_deterministic(ocr_result.bounding_boxes, doc_config)
    print(f"  Extraction result: {json.dumps(res)}")
