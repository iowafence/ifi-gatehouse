"""Deterministic normalization of printed drawing rules into typed, INFORMATIONAL constraints. Not a quantity, not an estimate input.

A printed "10'-0" O.C. MAXIMUM" is a spacing CONSTRAINT (an upper bound on the distance between adjacent posts). It is not a measured fence
length, not a post count and not an exact spacing. Everything returned here carries informational_only=True and is_measured_length=False.
"""
import re
from fractions import Fraction

from .validator import lengths_in, norm

_LEN = r"\d+(?:\.\d+)?\s*'\s*-?\s*(?:(?:\d+\s+)?\d+/\d+|\d+(?:\.\d+)?)?\s*\"?|\d+(?:\.\d+)?\s*\"|\d+(?:\.\d+)?\s*(?:ft|feet)\b"
_OC = r"(?:o\.?\s?c\.?|on\s+center|on\s+centers?)"
_BOUND = r"(?:maximum|max\.?|minimum|min\.?)"
SPACING = re.compile(rf"(?P<len>{_LEN})\s*{_OC}(?:\s*(?P<bound>{_BOUND}))?", re.I)
SUBJECT = re.compile(r"\b(?:space|spaced|spacing of)\s+(?P<what>.+?)\s+(?:at|@)\s*$", re.I)


def normalize_spacing(evidence_text):
    """Returns a list of spacing constraints found in the evidence text (usually 0 or 1)."""
    t = norm(evidence_text)
    out = []
    for m in SPACING.finditer(t):
        lens = lengths_in(m.group("len"))
        if len(lens) != 1:
            continue
        b = (m.group("bound") or "").lower().rstrip(".")
        bound = {"maximum": "maximum", "max": "maximum", "minimum": "minimum", "min": "minimum"}.get(b, "stated_without_bound")
        subj = SUBJECT.search(t[:m.start()].strip())
        inches = lens[0]
        out.append({"kind": "spacing_constraint", "basis": "on_center", "bound": bound,
                    "value_inches": str(inches), "value_feet": str(Fraction(inches, 12)), "unit": "ft",
                    "applies_to": subj.group("what") if subj else None,
                    "matched_text": m.group(0).strip(), "is_measured_length": False, "informational_only": True,
                    "meaning": {"maximum": "adjacent posts may be spaced no farther apart than this value",
                                "minimum": "adjacent posts may be spaced no closer than this value",
                                "stated_without_bound": "on-center spacing stated without a maximum or minimum qualifier"}[bound]})
    return out
