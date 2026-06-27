"""Checklist matching logic."""


def evaluate_checklist(checklist: dict, extracted_documents: dict) -> list[dict]:
    required_docs = checklist.get("required_documents", [])
    found_docs = set(extracted_documents.keys())
    exceptions = []

    for doc_name in required_docs:
        if doc_name not in found_docs:
            exceptions.append({"document": doc_name, "issue": "missing"})

    return exceptions
