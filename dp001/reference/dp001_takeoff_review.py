"""DP-001, public-documents-only deterministic nominal takeoff reconciliation.

NOT part of pricing-service.v1. NOT an AMD prompt/answer key. NOT a released bid.
All results remain proposal/draft until a named human reviews dimensions,
post-center geometry, gate assumptions and release qualifications.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_CEILING
import json
from pathlib import Path

D = Decimal
MAX_OC = D('10')
G1_FT = D('4')
G2_FT = D('12')  # Addendum No. 01 controls Rev0 F502's 6' opening.
G2_COUNT = 2

SCENARIOS = {
    'base': {'width': D('176'), 'depth': D('86'), 'divider_runs': 3},
    'alternate_a1': {'width': D('138'), 'depth': D('86'), 'divider_runs': 2},
}


def ceiling_spacing_intermediate(length_ft: Decimal, spacing_ft: Decimal = MAX_OC) -> int:
    if length_ft <= 0 or spacing_ft <= 0:
        raise ValueError('Nonpositive segment/spacing cannot support post-count approval')
    ratio = (length_ft / spacing_ft).quantize(D('0.000001'))
    return int(ratio.to_integral_value(rounding=ROUND_CEILING)) - 1


def _as_json_number(x):
    if isinstance(x, Decimal):
        if x == x.to_integral_value():
            return int(x)
        return float(x)
    return x


def reconcile(which: str, g3_clear_opening_ft: Decimal | None = None) -> dict:
    """Never substitutes a numeric width for missing G3 unless explicitly supplied."""
    c = SCENARIOS[which]
    width, depth, div_n = c['width'], c['depth'], c['divider_runs']
    gross_a = 2 * (width + depth)
    gross_b = D('64') * div_n
    deductions_known = G1_FT + G2_FT * G2_COUNT
    gate_openings = [
        {'tag': 'G1', 'count': 1, 'clear_ft_each': 4, 'basis': 'F502, 1/F502'},
        {'tag': 'G2', 'count': 2, 'clear_ft_each': 12, 'basis': 'Addendum 01, Item 1'},
        {'tag': 'G3', 'count': 1, 'clear_ft_each': _as_json_number(g3_clear_opening_ft) if g3_clear_opening_ft is not None else None,
         'basis': 'RFI; no documented opening', 'status': 'unresolved' if g3_clear_opening_ft is None else 'human_assumption'},
    ]
    result = {
        'scenario': which,
        'status': 'BLOCKED_G3_UNRESOLVED' if g3_clear_opening_ft is None else 'PROVISIONAL_G3_ASSUMED',
        'provenance': 'public DP001 ANSI B v2 coordinated package; human derivation, not AI output',
        'gross_type_a_lf': _as_json_number(gross_a),
        'gross_type_b_lf': _as_json_number(gross_b),
        'gross_fence_lf': _as_json_number(gross_a + gross_b),
        'gates': gate_openings,
        'known_gate_openings_lf': _as_json_number(deductions_known),
        'net_type_a_formula': f'{_as_json_number(gross_a - deductions_known)} - G3_width_ft',
        'net_total_formula': f'{_as_json_number(gross_a + gross_b - deductions_known)} - G3_width_ft',
        'net_type_a_lf': None,
        'net_type_b_lf': _as_json_number(gross_b),
        'net_fence_lf': None,
        'windscreen_south_lf': _as_json_number(width),
        'fence_guard_type_b_lf': _as_json_number(gross_b),
        'gate_count_each': {'G1': 1, 'G2': 2, 'G3': 1},
        'type_a_post_count': None,
        'type_b_post_count': None,
        'total_core_drill_holes': None,
        'gate_g3_post_size': None,
        'gate_g3_footing_size': None,
        'payment_rule': 'net LF fence separate by Type A/Type B; gates EACH inclusive of posts/footings; no double counting',
        'required_review': [
            'G3 RFI and assumed width not a contract fact',
            'centerline segment geometry and clear-opening deductions independently approved',
            'gate posts are part of gate EACH, not separately billed again in fence LF',
            'Type B footings are smaller than Type A; pricing engine mixed sizes must be reconciled',
            'all post holes core-drilled through completed HMA/base',
        ],
    }
    if g3_clear_opening_ft is None:
        return result
    g3 = D(g3_clear_opening_ft)
    if not (D('0') < g3 < D('31') * 2):
        raise ValueError('G3 width must be a plausible positive, explicitly reviewed assumption')
    # CONDITIONAL SEGMENTS, NOT VERIFIED POST-CENTER GEOMETRY.
    # Assumes G3 and G1 openings centered on CL points at x=31 and x=69;
    # G2 opening centered at y=43 on each side. Face-to-face widths are used
    # nominally; actual post-center offset and CAD-derived spans must be checked.
    a_segments = [
        D('31') - g3 / 2,
        D('69') - G1_FT / 2 - (D('31') + g3 / 2),
        width - (D('69') + G1_FT / 2),
        width,  # uninterrupted south fence
        *([depth / 2 - G2_FT / 2] * 4),  # 2 segments on each E/W side
    ]
    b_segments = [D('64')] * div_n
    if any(x <= 0 for x in a_segments):
        raise ValueError('Assumed gates overlap/erase a nominal north fence segment')
    net_a = gross_a - deductions_known - g3
    assert sum(a_segments) == net_a
    a_line_posts = sum(ceiling_spacing_intermediate(x) for x in a_segments)
    b_line_posts = sum(ceiling_spacing_intermediate(x) for x in b_segments)
    # 4 Type A corners, 2 G1 gateposts, 4 G2 gateposts, 2 G3 gateposts.
    a_terminals = 4 + 2 + 4 + 2
    b_terminals = 2 * div_n
    result.update({
        'net_type_a_lf': _as_json_number(net_a),
        'net_fence_lf': _as_json_number(net_a + gross_b),
        'nominal_type_a_segment_lf': [_as_json_number(x) for x in a_segments],
        'nominal_type_b_segment_lf': [_as_json_number(x) for x in b_segments],
        'type_a_post_count': {'line': a_line_posts, 'corners': 4, 'gate_posts_total': 8,
                              'gate_posts_unknown_size_g3': 2, 'all': a_line_posts + a_terminals},
        'type_b_post_count': {'line': b_line_posts, 'terminals': b_terminals,
                              'all': b_line_posts + b_terminals},
        'total_core_drill_holes': a_line_posts + a_terminals + b_line_posts + b_terminals,
        'count_status': 'PROVISIONAL_CENTERED_GATE_AND_FACE_TO_FACE_ASSUMPTIONS',
        'post_cost_ownership': {'G1_gateposts': 2, 'G2_gateposts': 4, 'G3_gateposts': 2,
                                'count_in_gate_each_not_fence_post_charge': True},
    })
    return result


def main():
    output = {
        'purpose': 'independent deterministic reference for contractor review only',
        'not_approved_for_model_prompt_or_public_release': True,
        'document_sha256': '62ab61d7f2558245f4a6f1708d9320a49e66fd28bf829a2329be5b79db9ac525',
        'modes': {
            'G3_UNRESOLVED': {n: reconcile(n) for n in SCENARIOS},
            'G3_ASSUMED_12_FT_DEMO_ONLY': {n: reconcile(n,D('12')) for n in SCENARIOS},
        },
        'footings': {
            'type_a_line': {'diameter_in': 12, 'depth_in': 48, 'basis': '3/F501'},
            'type_a_terminal_gate': {'diameter_in': 16, 'depth_in': 48, 'basis': '3/F501; G1/G2 gate posts only; G3 UNKNOWN'},
            'type_b_line': {'diameter_in': 8, 'depth_in': 30, 'basis': '3/F501'},
            'type_b_terminal': {'diameter_in': 10, 'depth_in': 30, 'basis': '3/F501'},
            'g3_gate_posts': {'diameter_in': None, 'depth_in': None, 'status':'RFI unresolved'},
        },
    }
    print(json.dumps(output,indent=2,ensure_ascii=False))


if __name__=='__main__':
    main()
