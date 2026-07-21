"""Canonical contract for future company JSON and indexed PDF verification."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PersonReference(BaseModel):
    """Trusted identity data for one party in a loan file."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    person_id: str | None = None
    role: str | None = None
    applicant_name: str | None = None
    aadhaar_number: str | None = None
    pan_number: str | None = None
    date_of_birth: str | None = None
    phone_number: str | None = None
    address: str | None = None
    pin_code: str | None = None


class IndexedDocument(BaseModel):
    """Company-supplied ownership and page mapping for one document."""

    model_config = ConfigDict(str_strip_whitespace=True)

    document_type: str = Field(min_length=1)
    pages: list[int] = Field(default_factory=list)
    person_id: str = "primary"
    expected_fields: dict[str, Any] | None = None
    required: bool = True
    source_document_id: str | None = None

    @field_validator("pages")
    @classmethod
    def validate_pages(cls, value: list[int]) -> list[int]:
        if any(page < 1 for page in value):
            raise ValueError("page numbers are one-based and must be positive")
        return list(dict.fromkeys(value))


class VerificationManifest(BaseModel):
    """Stable internal contract independent of the future API provider."""

    model_config = ConfigDict(str_strip_whitespace=True)

    schema_version: str = "1.0"
    loan_id: str = Field(min_length=1)
    product_type: str = "LAP"
    branch: str | None = None
    people: dict[str, PersonReference]
    # Empty means the shared OCR/classification pipeline must build the page
    # index automatically. Explicit entries remain supported as overrides.
    document_index: list[IndexedDocument] = Field(default_factory=list)
    source: str = "manual_json"

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_manifest(cls, raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        payload = dict(raw)
        if "people" not in payload:
            reference = payload.get("reference_data") or {}
            if isinstance(reference, dict) and any(isinstance(value, dict) for value in reference.values()):
                people = {
                    str(key): value
                    for key, value in reference.items()
                    if isinstance(value, dict)
                }
            else:
                people = {"primary": reference}
            payload["people"] = people
        if "document_index" not in payload:
            documents = []
            for item in payload.get("documents") or []:
                normalized = dict(item)
                normalized["person_id"] = normalized.pop(
                    "applicant_role", normalized.get("person_id", "primary")
                )
                documents.append(normalized)
            payload["document_index"] = documents
        return payload

    @model_validator(mode="after")
    def validate_relationships(self) -> "VerificationManifest":
        normalized_people: dict[str, PersonReference] = {}
        for key, person in self.people.items():
            person_id = str(key).strip()
            if not person_id:
                raise ValueError("people keys must be non-empty person identifiers")
            person.person_id = person.person_id or person_id
            person.role = person.role or person_id
            normalized_people[person_id] = person
        self.people = normalized_people

        unknown = sorted({item.person_id for item in self.document_index} - set(self.people))
        if unknown:
            raise ValueError(f"document_index references unknown people: {', '.join(unknown)}")

        owners: dict[int, tuple[str, str]] = {}
        for item in self.document_index:
            for page in item.pages:
                owner = (item.person_id, item.document_type.strip().lower())
                if page in owners and owners[page] != owner:
                    raise ValueError(
                        f"page {page} is assigned to conflicting mappings: "
                        f"{owners[page][0]}/{owners[page][1]} and {owner[0]}/{owner[1]}"
                    )
                owners[page] = owner
        return self

    def trusted_people(self) -> dict[str, dict[str, Any]]:
        return {
            person_id: person.model_dump(exclude_none=True)
            for person_id, person in self.people.items()
        }

    def pipeline_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "loan_id": self.loan_id,
            "product_type": self.product_type,
            "branch": self.branch,
            "source": self.source,
            "reference_data": self.trusted_people(),
            "documents": [
                {
                    "document_type": item.document_type,
                    "pages": item.pages,
                    "applicant_role": item.person_id,
                    "expected_fields": item.expected_fields,
                    "required": item.required,
                    "source_document_id": item.source_document_id,
                }
                for item in self.document_index
            ],
        }
