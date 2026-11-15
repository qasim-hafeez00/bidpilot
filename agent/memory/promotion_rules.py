"""Explicit promotion rules (R7). Raw tool output and raw user text NEVER enter long-term memory - only derived,
named patterns that pass these rules.

STYLE memory (learned from the user's edits to drafts)
  1. Each approved edit is diffed against the draft; `edit_patterns` maps the diff to named patterns
     (cut_first_sentence, removed_word:<w>, shortened, removed_closing_question, removed_greeting).
  2. A pattern is PROMOTED to a style rule when it appears in >= MIN_SUPPORT of the user's last WINDOW edits
     (default 3 of 5) - one-off edits are never learned.
  3. A promoted rule is DEMOTED when it appears in none of the last WINDOW edits (the user changed their mind).

OUTCOME memory (what got replies / hires per job category)
  1. Every marketplace outcome updates per-(category, opening style) counts (submitted, replied, hired).
  2. An insight is PROMOTED only when both compared arms have n >= MIN_ARM and the reply-rate gap is >= MIN_GAP.
"""
from __future__ import annotations

import difflib
import re

WINDOW, MIN_SUPPORT = 5, 3
MIN_ARM, MIN_GAP = 5, 0.15
WATCH_WORDS = ["passionate", "hardworking", "hard-working", "dear", "kindly", "expert", "guru", "ninja", "rockstar",
               "high quality", "best", "amazing", "leverage", "synergy", "delighted", "excited", "honestly"]
RULE_TEXT = {
    "cut_first_sentence": "Start directly with the second idea: the user always deletes the first sentence.",
    "shortened": "Keep it at least 20% shorter than the default length.",
    "removed_closing_question": "Do not end with a question.",
    "removed_greeting": "Never open with a greeting.",
}

_SENT = re.compile(r"(?<=[.!?])\s+")


def _sentences(t: str) -> list[str]:
    return [s.strip() for s in _SENT.split(t.strip()) if s.strip()]


def edit_patterns(original: str, edited: str) -> list[str]:
    o, e = _sentences(original), _sentences(edited)
    pats: list[str] = []
    if o and e and o[0] not in edited and (len(o) < 2 or difflib.SequenceMatcher(None, o[1], e[0]).ratio() > 0.6):
        pats.append("cut_first_sentence")
    for w in WATCH_WORDS:
        if re.search(rf"\b{re.escape(w)}\b", original, re.I) and not re.search(rf"\b{re.escape(w)}\b", edited, re.I):
            pats.append(f"removed_word:{w}")
    if len(edited.split()) <= 0.8 * len(original.split()):
        pats.append("shortened")
    if o and o[-1].endswith("?") and not (e and e[-1].endswith("?")):
        pats.append("removed_closing_question")
    if o and re.match(r"^(hi|hello|dear|greetings)\b", o[0], re.I) and not (e and re.match(r"^(hi|hello|dear|greetings)\b", e[0], re.I)):
        pats.append("removed_greeting")
    return pats


def rule_text(pattern: str) -> str:
    if pattern.startswith("removed_word:"):
        return f"Never use the word '{pattern.split(':', 1)[1]}'."
    return RULE_TEXT.get(pattern, pattern)


def should_promote_style(pattern: str, recent_edits: list[list[str]]) -> bool:
    window = recent_edits[-WINDOW:]
    return sum(pattern in pats for pats in window) >= MIN_SUPPORT


def should_demote_style(pattern: str, recent_edits: list[list[str]]) -> bool:
    window = recent_edits[-WINDOW:]
    return len(window) >= WINDOW and not any(pattern in pats for pats in window)


def outcome_insight(category: str, arms: dict[str, dict[str, int]]) -> str | None:
    """arms: style -> {"submitted": n, "replied": n}. Returns a promotable insight or None."""
    rates = {k: (v["replied"] / v["submitted"]) for k, v in arms.items() if v.get("submitted", 0) >= MIN_ARM}
    if len(rates) < 2:
        return None
    best, worst = max(rates, key=rates.get), min(rates, key=rates.get)
    if rates[best] - rates[worst] < MIN_GAP:
        return None
    return (f"In {category} jobs, '{best}' openings got {rates[best]:.0%} replies vs {rates[worst]:.0%} for '{worst}' "
            f"(n={arms[best]['submitted']}/{arms[worst]['submitted']}).")


def opening_style(cover_letter: str) -> str:
    first = _sentences(cover_letter)[:1]
    f = first[0] if first else ""
    if f.endswith("?"):
        return "question"
    if re.match(r"^(hi|hello|dear|i am|i'm|my name)", f, re.I):
        return "generic"
    if re.search(r"\d", " ".join(_sentences(cover_letter)[:2])):
        return "evidence_first"
    return "problem_first"


# backwards-compatible helper from the starter kit
def should_promote_style_edit(edit_count: int, consistent_pattern: bool) -> bool:
    return edit_count >= MIN_SUPPORT and consistent_pattern
