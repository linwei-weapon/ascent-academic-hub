import unittest
from unittest.mock import patch
from backend.expert_research import comparators, service


def plan(pid, name, **kw):
    return dict(plan_id=pid,major_name=name,plan_name=name,grade=2022,version='2022',source='real',course_rows=3,**kw)


def course(layer):
    return dict(layer=layer,name='真实课程',mandatory=True)


class ComparatorTests(unittest.TestCase):
    def setUp(self):
        self.plans=[plan('A','名称甲'),plan('B','名称甲相似'),plan('C','完全不同'),plan('D','第四专业')]
        self.courses={'A':{'1':course('main'),'2':course('main'),'P':course('common'),'U':course('unknown')},
                      'B':{'3':course('main'),'P':course('common')},
                      'C':{'1':course('main'),'2':course('main'),'U':course('unknown')},
                      'D':{'1':course('main'),'4':course('main')}}
    def run_recommendation(self, focus='non_common'):
        with patch.object(comparators.analysis,'assert_plan',return_value=self.plans[0]),patch.object(comparators.analysis,'plans',return_value=self.plans),patch.object(comparators.analysis,'courses',side_effect=lambda v,t,i:self.courses[i]),patch.object(comparators.analysis,'document',return_value={}):
            return comparators.recommend(None,None,{},'A',focus)
    def test_uses_courses_not_names(self):
        result=self.run_recommendation()
        self.assertEqual([r['plan_id'] for r in result['candidates']],['C','D'])
        self.assertEqual(result['candidates'][0]['shared'],2)
        self.plans[2]['major_name']='另一个名称';self.plans[2]['plan_name']='名称甲'
        # Distinct professional family is a validity gate, not a scoring feature.
        self.plans[2]['plan_name']='完全无关名字'
        self.assertEqual(self.run_recommendation()['candidates'][0]['plan_id'],'C')
    def test_public_pool_cannot_create_a_match_even_in_all_view(self):
        result=self.run_recommendation('all')
        self.assertEqual(result['focus'],'non_common')
        self.assertNotIn('B',[r['plan_id'] for r in result['candidates']])
    def test_pending_classification_is_excluded_and_disclosed(self):
        r=self.run_recommendation()['candidates'][0]
        self.assertEqual((r['shared'],r['union'],r['source_pending'],r['target_pending']),(2,2,1,1))
    def test_same_cohort_version_and_training_type_only(self):
        self.plans[2]['version']='2023';self.plans[3]['grade']=2023
        self.assertEqual(self.run_recommendation()['candidates'],[])
        self.plans[2]['version']='2022';self.plans[2]['plan_name']='完全不同（全英文）'
        self.assertEqual(self.run_recommendation()['candidates'],[])
    def test_not_filled_with_zero_overlap_results(self):
        self.courses['C']={'P':course('common')};self.courses['D']={'P':course('common')}
        r=self.run_recommendation();self.assertEqual(r['candidates'],[]);self.assertTrue(r['empty_reason'])
    def test_focus_applies_to_both_sides(self):
        self.courses['C']['2']=course('practice')
        r=self.run_recommendation('foundation_main')['candidates'][0]
        self.assertEqual((r['plan_id'],r['shared'],r['union']),('C',1,2))
    def test_unavailable_source_is_not_recommended(self):
        self.plans[2]['source']='demo'
        self.assertNotIn('C',[r['plan_id'] for r in self.run_recommendation()['candidates']])
    def test_permission_filtered_pool_never_reintroduces_other_plans(self):
        self.plans=self.plans[:2]
        r=self.run_recommendation()
        self.assertEqual({p['plan_id'] for p in r['ranking_inputs']},{'A','B'})
        self.assertEqual(r['candidates'],[])
    def test_saved_ranking_inputs_remain_authorization_dependencies(self):
        r=self.run_recommendation()
        self.assertEqual(service.dependency_ids({'comparison_recommendation':r}),{'A','B','C','D'})
    def test_invalid_focus_rejected(self):
        from backend.api.envelope import ApiError
        with self.assertRaises(ApiError):self.run_recommendation('name_similarity')
    def test_explicit_clear_does_not_restore_old_target(self):
        previous={'comparison':{'source':{'plan_id':'A'},'target':{'plan_id':'B'}}}
        self.assertEqual(service.continuation_target({'plan_id':'A','target_plan_id':''},previous),'')
    def test_changed_source_does_not_inherit_another_comparison(self):
        previous={'comparison':{'source':{'plan_id':'A'},'target':{'plan_id':'B'}}}
        self.assertEqual(service.continuation_target({'plan_id':'C'},previous),'')
    def test_omitted_target_preserves_same_source_continuation(self):
        previous={'comparison':{'source':{'plan_id':'A'},'target':{'plan_id':'B'}}}
        self.assertEqual(service.continuation_target({'plan_id':'A'},previous),'B')
