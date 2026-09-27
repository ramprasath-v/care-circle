"""Deterministic routing rules. These rules do not diagnose conditions."""
from carecircle.schemas import RedFlagEvaluation, SafetyAnswers

EMERGENCY_PLAN_INSTRUCTION = (
    "Follow the configured household emergency plan and seek appropriate "
    "professional or emergency help. CareCircle does not call emergency services."
)


def evaluate_red_flags(answers: SafetyAnswers) -> RedFlagEvaluation:
    matched: list[str] = []
    emergency_fields = (
        ("severe_trouble_breathing", answers.severe_trouble_breathing),
        ("chest_pain", answers.chest_pain),
        ("difficulty_speaking", answers.difficulty_speaking),
    )
    matched.extend(name for name, present in emergency_fields if present is True)
    if answers.awake_and_responsive is False:
        matched.append("not_awake_or_responsive")

    emergency = bool(matched)
    if answers.new_or_worsening_confusion is True:
        matched.append("new_or_worsening_confusion")

    return RedFlagEvaluation(
        has_emergency_red_flag=emergency,
        requires_caregiver_review=emergency or answers.new_or_worsening_confusion is True,
        matched_rules=matched,
        instruction=EMERGENCY_PLAN_INSTRUCTION if emergency else None,
    )
