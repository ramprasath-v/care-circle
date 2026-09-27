"""Exact, deterministic voice approval phrases; no model output grants consent."""
from __future__ import annotations

import re


YES = {"yes", "approve", "approve it", "go ahead", "do it"}
NO = {"no", "reject", "cancel", "don't do it", "do not do it", "don't do that", "do not do that"}
YES_ALL = {"approve all", "approve them all", "approve all of them", "yes, approve all", "yes to all", "go ahead with all"}
NO_ALL = {"reject all", "cancel all", "no to all"}


def approval_decision(transcript: str, pending_count: int) -> str:
    phrase = re.sub(r"[.!?,]+$", "", transcript.strip().lower())
    phrase = re.sub(r"\s+", " ", phrase)
    if pending_count > 1 and phrase in YES_ALL | NO_ALL:
        return "APPROVE_ALL" if phrase in YES_ALL else "REJECT_ALL"
    if phrase not in YES | NO:
        return "NONE"
    if pending_count != 1:
        return "AMBIGUOUS" if pending_count > 1 else "NONE"
    return "APPROVE" if phrase in YES else "REJECT"
