"""Shared in-process HTTP harness for route-level tests (binds 127.0.0.1 on an ephemeral port; fictional data only)."""
import json, os, threading, unittest, urllib.error, urllib.request, uuid
from http.server import ThreadingHTTPServer
from unittest import mock

from api import server
from engine import integration
from tests.test_ratebook_workflow import wage_args

KEY = "route-test-key-not-real"
OWNER_A, OWNER_B = "a" * 64, "b" * 64
G3 = "EX-MISSING_VALUE-/gates/2/clear_width_ft"
WHO = {"by": "Pat Estimator", "note": "reviewed"}


def plan(pref="CR13", assign=None, diff="standard", use_default=False):
    return {**({"preferred_crew": pref} if pref else {}), "assignments": {"L02": "CR13", **(assign or {})}, "use_default_for_unassigned": use_default,
            "difficulty": {"default": diff, "overrides": {}}}


class HttpBase(unittest.TestCase):
    ENV = {}

    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.book = integration.load_book()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"ENGINE_API_KEY": KEY, "ENGINE_DEMO_ROUTES": "1", **self.ENV})
        self.env.start()
        for d in (server.PROJECTS, server.META, server.LEDGER, server.PREVIEW_HITS, server.WAGE_HISTORY):
            d.clear()
        c, out = self.call("POST", "/demo/projects", {})
        self.assertEqual(c, 201, out)
        self.pid = out["project_id"]

    def tearDown(self):
        self.env.stop()

    def call(self, method, path, body=None, owner=OWNER_A, idem=None, headers_out=None, raw=None, key=KEY, raw_out=None):
        req = urllib.request.Request(self.base + path, method=method, data=raw if raw is not None else (None if body is None else json.dumps(body).encode()))
        req.add_header("Content-Type", "application/json")
        if key is not None:
            req.add_header("X-Engine-Key", key)
        if "/decisions/" in path and idem is not False:
            req.add_header("Idempotency-Key", idem or ("t-" + uuid.uuid4().hex))
        if owner:
            req.add_header("X-Demo-Owner", owner)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                if headers_out is not None:
                    headers_out.update({k.lower(): v for k, v in r.headers.items()})
                data = r.read()
                if raw_out is not None:
                    raw_out.append(data)                      # the exact bytes received (for byte-identity assertions)
                return r.status, json.loads(data)
        except urllib.error.HTTPError as e:
            if headers_out is not None:
                headers_out.update({k.lower(): v for k, v in e.headers.items()})
            try:
                return e.code, json.load(e)
            except Exception:
                return e.code, {}

    def post(self, suffix, body, expect=200, **kw):
        c, out = self.call("POST", f"/projects/{self.pid}/{suffix}", body, **kw)
        self.assertEqual(c, expect, out)
        return out

    def get(self, **kw):
        return self.call("GET", f"/projects/{self.pid}", **kw)[1]

    def to_labor_gate(self):
        self.post("scope/resolve", {"exception_id": G3, "value": 10.0, **WHO})
        sha = next(e["required_decision"]["sha256"] for e in self.get()["exceptions"] if e["code"] == "QUANTITY_RULESET_UNAPPROVED")
        return self.post("decisions/ruleset-approval", {**WHO, "ruleset_sha256": sha})

    def to_wage_cleared(self):
        self.to_labor_gate()
        return self.post("decisions/wage-determination", wage_args())

    def frozen(self):
        """Everything a refused/replayed/previewed request must not change: the whole summary (incl. audit and ledger)."""
        return json.dumps(self.get(), sort_keys=True)

    def mutations(self):
        return server.META[self.pid]["mutations"]
