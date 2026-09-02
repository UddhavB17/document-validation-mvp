#!/usr/bin/env python3
"""One-off helper to split monolithic domain modules into focused subpackages."""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]


def extract_functions(source: str, names: Iterable[str]) -> str:
    wanted = set(names)
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    chunks: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            chunks.append("".join(lines[node.lineno - 1 : node.end_lineno]))
    return "\n".join(chunk.rstrip() for chunk in chunks) + ("\n" if chunks else "")


def extract_constants_block(source: str, start_marker: str, end_before: str | None = None) -> str:
    lines = source.splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if start_marker in line)
    if end_before:
        try:
            end = next(i for i, line in enumerate(lines[start + 1 :], start + 1) if line.startswith(end_before))
        except StopIteration:
            end = len(lines)
    else:
        end = len(lines)
    return "".join(lines[start:end]).rstrip() + "\n"


def write_module(path: Path, header: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = header.rstrip() + "\n\n" + body.strip() + "\n"
    path.write_text(content)


EXTRACTION_HEADER = textwrap.dedent(
    '''\
    """Shared extraction helpers — no imports from high-level services."""

    from __future__ import annotations

    import re
    from datetime import date
    from typing import Any

    from services.person_names import canonicalize_person_name, is_name_field

    try:
        from dateutil import parser as _dateutil_parser

        _DATEUTIL_AVAILABLE = True
    except ImportError:  # pragma: no cover
        _DATEUTIL_AVAILABLE = False
    '''
)

EXTRACTION_GENERIC_HEADER = textwrap.dedent(
    '''\
    """Generic labeled-field extraction shared across document families."""

    from __future__ import annotations

    import re
    from typing import Any

    from services.extraction._shared import (
        _ADDRESS_FIELD_NAMES,
        _PAGE_COUNTER_RE,
        _clean_name_like_value,
        _digits_only,
        _normalize_amount,
        _raw_value_after_label,
    )
    '''
)

EXTRACTION_LOAN_HEADER = textwrap.dedent(
    '''\
    """Loan-term extractors: CAM, sanction letter, loan agreement."""

    from __future__ import annotations

    import re
    from typing import Any

    from services.extraction._shared import (
        _clean_name_like_value,
        _extract_amount,
        _extract_date_near,
        _extract_emi,
        _extract_identifier,
        _extract_percentage_near,
        _extract_roi,
        _extract_tenure_months,
        _float_or_none,
        _int_or_none,
        _next_nonempty_line,
        _normalize_amount,
        _numeric_line_after_label,
        _parse_date,
        _sanitize_address_value,
        _sanitize_generic_value,
    )
    '''
)

EXTRACTION_IDENTITY_HEADER = textwrap.dedent(
    '''\
    """Identity-document extractors: PAN, Aadhaar, voter ID, driving licence."""

    from __future__ import annotations

    import re
    from typing import Any

    from services.extraction._shared import (
        _clean_name_like_value,
        _digits_only,
        _extract_date_below_label,
        _extract_date_near,
        _line_after_label,
        _lines_after_label,
        _parse_date,
        _xml_cleaner,
    )
    from services.identifiers import plausible_aadhaar_digits
    from services.validation_gates import has_labeled_aadhaar_value, is_aadhaar_verification_appendix
    '''
)

EXTRACTION_APPLICATION_HEADER = textwrap.dedent(
    '''\
    """Application-form extraction and layout-based address parsing."""

    from __future__ import annotations

    import re
    from typing import Any

    from services.extraction._shared import (
        _clean_name_like_value,
        _extract_date_near,
        _line_after_label,
        _normalize_label,
        _ocr_normalized_pin,
        _sanitize_address_value,
        _sanitize_generic_value,
    )
    from services.identifiers import plausible_aadhaar_digits
    from services.validation_gates import has_labeled_aadhaar_value
    '''
)

EXTRACTION_BANKING_HEADER = textwrap.dedent(
    '''\
    """Banking-document extractors: statements, passbook, cheque, NACH, PDC."""

    from __future__ import annotations

    import re
    from typing import Any

    from services.extraction._shared import (
        _clean_name_like_value,
        _digits_only,
        _extract_date_near,
        _line_after_label,
        _normalize_amount,
        _parse_date,
        _sanitize_generic_value,
    )
    '''
)

EXTRACTION_BUREAU_HEADER = textwrap.dedent(
    '''\
    """Credit-bureau report extractors."""

    from __future__ import annotations

    import re
    from typing import Any

    from services.bureau_scores import has_explicit_no_score_evidence
    from services.extraction._shared import (
        _clean_name_like_value,
        _digits_only,
        _line_after_label,
        _normalize_amount,
    )
    '''
)

EXTRACTION_PROPERTY_HEADER = textwrap.dedent(
    '''\
    """Property, compliance, and ancillary document extractors."""

    from __future__ import annotations

    import re
    from typing import Any

    from services.cersai import DEBTOR_BASED, search_criteria_text, search_type
    from services.extraction._shared import (
        _clean_name_like_value,
        _digits_only,
        _extract_date_near,
        _extract_identifier,
        _inline_identifier_after_label,
        _inline_text_after_label,
        _line_after_label,
        _lines_after_label,
        _normalize_amount,
        _parse_date,
        _sanitize_address_value,
        _sanitize_generic_value,
        _value_after_label,
    )
    '''
)


def split_field_extractor() -> None:
    source = (ROOT / "services/field_extractor.py").read_text()
    shared_names = [
        "_digits_only",
        "_normalize_amount",
        "_raw_value_after_label",
        "_extract_amount",
        "_numeric_line_after_label",
        "_has_repayment_summary_evidence",
        "_int_or_none",
        "_float_or_none",
        "_extract_tenure_months",
        "_extract_roi",
        "_extract_percentage_near",
        "_extract_identifier",
        "_extract_emi",
        "_line_after_label",
        "_clean_name_like_value",
        "_sanitize_name_fields",
        "_lines_after_label",
        "_lines_after_label_until_stop",
        "_value_after_label",
        "_normalize_label",
        "_parse_date",
        "_extract_date_near",
        "_extract_date_after_label",
        "_extract_date_below_label",
        "_is_past_date",
        "_next_nonempty_line",
        "_strip_trailing_page_footer",
        "_sanitize_address_fields",
        "_sanitize_address_value",
        "_address_value_is_contaminated",
        "_ocr_normalized_pin",
        "_looks_like_postal_address",
        "_inline_identifier_after_label",
        "_inline_text_after_label",
        "_xml_cleaner",
    ]
    generic_names = [
        "_extract_generic_labeled_fields",
        "_generic_fields_allowed_for",
        "_sanitize_generic_value",
    ]
    loan_names = [
        "_extract_cam",
        "_extract_cam_decision_fields",
        "_extract_cam_person_records",
        "_extract_cam_kyc_records",
        "_extract_cam_address_records",
        "_extract_cam_score_records",
        "_extract_sanction_letter",
        "_extract_loan_agreement",
        "_extract_end_use_letter",
    ]
    identity_names = [
        "_extract_pan",
        "_extract_aadhaar",
        "_extract_digilocker_aadhaar_summary",
        "_extract_aadhaar_xml",
        "_extract_aadhaar_address",
        "_clean_aadhaar_address_value",
        "_extract_voter_id",
        "_voter_cardholder_name",
        "_extract_driving_license",
    ]
    application_names = [
        "_extract_application_form",
        "_extract_application_coapplicant_records",
        "_extract_application_kyc_records",
        "_extract_application_layout_addresses",
        "_layout_region_geometry",
        "_normalized_layout_text",
        "_layout_address_value",
        "_is_layout_address_piece",
        "_extract_application_address_block",
        "_extract_residential_address_alias",
        "_extract_jumbled_residential_block",
        "_extract_coapplicant_address_record",
    ]
    banking_names = [
        "_extract_bank_statement",
        "_stacked_bank_statement_account_number",
        "_bank_statement_header_holder_name",
        "_statement_holder_after_title",
        "_extract_passbook",
        "_extract_cheque",
        "_extract_cheque_signature_holder",
        "_extract_cheque_number",
        "_extract_statement_period",
        "_extract_bank_transaction_dates",
        "_extract_nach_form",
        "_extract_pdc",
    ]
    bureau_names = ["_extract_crif_report", "_extract_bureau_applicant_name"]
    property_names = [
        "_extract_cersai_report",
        "_extract_utility_bill",
        "_utility_service_block_after_bill_heading",
        "_extract_salary_slip",
        "_extract_salary_month",
        "_extract_stamp_duty",
        "_extract_insurance_form",
        "_extract_insurance_consent",
        "_extract_clearance_report",
        "_clearance_status_window",
    ]

    generic_constants = extract_constants_block(source, "_IDENTITY_GENERIC_FIELDS", "def _generic_fields_allowed_for")
    address_constants = extract_constants_block(source, "_ADDRESS_FIELD_NAMES", "def _address_value_is_contaminated")
    noise_constants = extract_constants_block(source, "_ADDRESS_FORM_NOISE_PATTERNS", "def _raw_value_after_label")

    shared_body = address_constants + "\n" + noise_constants + "\n"
    shared_body += extract_functions(source, shared_names)
    write_module(ROOT / "services/extraction/_shared.py", EXTRACTION_HEADER, shared_body)

    write_module(
        ROOT / "services/extraction/_generic.py",
        EXTRACTION_GENERIC_HEADER,
        generic_constants + extract_functions(source, generic_names),
    )
    write_module(
        ROOT / "services/extraction/loan_terms.py",
        EXTRACTION_LOAN_HEADER,
        extract_functions(source, loan_names),
    )
    write_module(
        ROOT / "services/extraction/identity.py",
        EXTRACTION_IDENTITY_HEADER,
        extract_functions(source, identity_names),
    )
    write_module(
        ROOT / "services/extraction/application.py",
        EXTRACTION_APPLICATION_HEADER,
        extract_constants_block(source, "_APPLICATION_LAYOUT_ADDRESS_LABELS", "def _extract_application_layout_addresses")
        + extract_functions(source, application_names),
    )
    write_module(
        ROOT / "services/extraction/banking.py",
        EXTRACTION_BANKING_HEADER,
        extract_functions(source, banking_names),
    )
    write_module(
        ROOT / "services/extraction/bureau.py",
        EXTRACTION_BUREAU_HEADER,
        extract_functions(source, bureau_names),
    )
    write_module(
        ROOT / "services/extraction/property_compliance.py",
        EXTRACTION_PROPERTY_HEADER,
        extract_functions(source, property_names),
    )


if __name__ == "__main__":
    split_field_extractor()
    print("field_extractor split complete")
