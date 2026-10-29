import json,os,shutil,subprocess,sys
from pathlib import Path
import pytest
from doc_review.agents import Mock,Codex,AgentError,clean_env,run_command
from doc_review.engine import Engine
from doc_review.storage import atomic_json,sha
from doc_review.schemas import REVIEW,EDIT,POLICY,validate,parse_json,InvalidOutput,semantic_review
from doc_review.workspace import tree,check_scope,markdown,SafetyError,discover,safe_path
from doc_review.validator import Validator
from doc_review.main import main

REPO=Path(__file__).resolve().parents[3]
NODE=shutil.which('node.exe') or shutil.which('node')
TEMPLATE='''---
id: demo-tools
title: 模拟工具文章
description: 模拟文章，不是实际运行日志。
date: '2026-10-29'
updated: '2026-10-29'
category: ai-agent
type: reference
tags: [ai-agent]
draft: true
source: {kind: demo}
collection: ai-agent
---

# 模拟工具文章

## 调用过程

执行器先校验参数，再调用工具。

<!-- NEEDS_EXAMPLE -->
'''
@pytest.fixture
def project(tmp_path):
    root=tmp_path/'repo';(root/'docs/articles').mkdir(parents=True)
    subprocess.run(['git','init','-q',str(root)],check=True)
    p=root/'docs/articles/actual-filename.md';p.write_text(TEMPLATE,encoding='utf-8')
    return root,{'id':'demo-tools','path':'docs/articles/actual-filename.md','order':4}

class DeterministicTestValidator:
    def __init__(self,repo,build_ok=True):self.repo=repo;self.build_ok=build_ok;self.calls=0
    def __call__(self,job,directory):
        self.calls+=1
        result=Validator(REPO,NODE,timeout=30,build=False)(job,directory)
        if not self.build_ok:result.update(ok=False,errors=['SIMULATED build failure'])
        return result
def setup(project,tmp_path,scenario='p1',rounds=2,build_ok=True):
    repo,article=project;backend=Mock(scenario);validator=DeterministicTestValidator(repo,build_ok)
    engine=Engine(repo,tmp_path/'private',backend,validator,rounds)
    job,_=engine.create(article,fixture=True)
    return engine,job,backend,validator

@pytest.mark.parametrize('scenario,edit_count',[('clean',0),('p1',1),('p2',1),('introduced',2)])
def test_success_and_independent_sessions(project,tmp_path,scenario,edit_count):
    engine,job,backend,v=setup(project,tmp_path,scenario)
    original=sha(project[0]/project[1]['path']);engine.drive(job)
    assert job['state']=='PASS_FOR_HUMAN',job['errors']
    assert backend.calls.count('editor')==edit_count
    assert len({s['session_id'] for s in job['sessions']})==len(job['sessions'])
    assert backend.calls[0]==backend.calls[-1]=='reviewer'
    assert sha(project[0]/project[1]['path'])==original
    assert (Path(job['directory'])/'candidate.md').exists()

@pytest.mark.parametrize('scenario',['p0','unverified','diagram','invalid_json','timeout','quota','auth','cancel','permission'])
def test_blockers_never_enter_editor(project,tmp_path,scenario):
    engine,job,backend,v=setup(project,tmp_path,scenario);engine.drive(job)
    assert job['state']=='NEEDS_HUMAN';assert 'editor' not in backend.calls
    if scenario in ['quota','auth','cancel','permission']:assert job['stop_batch']

def test_out_of_scope_quarantined(project,tmp_path):
    engine,job,backend,v=setup(project,tmp_path,'out_of_scope');engine.drive(job)
    assert job['state']=='NEEDS_HUMAN';assert v.calls==0
    assert (Path(job['workspace'])/'UNAUTHORIZED.txt').exists()
    assert not (project[0]/'UNAUTHORIZED.txt').exists()

@pytest.mark.parametrize('rounds,expected',[(1,1),(2,2),(3,2)])
def test_round_limit_and_no_progress(project,tmp_path,rounds,expected):
    engine,job,b,v=setup(project,tmp_path,'unresolved',rounds);engine.drive(job)
    assert job['state']=='NEEDS_HUMAN';assert b.calls.count('editor')==expected

