// Local-preview adapter: renames fields from the ACTUAL engine response to the shapes the UI components read.
// Rules: rename only. Nothing is computed, defaulted to a success state, or invented. A field the engine does
// not return stays undefined so the UI shows it as unavailable.
import type {CrewData, Pricing, Project, SourceRef} from './types';

type Raw = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

function source(e: Raw): SourceRef {
  return {doc_id: e.doc_id, sheet: e.sheet_label, page: e.page, excerpt: [e.excerpt, e.stated_value !== undefined && e.stated_value !== null ? `states ${e.stated_value}` : ''].filter(Boolean).join(' — '), source_type: e.source_type};
}

export function fromEngine(raw: unknown): Project {
  const r = (raw && typeof raw === 'object' ? raw : {}) as Raw;
  const lr = (r.labor_review || {}) as Raw;
  const est = r.estimate as Raw | null | undefined;
  const audit = Array.isArray(r.audit) ? r.audit : [];
  // Qualifications are taken only from what the engine itself recorded: the labor decision's qualification and
  // human value assumptions in the audit trail. The engine's GET summary has no separate qualifications field.
  const qualifications: string[] = [];
  if (lr.status === 'decided' && lr.provisional && lr.qualification) qualifications.push(`Labor (provisional): ${lr.qualification}`);
  for (const a of audit as Raw[]) if (a.event === 'resolved' && a.value !== null && a.value !== undefined) {
    qualifications.push(`Scope assumption by ${a.actor}: ${a.exception_id} = ${JSON.stringify(a.value)} (${a.note})`);
  }
  return {
    project_id: r.project_id,
    status: r.status,
    scope_version: r.scope_version,
    approved_by: typeof r.approved_by === 'string' ? r.approved_by : null,       // who recorded the release (self-declared) and when: shown in the Release recorded block
    released_at: typeof r.released_at === 'string' ? r.released_at : null,
    exceptions: (Array.isArray(r.exceptions) ? r.exceptions : []).map((e: Raw) => ({
      exception_id: e.exception_id, code: e.code, severity: e.severity, blocking: e.severity === 'blocking',
      question: e.question, status: 'open', affected_paths: e.affects,
      allows_free_text: e.allows_free_text_resolution === true,
      options: (e.candidate_resolutions || []).map((o: Raw) => ({option_id: o.option_id, label: o.label})),
      evidence: (e.evidence || []).filter((x: Raw) => x && x.doc_id !== undefined).map(source), required_decision: e.required_decision ?? null,
    })),
    reconciliation: (Array.isArray(r.reconciliation) ? r.reconciliation : []).map((x: Raw) => ({
      item: x.item_no, label: x.description, derived: x.derived_qty, scheduled: x.stated_qty, status: x.status,
      variance: x.delta,
    })),
    takeoff: r.takeoff,
    addenda: Array.isArray(r.addenda) ? r.addenda : [], // engine intake records; displayed only
    crews: r.crews && typeof r.crews === 'object' ? r.crews as CrewData : undefined, // computed by the engine; displayed only
    pricing: r.pricing && typeof r.pricing === 'object' ? r.pricing as Pricing : undefined, // crew comparison, wage status, estimate view: all engine output
    labor_review: {
      status: lr.status === 'decided' ? String(lr.decision) : String(lr.status ?? 'unresolved'),
      decision: lr.decision ?? null, by: lr.decided_by, qualification: lr.qualification ?? undefined,
      applicability_review: lr.applicability_review, certified_payroll: lr.certified_payroll === undefined ? undefined : String(lr.certified_payroll),
      source_refs: lr.source_refs,
    },
    estimate: est ? {
      total: est.price_total, rate_basis: est.rates_profile,
      items: (est.pay_items || []).map((p: Raw) => ({description: p.description, qty: p.qty, unit: p.unit, unit_price: p.unit_price, total: p.price})),
      qualifications: (r.pricing?.estimate_view?.qualifications as string[] | undefined) ?? qualifications, exclusions: [],
    } : null,
    proposal_digest: r.proposal_digest ?? null,
    audit: audit.map((a: Raw) => ({event_id: String(a.event_id), actor: a.actor ?? undefined, timestamp: a.utc, event_type: a.event, note: a.note ?? a.reason, exception_id: a.exception_id ?? undefined, option_id: a.option_id ?? undefined})),
    // facts and documents: the engine does not return them in this build; intentionally left undefined.
  };
}
