from services.stamp_duty_rules import evaluate_stamp_duty, load_stamp_duty_rules


RULES = [
    {
        "rule_id": "test-gujarat-article-5h-2025",
        "jurisdiction": "Gujarat",
        "instrument_codes": ["5(h)"],
        "effective_from": "2025-04-02",
        "effective_to": None,
        "calculation": {"kind": "flat", "amount": "300"},
        "source_url": "https://example.invalid/legal-approved-rule",
    }
]


def test_default_rule_file_does_not_guess_legal_rates() -> None:
    load_stamp_duty_rules.cache_clear()
    assert load_stamp_duty_rules() == []


def test_stamp_duty_rule_uses_state_instrument_and_effective_date() -> None:
    result = evaluate_stamp_duty(
        {
            "stamp_jurisdiction_state": "Gujarat",
            "stamp_article": "Article 5(h)",
            "stamp_date": "2025-04-02",
            "stamp_duty_amount": "300",
        },
        {},
        RULES,
    )

    assert result["status"] == "COMPLIANT"
    assert result["expected_amount"] == "300"
    assert result["rule_id"] == "test-gujarat-article-5h-2025"


def test_stamp_duty_rule_does_not_guess_for_unconfigured_state() -> None:
    result = evaluate_stamp_duty(
        {
            "stamp_jurisdiction_state": "Rajasthan",
            "stamp_article": "5(h)",
            "stamp_date": "2025-04-02",
            "stamp_duty_amount": "300",
        },
        {},
        RULES,
    )

    assert result["status"] == "RULE_NOT_CONFIGURED"


def test_stamp_duty_percentage_rule_uses_configured_base_and_minimum() -> None:
    rules = [
        {
            "rule_id": "configured-percentage-rule",
            "jurisdiction": "Example State",
            "instrument_codes": ["loan agreement"],
            "effective_from": "2026-01-01",
            "calculation": {
                "kind": "percentage",
                "base_field": "secured_amount",
                "rate_percent": "0.1",
                "minimum": "500",
                "rounding": "ceil_rupee",
            },
        }
    ]
    result = evaluate_stamp_duty(
        {
            "stamp_jurisdiction_state": "Example State",
            "stamp_article": "Loan Agreement",
            "stamp_date": "2026-07-01",
            "stamp_duty_amount": "499",
        },
        {"secured_amount": "100000"},
        rules,
    )

    assert result["status"] == "UNDERPAID"
    assert result["expected_amount"] == "500"


def test_stamp_duty_rule_can_use_explicit_wildcard_instrument() -> None:
    rules = [
        {
            "rule_id": "configured-catchall",
            "jurisdiction": "Example State",
            "instrument_codes": ["*"],
            "effective_from": "2026-01-01",
            "calculation": {"kind": "flat", "amount": "100"},
        }
    ]
    result = evaluate_stamp_duty(
        {
            "stamp_jurisdiction_state": "Example State",
            "stamp_article": "Article 99",
            "stamp_date": "2026-07-01",
            "stamp_duty_amount": "100",
        },
        {},
        rules,
    )

    assert result["status"] == "COMPLIANT"