def test_missing_image(project,tmp_path):
    p=project[0]/project[1]['path'];p.write_text(TEMPLATE+'\n![diagram](/assets/missing.png)\n',encoding='utf-8')
    engine,job,b,v=setup(project,tmp_path,'clean');engine.drive(job)
    assert job['state']=='NEEDS_HUMAN'
    assert any('missing.png' in x for x in job['validation']['errors'])

def test_build_failure(project,tmp_path):
    engine,job,b,v=setup(project,tmp_path,'clean',build_ok=False);engine.drive(job)
    assert job['state']=='NEEDS_HUMAN';assert b.calls==['reviewer','reviewer']

def test_source_changed_invalidates_resume(project,tmp_path):
    engine,job,b,v=setup(project,tmp_path)
    p=project[0]/project[1]['path'];p.write_text(TEMPLATE+'\n人工改动\n',encoding='utf-8')
    engine.resume();assert job['id']==engine.store.all()[0]['id']
    assert engine.store.all()[0]['state']=='NEEDS_HUMAN';assert not b.calls
    assert '人工改动' in p.read_text(encoding='utf-8')

def test_interrupted_edit_never_overwrites(project,tmp_path):
    engine,job,b,v=setup(project,tmp_path);engine.state(job,'EDITING')
    p=Path(job['workspace'])/job['article_path'];p.write_text(TEMPLATE+'\n未确认写入\n',encoding='utf-8');current=sha(p)
    engine.resume();assert sha(p)==current
    assert engine.store.all()[0]['state']=='NEEDS_HUMAN';assert not b.calls

def test_validating_resume_does_not_edit_twice(project,tmp_path):
    engine,job,b,v=setup(project,tmp_path)
    job['review']=engine.call(job,'reviewer','INITIAL');job['findings']=job['review']['findings'];job['remaining_findings']=job['findings']
    job['review_round']=1;engine.state(job,'EDITING');engine.call(job,'editor','EDIT');engine.state(job,'VALIDATING')
    b2=Mock('p1');resumed=Engine(project[0],tmp_path/'private',b2,v);resumed.resume()
    assert b2.calls==['reviewer'];assert resumed.store.all()[0]['state']=='PASS_FOR_HUMAN'

def test_completed_hash_policy_skips(project,tmp_path):
    engine,job,b,v=setup(project,tmp_path);engine.drive(job)
    again,skipped=engine.create(project[1],fixture=True);assert skipped;assert again['id']==job['id']
    p=project[0]/project[1]['path'];p.write_text(TEMPLATE+'\nnew source\n',encoding='utf-8')
    again,skipped=engine.create(project[1],fixture=True);assert not skipped;assert again['id']!=job['id']

def test_multifile_serial(project,tmp_path):
    repo,article=project
    (repo/'docs/articles/second.md').write_text(TEMPLATE.replace('id: demo-tools','id: demo-second'),encoding='utf-8')
    backend=Mock('p1');engine=Engine(repo,tmp_path/'private',backend,DeterministicTestValidator(repo))
    jobs=[engine.create(a,fixture=True)[0] for a in discover(repo,'ai-agent')]
    for job in jobs:engine.drive(job)
    assert backend.calls==['reviewer','editor','reviewer']*2
    assert all(j['state']=='PASS_FOR_HUMAN' for j in jobs)

def test_read_only_is_not_acceptance(project,tmp_path):
    repo,article=project;b=Mock('p1');engine=Engine(repo,tmp_path/'private',b,DeterministicTestValidator(repo))
    job,_=engine.create(article,review_only=True,fixture=True);engine.drive(job)
    assert job['state']=='REVIEWED';assert b.calls==['reviewer']

@pytest.mark.parametrize('mutation',["id: changed",'draft: false'])
def test_identity_and_publication_metadata_protected(project,tmp_path,mutation):
    engine,job,b,v=setup(project,tmp_path)
    p=Path(job['workspace'])/job['article_path'];p.write_text(TEMPLATE.replace('id: demo-tools',mutation) if mutation.startswith('id') else TEMPLATE.replace('draft: true',mutation),encoding='utf-8')
    assert not v(job,Path(job['directory'])/'validation')['ok']

