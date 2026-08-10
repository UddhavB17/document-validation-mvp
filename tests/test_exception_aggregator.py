from services.exception_aggregator import aggregate_exceptions


def test_overlapping_validation_passes_do_not_emit_duplicate_exception() -> None:
    duplicate = {
        "rule_id": "AUTO_OWNER_UNRESOLVED",
        "severity": "LOW",
        "document_type": "CRIF Report",
        "person_id": None,
        "expected_value": "Automatic person assignment",
        "found_value": None,
        "page_number": 2,
        "reason": "No subject identity was found.",
    }

    result = aggregate_exceptions([duplicate], [{**duplicate}])

    assert result == [duplicate]
