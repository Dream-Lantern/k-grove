from pathlib import Path
from test_pipeline import project,DeterministicTestValidator
from doc_review.agents import Mock
from doc_review.engine import Engine

def test_soft_validator_failure_returns_to_editor(project,tmp_path):
    class Feedback(Mock):
        def invoke(self,role,work,payload,directory):
            r,m=super().invoke(role,work,payload,directory)
            if role=='reviewer' and payload['phase']=='RE_REVIEW' and not payload['validation']['ok']:
                f={'finding_id':'P2-001','severity':'P2','category':'format','section':'调用过程','location':{'line_start':20,'line_end':20,'quote':'<!-- NEEDS_EXAMPLE -->'},'problem':'SIMULATED format gate','evidence':'validator failed','sources':[],'suggested_fix':'local fix','acceptance':'validator passes','risk':'LOW','requires_human':False}
                r.update(decision='FAIL',findings=[f],resolutions=[{'finding_id':'P2-001','status':'INTRODUCED','reason':'validator evidence'}])
            return r,m
    class FailsOnce(DeterministicTestValidator):
        def __call__(self,job,directory):
            result=super().__call__(job,directory)
            if self.calls==1:result.update(ok=False,errors=['SIMULATED build format failure'],hard_failure=False)
            return result
    repo,a=project;b=Feedback('clean');e=Engine(repo,tmp_path/'private',b,FailsOnce(repo))
    j,_=e.create(a,fixture=True);e.drive(j)
    assert j['state']=='PASS_FOR_HUMAN',j['errors']
    assert b.calls==['reviewer','reviewer','editor','reviewer']