def test_mermaid_is_immutable(project,tmp_path):
    repo,a=project;p=repo/a['path'];p.write_text(TEMPLATE+'\n```mermaid\nflowchart LR\n A-->B\n```\n',encoding='utf-8')
    engine,job,b,v=setup(project,tmp_path)
    p=Path(job['workspace'])/job['article_path'];p.write_text(p.read_text(encoding='utf-8').replace('A-->B','B-->A'),encoding='utf-8')
    assert not v(job,Path(job['directory'])/'validation')['ok']

def test_unclosed_fence(project,tmp_path):
    engine,job,b,v=setup(project,tmp_path);p=Path(job['workspace'])/job['article_path'];p.write_text(TEMPLATE+'\n```python\nx=1\n',encoding='utf-8')
    assert not v(job,Path(job['directory'])/'validation')['ok']

def test_json_contract_rejects_extra_and_mismatched_hash(project,tmp_path):
    engine,job,b,v=setup(project,tmp_path);payload=engine.payload(job,'INITIAL');r,_=b.invoke('reviewer',Path(job['workspace']),payload,Path(job['directory'])/'manual')
    r['unexpected']=True
    with pytest.raises(InvalidOutput):validate(r,REVIEW)
    r.pop('unexpected');r['current_sha256']='0'*64
    with pytest.raises(InvalidOutput):semantic_review(r,job['article_id'],job['original_sha256'],job['current_sha256'],0,'INITIAL')

def test_duplicate_json_rejected(tmp_path):
    p=tmp_path/'bad.json';p.write_text('{"article_id":"a","article_id":"b"}',encoding='utf-8')
    with pytest.raises(InvalidOutput):parse_json(p,REVIEW)

def test_auth_key_environment_removed(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','not-a-real-key');monkeypatch.setenv('CODEX_API_KEY','not-a-real-key')
    assert 'OPENAI_API_KEY' not in clean_env();assert 'CODEX_API_KEY' not in clean_env()

def test_cli_has_no_resume_no_bypass_and_least_privilege():
    cli=Codex(executable='codex.exe')
    for role,mode in [('reviewer','read-only'),('editor','workspace-write')]:
        args=cli.command('workspace',role,'schema','result')
        assert args[args.index('--sandbox')+1]==mode
        assert args[-1]=='-';assert 'resume' not in args
        assert not any('bypass' in x or 'danger-full-access' in x for x in args)

def test_cancel_stops_child_process(tmp_path):
    with pytest.raises(AgentError) as e:run_command([sys.executable,'-c','import time; time.sleep(20)'],tmp_path,tmp_path/'logs',10,lambda:True)
    assert e.value.kind=='CANCELLED'

def test_timeout_is_bounded(tmp_path):
    with pytest.raises(AgentError) as e:run_command([sys.executable,'-c','import time; time.sleep(20)'],tmp_path,tmp_path/'logs',.3)
    assert e.value.kind=='TIMEOUT'
    metadata=json.loads((tmp_path/'logs/process.json').read_text(encoding='utf-8'))
    assert metadata['pid']>0;assert metadata['exit_code'] is not None

def test_private_notes_are_always_rejected():
    with pytest.raises(SafetyError):safe_path('E:/51_tech_note/never-read.md')

def test_real_edits_require_explicit_confirmation(project,tmp_path):
    with pytest.raises(SafetyError):main(['run','--repo',str(project[0]),'--state-dir',str(tmp_path/'private'),'--real','--collection','ai-agent','--backend','mock'])

def test_cli_batch_limit():
    with pytest.raises(SystemExit) as e:main(['run','--limit','4'])
    assert e.value.code==2

def test_state_lock(project,tmp_path):
    engine,job,b,v=setup(project,tmp_path)
    from doc_review.storage import Store
    with engine.store.lock():
        with pytest.raises(RuntimeError):
            with Store(tmp_path/'private').lock():pass

def test_frontmatter_duplicate_key(project):
    p=project[0]/project[1]['path'];p.write_text(TEMPLATE.replace('title: 模拟工具文章','id: duplicate\ntitle: 模拟工具文章'),encoding='utf-8')
    with pytest.raises(SafetyError):markdown(p)
