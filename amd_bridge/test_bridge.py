"""Offline tests for the AMD->Gatehouse bridge. Run: PYTHONDONTWRITEBYTECODE=1 ~/ifi-amd-inference-experiment/.venv/bin/python -m unittest amd_bridge.test_bridge -v
No test makes a network call; one asserts that any socket attempt inside the builder fails."""
import hashlib, json, pathlib, re, socket, sys, unittest
HERE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from amd_bridge import ledger as L

EXP = L.EXP
H = lambda p: hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()

class Bridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stored = json.loads(L.OUT.read_text()); cls.fresh = L.build()

    def test_ledger_is_reproducible_from_stored_outputs(self):
        self.assertEqual(self.fresh, self.stored)

    def test_no_amd_client_and_no_network(self):
        self.assertNotIn("ext.amd_client", sys.modules); self.assertNotIn("ext.streaming", sys.modules)
        self.assertTrue((EXP / "LIVE_CALLS_DISABLED").exists())
        real = socket.socket; socket.socket = L._deny
        try:
            with self.assertRaises(L._NoNetwork): socket.socket()
        finally: socket.socket = real
        self.assertIs(socket.socket, real, "builder must restore the socket module")
        import ast
        tree = ast.parse(pathlib.Path(L.__file__).read_text()); mods, ext_names = set(), set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import): mods |= {a.name.split(".")[0] for a in n.names}
            if isinstance(n, ast.ImportFrom):
                mods.add((n.module or "").split(".")[0])
                if n.module == "ext": ext_names |= {a.name for a in n.names}
        self.assertFalse(mods & {"requests", "urllib", "http", "httpx", "aiohttp", "websockets", "ssl"}, mods)
        self.assertEqual(ext_names, {"pipeline", "spatial2", "validator"}, "only the experiment's trust modules are imported (never the client or streaming)")

    def test_web_app_makes_no_amd_reference(self):
        for f in list((HERE / "web/lib").glob("*.ts")) + list((HERE / "web/app").rglob("*.tsx")):
            t = f.read_text().lower()
            self.assertFalse(re.search(r"developer\.amd|amd_token|api\.amd|token_factory", t), f"{f.name} references an AMD endpoint")

    def test_identities_and_required_fields(self):
        self.assertEqual(self.stored["target_document"]["sha256"], L.ANSI_B_SHA); self.assertEqual(H(L.ANSI_B_PDF), L.ANSI_B_SHA)
        for f in self.stored["findings"]:
            for k in ("finding_id", "provenance", "origin_document", "model", "run", "claim", "evidence", "verification", "uncertainty", "human_review", "origin_label"):
                self.assertIn(k, f, f["finding_id"])
            self.assertEqual(len(f["origin_document"]["sha256"]), 64); self.assertTrue(f["origin_document"]["page"])
            self.assertEqual(f["human_review"]["status"], "pending", "a candidate is never pre-accepted")
            self.assertEqual(f["uncertainty"]["classification"] in ("MODEL_STATED_NOT_EVIDENCE", "SIMULATED"), True)

    def test_real_vs_simulated_accounting(self):
        real = [f for f in self.stored["findings"] if f["provenance"] == "REAL_AMD_OUTPUT"]; sim = [f for f in self.stored["findings"] if f["provenance"] == "SIMULATED_TEST_DATA"]
        a = self.stored["accounting"]; self.assertEqual((a["real_findings"], a["simulated_findings"]), (len(real), len(sim))); self.assertEqual((len(real), len(sim)), (32, 0))      # no simulated fixture ships in the product ledger
        self.assertTrue(all(not f["finding_id"].startswith("SIM-") for f in real))

    def test_other_document_evidence_is_not_reassigned_to_ansi_b(self):
        for f in self.stored["findings"]:
            if f["provenance"] == "REAL_AMD_OUTPUT" and f["origin_document"]["doc_id"] == L.D34:
                self.assertEqual(f["origin_document"]["sha256"], L.D34_SHA)
                self.assertIn("NOT an AMD inference on the ANSI B drawing", f["corroboration_on_dp001_ansi_b"]["attribution"])
        corr = [f["finding_id"] for f in self.stored["findings"] if f.get("corroboration_on_dp001_ansi_b", {}).get("result") == "EXACT"]
        self.assertEqual(corr, ["AMD-qwen-exp2-F12"], "only the revision row appears verbatim on the ANSI B sheet")

    def test_spatial_trust_boundaries(self):
        sp = {f["finding_id"]: f for f in self.stored["findings"] if f["type"] == "spatial_association" and f["run"]["run_id"] == "spatial_c101_live_002"}
        self.assertEqual(sum(f["verification"]["verdict"] == "SIDE_CONFIRMED_BY_PDF_POSITION" for f in sp.values()), 4)
        types = [f for f in sp.values() if f["claim"]["category"] == "fence_type_tag"]
        self.assertTrue(types and all(f["verification"]["verdict"] == "NOT_VERIFIABLE_FROM_PDF" for f in types))
        self.assertTrue(next(f for f in types if f["claim"]["key"] == "B")["post_hoc_reading"]["disagrees_with_claim"])
        self.assertFalse(any("scope_link" in f for f in self.stored["findings"] if f.get("claim", {}).get("category") in ("fence_type_tag", "gate_symbol", "gate_tag_position")), "type-tag, symbol and Test 003 position claims can never be linked to a scope mutation")
        self.assertEqual(self.stored["accounting"]["real_fence_type_to_element_associations_verified"], 1, "only tag A in Test 003 is formally vector-confirmed")

    def test_attempts_include_every_failure_and_diagnostics_are_not_accepted(self):
        st = {a["attempt_id"]: a for a in self.stored["attempts"]}
        self.assertEqual(st["spatial_c101_live_001"]["state"], "TIMED_OUT"); self.assertTrue(st["spatial_c101_live_001"]["accepted_output"].startswith("none"))
        self.assertEqual(st["exp2-deepseek-crop"]["state"], "TIMED_OUT"); self.assertEqual(st["exp1-gemma-fullpage"]["state"], "FAILED")
        self.assertFalse(any("spatial_c101_live_001" in f["run"]["run_id"] for f in self.stored["findings"]), "diagnostic partial output never becomes a finding")
        for a in self.stored["attempts"]:
            for art in a["artifacts"]: self.assertEqual(H((HERE if art.get("root") == "workspace" else EXP) / art["path"]), art["sha256"], "artifact bound by hash")

    def test_frozen_experiment_evidence_untouched(self):
        for name in ("FROZEN_TEST001.json", "FROZEN_TEST002.json"):
            m = json.loads((EXP / "runs_v2" / name).read_text())
            for rel, h in m["files"].items(): self.assertEqual(H(EXP / rel), h, rel)

    def test_all_seven_states_are_derivable(self):
        A = {"document": {"doc_id": L.ANSI_B}, "page": 2}
        mk = lambda state: [{**A, "attempt_id": "x", "state": state}]
        ok_f = {"provenance": "REAL_AMD_OUTPUT", "origin_document": {"doc_id": L.ANSI_B, "page": 2}, "verification": {"verdict": "SIDE_CONFIRMED_BY_PDF_POSITION"}}
        un_f = {**ok_f, "verification": {"verdict": "NOT_VERIFIABLE_FROM_PDF"}}
        bad = {**un_f, "post_hoc_reading": {"disagrees_with_claim": True}}
        c = lambda at, fs: L.derive_states(at, fs)["C101"]["state"]
        self.assertEqual(c([], []), "NOT_ANALYZED"); self.assertEqual(c(mk("PROCESSING"), []), "PROCESSING"); self.assertEqual(c(mk("CANDIDATES_AVAILABLE"), [ok_f]), "CANDIDATES_AVAILABLE")
        self.assertEqual(c(mk("CANDIDATES_AVAILABLE"), [ok_f, un_f]), "PARTIALLY_VERIFIED"); self.assertEqual(c(mk("CANDIDATES_AVAILABLE"), [ok_f, un_f, bad]), "REVIEW_REQUIRED")
        self.assertEqual(c(mk("FAILED"), []), "FAILED"); self.assertEqual(c(mk("TIMED_OUT"), []), "TIMED_OUT")
        self.assertEqual(c(mk("TIMED_OUT") + mk("CANDIDATES_AVAILABLE"), [ok_f]), "CANDIDATES_AVAILABLE", "a later timeout never erases earlier verified candidates")

