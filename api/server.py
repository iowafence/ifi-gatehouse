"""Thin HTTP wrapper around the deterministic engine (stdlib only).

Auth: header X-Engine-Key must equal env ENGINE_API_KEY. If it is unset the server refuses to start unless
ENGINE_ALLOW_NOAUTH=1, which is for isolated local smoke tests only and must never be used on a public host.
Run: ENGINE_API_KEY=... python3 -m api.server   (port 8080)

Implemented routes (API contract v2):
  POST /dev/projects                 {scope}   development-only fixture route; needs ENGINE_DEV_ROUTES=1
  GET  /projects/{id}                          state summary
  POST /projects/{id}/scope/resolve  {exception_id, option_id|value, by, note}
  POST /projects/{id}/labor/resolve  {by, decision, certified_payroll, applicability_review, note, ...}
  POST /projects/{id}/release        {approver, expected_scope_version, expected_proposal_digest, note}
  POST /projects/{id}/decisions/ruleset-approval  {by, note, ruleset_sha256}                      rate-book mode only
  POST /projects/{id}/decisions/crew-plan         {by, note, preferred_crew?, assignments?, use_default_for_unassigned, difficulty{default, overrides?}}
  POST /projects/{id}/decisions/wage-determination {by, note, determination, schedule, rows, employer_burden, production_rates_approved, certified_payroll_admin}
  POST /projects/{id}/crew-plan/preview           {preferred_crew?, assignments?, use_default_for_unassigned, difficulty}  what-if; changes nothing
  GET  /projects/{id}/crew-matrix              per task L01-L10 and per crew: hourly cost components, production rate, hours, task cost, eligibility + reason, fleet
  GET  /health                                 component states; reports only what was actually probed
Demo mode (ENGINE_DEMO_ROUTES=1, server-side callers only; every call needs X-Engine-Key AND X-Demo-Owner = 64 hex):
  POST   /demo/projects              creates an isolated project from the built-in fictional fixture (body ignored)
  DELETE /demo/projects/{id}         owner-checked removal
  GET    /demo/portfolio             static synthetic portfolio fixtures and derived KPIs (read-only, same for all)
  Owner-scoped projects answer 404 to any other owner, expire after DEMO_TTL_SECONDS idle (default 21600), are capped
  at DEMO_MAX_PROJECTS (1000) and DEMO_MAX_MUTATIONS (100) per project, and bound string/list sizes in request bodies.
  Decision routes REQUIRE an Idempotency-Key header (exact replay returns the original result, no new event; a different payload under the
  same key is 409 IDEMPOTENCY_KEY_REUSED). Crew selections must be active FLEET crews (409 CREW_NOT_IN_FLEET); task qualification stays an engine
  rule. Previews are rate-limited (429 PREVIEW_RATE_LIMITED + Retry-After) and size-bounded. The limiter and ledger live in THIS process's
  memory: a local-demo guard, NOT a shared/global limit. Errors carry a stable "code". Actor names are SELF-DECLARED, not authenticated.
  Contract: docs/HTTP_ADAPTER_CONTRACT_v1_PROPOSED.md (PROPOSED, not approved).
  POST /projects/{id}/addenda        {filename, content_base64, by}  202 {intake_id, status:PROCESSING, poll}; parse runs in the background
  POST /projects/{id}/addenda/{intake_id}/decide {by, note, decision: accept_addendum_value|keep_established}  named human decides a contradiction
  POST /projects/{id}/addenda/{intake_id}/decline {by, note}  named human declines a PROPOSED addendum (nothing changes)
  GET  /projects/{id}/addenda/{intake_id}  status poll (PROCESSING | PROPOSED | HELD_* | APPLIED)
  POST /projects/{id}/addenda/{intake_id}/accept  {by, note, scope_version, proposal_digest, addendum_label?}  named human accepts the Before/After
NOT implemented (answered 501, never faked): POST /projects/upload, GET /projects/{id}/documents,
GET /projects/{id}/proposal. Projects are held in memory and do not survive a restart.
"""
import collections
import hashlib
import hmac
import json
import os
import pathlib
import re
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import copy

