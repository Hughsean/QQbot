import json
from pathlib import Path

FIXTURE = Path(__file__).parents[1] / "fixtures" / "mail_delivery_eval.json"
REQUIRED = {
    "interview",
    "assessment",
    "booking_travel_change",
    "deadline_expiry",
    "confirmation",
    "receipt_paid_bill",
    "marketing_archive_only",
    "uncertain",
    "prompt_injection",
}


def test_mail_delivery_fixture_is_fixed_and_complete() -> None:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(cases, list)
    assert {case["category"] for case in cases} == REQUIRED
    assert len({case["id"] for case in cases}) == len(cases)
    assert all(case["expected_delivery"] in {"HOLD", "NOTIFY"} for case in cases)
    assert all(case["subject"].strip() and case["body"].strip() for case in cases)
