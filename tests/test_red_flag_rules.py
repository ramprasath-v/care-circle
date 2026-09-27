import pytest

from carecircle.policy.red_flag_rules import evaluate_red_flags
from carecircle.schemas import SafetyAnswers


@pytest.mark.parametrize(
    "field",
    ["severe_trouble_breathing", "chest_pain", "difficulty_speaking"],
)
def test_emergency_rules(field):
    result = evaluate_red_flags(SafetyAnswers(**{field: True}))
    assert result.has_emergency_red_flag
    assert result.requires_caregiver_review
    assert field in result.matched_rules
    assert "emergency plan" in result.instruction


def test_awake_and_responsive_normal_path():
    result = evaluate_red_flags(SafetyAnswers(awake_and_responsive=True))
    assert not result.has_emergency_red_flag
    assert not result.requires_caregiver_review
    assert result.matched_rules == []
    assert result.instruction is None


def test_worsening_confusion_requires_review_without_emergency_stop():
    result = evaluate_red_flags(SafetyAnswers(new_or_worsening_confusion=True))
    assert not result.has_emergency_red_flag
    assert result.requires_caregiver_review
    assert result.matched_rules == ["new_or_worsening_confusion"]


def test_rules_are_plain_deterministic_code():
    # The rule engine accepts a typed value and has no model/provider dependency.
    result = evaluate_red_flags(SafetyAnswers())
    assert result.has_emergency_red_flag is False
    assert result.instruction is None
