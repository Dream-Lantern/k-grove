"""Synthetic chapter 6 arithmetic; no model, network, or business environment."""
from fractions import Fraction
from itertools import product
from math import comb
import json


def finite_pass_at_k(n: int, c: int, k: int) -> Fraction:
    if not (0 <= c <= n and 1 <= k <= n):
        raise ValueError('require 0 <= c <= n and 1 <= k <= n')
    return Fraction(1) - Fraction(comb(n - c, k), comb(n, k))


def summarize_campaign(tasks, variants, repeats, runs):
    """Missing and evidence-UNKNOWN remain outside known-result denominators."""
    axes = [tuple(tasks), tuple(variants), tuple(repeats)]
    if any(not axis or len(set(axis)) != len(axis) for axis in axes):
        raise ValueError('axes must be nonempty and unique')
    expected = set(product(*axes))
    actual = {}
    for run in runs:
        key = (run['task'], run['variant'], run['repeat'])
        if key not in expected or key in actual:
            raise ValueError('duplicate or unplanned run')
        if run['verdict'] not in {'PASS', 'FAIL', 'UNKNOWN'}:
            raise ValueError('invalid verdict')
        actual[key] = run['verdict']
    known = {k: v for k, v in actual.items() if v != 'UNKNOWN'}
    per_variant = {}
    for variant in axes[1]:
        values = [v for k, v in known.items() if k[1] == variant]
        per_variant[variant] = {
            'known': len(values), 'successes': values.count('PASS'),
            'success_rate': values.count('PASS') / len(values) if values else None,
        }
    pairs = [(task, repeat) for task, repeat in product(axes[0], axes[2])
             if all((task, variant, repeat) in known for variant in axes[1])]
    return {
        'expected': len(expected), 'executed': len(actual), 'known': len(known),
        'missing': len(expected) - len(actual),
        'executed_unknown': len(actual) - len(known),
        'result_unknown': len(expected) - len(known),
        'run_coverage': len(actual) / len(expected),
        'evidence_coverage': len(known) / len(expected),
        'conditional_evidence_coverage': len(known) / len(actual) if actual else None,
        'per_variant': per_variant,
        'expected_pairs': len(axes[0]) * len(axes[2]),
        'known_pairs': len(pairs),
        'paired_successes': {v: sum(known[(t, v, r)] == 'PASS' for t, r in pairs)
                             for v in axes[1]},
    }


def sample_campaign():
    rows = [('T1', 1, 'PASS', 'PASS'), ('T1', 2, 'FAIL', 'UNKNOWN'),
            ('T1', 3, 'PASS', 'PASS'), ('T2', 1, 'PASS', 'FAIL'),
            ('T2', 2, 'FAIL', 'PASS')]
    runs = [{'task': t, 'variant': v, 'repeat': r, 'verdict': verdict}
            for t, r, a, b in rows for v, verdict in [('A', a), ('B', b)]]
    return ['T1', 'T2'], ['A', 'B'], [1, 2, 3], runs


def token_timeline(request_ms, token_ms):
    """Client-observed individual tokens; final token is completion in this demo."""
    if not token_ms or token_ms[0] < request_ms or any(
            b < a for a, b in zip(token_ms, token_ms[1:])):
        raise ValueError('need nondecreasing observed tokens after request')
    intervals = [b - a for a, b in zip(token_ms, token_ms[1:])]
    return {'ttft_ms': token_ms[0] - request_ms, 'itl_ms': intervals,
            'tpot_ms': sum(intervals) / len(intervals) if intervals else None,
            'e2e_ms': token_ms[-1] - request_ms}


if __name__ == '__main__':
    print(json.dumps({'data_kind': 'synthetic teaching data',
                      'finite_pass_at_2': str(finite_pass_at_k(5, 2, 2)),
                      'campaign': summarize_campaign(*sample_campaign()),
                      'timeline': token_timeline(0, [400, 460, 550, 700])}, indent=2))
