from copy import deepcopy
import unittest

from controlled_plan import SimulatedController, assess_slo, candidate_plan, demo, plan_hash


class PlanTests(unittest.TestCase):
    def test_fixed_input_and_candidate_is_not_execution(self):
        plan=candidate_plan()
        self.assertEqual((plan['model'],plan['goal'],plan['dataset']),
                         ('DemoLLM','MAX_THROUGHPUT','Synthetic Dataset'))
        self.assertEqual((plan['input_tokens'],plan['output_tokens'],plan['concurrency']),
                         (128,128,[1,2,4]))
        self.assertEqual(plan['measurement_seconds_per_point'],30)
        controller=SimulatedController(plan)
        self.assertEqual(controller.state,'CANDIDATE')
        with self.assertRaises(PermissionError):
            controller.simulate_start(approval_hash=controller.identity,can_execute=True,idempotency_key='r1')

    def test_approval_requires_exact_hash_and_permission(self):
        controller=SimulatedController(candidate_plan())
        with self.assertRaises(ValueError): controller.approve('other-plan')
        controller.approve(controller.identity)
        self.assertEqual(controller.state,'APPROVED')
        with self.assertRaises(PermissionError):
            controller.simulate_start(approval_hash=controller.identity,can_execute=False,idempotency_key='r1')

    def test_mutated_plan_requires_new_approval(self):
        controller=SimulatedController(candidate_plan()); controller.approve(controller.identity)
        controller.plan['measurement_seconds_per_point']=60
        with self.assertRaises(PermissionError):
            controller.simulate_start(approval_hash=controller.identity,can_execute=True,idempotency_key='r1')

    def test_retry_reuses_simulated_execution(self):
        controller=SimulatedController(candidate_plan()); controller.approve(controller.identity)
        args={'approval_hash':controller.identity,'can_execute':True,'idempotency_key':'request-1'}
        first=controller.simulate_start(**args); second=controller.simulate_start(**args)
        self.assertEqual(first,second)
        self.assertEqual(len(controller.executions),1)
        self.assertTrue(first['simulated'])
        self.assertEqual(controller.state,'APPROVED')

    def test_same_key_conflicting_fingerprint_rejected(self):
        controller=SimulatedController(candidate_plan()); controller.approve(controller.identity)
        controller.executions['request-1']={'plan_hash':'another-plan','execution_id':'older-fixture'}
        with self.assertRaisesRegex(ValueError,'conflict'):
            controller.simulate_start(approval_hash=controller.identity,can_execute=True,idempotency_key='request-1')

    def test_slo_boundary_failure_and_missing(self):
        self.assertEqual(assess_slo({'p95_ttft_ms':300,'error_rate':.01,'output_tokens_per_second':10}),'PASS')
        self.assertEqual(assess_slo({'p95_ttft_ms':301,'error_rate':0,'output_tokens_per_second':10}),'FAIL')
        self.assertEqual(assess_slo({'p95_ttft_ms':200,'error_rate':.02,'output_tokens_per_second':10}),'FAIL')
        for case in [{}, {'p95_ttft_ms':100,'error_rate':0},
                     {'p95_ttft_ms':float('nan'),'error_rate':0,'output_tokens_per_second':10},
                     {'p95_ttft_ms':True,'error_rate':0,'output_tokens_per_second':10}]:
            self.assertEqual(assess_slo(case),'UNKNOWN')

    def test_json_order_and_source_input_are_stable(self):
        plan=candidate_plan(); snapshot=deepcopy(plan)
        SimulatedController(plan)
        self.assertEqual(plan,snapshot)
        self.assertEqual(plan_hash(plan),plan_hash(dict(reversed(list(plan.items())))))
        self.assertEqual(demo()['before_approval'],'REJECTED')
        self.assertEqual(demo()['missing_metrics'],'UNKNOWN')


if __name__ == '__main__': unittest.main()