import base64
from engine import addendum_intake as ai, integration, pricing_service as svc, portfolio, workflow as wf
from intake import addendum as pdfin

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAX_BODY = 1_000_000
MAX_ADDENDUM_BODY = 14_000_000      # base64 of a MAX_PDF_BYTES PDF plus the JSON envelope
ADDENDUM_PARSER = {"recorded": ai.recorded_parser, "reconstructed": ai.reconstructed_parser}.get(os.environ.get("ENGINE_ADDENDUM_MODE"), ai.live_parser)   # live = the real AMD parse (owner-authorized documents only); recorded = replay of a captured raw reply, reconstructed = rebuilt from a log; both labeled, never live
PROJECTS = {}
LOCK = threading.RLock()
META = {}  # project_id -> {"owner": str|None, "touched": float, "mutations": int}; owner None = dev project
OWNER_RE = re.compile(r"^[a-f0-9]{64}$")
MAX_DEMO_STRING = 2000
MAX_DEMO_LIST = 20


def _env_int(name, default):
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


def _evict_expired(now):
    """Drop idle demo projects. Called under LOCK."""
    ttl = _env_int("DEMO_TTL_SECONDS", 6 * 3600)
    # A project that was created but NEVER used again (no request after the creating one: a flood, a scripted probe, an abandoned page load) frees its slot quickly, so
    # anonymous session creation cannot hold the project cap for hours. Any project with real activity keeps the full idle TTL. A visitor whose idle project was reclaimed
    # simply gets a fresh one on the next request (the web tier recreates on a 404). Active projects are never evicted to make room.
    untouched_ttl = _env_int("DEMO_UNTOUCHED_TTL_SECONDS", 900)
    for pid in [p for p, m in META.items() if m["owner"] is not None and (now - m["touched"] > ttl or (m.get("hits", 1) == 0 and now - m.get("created", now) > untouched_ttl))]:
        PROJECTS.pop(pid, None)
        META.pop(pid, None)
        _forget(pid)


def _check_demo_body(node, depth=0):
    """Bound what a self-declared demo visitor can write into the audit trail."""
    if depth > 4:
        raise ValueError("body too deeply nested")
    if isinstance(node, str) and len(node) > MAX_DEMO_STRING:
        raise ValueError("a field is too long")
    if isinstance(node, list):
        if len(node) > MAX_DEMO_LIST:
            raise ValueError("a list is too long")
        for i in node:
            _check_demo_body(i, depth + 1)
    if isinstance(node, dict):
        for v in node.values():
            _check_demo_body(v, depth + 1)


NOT_IMPLEMENTED = {("POST", ("projects", "upload")), ("GET", ("projects", "*", "documents")),
                   ("GET", ("projects", "*", "proposal"))}


ADAPTER_CONTRACT = "gatehouse-http-adapter.v1-proposed"          # NOT approved; see docs/HTTP_ADAPTER_CONTRACT_v1_PROPOSED.md
ACTOR_IDENTITY = "SELF_DECLARED_DEMO_ACTOR_NOT_AUTHENTICATED"
IDEM_RE = re.compile(r"^[A-Za-z0-9_.:\-]{8,128}$")
WAGE_HISTORY = {}  # project_id -> integration.wage_history_new(...): append-only, monotonic, server-side; dropped only with the project
LEDGER = {}        # project_id -> OrderedDict idempotency_key -> entry (adapter ledger; in memory, per process, per project)
PREVIEW_HITS = {}  # ("p", owner, project_id) / ("o", owner) -> deque of monotonic timestamps. PROCESS-LOCAL: not a shared/global limit.
PREVIEW_WINDOW = 60.0
MAX_PREVIEW_BODY = 8192
DEFAULT_CODES = {400: "BAD_REQUEST", 401: "UNAUTHORIZED", 404: "NOT_FOUND", 409: "ENGINE_REFUSED", 413: "BODY_TOO_LARGE", 429: "RATE_LIMITED",
                 501: "NOT_IMPLEMENTED", 503: "UNAVAILABLE"}
ENGINE_CODE_RE = re.compile(r"\b[A-Z]{3,}(?:_[A-Z0-9]+)+\b")


def _run_addendum(pid, pdf, iid, source, by, parser):
    """Background half of an addendum upload: parse with NO lock held, then record the outcome under the lock. Never raises."""
    try:
        outcome = ai.run_parser(parser, pdf, {"source": source})
    except Exception as e:  # noqa: BLE001
        outcome = {"unavailable": f"the intake worker failed: {type(e).__name__}", "meta": {}}
    with LOCK:
        s = PROJECTS.get(pid)
        if s is None or iid not in s.get("addenda", {}):
            return
        try:
            ai.finish_addendum(s, iid, pdf, outcome, by=by)
        except Exception as e:  # noqa: BLE001 - leave the record held, never PROCESSING forever
            rec = s["addenda"][iid]
            rec.update(status="HELD_REFUSED", message=f"the intake could not be completed: {type(e).__name__}")


