'use client';
// Landing dashboard: the project list. It only presents what the engine and the registered draft already say and opens the workspace on a click.
// Scope review stays empty here: findings land in the workspace, not on the list.
import { ArrowRight, FolderOpen, Info } from 'lucide-react';

/* eslint-disable @typescript-eslint/no-explicit-any */
const money = (n: number | null | undefined) => typeof n === 'number' ? `${n < 0 ? '-' : ''}$${Math.abs(n).toLocaleString('en-US')}` : 'n/a';
const pct = (n: number | null | undefined) => typeof n === 'number' ? `${n.toFixed(1)}%` : 'n/a';

export function KpiRow({portfolio}:{portfolio:any|null}){
  const k=portfolio?.kpis;
  if(!k)return <section className="kpi-panel kpi-row" data-testid="kpi-row" aria-label="Portfolio KPIs"><div className="kpi-title">PORTFOLIO KPIs</div><p className="kpi-note">Portfolio data unavailable.</p></section>;
  const cells:[string,string,string,string?][]=[
    ['Active bids',String(k.active_bids),'Projects with status Bidding. Won and Lost are not counted.'],
    ['Win rate',pct(k.win_rate_pct),'Won ÷ (Won + Lost). Undecided bids are excluded.',`${k.won} won · ${k.lost} lost`],
    ['Avg est. GP %',pct(k.avg_estimated_gp_pct),'Simple average of each project\'s estimated gross profit % = (bid − materials − labor − other direct cost) ÷ bid. Estimated at bid; not realized profit.'],
    ['Avg exp. NP %',pct(k.avg_expected_np_pct),'Simple average of each project\'s projected net profit % = (estimated gross profit − allocated overhead) ÷ bid. Estimated at bid; not realized profit.'],
    ['Open pipeline',money(k.open_bid_pipeline),'Sum of bid amounts for projects with status Bidding.'],
    ['Exp. pipeline NP',money(k.expected_pipeline_net_profit),'Sum over open bids of projected net profit × the bid\'s stored win probability.'],
  ];
  return <section className="kpi-panel kpi-row" data-testid="kpi-row" aria-label="Portfolio KPIs">
    <div className="kpi-title">PORTFOLIO KPIs</div>
    <div className="kpi-grid">{cells.map(([label,val,tip,sub])=><div className="kpi" key={label} title={tip}><small>{label}</small><strong>{val}</strong>{sub&&<em>{sub}</em>}</div>)}</div>
    <p className="kpi-note" title="Includes the active demo project's seeded figures, which are not the live engine estimate. Margins are estimated at bid, not realized profit.">Synthetic · estimated at bid</p>
  </section>;
}


/** Bid status for the list. DP-001 is "Unbid" until a named person selects a bid; a released estimate says so and still is not a bid. */
export function bidStatusLabel(project: any): string {
  if (!project) return 'Unbid';
  if (project.status === 'released') return 'Demonstration release (not a bid)';
  const chose = (project.audit || []).some((a: any) => a.event_type === 'resolved' && String(a.exception_id || '').includes('BID_SELECTION'));
  return chose ? 'Bidding' : 'Unbid';
}

export function LandingDashboard({ project, draft, portfolio, onOpen, onOpenExample }: { project: any; draft: any | null; portfolio: any | null; onOpen: () => void; onOpenExample: (p: any) => void }) {
  const name = draft ? `${draft.project_ref} · Municipal Recreation Courts` : project?.label || `Project ${String(project?.project_id || '').slice(0, 8)}`;
  const status = bidStatusLabel(project);
  const examples: any[] = (portfolio?.projects || []).filter((p: any) => p.kind !== 'active_estimating');
  return <section className="dashboard" aria-label="Projects" data-testid="dashboard">
    <p className="eyebrow green">COMMERCIAL FENCE ESTIMATING / IFI LABS</p>
    <h1>Projects</h1>
    <KpiRow portfolio={portfolio} />
    <div className="notice info" role="note" data-testid="sample-notice"><Info size={17} /><span>Sample project loaded for this demo.</span></div>
    <ul className="proj-table" aria-label="Project list">
      <li><button type="button" className="proj-open" data-testid="open-dp001" onClick={onOpen}>
        <span className="proj-icon"><FolderOpen size={20} /></span>
        <span className="proj-main"><strong>{name}</strong><small>Four-court Base Bid · three-court Alternate A-1 · fictional owner and site</small></span>
        <span className="proj-status-col"><span className={`status-pill ${status === 'Unbid' ? 'neutral' : 'attention'}`} data-testid="dp001-status"><span className="status-dot" />{status}</span><small data-testid="dp001-scope">Scope review: empty until the workspace is opened</small></span>
        <ArrowRight size={16} />
      </button></li>
      {examples.map(p => <li key={p.project_id}><button type="button" className="proj-open example" onClick={() => onOpenExample(p)}>
        <span className="proj-icon"><FolderOpen size={20} /></span>
        <span className="proj-main"><strong>{p.name}</strong><small>Read-only fictional example</small></span>
        <span className="proj-status-col"><span className="status-pill neutral"><span className="status-dot" />{p.status === 'bidding' ? 'Bidding' : p.status === 'won' ? 'Won' : 'Lost'}</span></span>
        <ArrowRight size={16} />
      </button></li>)}
    </ul>
  </section>;
}
