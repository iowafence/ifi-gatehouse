"""Offline tests for amd_bridge/flight_trace.py. Run: python3 -m unittest amd_bridge.test_flight_trace   (stdlib only; no network, no AMD client)."""
import hashlib, json, pathlib, unittest
from amd_bridge import flight_trace as FT

ROOT = FT.HERE


class FlightTrace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = FT.build()

    def test_committed_file_equals_a_fresh_offline_rebuild(self):
        self.assertEqual(json.loads(FT.OUT.read_text()), self.doc)

    def test_every_recorded_event_hash_matches_its_stored_record(self):
        n = 0
        for L in self.doc["layers"]:
            for e in L["events"]:
                s = e["source"]
                if s["kind"] == "stored_inference_record":
                    n += 1
                    self.assertEqual(hashlib.sha256((ROOT / s["record_path"]).read_bytes()).hexdigest(), s["record_sha256"], e["event_id"])
        self.assertGreaterEqual(n, 11)

    def test_nothing_unreported_has_a_value_and_nothing_reported_is_null(self):
        for L in self.doc["layers"]:
            for e in L["events"]:
                for k, f in e["fields"].items():
                    self.assertEqual(f["reported"], f["value"] is not None, f"{e['event_id']}.{k}")

    def test_derived_values_follow_their_formula_from_measured_fields(self):
        seen = 0
        for e in self.doc["layers"][0]["events"]:
            f = e["fields"]
            if "ttft_s" not in f:
                continue
            if f["ttft_s"]["value"] is not None:
                seen += 1
                self.assertAlmostEqual(f["ttft_s"]["value"], f["t_first_content_token_s"]["value"] - f["t_request_sent_s"]["value"], places=3)
            if f["tokens_per_s"]["value"] is not None:
                self.assertAlmostEqual(f["tokens_per_s"]["value"], f["completion_tokens"]["value"] / (f["t_end_s"]["value"] - f["t_first_content_token_s"]["value"]), delta=0.06)
                self.assertEqual(f["tokens_per_s"]["derived"]["inputs"], ["completion_tokens", "t_end_s", "t_first_content_token_s"])
        self.assertGreaterEqual(seen, 5)

    def test_token_and_cost_numbers_agree_with_the_ledger_for_spatial_test_003(self):
        led = json.loads(FT.LEDGER.read_text()); by = {e["event_id"]: e for e in self.doc["layers"][0]["events"]}
        for a in led["attempts"]:
            if a["attempt_id"].startswith("spatial_003_"):
                f = by["amd:" + a["attempt_id"]]["fields"]
                self.assertEqual(f["prompt_tokens"]["value"], a["usage"]["prompt_tokens"]); self.assertEqual(f["completion_tokens"]["value"], a["usage"]["completion_tokens"])
                self.assertAlmostEqual(f["cost_usd"]["value"], a["usage"]["cost_usd"], places=9)

    def test_only_the_gemma_attempt_is_in_the_gemma_layer_and_evolus_is_empty(self):
        L = {x["layer"]: x for x in self.doc["layers"]}
        self.assertEqual([e["fields"]["model"]["value"] for e in L["gemma"]["events"]], ["Gemma-4-31B-IT"])
        self.assertEqual(L["gemma"]["state"], "FAILED"); self.assertEqual(L["evolus"]["events"], []); self.assertEqual(L["evolus"]["state"], "NOT_REPORTED")
        self.assertTrue(all("gemma" not in e["fields"]["model"]["value"].lower() for e in L["amd"]["events"] if "gemma" not in e["event_id"]))

    def test_one_event_per_ledger_attempt_and_failures_are_marked_failed(self):
        led = json.loads(FT.LEDGER.read_text())
        ev = {e["event_id"]: e for e in self.doc["layers"][0]["events"]}
        self.assertEqual(len(ev), len(led["attempts"]))
        for a in led["attempts"]:
            self.assertEqual(ev["amd:" + a["attempt_id"]]["state"], "RECORDED" if a["state"] == "CANDIDATES_AVAILABLE" else "FAILED")


if __name__ == "__main__":
    unittest.main()
