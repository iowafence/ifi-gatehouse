// DP-001 contractor takeoff reconciliation: a pure, deterministic reference derivation (no imports, no I/O, no model).
// It is a TypeScript port of the independently prepared reference (dp001_takeoff_review.py, sha256 724ae05b...) extended with the
// per-class footing/concrete ledger. It is NOT part of pricing-service.v1 and prices nothing. Every figure is human-derived arithmetic on
// the written DP-001 dimensions and stays PROVISIONAL until a named person reviews geometry, gate assumptions and conventions.
// Parity with the Python reference is checked by dp001/parity_check.py (G3 = 1..61 ft).

export type Scenario = 'base' | 'alt';
export const SCENARIOS: Record<Scenario, { label: string; width: number; depth: number; dividers: number }> = {
  base: { label: 'Base Bid', width: 176, depth: 86, dividers: 3 },
  alt: { label: 'Alternate A-1', width: 138, depth: 86, dividers: 2 },
};
export const DIVIDER_LF = 64, G1_FT = 4, G2_FT = 12, G2_COUNT = 2, MAX_OC = 10;
export const CY_PER_CUIN = 1 / 46656;

// Footing classes from Detail 3/F501 (Rev 0). G3 gate posts are NOT specified (F502 note 4): their size and footing stay unknown.
export const FOOTING_CLASSES = [
  { id: 'a_line', label: 'Type A line post', dia: 12, depth: 48, owner: 'Type A fence LF', basis: '3/F501, Type A line post' },
  { id: 'a_terminal', label: 'Type A corner / terminal post', dia: 16, depth: 48, owner: 'Type A fence LF', basis: '3/F501, Type A terminal / gate post' },
  { id: 'g12_gate', label: 'G1 / G2 gate post', dia: 16, depth: 48, owner: 'Gate EACH (G1, G2): not billed again in fence LF', basis: '3/F501 terminal / gate; G2 posts per Addendum 01 item 1.5' },
  { id: 'g3_gate', label: 'G3 gate post (UNKNOWN size)', dia: null, depth: null, owner: 'Gate EACH (G3): pending RFI', basis: 'F502 note 4: not specified' },
  { id: 'b_line', label: 'Type B line post', dia: 8, depth: 30, owner: 'Type B fence LF', basis: '3/F501, Type B line post' },
  { id: 'b_terminal', label: 'Type B terminal post', dia: 10, depth: 30, owner: 'Type B fence LF', basis: '3/F501, Type B terminal post' },
] as const;
export type ClassId = typeof FOOTING_CLASSES[number]['id'];

export function ceilSpacing(lengthFt: number, spacingFt = MAX_OC): number {
  // intermediate line posts for one uninterrupted segment: ceil(L / spacing) - 1, with the same 6-decimal rounding as the reference
  if (!(lengthFt > 0) || !(spacingFt > 0)) throw new Error('Nonpositive segment/spacing cannot support post-count approval');
  return Math.ceil(Number((lengthFt / spacingFt).toFixed(6))) - 1;
}
export const holeCy = (dia: number, depth: number) => Math.PI * (dia / 2) ** 2 * depth * CY_PER_CUIN;
const r6 = (x: number) => Number(x.toFixed(6));

export type Opening = { tag: string; count: number; each: number | null; total: number | null; basis: string; status: 'documented' | 'unresolved' | 'human_assumption'; evidence: string };
export type ClassRow = { id: ClassId; label: string; dia: number | null; depth: number | null; count: number | null; owner: string; basis: string; status: string; cy_each: number | null; cy_total: number | null };
export type Ledger = {
  scenario: Scenario; label: string; status: 'BLOCKED_G3_UNRESOLVED' | 'PROVISIONAL_G3_ASSUMED';
  g3_width_ft: number | null;
  gross: { type_a: number; type_b: number; total: number; formula_a: string; formula_b: string };
  openings: Opening[]; known_openings_lf: number;
  net: { type_a: number | null; type_b: number; total: number | null; formula_a: string; formula_total: string };
  accessories: { windscreen_lf: number; fence_guard_lf: number };
  gates: Record<string, number>;
  segments: { type_a: number[] | null; type_b: number[] };
  classes: ClassRow[];
  holes: { total: number | null; known_classes: number; unknown_line_posts_pending_g3: boolean };
  concrete_cy: { known_classes: number; g3_posts_excluded: number; complete: boolean };
  geometry_status: 'PROVISIONAL_GEOMETRY';
  geometry_assumptions: string[];
};

