"""allow_mixed_crew_plan is reachable ONLY by code that calls wf.start(policy=...) itself (the labelled baseline script and engine-mechanics tests).
It cannot be set through any served route, environment variable or request field."""
import ast
import os
import pathlib
import unittest
from unittest import mock

from engine import integration, workflow as wf
from tests import footing_helpers as H
from tests.http_harness import HttpBase, WHO, plan

ROOT = pathlib.Path(__file__).resolve().parent.parent


class Static(unittest.TestCase):
    def test_no_served_code_reads_the_flag_or_writes_a_policy(self):
        for f in list((ROOT / "api").glob("*.py")) + list((ROOT / "engine").glob("*.py")) + list((ROOT / "pricing").glob("*.py")):
            src = f.read_text()
            tree = ast.parse(src)
            for node in ast.walk(tree):
                # no assignment to any state["policy"]... and no environment lookup whose key mentions policy / mixed
                if isinstance(node, (ast.Assign, ast.AugAssign)):
                    for t in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                        s = ast.unparse(t)
                        if s.startswith("state[") and "policy" in s and f.name != "workflow.py":
                            self.fail(f"{f.name}: writes {s}")
                if isinstance(node, ast.Call) and ast.unparse(node.func) in ("os.environ.get", "os.getenv", "environ.get"):
                    arg = ast.unparse(node.args[0]) if node.args else ""
                    self.assertNotIn("MIXED", arg.upper(), f"{f.name}: environment lookup {arg}")
                    self.assertNotIn("POLICY", arg.upper(), f"{f.name}: environment lookup {arg}")
        self.assertNotIn("allow_mixed_crew_plan", (ROOT / "api" / "server.py").read_text())

    def test_only_workflow_start_sets_the_policy_and_the_served_start_sites_pass_no_flag(self):
        src = (ROOT / "api" / "server.py").read_text()
        starts = [l.strip() for l in src.splitlines() if "wf.start(" in l]
        self.assertEqual(len(starts), 2)
        self.assertTrue(any("policy=integration.POLICY" in l for l in starts))             # demo project: the fixed constant
        self.assertTrue(any('body.get("scope"), _rates()' in l and "policy" not in l for l in starts))   # dev route: the body supplies the scope only
        self.assertNotIn("allow_mixed_crew_plan", integration.POLICY)

    def test_the_scope_cannot_carry_a_policy(self):
        scope = H.fixture()
        scope["policy"] = {"allow_mixed_crew_plan": True}
        scope["allow_mixed_crew_plan"] = True
        st = wf.start(scope, None, ratebook=H.book(), policy={"as_of": H.AS_OF})
        self.assertFalse(st["policy"].get("allow_mixed_crew_plan"))


class Served(HttpBase):
    def test_request_fields_and_headers_cannot_enable_it_and_mixed_plans_stay_rejected(self):
        self.to_wage_cleared()
        mixed = plan("CR13", {"L02": "CR14"})
        for extra in ({"policy": {"allow_mixed_crew_plan": True}}, {"allow_mixed_crew_plan": True}, {"policy": 1}):
            c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **mixed, **extra})
            self.assertIn(c, (400, 409), (extra, out))                                      # unknown field (400) or the mixed-plan refusal (409), never accepted
            c, out = self.call("POST", f"/projects/{self.pid}/crew-plan/preview", {**mixed, **extra})
            self.assertTrue(c == 400 or not out["valid"], (extra, out))
        c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **mixed}, headers_out={}, raw=None)
        self.assertEqual((c, out["code"]), (409, "CREW_PLAN_MIXED"))
        self.assertIsNone(self.get()["pricing"]["crew_plan"])

    def test_creation_bodies_and_environment_variables_cannot_enable_it(self):
        env = {k: "1" for k in ("ALLOW_MIXED_CREW_PLAN", "ENGINE_ALLOW_MIXED_CREW_PLAN", "GATEHOUSE_ALLOW_MIXED_CREW_PLAN", "ENGINE_POLICY", "POLICY", "allow_mixed_crew_plan")}
        with mock.patch.dict(os.environ, env):
            c, out = self.call("POST", "/demo/projects", {"policy": {"allow_mixed_crew_plan": True}, "allow_mixed_crew_plan": True})
            self.assertEqual(c, 201)
            pid = out["project_id"]
            from api import server
            self.assertFalse(server.PROJECTS[pid]["policy"].get("allow_mixed_crew_plan"))
            self.assertFalse(server.PROJECTS[self.pid]["policy"].get("allow_mixed_crew_plan"))
            self.to_wage_cleared()
            c, out = self.call("POST", f"/projects/{self.pid}/decisions/crew-plan", {**WHO, **plan("CR13", {"L02": "CR14"})})
            self.assertEqual((c, out["code"]), (409, "CREW_PLAN_MIXED"))


if __name__ == "__main__":
    unittest.main()
