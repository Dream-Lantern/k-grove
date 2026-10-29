"""Focused tests of chapter arithmetic, byte boundaries, and evidence contract."""
from copy import deepcopy
from fractions import Fraction
import json
import math
import unittest

from copy_audit import audit, demo as copy_demo
from evaluation_demo import finite_pass_at_k, sample_campaign, summarize_campaign, token_timeline
from structured_evidence_demo import check_claim, demo as evidence_demo, sample


class EvaluationTests(unittest.TestCase):
    def test_probability_walkthrough(self):
        p = Fraction(3, 5)
        self.assertEqual(1 - (1-p)**2, Fraction(21, 25))
        self.assertEqual(p**2, Fraction(9, 25))
        self.assertEqual(finite_pass_at_k(5, 2, 2), Fraction(7, 10))
        self.assertNotEqual(finite_pass_at_k(5, 2, 2), 1 - (1-Fraction(2, 5))**2)

    def test_finite_estimator_edges(self):
        self.assertEqual(finite_pass_at_k(5, 0, 2), 0)
        self.assertEqual(finite_pass_at_k(5, 5, 2), 1)
        self.assertEqual(finite_pass_at_k(5, 4, 2), 1)
        with self.assertRaises(ValueError):
            finite_pass_at_k(1, 1, 2)

    def test_coverage_and_known_denominators(self):
        s = summarize_campaign(*sample_campaign())
        self.assertEqual((s['expected'], s['executed'], s['known']), (12, 10, 9))
        self.assertEqual((s['missing'], s['executed_unknown'], s['result_unknown']), (2, 1, 3))
        self.assertAlmostEqual(s['run_coverage'], 10/12)
        self.assertEqual(s['evidence_coverage'], .75)
        self.assertEqual(s['conditional_evidence_coverage'], .9)
        self.assertEqual(s['per_variant']['A']['success_rate'], .6)
        self.assertEqual(s['per_variant']['B']['success_rate'], .75)
        self.assertEqual((s['expected_pairs'], s['known_pairs']), (6, 4))
        self.assertEqual(s['paired_successes'], {'A': 3, 'B': 3})

    def test_missing_does_not_become_failure(self):
        s = summarize_campaign(['T1'], ['A', 'B'], [1], [])
        self.assertEqual(s['result_unknown'], 2)
        self.assertIsNone(s['per_variant']['A']['success_rate'])
        self.assertIsNone(s['conditional_evidence_coverage'])

    def test_duplicate_or_unplanned_rejected(self):
        tasks, variants, repeats, runs = sample_campaign()
        for extra in [runs[0], {**runs[0], 'task': 'T3'}]:
            with self.assertRaises(ValueError):
                summarize_campaign(tasks, variants, repeats, runs + [extra])

    def test_timeline(self):
        self.assertEqual(token_timeline(0, [400, 460, 550, 700]),
                         {'ttft_ms': 400, 'itl_ms': [60, 90, 150], 'tpot_ms': 100, 'e2e_ms': 700})
        self.assertIsNone(token_timeline(0, [400])['tpot_ms'])
        for invalid in [[], [400, 399], [-1]]:
            with self.assertRaises(ValueError):
                token_timeline(0, invalid)

    def test_lora_and_cross_entropy_arithmetic(self):
        self.assertEqual(4096**2, 16777216)
        self.assertEqual(2 * 4096 * 8, 65536)
        self.assertEqual(Fraction(65536, 16777216), Fraction(1, 256))
        self.assertEqual(16/8, 2)
        self.assertAlmostEqual(-math.log(.25), 1.3862943611198906)
        self.assertAlmostEqual(-math.log(.5), .6931471805599453)


class CopyTests(unittest.TestCase):
    def test_prediction_only_strip(self):
        result = audit(' abc\n', 'abc')
        self.assertFalse(result['raw_exact'])
        self.assertTrue(result['normalized_exact'])
        self.assertFalse(audit('abc', ' abc ')['normalized_exact'])

    def test_unicode_is_not_implicitly_normalized(self):
        result = audit('\u00e9', 'e\u0301')
        self.assertFalse(result['raw_exact'])
        self.assertFalse(result['normalized_exact'])
        self.assertTrue(result['nfc_diagnostic_equal'])
        self.assertEqual((result['prediction_bytes'], result['target_bytes']), (2, 3))

    def test_internal_newlines(self):
        result = audit('a\r\nb', 'a\nb')
        self.assertFalse(result['normalized_exact'])
        self.assertEqual(result['raw_first_diff_byte'], 1)

    def test_json_layer_and_identical_bytes(self):
        result = copy_demo()
        self.assertTrue(result['wire_differs_from_unescaped_json'])
        self.assertTrue(result['audits'][3]['raw_exact'])
        self.assertIsNone(result['audits'][3]['raw_first_diff_byte'])
        self.assertEqual(audit('ab', 'abc')['raw_first_diff_byte'], 2)
        self.assertEqual(audit('', '')['raw_first_diff_byte'], None)
        self.assertEqual(json.loads(result['json_wire'])['value'], '中文\né')


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.claim, self.obs = sample()

    def verdict(self, claim=None, obs=None):
        return check_claim(self.claim if claim is None else claim,
                           {'obs-1': self.obs if obs is None else obs})['verdict']

    def test_four_teaching_cases(self):
        self.assertEqual([r['verdict'] for r in evidence_demo()],
                         ['PASS', 'FAIL', 'UNKNOWN', 'UNKNOWN'])

    def test_legal_null_vs_missing(self):
        claim, obs = {**self.claim, 'expected': None}, {**self.obs, 'value': None}
        self.assertEqual(self.verdict(claim, obs), 'PASS')
        self.assertEqual(self.verdict(claim, {**obs, 'present': False}), 'UNKNOWN')
        del obs['value']
        self.assertEqual(self.verdict(claim, obs), 'UNKNOWN')

    def test_identity_time_and_incomplete(self):
        for mutation in [{'call_id': 'wrong'}, {'step_id': 2}, {'step_id': 3},
                         {'complete': False}, {'evidence_id': 'wrong'}, {'key': 'other'},
                         {'source': 'model'}, {'step_id': True}]:
            with self.subTest(mutation=mutation):
                self.assertEqual(self.verdict(obs={**self.obs, **mutation}), 'UNKNOWN')

    def test_self_claim_and_unstructured_input(self):
        self.assertEqual(check_claim({}, {})['verdict'], 'UNKNOWN')
        self.assertEqual(check_claim('完成', {})['verdict'], 'UNKNOWN')
        self.assertEqual(check_claim({**self.claim, 'evidence_ids': []}, {})['verdict'], 'UNKNOWN')
        for statement in ['完成', 'done', '任务 done']:
            self.assertEqual(check_claim({**self.claim, 'assertion': statement}, {})['verdict'], 'UNKNOWN')

    def test_conflicting_trusted_evidence_is_unknown(self):
        claim = {**self.claim, 'evidence_ids': ['obs-1', 'obs-2']}
        registry = {'obs-1': self.obs,
                    'obs-2': {**self.obs, 'evidence_id': 'obs-2', 'value': 'failed'}}
        self.assertEqual(check_claim(claim, registry)['verdict'], 'UNKNOWN')

    def test_no_mutation_and_no_bool_int_equivalence(self):
        claim, obs = deepcopy(self.claim), deepcopy(self.obs)
        self.verdict()
        self.assertEqual((self.claim, self.obs), (claim, obs))
        self.assertEqual(self.verdict({**claim, 'expected': True}, {**obs, 'value': 1}), 'FAIL')


if __name__ == '__main__':
    unittest.main()
