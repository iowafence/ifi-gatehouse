"""What the demo API may disclose. Replaces the source repo's blanket "api/server.py must not contain 'ratebook'" with a PRECISE allowlist:
derived pricing values for the FICTIONAL_DEMO book are allowed; raw workbook contents, the file hash, role wage tables, private storage and
secrets are not. A key not in tests/disclosure_allowlist.json fails until a maintainer reviews it."""
import json
import pathlib
import unittest

from tests.http_harness import HttpBase, KEY, OWNER_A, OWNER_B, WHO, plan
from tests.test_ratebook_workflow import wage_args

ALLOW = set(json.loads((pathlib.Path(__file__).parent / "disclosure_allowlist.json").read_text())["keys"])
FORBIDDEN_KEYS = {"base_wage_per_hr", "burden_pct", "loaded_rate_per_hr", "file_sha256", "hashes", "source_url_or_sku", "unused_template_lines",
                  "crew_options", "labor_tasks", "data_classification", "role_wages", "workbook", "xlsx", "path", "api_key", "password", "secret"}
FORBIDDEN_TEXT = ("file_sha256", "3d43120473c8db3840557d62397e5f4fc5669b7f2b3cf5a0c86005fc88dde8f1", "/home/", ".xlsx", "ratebook_reference",
                  "config/", "GATEHOUSE_RATEBOOK_DIR", "rates.local", "ENGINE_API_KEY", KEY, "drilling_operator", "crew_1", "crew_2", "crew_3")


def keys_of(node, acc):
    if isinstance(node, dict):
        for k, v in node.items():
            acc.add(k)
            keys_of(v, acc)
    elif isinstance(node, list):
        for v in node:
            keys_of(v, acc)
    return acc


class Disclosure(HttpBase):
    def collect(self):
        r = [self.get(), self.call("GET", "/demo/portfolio")[1], self.call("GET", "/health")[1]]
        self.to_labor_gate()
        r.append(self.get())
        r.append(self.post("decisions/wage-determination", wage_args()))
        r.append(self.call("POST", f"/projects/{self.pid}/crew-plan/preview", plan())[1])
        r.append(self.post("decisions/crew-plan", {**WHO, **plan()}))
        r.append(self.get())
        for bad in ({**WHO, **plan(assign={"L02": "CR1"})}, {**WHO, **plan(assign={"L02": "CR11"})}, {"x": 1}):               # error bodies too
            r.append(self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", bad)[1])
        r.append(self.call("GET", f"/projects/{self.pid}", owner=OWNER_B)[1])
        r.append(self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan()}, idem=False)[1])
        return r

    def test_every_response_key_is_on_the_reviewed_allowlist_and_none_is_forbidden(self):
        found = set()
        for resp in self.collect():
            keys_of(resp, found)
        self.assertEqual(sorted(found - ALLOW), [], "new response keys need review; add to tests/disclosure_allowlist.json only after checking they are not raw rate-book data")
        self.assertEqual(sorted(found & FORBIDDEN_KEYS), [])

    def test_no_response_contains_paths_file_hash_secrets_or_legacy_roster_text(self):
        text = json.dumps(self.collect())
        for needle in FORBIDDEN_TEXT:
            self.assertNotIn(needle, text, needle)
        self.assertNotIn(OWNER_A, text)                                      # the session identity is never echoed back
        self.assertNotIn(OWNER_B, text)

    def test_only_lines_actually_priced_are_disclosed_and_the_book_is_declared_fictional(self):
        self.to_wage_cleared()
        s = self.post("decisions/crew-plan", {**WHO, **plan()})
        self.assertEqual(s["pricing"]["ratebook_ref"]["classification"], "FICTIONAL_DEMO")
        head = s["estimate"]["scenarios"][s["estimate"]["headline_scope_ref"]]
        self.assertTrue(all(l["quantity"] for l in head["materials"]["lines"]))          # no unused price-list rows
        self.assertEqual(s["estimate"]["ratebook_ref"]["ratebook_id"], "IFI-REF-FICTIONAL")
        self.assertEqual(self.book["meta"]["data_classification"], "FICTIONAL_DEMO")     # the policy refuses anything else at project creation

    def test_cross_session_responses_do_not_reveal_that_a_project_exists(self):
        s = self.get()
        for owner in (OWNER_B, None):
            c, out = self.call("GET", f"/projects/{self.pid}", owner=owner)
            self.assertEqual((c, out["error"]), (404, "no such project"))
        self.assertEqual(self.call("GET", f"/projects/{'0' * 32}", owner=OWNER_A)[1]["error"], "no such project")
        self.assertEqual(self.get()["project_id"], s["project_id"])


if __name__ == "__main__":
    unittest.main()