export function reconcile(which: Scenario, g3: number | null): Ledger {
  const c = SCENARIOS[which];
  const grossA = 2 * (c.width + c.depth), grossB = DIVIDER_LF * c.dividers;
  const known = G1_FT + G2_FT * G2_COUNT;
  if (g3 !== null && (!Number.isFinite(g3) || !(g3 > 0 && g3 < 62))) throw new Error('G3 width must be a plausible positive, explicitly reviewed assumption');
  const openings: Opening[] = [
    { tag: 'G1', count: 1, each: G1_FT, total: G1_FT, basis: 'F502 gate schedule, 1/F502 (4\'-0" clear)', status: 'documented', evidence: 'g1' },
    { tag: 'G2', count: G2_COUNT, each: G2_FT, total: G2_FT * G2_COUNT, basis: 'Addendum 01 item 1.1/1.6 (12\'-0" clear double leaf, two locations); Rev 0 6\'-0" superseded', status: 'documented', evidence: 'g2' },
    { tag: 'G3', count: 1, each: g3, total: g3, basis: g3 === null ? 'NOT SPECIFIED: RFI required (F502 note 4; Addendum 01 item 2.2). Never defaulted to 0.' : 'HUMAN_ASSUMPTION: NOT DOCUMENTED. Self-declared; the RFI remains open and unsent.', status: g3 === null ? 'unresolved' : 'human_assumption', evidence: 'g3' },
  ];
  const netA = g3 === null ? null : grossA - known - g3;
  const L: Ledger = {
    scenario: which, label: c.label, status: g3 === null ? 'BLOCKED_G3_UNRESOLVED' : 'PROVISIONAL_G3_ASSUMED', g3_width_ft: g3,
    gross: { type_a: grossA, type_b: grossB, total: grossA + grossB, formula_a: `2 × (${c.width} + ${c.depth})`, formula_b: `${c.dividers} × ${DIVIDER_LF}` },
    openings, known_openings_lf: known,
    net: { type_a: netA, type_b: grossB, total: netA === null ? null : netA + grossB, formula_a: `${grossA} − ${known} − G3 width`, formula_total: `${grossA + grossB - known} − G3 width` },
    accessories: { windscreen_lf: c.width, fence_guard_lf: grossB },
    gates: { G1: 1, G2: 2, G3: 1 },
    segments: { type_a: null, type_b: Array(c.dividers).fill(DIVIDER_LF) },
    classes: [], holes: { total: null, known_classes: 0, unknown_line_posts_pending_g3: g3 === null }, concrete_cy: { known_classes: 0, g3_posts_excluded: 2, complete: false },
    geometry_status: 'PROVISIONAL_GEOMETRY',
    geometry_assumptions: [
      'C101 enclosure dimensions are to post centerlines; gate openings are measured face-of-post to face-of-post (32 31 13 1.5.A). The nominal deduction below uses the clear openings directly, with no centerline-to-face allowance.',
      'ILLUSTRATIVE segment geometry (not verified): G3 and G1 centered on the north fence at 31 ft and 69 ft; G2 centered at mid-depth (43 ft) on the east and west fences; the south fence is uninterrupted.',
      'Line posts are spaced at 10 ft on center MAXIMUM per uninterrupted segment: ceil(L / 10) − 1 intermediate posts.',
      'Gate posts belong to the gate EACH item and are never counted again as fence line posts.',
    ],
  };
  let aLine: number | null = null;
  if (g3 !== null) {
    const segA = [31 - g3 / 2, 69 - G1_FT / 2 - (31 + g3 / 2), c.width - (69 + G1_FT / 2), c.width, ...Array(4).fill(c.depth / 2 - G2_FT / 2)];
    if (segA.some(x => !(x > 0))) throw new Error('Assumed gates overlap/erase a nominal north fence segment');
    if (Math.abs(segA.reduce((a, b) => a + b, 0) - (netA as number)) > 1e-9) throw new Error('segment decomposition does not equal the net Type A length');
    L.segments.type_a = segA.map(r6);
    aLine = segA.reduce((a, x) => a + ceilSpacing(x), 0);
  }
  const bLine = L.segments.type_b.reduce((a, x) => a + ceilSpacing(x), 0);
  const counts: Record<ClassId, number | null> = { a_line: aLine, a_terminal: 4, g12_gate: 6, g3_gate: 2, b_line: bLine, b_terminal: 2 * c.dividers };
  L.classes = FOOTING_CLASSES.map(f => {
    const n = counts[f.id];
    const cyEach = f.dia === null ? null : holeCy(f.dia, f.depth as number);
    return { id: f.id, label: f.label, dia: f.dia, depth: f.depth, count: n, owner: f.owner, basis: f.basis,
      status: f.id === 'g3_gate' ? 'UNKNOWN: RFI required' : f.id === 'a_line' && g3 === null ? 'UNRESOLVED: depends on G3' : 'PROVISIONAL_GEOMETRY',
      cy_each: cyEach === null ? null : r6(cyEach), cy_total: cyEach === null || n === null ? null : r6(cyEach * n) };
  });
  const knownRows = L.classes.filter(x => x.count !== null);
  L.holes = { total: g3 === null ? null : knownRows.reduce((a, x) => a + (x.count as number), 0), known_classes: knownRows.reduce((a, x) => a + (x.count as number), 0), unknown_line_posts_pending_g3: g3 === null };
  L.concrete_cy = { known_classes: r6(L.classes.reduce((a, x) => a + (x.cy_total ?? 0), 0)), g3_posts_excluded: 2, complete: false };
  return L;
}

// What the existing pricing service prices for footings: ONE terminal set and ONE line set for the whole project (global requirements).
export function engineFootingModel(terminals: number, linePosts: number, term: { dia: number; depth: number }, line: { dia: number; depth: number }) {
  const cy = terminals * holeCy(term.dia, term.depth) + linePosts * holeCy(line.dia, line.depth);
  return { terminals, line_posts: linePosts, holes: terminals + linePosts, concrete_cy: r6(cy), terminal_set: term, line_set: line };
}
