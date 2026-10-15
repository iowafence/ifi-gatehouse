import unittest
from decimal import Decimal as D
from dp001_takeoff_review import reconcile, ceiling_spacing_intermediate

class PublicTakeoffTests(unittest.TestCase):
    def test_g3_unresolved_never_deducted_as_zero(self):
        for name in ('base','alternate_a1'):
            x=reconcile(name)
            self.assertIsNone(x['net_type_a_lf']); self.assertIsNone(x['net_fence_lf'])
            self.assertIsNone(x['total_core_drill_holes'])
            self.assertEqual(x['status'],'BLOCKED_G3_UNRESOLVED')
    def test_preliminary_12ft_assumption_deductions(self):
        a=reconcile('base',D('12')); b=reconcile('alternate_a1',D('12'))
        self.assertEqual((a['gross_fence_lf'],b['gross_fence_lf']),(716,576))
        self.assertEqual((a['net_type_a_lf'],b['net_type_a_lf']),(484,408))
        self.assertEqual((a['net_type_b_lf'],b['net_type_b_lf']),(192,128))
        self.assertEqual((a['net_fence_lf'],b['net_fence_lf']),(676,536))
        self.assertEqual((a['windscreen_south_lf'],b['windscreen_south_lf']),(176,138))
        self.assertEqual((a['fence_guard_type_b_lf'],b['fence_guard_type_b_lf']),(192,128))
    def test_gate_post_count_allocated_to_gate_each(self):
        for name in ('base','alternate_a1'):
            x=reconcile(name,D('12'))
            self.assertEqual(x['type_a_post_count']['gate_posts_total'],8)
            self.assertEqual(x['type_a_post_count']['gate_posts_unknown_size_g3'],2)
            self.assertTrue(x['post_cost_ownership']['count_in_gate_each_not_fence_post_charge'])
    def test_nominal_post_counts_are_conditional(self):
        a=reconcile('base',D('12'));b=reconcile('alternate_a1',D('12'))
        self.assertEqual((a['type_a_post_count']['line'],b['type_a_post_count']['line']),(43,35))
        self.assertEqual((a['type_b_post_count']['line'],b['type_b_post_count']['line']),(18,12))
        self.assertEqual((a['total_core_drill_holes'],b['total_core_drill_holes']),(79,63))
        self.assertIn('PROVISIONAL',a['count_status'])
    def test_exact_post_spacing(self):
        self.assertEqual(ceiling_spacing_intermediate(D('30')),2)
        self.assertEqual(ceiling_spacing_intermediate(D('30.000000001')),2)
        self.assertEqual(ceiling_spacing_intermediate(D('30.01')),3)
        self.assertEqual(ceiling_spacing_intermediate(D('64')),6)
    def test_gate_2_addendum_twelve_foot_not_old_six(self):
        self.assertEqual(reconcile('base',D('12'))['known_gate_openings_lf'],28)
        self.assertEqual(reconcile('base',D('12'))['gates'][1]['clear_ft_each'],12)
    def test_three_court_alternate_not_added_to_base(self):
        self.assertEqual(reconcile('base')['gross_fence_lf'],716)
        self.assertEqual(reconcile('alternate_a1')['gross_fence_lf'],576)
    def test_invalid_g3_assumption_rejected(self):
        for x in ['0','62','-1']:
            with self.assertRaises(ValueError): reconcile('base',D(x))

if __name__ == '__main__': unittest.main()
