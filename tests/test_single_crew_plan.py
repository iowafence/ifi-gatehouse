"""Owner decision 2026-10-16 4:04 PM CT: ONE crew for the whole job (L01-L10), never a mix; job-level eligibility; fail closed on mixed plans."""
import copy
import unittest

from engine import integration, workflow as wf
from pricing import crews
from tests import footing_helpers as H

TASKS = [f"L{i:02d}" for i in range(1, 11)]
BASE = dict(by=H.WHO, note="test", difficulty={"default": "standard", "overrides": {}})


class SingleCrew(unittest.TestCase):
    def setUp(self):
        self.st = H.priced()                                   # approved plan: CR13 for the whole job

    def refused(self, code, **kw):
        before = copy.deepcopy(self.st)
        with self.assertRaises(wf.GateError) as c:
            wf.approve_crew_plan(self.st, **{**BASE, **kw})
        self.assertIn(code, str(c.exception))
        self.assertEqual(self.st, before)                      # fail closed: nothing recorded, plan and digest untouched
        return str(c.exception)

    def test_mixed_plans_are_refused_by_the_engine_under_the_default_policy(self):
        self.refused("CREW_PLAN_MIXED", preferred_crew="CR13", assignments={"L02": "CR14"}, use_default_for_unassigned=False)
        self.refused("CREW_PLAN_MIXED", preferred_crew="CR13", assignments={t: ("CR13" if t != "L05" else "CR12") for t in TASKS}, use_default_for_unassigned=False)
        self.refused("CREW_PLAN_MIXED", preferred_crew="CR13", assignments={}, use_default_for_unassigned=True)
        self.refused("CREW_PLAN_MIXED", preferred_crew=None, assignments={t: "CR13" for t in TASKS}, use_default_for_unassigned=False)     # no crew named once for the job
        self.refused("CREW_PLAN_MIXED", preferred_crew=None, assignments={}, use_default_for_unassigned=True)

    def test_a_crew_that_cannot_do_every_task_is_refused_for_the_job_with_the_reason(self):
        for bad in ("CR11", "CR12"):
            msg = self.refused("CREW_NOT_ELIGIBLE_FOR_JOB", preferred_crew=bad, assignments={}, use_default_for_unassigned=False)
            self.assertIn("R4", msg)
        msg = self.refused("CREW_NOT_ELIGIBLE_FOR_JOB", preferred_crew="CR1", assignments={}, use_default_for_unassigned=False)     # a legacy default crew has no rate for most tasks
        self.assertIn("no production rate", msg)

    def test_one_crew_for_every_task_is_accepted_whether_named_once_or_on_every_task(self):
        for crew in ("CR13", "CR14"):
            for asg in ({}, {t: crew for t in TASKS}):
                wf.approve_crew_plan(self.st, **{**BASE, "preferred_crew": crew, "assignments": asg, "use_default_for_unassigned": False})
                self.assertEqual({l["crew_id"] for l in self.st["estimate"]["scenarios"]["BASE"]["labor"]["lines"]}, {crew})
                self.assertEqual({l["crew_id"] for l in self.st["estimate"]["scenarios"]["ALT-A1"]["labor"]["lines"]}, {crew})

    def test_job_eligibility_function(self):
        rb = self.st["ratebook"]
        je = {c: crews.job_eligibility(rb, c) for c in ("CR11", "CR12", "CR13", "CR14", "CR1")}
        self.assertEqual({c: v["eligible"] for c, v in je.items()}, {"CR11": False, "CR12": False, "CR13": True, "CR14": True, "CR1": False})
        self.assertEqual([r["task_id"] for r in je["CR11"]["reasons"]], ["L02"])
        self.assertEqual(crews.job_eligibility(rb, "CR99")["reasons"][0]["code"], "UNKNOWN_CREW")

    def test_the_mixed_plan_flag_is_not_reachable_from_the_served_policy(self):
        self.assertNotIn("allow_mixed_crew_plan", integration.POLICY)
        self.assertFalse(self.st["policy"].get("allow_mixed_crew_plan"))

    def test_a_selected_plan_averages_nothing_drilling_is_the_selected_crews_own_cost(self):
        crew_cost = {}
        for crew in ("CR13", "CR14"):
            wf.approve_crew_plan(self.st, **{**BASE, "preferred_crew": crew, "assignments": {}, "use_default_for_unassigned": False})
            l02 = next(l for l in self.st["estimate"]["scenarios"]["BASE"]["labor"]["lines"] if l["task_id"] == "L02")
            crew_cost[crew] = l02["extended"]
        self.assertNotEqual(crew_cost["CR13"], crew_cost["CR14"])                          # each crew's own cost, no mean of the two

    def test_before_a_crew_is_selected_there_is_no_total_and_the_provisional_is_labeled(self):
        st = H.start(H.fixture())
        self.assertIsNone(st["estimate"])
        st2 = copy.deepcopy(self.st)
        st2["crew_plan"] = None
        wf._advance(st2)
        self.assertIsNone(st2["estimate"])
        self.assertIn("CREW_PLAN_REQUIRED", [e["code"] for e in st2["exceptions"] if e["severity"] == "blocking"])
        prov = integration.view(st2)["provisional"]
        self.assertTrue(prov.get("provisional") or "PROVISIONAL" in str(prov).upper())


if __name__ == "__main__":
    unittest.main()
