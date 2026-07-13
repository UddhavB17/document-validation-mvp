"""Provider boundary for future company-system or Google API reference data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from services.verification_manifest import PersonReference


class CompanyReferenceData(BaseModel):
    """Trusted company values before they are combined with a PDF index."""

    model_config = ConfigDict(str_strip_whitespace=True)

    loan_id: str = Field(min_length=1)
    product_type: str = "LAP"
    branch: str | None = None
    people: dict[str, PersonReference]
    source: str = "manual_json"


class CompanyDataProvider(Protocol):
    """Interface the future authenticated Google/company client implements."""

    def get_reference_data(self, loan_id: str) -> CompanyReferenceData:
        ...


class LocalJsonCompanyDataProvider:
    """Demo provider with the same output contract as the future company API."""

    def __init__(self, source: str | Path | dict[str, Any]) -> None:
        self.source = source

    def get_reference_data(self, loan_id: str) -> CompanyReferenceData:
        if isinstance(self.source, dict):
            payload = dict(self.source)
        else:
            payload = json.loads(Path(self.source).read_text(encoding="utf-8"))
        payload.setdefault("loan_id", loan_id)
        payload.setdefault("source", "local_json")
        reference = CompanyReferenceData.model_validate(payload)
        if reference.loan_id != loan_id:
            raise ValueError(
                f"company data returned loan_id {reference.loan_id!r}; expected {loan_id!r}"
            )
        return reference


class GoogleCompanyDataProvider:
    """Explicit integration seam; credentials and endpoint will be supplied later."""

    def __init__(self, *, endpoint: str | None = None) -> None:
        self.endpoint = endpoint

    def get_reference_data(self, loan_id: str) -> CompanyReferenceData:
        raise RuntimeError(
            "Google company API is not configured. Inject an authenticated client and map its "
            f"response to CompanyReferenceData for loan {loan_id}."
        )

