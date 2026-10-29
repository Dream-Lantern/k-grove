"""Narrow local teaching contract, NOT the upstream checker or production gate.

trusted_records is supplied out of band by the simulated adapter/test harness.
This module cannot establish provenance/authentication or query real state.
"""
from copy import deepcopy
import json


def json_equal(left, right):
    # JSON primitive types stay distinct: in particular True is not integer 1.
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(json_equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(json_equal(a, b) for a, b in zip(left, right))
    return left == right


def check_claim(claim, trusted_records):
    def result(verdict, reason):
        return {'verdict': verdict, 'reason': reason}
    required = {'step_id', 'call_id', 'key', 'expected', 'evidence_ids'}
    if not isinstance(claim, dict) or not required <= claim.keys():
        return result('UNKNOWN', 'claim incomplete')
    ids = claim['evidence_ids']
    if (type(claim['step_id']) is not int or not isinstance(ids, list) or not ids
            or any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids))):
        return result('UNKNOWN', 'invalid claim identity or references')
    values = []
    for evidence_id in ids:
        record = trusted_records.get(evidence_id)
        fields = {'evidence_id', 'source', 'call_id', 'step_id', 'key',
                  'value', 'present', 'complete'}
        if not isinstance(record, dict) or not fields <= record.keys():
            return result('UNKNOWN', 'missing adapter evidence')
        if (record['evidence_id'] != evidence_id or record['source'] not in {'tool', 'environment'}
                or record['call_id'] != claim['call_id'] or record['key'] != claim['key']):
            return result('UNKNOWN', 'evidence identity or source mismatch')
        if (type(record['step_id']) is not int or record['step_id'] >= claim['step_id']
                or record['present'] is not True or record['complete'] is not True):
            return result('UNKNOWN', 'future, absent, or incomplete observation')
        values.append(record['value'])
    if any(not json_equal(values[0], value) for value in values[1:]):
        return result('UNKNOWN', 'conflicting adapter evidence needs a business policy')
    if json_equal(values[0], claim['expected']):
        return result('PASS', 'known structured value agrees')
    return result('FAIL', 'known structured value disagrees')


def sample():
    claim = {'step_id': 2, 'call_id': 'call-1', 'key': 'task.status',
             'expected': 'done', 'evidence_ids': ['obs-1']}
    obs = {'evidence_id': 'obs-1', 'source': 'tool', 'call_id': 'call-1',
           'step_id': 1, 'key': 'task.status', 'value': 'done',
           'present': True, 'complete': True}
    return claim, obs


def demo():
    claim, obs = sample()
    conflicting = deepcopy(obs)
    conflicting['value'] = 'failed'
    model_claim = {**claim, 'source': 'tool', 'assertion': 'already done'}
    return [check_claim(claim, {'obs-1': obs}),
            check_claim(claim, {'obs-1': conflicting}),
            check_claim(claim, {}), check_claim(model_claim, {})]


if __name__ == '__main__':
    print(json.dumps({'data_kind': 'synthetic adapter evidence', 'results': demo()}, indent=2))
