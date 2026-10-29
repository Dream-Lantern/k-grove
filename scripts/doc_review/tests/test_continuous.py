from pathlib import Path
import pytest
from test_pipeline import project,TEMPLATE,DeterministicTestValidator
from doc_review.agents import Mock
from doc_review.engine import Engine
from doc_review.continuous import create_queue,drain,retry_environment
from doc_review.workspace import discover,SafetyError

def prepare(project,tmp_path,count=4,scenario='clean'):
    repo,a=project
    for i in range(1,count):
        (repo/f'docs/articles/demo-{i}.md').write_text(TEMPLATE.replace('id: demo-tools',f'id: demo-{i}'),encoding='utf-8')
    backend=Mock(scenario);engine=Engine(repo,tmp_path/'private',backend,DeterministicTestValidator(repo))
    return engine,backend,create_queue(engine,discover(repo),True,3,False)

def test_drain_crosses_three_article_boundary(project,tmp_path):
    engine,b,q=prepare(project,tmp_path);drain(engine,q)
    assert q['state']=='PASS_FOR_HUMAN';assert q['pending']==[];assert q['batch_number']==2
    assert len(q['results'])==4;assert b.calls==['reviewer','reviewer']*4

def test_environment_pause_does_not_start_next_article(project,tmp_path):
    engine,b,q=prepare(project,tmp_path,2,'quota');drain(engine,q)
    assert q['state']=='PAUSED';assert len(b.calls)==1;assert len(q['pending'])==2

def test_explicit_retry_resumes_safe_checkpoint(project,tmp_path):
    engine,b,q=prepare(project,tmp_path,2,'quota');drain(engine,q)
    b.scenario='clean';retry_environment(engine,q);drain(engine,q)
    assert q['state']=='PASS_FOR_HUMAN';assert not q['pending']

def test_resume_refuses_changed_confirmed_article(project,tmp_path):
    engine,b,q=prepare(project,tmp_path,1)
    p=engine.repo/q['articles'][0]['path'];p.write_text(TEMPLATE+'\nmanual change\n',encoding='utf-8')
    drain(engine,q);assert q['state']=='PAUSED';assert not b.calls

def test_new_queue_cannot_replace_live_queue(project,tmp_path):
    engine,b,q=prepare(project,tmp_path,1)
    with pytest.raises(SafetyError):create_queue(engine,discover(engine.repo),True,3,False)

def test_retry_blocked_initial_review_does_not_enter_editor(project,tmp_path):
    engine,b,q=prepare(project,tmp_path,1,'unverified')
    article=q['articles'][0];job,_=engine.create(article,fixture=True)
    engine.drive(job);job['stop_batch']=True;engine.store.save(job)
    q['current_job']=job['id'];q['state']='PAUSED'
    b.scenario='clean';retry_environment(engine,q);drain(engine,q)
    assert b.calls==['reviewer','reviewer','reviewer'];assert q['state']=='PASS_FOR_HUMAN'
