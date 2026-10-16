"""Deterministic reading of a dimension from the cited text, tied to ONE named field.

A model may propose a number; the engine never takes it on trust. It re-reads the cited excerpt with the fixed rules below, converts
feet/inches with exact fractions, and accepts a value only when exactly one quantity in the excerpt is tied to the field by its label
and equals the model's number. Anything unlabeled, ambiguous (two different numbers for one field, or one number claimed by two
fields) or unequal is refused. No guessing, no inference from other fields."""
import re
from fractions import Fraction

_Q = str.maketrans({"‘": "'", "’": "'", "′": "'", "“": '"', "”": '"', "″": '"', "–": "-", "—": "-", "−": "-", " ": " "})
NUM = r"(?:\d+\s+\d+/\d+|\d+-\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
FT = r"(?:'|\bFT\b\.?|\bFEET\b|\bFOOT\b)"
IN = r"(?:\"|\bIN\b\.?|\bINCHES\b|\bINCH\b)"
QTY = re.compile(rf"(?P<fi>(?P<fi_f>{NUM})\s*{FT}\s*-\s*(?P<fi_i>{NUM})\s*{IN}?)|(?P<f>(?P<f_n>{NUM})\s*{FT})|(?P<i>(?P<i_n>{NUM})\s*{IN})", re.I)

# field -> (unit of the stored value, label words that tie a number to it, words that must also appear in the excerpt)
FIELDS = {
    "clear_width_ft": ("ft", ("clear opening", "opening width", "clear width", "width", "opening"), ()),
    "post_od_in": ("in", ("outside diameter", "o.d.", "o.d", "od", "post size"), ()),
    "diameter_in": ("in", ("diameter", "dia."), ("footing",)),
    "depth_in": ("in", ("depth", "deep"), ()),
}
TRAIL_GAP, LEAD_GAP = 4, 8


def _num(s):
    s = s.strip()
    if " " in s and "/" in s:
        w, f = s.split(None, 1)
        return Fraction(int(w)) + Fraction(f)
    if "-" in s and "/" in s:
        w, f = s.split("-", 1)
        return Fraction(int(w)) + Fraction(f)
    if "/" in s:
        return Fraction(s)
    return Fraction(s)


def quantities(text):
    """[(start, end, inches as Fraction, matched text)] for every labeled-unit dimension in the text, left to right."""
    t = str(text).translate(_Q)
    out = []
    for m in QTY.finditer(t):
        if m.group("fi"):
            inches = _num(m.group("fi_f")) * 12 + _num(m.group("fi_i"))
        elif m.group("f"):
            inches = _num(m.group("f_n")) * 12
        else:
            inches = _num(m.group("i_n"))
        out.append((m.start(), m.end(), inches, m.group(0).strip()))
    return out


def _kw_spans(t, words):
    low = t.lower()
    return [(m.start(), m.end()) for w in words for m in re.finditer(re.escape(w), low)]


def tied_values(field, text):
    """The set of distinct values (in the field's unit) the text ties to `field`, and the quantities (start) each came from."""
    unit, words, needs = FIELDS[field]
    t = str(text).translate(_Q)
    if any(n not in t.lower() for n in needs):
        return {}
    qs, spans = quantities(t), _kw_spans(t, words)
    others = [s for f, (u, w, n) in FIELDS.items() if f != field for s in _kw_spans(t, w)]
    def between_clean(a, b):
        gap = t[a:b]
        return not re.search(r"\d", gap) and not any(a <= s < b for s, _ in others)
    trail = [q for q in qs if any(0 <= ks - q[1] <= TRAIL_GAP and between_clean(q[1], ks) for ks, _ in spans)]
    lead = [q for q in qs if any(0 <= q[0] - ke <= LEAD_GAP and between_clean(ke, q[0]) for _, ke in spans)]
    use = trail or lead
    div = Fraction(12) if unit == "ft" else Fraction(1)
    return {q[0]: (q[2] / div, q[3]) for q in use}


def read_field(field, text):
    """-> (value float | None, matched text | None, reason). The ONLY number that may stand for `field` in this text.
    Refused unless every dimension in the text is tied to exactly one known field and `field` has exactly one value."""
    if field not in FIELDS:
        return None, None, "no deterministic unit rule exists for this field"
    owner = {}
    for f in FIELDS:
        for start in tied_values(f, text):
            if owner.setdefault(start, f) != f:
                return None, None, "one number in the cited text is tied to two different fields"
    if any(q[0] not in owner for q in quantities(text)):
        return None, None, "the cited text contains a dimension that is not tied to any field"
    found = tied_values(field, text)
    if not found:
        return None, None, "no dimension in the cited text is labeled as this field"
    vals = {v for v, _ in found.values()}
    if len(vals) != 1:
        return None, None, "the cited text ties more than one different number to this field"
    v = next(iter(vals))
    return float(v), next(m for _, m in found.values()), None
