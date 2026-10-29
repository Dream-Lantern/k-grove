"""Synthetic approval/identity lesson. No benchmark worker, endpoint, or API call."""
from copy import deepcopy
import hashlib
import json
import math


def candidate_plan():
    return {'model': 'DemoLLM', 'goal': 'MAX_THROUGHPUT', 'dataset': 'Synthetic Dataset',
            'input_tokens': 128, 'output_tokens': 128, 'concurrency': [1, 2, 4],
            'measurement_seconds_per_point': 30, 'approval_required': True,
            'slo': {'p95_ttft_ms_lte': 300, 'error_rate_lte': .01}}


def plan_hash(plan):
    raw = json.dumps(plan, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


class SimulatedController:
    """Approval hash and permissions come from a simulated trusted caller.

    Does not authenticate a human, persist data, solve atomic deduplication, or
    execute benchmarks. RUNNING below is a protocol fixture, never a real receipt.
    """
    def __init__(self, plan):
        if plan != candidate_plan():
            raise ValueError('this lesson only accepts the frozen synthetic input')
        self.plan = deepcopy(plan)
        self.identity = plan_hash(self.plan)
        self.state = 'CANDIDATE'
        self.approval = None
        self.executions = {}

    def approve(self, approved_hash):
        if approved_hash != self.identity or plan_hash(self.plan) != self.identity:
            raise ValueError('approval is not bound to this exact plan')
        self.approval, self.state = approved_hash, 'APPROVED'

    def simulate_start(self, *, approval_hash, can_execute, idempotency_key):
        if (not can_execute or self.approval is None or approval_hash != self.approval
                or plan_hash(self.plan) != self.identity):
            raise PermissionError('no matching approval/permission for unchanged plan')
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise ValueError('stable business key required')
        prior = self.executions.get(idempotency_key)
        if prior:
            if prior['plan_hash'] != self.identity:
                raise ValueError('idempotency conflict')
            return deepcopy(prior)
        execution = {'execution_id': f'sim-exec-{len(self.executions)+1}',
                     'plan_hash': self.identity, 'status': 'RUNNING', 'simulated': True}
        self.executions[idempotency_key] = execution
        return deepcopy(execution)


def assess_slo(metrics):
    if not isinstance(metrics, dict):
        return 'UNKNOWN'
    keys = ('p95_ttft_ms', 'error_rate', 'output_tokens_per_second')
    if any(type(metrics.get(k)) not in (int, float) or not math.isfinite(metrics[k]) for k in keys):
        return 'UNKNOWN'
    if metrics['p95_ttft_ms'] < 0 or not 0 <= metrics['error_rate'] <= 1 or metrics['output_tokens_per_second'] < 0:
        return 'UNKNOWN'
    return 'PASS' if metrics['p95_ttft_ms'] <= 300 and metrics['error_rate'] <= .01 else 'FAIL'


def demo():
    controller = SimulatedController(candidate_plan())
    try:
        controller.simulate_start(approval_hash=controller.identity, can_execute=True, idempotency_key='request-1')
        before_approval = 'UNEXPECTED'
    except PermissionError:
        before_approval = 'REJECTED'
    controller.approve(controller.identity)
    first = controller.simulate_start(approval_hash=controller.identity, can_execute=True, idempotency_key='request-1')
    second = controller.simulate_start(approval_hash=controller.identity, can_execute=True, idempotency_key='request-1')
    return {'data_kind': 'simulated approvals and states; NO benchmark executed',
            'candidate': controller.plan, 'formal_plan_hash': controller.identity,
            'before_approval': before_approval, 'after_approval': controller.state,
            'same_execution_on_retry': first == second,
            'execution_fixture': first,
            'missing_metrics': assess_slo({})}


if __name__ == '__main__':
    print(json.dumps(demo(), ensure_ascii=False, indent=2))