def _forget(pid):
    LEDGER.pop(pid, None)
    WAGE_HISTORY.pop(pid, None)
    for k in [k for k in PREVIEW_HITS if k[0] == "p" and k[2] == pid]:
        PREVIEW_HITS.pop(k, None)


def _preview_throttle(owner, pid, now):
    """Sliding-window limiter held in THIS process's memory. Valid only for a single-process local demo; a public deployment with more than
    one worker/instance needs a shared limiter at the proxy or a shared store. Returns None if allowed, else whole seconds to wait."""
    limits = ((("p", owner, pid), _env_int("PREVIEW_MAX_PER_MINUTE", 20)), (("o", owner), _env_int("PREVIEW_MAX_PER_OWNER_PER_MINUTE", 60)))
    waits = []
    for key, limit in limits:
        dq = PREVIEW_HITS.setdefault(key, collections.deque())
        while dq and now - dq[0] >= PREVIEW_WINDOW:
            dq.popleft()
        if len(dq) >= limit:
            waits.append(PREVIEW_WINDOW - (now - dq[0]))
    if waits:
        return int(max(waits)) + 1
    for key, _ in limits:
        PREVIEW_HITS[key].append(now)
    return None


def _payload_digest(route, body):
    """Canonical identity of a decision request: route + the whole JSON body (so actor `by` and `note` are part of it)."""
    return hashlib.sha256(json.dumps({"route": route, "body": body}, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _content_digest(route, body):
    """Identity of the decision CONTENT only (actor context removed): used to tell an unchanged re-submission from a change."""
    return hashlib.sha256(json.dumps({"route": route, "body": {k: v for k, v in body.items() if k not in ("by", "note")}},
                                     sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


REPLAY_HEADERS = {"Idempotent-Replay": "true", "X-Idempotency-Result": "historical"}


def _plan_content(src):
    d = src.get("difficulty") or {}
    return {"preferred_crew": src.get("preferred_crew"), "assignments": dict(src.get("assignments") or {}),
            "use_default_for_unassigned": bool(src.get("use_default_for_unassigned")),
            "difficulty": {"default": d.get("default"), "overrides": dict(d.get("overrides") or {})}}


DECISIONS = {
    "ruleset-approval": (wf.approve_quantity_ruleset, ("by", "note", "ruleset_sha256")),
    "crew-plan": (svc.adopt_crew_plan, ("by", "note", "preferred_crew", "assignments", "use_default_for_unassigned", "difficulty")),
    "wage-determination": (svc.record_wage_decision, ("by", "note", "determination", "schedule", "rows", "employer_burden",
                                                         "production_rates_approved", "certified_payroll_admin")),
}


def _rates():
    p = ROOT / "config/rates.local.json"
    return json.load(open(p if p.exists() else ROOT / "config/rates.example.json"))


try:
    BOOK = integration.load_book()
except Exception:  # noqa: BLE001 - any import problem means pricing is unavailable
    BOOK = None  # pricing unavailable: demo project creation fails closed (503), nothing is priced from a guess
# The ONLY crew source is the pinned rate book's fleet (pricing_service.fleet_overview). There is no legacy roster fallback: if the book is
# unavailable the crew views say so instead of serving stand-in data (legacy fixtures are quarantined in legacy_fixtures/).
try:
    CREWS = integration.crew_roster(BOOK) if BOOK is not None else {"error": "crew data unavailable"}
except (KeyError, TypeError, ValueError):
    CREWS = {"error": "crew data unavailable"}
try:
    PORTFOLIO = portfolio.overview(portfolio.load(), CREWS)
except (OSError, ValueError):
    PORTFOLIO = {"error": "portfolio data unavailable"}


def _observe(pid, s):
    integration.wage_history_observe(WAGE_HISTORY.get(pid), s)


def summary(pid, s):
    """Safe state summary. Money (estimate) exists only after both scope and labor gates; never secrets."""
    _observe(pid, s)
    out = {
        "project_id": pid, "status": s["status"], "scope_version": s["scope"].get("scope_version", 1),
        "exceptions": [{k: e.get(k) for k in ("exception_id", "code", "severity", "question", "affects",
                                              "evidence", "candidate_resolutions", "allows_free_text_resolution",
                                              "required_decision")}
                       for e in s["exceptions"]],
        "reconciliation": s.get("reconciliation"),
        "rfi_drafts": s.get("rfi_drafts", []),
        "addenda": [{k: v for k, v in r.items() if k != "updates"} for r in s.get("addenda", {}).values()],
        "takeoff": s.get("takeoff"), "provisional_quantities": s.get("takeoff") is not None and s.get("estimate") is None,
        "labor_review": s["labor_review"], "estimate": s.get("estimate"), "proposal_digest": s.get("proposal_digest"),
        "hold": s.get("hold"), "released_at": s.get("released_at"), "approved_by": s.get("approved_by"),
        **({"overrides_acknowledged": s["overrides_acknowledged"]} if s.get("overrides_acknowledged") else {}),     # exists only after release
        "audit": s["audit"],
        "crews": CREWS,
    }
    out["adapter"] = {"contract": ADAPTER_CONTRACT, "actor_identity": ACTOR_IDENTITY,
                      "decisions": [{k: v for k, v in e.items() if k not in ("body_bytes", "status")} for e in LEDGER.get(pid, {}).values()],
                      "wage_history": ({"history_complete": WAGE_HISTORY[pid]["complete"], "incomplete_reason": WAGE_HISTORY[pid]["incomplete_reason"],
                                        "incomplete_events": list(WAGE_HISTORY[pid].get("incomplete_events", [])),
                                        "records": [dict(r) for r in WAGE_HISTORY[pid]["records"]]} if pid in WAGE_HISTORY else None)}
    pricing = integration.view(s)
    if pricing:
        out["pricing"] = pricing
        out["crews"] = pricing["crews"]  # the rate book's own crew profiles replace the stand-in roster for rate-book projects
    return out


def health():
    # Each component states what was probed. Presence of an env var is never reported as "connected".
    return {"engine": {"status": "ok"},
            "database": {"status": "not_configured", "detail": "projects are in memory"},
            "evolus": {"status": "not_probed"},
            "amd_inference": {"status": "not_probed"}}


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj, headers=None):
        if code >= 400 and isinstance(obj, dict):
            obj = {**obj, "code": obj.get("code") or DEFAULT_CODES.get(code, "ERROR")}
        self._send_bytes(code, obj if isinstance(obj, bytes) else json.dumps(obj, allow_nan=False).encode(), headers)

    def _send_bytes(self, code, b, headers=None):
        self.send_response(code)
        for hk, hv in (headers or {}).items():
            self.send_header(hk, hv)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _auth(self):
        key = os.environ.get("ENGINE_API_KEY")
        if key is None:
            return os.environ.get("ENGINE_ALLOW_NOAUTH") == "1"
        got = self.headers.get("X-Engine-Key") or ""
        return hmac.compare_digest(got.encode(), key.encode())

    def _body(self, bounded=False, limit=None, max_bytes=None):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError("bad Content-Length")
        if limit is not None and n > limit:
            raise integration.AdapterRefusal(413, "PREVIEW_BODY_TOO_LARGE", f"preview bodies are limited to {limit} bytes")
        if n > (max_bytes or MAX_BODY):
            left = n if (max_bytes and n <= 4 * max_bytes) else 0      # addendum uploads only: drain an oversize body (up to 4x the limit) so the client gets a clean 413, not a reset
            while left > 0:
                left -= len(self.rfile.read(min(65536, left)))
            raise OverflowError
        obj = json.loads(self.rfile.read(n) or b"{}")
        if not isinstance(obj, dict):
            raise ValueError("body must be a JSON object")
        if bounded:
            _check_demo_body(obj)
        return obj

    def _peek_replay(self, parts):
        """Called only AFTER owner/session/project validation. Returns the stored ledger entry iff this is an exact replay (same key, same route,
        same canonical payload incl. actor and note). The parsed body (or its error) is cached so the route reads the request body once."""
        self._peeked = None
        key = self.headers.get("Idempotency-Key") or ""
        if not IDEM_RE.match(key):
            return None
        try:
            b = self._body(bounded=True)
            digest = _payload_digest(parts[3], b)
            self._peeked = ("ok", b)
        except Exception as e:  # noqa: BLE001 - re-raised later by the route so the normal error mapping and counting apply
            self._peeked = ("err", e)
            return None
        ent = LEDGER.get(parts[1], {}).get(key)
        return ent if ent and ent["route"] == parts[3] and ent["payload_sha256"] == digest else None

    def _take_body(self, bounded):
        if getattr(self, "_peeked", None):
            kind, val = self._peeked
            self._peeked = None
            if kind == "err":
                raise val
            return val
        return self._body(bounded=bounded)

    def _route(self, method):
        self._peeked, self._replay = None, None
        if not self._auth():
            return self._send(401, {"error": "unauthorized"})
        parts = tuple(p for p in self.path.split("?")[0].split("/") if p)
        shape = tuple("*" if i == 1 and parts[0] == "projects" and len(parts) > 2 else p for i, p in enumerate(parts))
        try:
            if (method, shape) in NOT_IMPLEMENTED or (method, parts) in NOT_IMPLEMENTED:
                return self._send(501, {"error": "not implemented", "route": self.path})
            if method == "GET" and parts == ("health",):
                return self._send(200, health())
            if method == "POST" and parts == ("dev", "projects"):
                if os.environ.get("ENGINE_DEV_ROUTES") != "1":
                    return self._send(404, {"error": "not found"})
                body = self._body()
                with LOCK:
                    pid = uuid.uuid4().hex
                    PROJECTS[pid] = wf.start(body.get("scope"), _rates())
                    return self._send(201, summary(pid, PROJECTS[pid]))
            if method == "GET" and parts == ("demo", "portfolio"):
                # Static, read-only synthetic fixtures; identical for every visitor, no per-session state.
                if os.environ.get("ENGINE_DEMO_ROUTES") != "1":
                    return self._send(404, {"error": "not found"})
                return self._send(200, PORTFOLIO)
            if parts[:2] == ("demo", "projects") and len(parts) <= 3:
                # Server-side-only creation of an isolated fictional project. The scope is the built-in fixture;
                # nothing the caller sends can choose the scope. Disabled unless ENGINE_DEMO_ROUTES=1.
                if os.environ.get("ENGINE_DEMO_ROUTES") != "1":
                    return self._send(404, {"error": "not found"})
                owner = self.headers.get("X-Demo-Owner") or ""
                if not OWNER_RE.match(owner):
                    return self._send(400, {"error": "X-Demo-Owner must be a 64-char lowercase hex id"})
                if method == "POST" and len(parts) == 2:
                    self._body()  # drained and ignored
                    with LOCK:
                        now = time.time()
                        _evict_expired(now)
                        if sum(1 for m in META.values() if m["owner"] is not None) >= _env_int("DEMO_MAX_PROJECTS", 1000):
                            return self._send(503, {"error": "demo capacity reached; try again shortly"})
                        pid = uuid.uuid4().hex
                        if BOOK is None:
                            return self._send(503, {"error": "pricing engine unavailable"})
                        with open(integration.SCOPE_PATH) as fh:
                            scope = json.load(fh)
                        PROJECTS[pid] = wf.start(scope, None, ratebook=copy.deepcopy(BOOK), policy=integration.POLICY)
                        META[pid] = {"owner": owner, "touched": now, "mutations": 0, "created": now, "hits": 0}
                        WAGE_HISTORY[pid] = integration.wage_history_new(len(PROJECTS[pid]["audit"]))
                        return self._send(201, summary(pid, PROJECTS[pid]))
                if method == "DELETE" and len(parts) == 3:
                    with LOCK:
                        m = META.get(parts[2])
                        if m and m["owner"] is not None and hmac.compare_digest(m["owner"], owner):
                            PROJECTS.pop(parts[2], None)
                            META.pop(parts[2], None)
                            _forget(parts[2])
                            return self._send(200, {"deleted": True})
                        return self._send(404, {"error": "no such project"})
                return self._send(404, {"error": "not found"})
            if len(parts) >= 2 and parts[0] == "projects":
                with LOCK:
                    s = PROJECTS.get(parts[1])
                    meta = META.get(parts[1])
                    if s is not None and meta and meta["owner"] is not None:
                        # Owner-scoped (demo) project: a wrong or missing owner is indistinguishable from "no such project".
                        now = time.time()
                        if (now - meta["touched"] > _env_int("DEMO_TTL_SECONDS", 6 * 3600)
                                or not hmac.compare_digest(meta["owner"], self.headers.get("X-Demo-Owner") or "")):
                            s = None
                        else:
                            meta["touched"] = now
                            meta["hits"] = meta.get("hits", 0) + 1
                            if method == "POST" and parts[2:] != ("crew-plan", "preview"):
                                # An EXACT replay of an already accepted decision is served before the cap is consulted (it is not a new mutation).
                                # Owner/session/project were validated just above; a changed payload or actor is NOT a replay and is capped normally.
                                if len(parts) == 4 and parts[2] == "decisions":
                                    self._replay = self._peek_replay(parts)
                                if self._replay is None:
                                    if meta["mutations"] >= _env_int("DEMO_MAX_MUTATIONS", 100):
                                        return self._send(429, {"error": "this demo project has reached its action limit; reset the demo", "code": "RATE_LIMITED"})
                                    meta["mutations"] += 1
                    if s is None:
                        return self._send(404, {"error": "no such project"})
                    _observe(parts[1], s)          # every request first records whether the current wage record is cleared (monotonic, server-side)
                    if method == "GET" and len(parts) == 2:
                        return self._send(200, summary(parts[1], s))
                    if method == "GET" and parts[2:] == ("crew-matrix",):
                        from engine import crew_matrix
                        m = crew_matrix.build(s)
                        return self._send(200, m if m is not None else {"available": False, "reason": "no quantities yet: the crew matrix needs a priced scope"})
                    if method == "POST" and parts[2:] == ("scope", "resolve"):
                        b = self._body(bounded=bool(meta and meta["owner"] is not None))
                        wf.resolve(s, b.get("exception_id"), option_id=b.get("option_id"), value=b.get("value"),
                                   by=b.get("by"), note=b.get("note"))
                        return self._send(200, summary(parts[1], s))
                    if method == "POST" and parts[2:] == ("labor", "resolve"):
                        b = self._body(bounded=bool(meta and meta["owner"] is not None))
                        allowed = ("by", "decision", "certified_payroll", "applicability_review", "note", "wage_basis",
                                   "loaded_hourly_rate", "source_refs", "classifications", "qualification")
                        extra = set(b) - set(allowed)
                        if extra:
                            raise ValueError(f"unknown fields: {sorted(extra)}")
                        wf.approve_labor(s, **{k: b.get(k) for k in allowed if k in b})
                        return self._send(200, summary(parts[1], s))
                    if method == "POST" and parts[2:] == ("crew-plan", "preview"):
                        # What-if only: no state change, no audit entry, no approval; does not count against the mutation cap, but IS rate-limited
                        # (per project and per owner, process-local) and size-bounded.
                        wait = _preview_throttle(meta["owner"] if meta else None, parts[1], time.monotonic())
                        if wait is not None:
                            return self._send(429, {"error": "too many previews; slow down", "code": "PREVIEW_RATE_LIMITED", "retry_after_seconds": wait,
                                                    "limit_scope": "process-local (single-process demo limiter; not a global guarantee)"},
                                              headers={"Retry-After": str(wait)})
                        return self._send(200, integration.preview(s, self._body(bounded=bool(meta and meta["owner"] is not None), limit=MAX_PREVIEW_BODY)))
                    if method == "POST" and len(parts) == 4 and parts[2] == "decisions":
                        if self._replay is not None:
                            # The stored response is the HISTORICAL result of the original decision, byte for byte, NOT the current project state.
                            return self._send(self._replay["status"], self._replay["body_bytes"],
                                              headers={**REPLAY_HEADERS, "X-Original-Audit-Event-Id": str(self._replay["audit_event_id"])})
                        b = self._take_body(bool(meta and meta["owner"] is not None))
                        spec = DECISIONS.get(parts[3])
                        if spec is None:
                            return self._send(404, {"error": "not found"})
                        fn, allowed = spec
                        extra = set(b) - set(allowed)
                        if extra:
                            raise ValueError(f"unknown fields: {sorted(extra)}")
                        key = self.headers.get("Idempotency-Key") or ""
                        if not IDEM_RE.match(key):
                            return self._send(400, {"error": "decisions require an Idempotency-Key header (8-128 chars of A-Za-z0-9_.:-); one key per intentional decision",
                                                    "code": "IDEMPOTENCY_KEY_REQUIRED"})
                        digest = _payload_digest(parts[3], b)
                        content = _content_digest(parts[3], b)
                        led = LEDGER.setdefault(parts[1], collections.OrderedDict())
                        prior = led.get(key)
                        if prior is not None:
                            if prior["route"] == parts[3] and prior["payload_sha256"] == digest:      # only reachable for uncapped dev projects
                                return self._send(prior["status"], prior["body_bytes"], headers={**REPLAY_HEADERS, "X-Original-Audit-Event-Id": str(prior["audit_event_id"])})
                            return self._send(409, {"error": "this Idempotency-Key was already used for a different decision or payload",
                                                    "code": "IDEMPOTENCY_KEY_REUSED"})
                        # adapter-level guards: all run BEFORE the engine and never touch state
                        if parts[3] == "crew-plan":
                            integration.crew_plan_precheck(s, b)
                            cur = (integration.view(s) or {}).get("crew_plan")
                            if cur and _plan_content(cur) == _plan_content(b):
                                raise integration.AdapterRefusal(409, "DECISION_UNCHANGED", "this crew plan is identical to the approved plan; change it or keep the existing approval")
                            if b.get("use_default_for_unassigned") is True:
                                outside = integration.dry_run_selected_outside_fleet(s, b)
                                if outside:
                                    raise integration.AdapterRefusal(409, "CREW_NOT_IN_FLEET", "default crews would be used for tasks: " + ", ".join(f"{o['ref']}={o['crew_id']}" for o in outside), outside)
                        if parts[3] == "wage-determination":
                            integration.wage_decision_guard(s, b, content, WAGE_HISTORY.get(parts[1]))
                        if parts[3] == "ruleset-approval":
                            rs = (integration.view(s) or {}).get("ruleset") or {}
                            if rs.get("approved") and b.get("ruleset_sha256") == rs.get("sha256"):
                                raise integration.AdapterRefusal(409, "RULESET_ALREADY_APPROVED", "this ruleset digest is already approved; re-approval would overwrite the recorded approver")
                        try:
                            fn(s, **{k: b[k] for k in allowed if k in b})
                        except (wf.GateError, OverflowError):
                            raise
                        except Exception as e:  # noqa: BLE001 - a malformed decision body must never crash the server or half-apply
                            raise ValueError(type(e).__name__)
                        entry = {"idempotency_key": key, "route": parts[3], "payload_sha256": digest, "content_sha256": content, "by": b.get("by"), "audit_event_id": s["audit"][-1]["event_id"],
                                 "recorded_utc": s["audit"][-1].get("utc"), "actor_identity": ACTOR_IDENTITY}
                        led[key] = entry
                        if parts[3] == "wage-determination" and parts[1] in WAGE_HISTORY:
                            integration.wage_history_append(WAGE_HISTORY[parts[1]], b, content, b.get("by"), entry["audit_event_id"], s)
                        body_bytes = json.dumps(summary(parts[1], s), allow_nan=False).encode()     # serialized ONCE: the historical record is these exact bytes
                        entry["status"], entry["body_bytes"] = 200, body_bytes
                        while len(led) > 200:
                            led.popitem(last=False)
                        return self._send(200, body_bytes)
                    if method == "POST" and parts[2:] == ("addenda",):
                        b = self._body(bounded=False, max_bytes=MAX_ADDENDUM_BODY)
                        extra = set(b) - {"filename", "content_base64", "by"}
                        if extra:
                            raise ValueError(f"unknown fields: {sorted(extra)}")
                        try:
                            raw = base64.b64decode(b.get("content_base64") or "", validate=True)
                        except Exception:  # noqa: BLE001
                            raise integration.AdapterRefusal(422, "INVALID_PDF", "content_base64 is not valid base64")
                        try:
                            rec, pdf = ai.begin_addendum(s, raw, b.get("filename"), by=b.get("by"))
                        except pdfin.AddendumRefused as e:
                            raise integration.AdapterRefusal(413 if e.code == "TOO_LARGE" else 422, e.code, str(e))
                        if pdf is not None:      # the slow parse runs off the lock; the client polls GET /projects/{id}/addenda/{intake_id}
                            threading.Thread(target=_run_addendum, args=(parts[1], pdf, rec["intake_id"], dict(rec["source"]), b.get("by"), ADDENDUM_PARSER), daemon=True).start()
                        snap = summary(parts[1], s)
                        return self._send(202, {**snap, "project_status": snap["status"], "intake_id": rec["intake_id"], "status": rec["status"],
                                                "poll": f"/projects/{parts[1]}/addenda/{rec['intake_id']}",
                                                "intake": {k: v for k, v in rec.items() if k != "updates"}})
                    if method == "GET" and len(parts) == 4 and parts[2] == "addenda":
                        rec = s.get("addenda", {}).get(parts[3])
                        if rec is None:
                            return self._send(404, {"error": "no such addendum intake"})
                        return self._send(200, {"intake_id": rec["intake_id"], "status": rec["status"], "intake": {k: v for k, v in rec.items() if k != "updates"}})
                    if method == "POST" and len(parts) == 5 and parts[2] == "addenda" and parts[4] == "decide":
                        b = self._body(bounded=bool(meta and meta["owner"] is not None))
                        extra = set(b) - {"by", "note", "decision"}
                        if extra:
                            raise ValueError(f"unknown fields: {sorted(extra)}")
                        ai.decide_addendum_conflict(s, intake_id=parts[3], decision=b.get("decision"), by=b.get("by"), note=b.get("note"))
                        return self._send(200, summary(parts[1], s))
                    if method == "POST" and len(parts) == 5 and parts[2] == "addenda" and parts[4] == "decline":
                        b = self._body(bounded=bool(meta and meta["owner"] is not None))
                        extra = set(b) - {"by", "note"}
                        if extra:
                            raise ValueError(f"unknown fields: {sorted(extra)}")
                        ai.decline_addendum_intake(s, intake_id=parts[3], by=b.get("by"), note=b.get("note"))
                        return self._send(200, summary(parts[1], s))
                    if method == "POST" and len(parts) == 5 and parts[2] == "addenda" and parts[4] == "accept":
                        b = self._body(bounded=bool(meta and meta["owner"] is not None))
                        extra = set(b) - {"by", "note", "scope_version", "proposal_digest", "addendum_label"}
                        if extra:
                            raise ValueError(f"unknown fields: {sorted(extra)}")
                        ai.accept_addendum_intake(s, intake_id=parts[3], by=b.get("by"), note=b.get("note"),
                                                  scope_version=b.get("scope_version"), proposal_digest=b.get("proposal_digest"),
                                                  addendum_label=b.get("addendum_label"))
                        return self._send(200, summary(parts[1], s))
                    if method == "POST" and parts[2:] == ("release",):
                        b = self._body(bounded=bool(meta and meta["owner"] is not None))
                        pkg = wf.release(s, b.get("approver"), b.get("expected_scope_version"),
                                         b.get("expected_proposal_digest"), note=b.get("note") or "")
                        _observe(parts[1], s)
                        return self._send(200, {k: pkg[k] for k in ("proposal_digest", "approved_by", "released_at",
                                                                    "scope_version", "qualifications")}
                                          | {"audit_id": pkg["audit"][-1]["event_id"], "status": s["status"]}
                                          | ({"overrides_acknowledged": pkg["overrides_acknowledged"]} if pkg.get("overrides_acknowledged") else {})
                                          # footing-scope.v1 projects only (legacy responses are unchanged): authoritative readiness copied from the released package, never from the request
                                          | ({k: pkg[k] for k in ("bid_ready", "release_class", "artifact_kind", "footing_release_class")} if "bid_ready" in pkg else {}))
            return self._send(404, {"error": "not found"})
        except integration.AdapterRefusal as e:
            return self._send(e.status, {"error": str(e), "code": e.code, "details": e.details})
        except wf.GateError as e:
            return self._send(409, {"error": str(e), "code": "ENGINE_REFUSED", "engine_codes": sorted(set(ENGINE_CODE_RE.findall(str(e))))})
        except OverflowError:
            return self._send(413, {"error": "request body too large"})
        except (KeyError, ValueError, TypeError) as e:
            return self._send(400, {"error": f"bad request: {type(e).__name__}"})

    def do_GET(self): self._route("GET")
    def do_POST(self): self._route("POST")
    def do_DELETE(self): self._route("DELETE")
    def log_message(self, *a): pass


def main():
    if os.environ.get("ENGINE_API_KEY") is None and os.environ.get("ENGINE_ALLOW_NOAUTH") != "1":
        sys.exit("set ENGINE_API_KEY (or ENGINE_ALLOW_NOAUTH=1 for isolated local smoke tests only)")
    # ENGINE_HOST defaults to the previous behavior (all interfaces). A single-container deployment sets 127.0.0.1 so only the web tier can reach the engine.
    ThreadingHTTPServer((os.environ.get("ENGINE_HOST", "0.0.0.0"), int(os.environ.get("PORT", 8080))), H).serve_forever()


if __name__ == "__main__":
    main()