class Test003(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.led = json.loads(L.OUT.read_text()); cls.F = {f["finding_id"]: f for f in cls.led["findings"]}; cls.man = json.loads((HERE / "spatial_plan/FROZEN_TEST003.json").read_text())

    def test_manifest_and_plan_hashes(self):
        for f, h in self.man["files"].items(): self.assertEqual(H(HERE / f), h, f)
        self.assertEqual(self.man["plan_sha256"], "784c93c8d9457cf6c8005070c15280f1e2626588fccb4dc57a32759c7662b96d"); self.assertEqual(self.led["test003_manifest"]["plan_sha256"], self.man["plan_sha256"])
        ev = HERE / "evidence/spatial_test_003_runs"
        for f in self.man["files"]:
            if f.startswith("spatial_plan/runs_v3/"): self.assertEqual(H(HERE / f), H(ev / pathlib.Path(f).relative_to("spatial_plan/runs_v3")), "evidence copy identical")

    def test_attempts_distinct_and_provenance(self):
        a = {x["attempt_id"]: x for x in self.led["attempts"]}; ids = [k for k in a if k.startswith("spatial_003_")]; self.assertEqual(len(ids), 3); self.assertIn("spatial_c101_live_002", a)
        self.assertEqual(len(self.led["attempts"]), 10)
        for k in ids:
            x = a[k]; self.assertEqual(x["document"]["sha256"], L.ANSI_B_SHA); self.assertEqual(x["plan_sha256"], self.man["plan_sha256"]); self.assertEqual(x["response_text_sha256"], hashlib.sha256(json.loads((HERE / x["artifacts"][0]["path"]).read_text())["content"].encode()).hexdigest())
            self.assertTrue(x["input_sha256"] and x["request_started_utc"] and x["usage"]["prompt_tokens"])
        for f in self.led["findings"]:
            if f["run"]["run_id"].startswith("spatial_003_"): self.assertEqual(f["origin_document"]["sha256"], L.ANSI_B_SHA); self.assertNotEqual(f["origin_document"]["doc_id"], L.D34); self.assertEqual(f["run"]["plan_sha256"], self.man["plan_sha256"])

    def test_classifications(self):
        F = self.F
        for k in ("AMD-spatial003-N-gate_position-G3", "AMD-spatial003-N-gate_position-G1", "AMD-spatial003-E-gate_position-G2", "AMD-spatial003-W-gate_position-G2"): self.assertEqual(F[k]["classification"], "GATE_LABEL_POSITION_CONFIRMED"); self.assertIn("LOCALIZATION", F[k]["verification"]["why"].upper())
        self.assertEqual(F["AMD-spatial003-E-type_tag-A"]["classification"], "VECTOR_CONFIRMED")
        for k in ("AMD-spatial003-N-type_tag-B", "AMD-spatial002-4-fence_type_tag-B-top"):
            b = F[k]; self.assertEqual(b["classification"], "CONTRADICTED_BY_DRAWING_EVIDENCE"); self.assertEqual(b["origin_label"], "AI CLAIM CONTRADICTED BY DRAWING EVIDENCE"); self.assertEqual(b["uncertainty"]["model_stated"], "clear")
        b3 = F["AMD-spatial003-N-type_tag-B"]; self.assertEqual(b3["evidence"]["vector_anchor"]["terminal_element"], "interior_divider"); self.assertEqual(b3["claim"]["normalized"]["leader_ends_on"], "perimeter_fence"); self.assertTrue(b3["free_text_from_same_response"])
        for k, f in F.items():
            if "gate_symbol" in k: self.assertEqual(f["classification"], "NOT_VERIFIED_VISUAL_ONLY"); self.assertNotIn("verified", f["origin_label"].replace("NOT VERIFIED", ""))
        w = F["AMD-spatial003-W-gate_symbol-G2"]; self.assertTrue(w["crop_clipped"]); self.assertLess(w["evidence"]["crop_visibility"]["symbol_fraction_inside_crop"], 1.0); self.assertTrue(w["conflict"]["blocks_accept"]); self.assertIn("Addendum 01", w["conflict"]["rule"])
        self.assertTrue(F["AMD-spatial003-N-gate_symbol-G3"]["crop_clipped"], "the G3 symbol lies outside the north crop")
        k6 = F["AMD-spatial003-W-type_tag-6"]; self.assertEqual(k6["classification"], "FALSE_CANDIDATE"); self.assertEqual(k6["uncertainty"]["model_stated"], "cannot_establish"); self.assertEqual(k6["verification"]["verdict"], "NOT_A_FENCE_TYPE_TAG")

    def test_repeat_observations_not_counted_as_independent_facts(self):
        a = self.led["accounting"]; rep = a["repeat_observations_not_independent"]
        self.assertEqual(rep["type_tag_leader:B"], 2); self.assertEqual(rep["gate_tag_position:G3:N"], 2); self.assertEqual(a["spatial_observations"], 18); self.assertEqual(a["spatial_distinct_relationships"], 12); self.assertEqual(a["confident_and_contradicted_observations"], 2)
        self.assertEqual(a["spatial_test_003"]["gate_symbol_relationships_verified"], 0); self.assertEqual(a["spatial_test_003"]["predefined_success_criterion"], "NOT MET")

    def test_deviation_recorded_not_rewritten(self):
        d = self.led["execution_control_deviations"][0]; self.assertIn("bba9fb90", d["what_happened"]); self.assertIn("784c93c8", d["what_happened"]); self.assertIn("judgement call", d["decision"])

    def test_ingest_is_idempotent(self):
        from amd_bridge import test003 as T3
        sys.path.insert(0, str(EXP)); from ext import pipeline; from spatial_plan import score as S; from spatial_plan.oracle3 import Oracle3
        cfg = json.loads((EXP / "experiments/c101_base_plan_crop_ansi_b_v2.json").read_text()); o3 = Oracle3(L.ANSI_B_PDF, cfg)
        try:
            led = json.loads(L.OUT.read_text()); n = (len(led["attempts"]), len(led["findings"])); T3.ingest(led, o3, pipeline, S, L.ANSI_B, L.ANSI_B_SHA); T3.ingest(led, o3, pipeline, S, L.ANSI_B, L.ANSI_B_SHA)
            self.assertEqual((len(led["attempts"]), len(led["findings"])), n, "a second import must not duplicate evidence")
            fresh = {"attempts": [a for a in led["attempts"] if not a["attempt_id"].startswith("spatial_003_")], "findings": [f for f in led["findings"] if not f["run"]["run_id"].startswith("spatial_003_")]}
            T3.ingest(fresh, o3, pipeline, S, L.ANSI_B, L.ANSI_B_SHA); self.assertEqual((len(fresh["attempts"]), len(fresh["findings"])), n)
            self.assertEqual(sorted(f["finding_id"] for f in fresh["findings"]), sorted(f["finding_id"] for f in led["findings"]))
        finally: o3.close()

    def test_before_after_counts(self):
        b = json.loads((HERE / "evidence/ai_findings.before_test003.json").read_text()); self.assertEqual((len(b["attempts"]), len(b["findings"])), (7, 23)); self.assertEqual((len(self.led["attempts"]), len(self.led["findings"])), (10, 32))
        old = {f["finding_id"] for f in b["findings"]} - {"SIM-g2-rev0-6ft", "SIM-g3-12ft-unverified"}   # the two simulated fixtures were removed from the shipped ledger on purpose
        self.assertTrue(old <= set(self.F), "every earlier REAL finding id survives"); self.assertEqual(len(set(self.F) - old), 11)
        for fid in old:   # earlier evidence is not altered, only classified further
            self.assertEqual(self.F[fid]["claim"], next(x for x in b["findings"] if x["finding_id"] == fid)["claim"])

if __name__ == "__main__":
    unittest.main()
