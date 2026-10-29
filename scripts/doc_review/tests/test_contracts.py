import copy,json,subprocess,sys
from pathlib import Path
import pytest
from doc_review.agents import Mock,AgentError
from doc_review.schemas import POLICY,InvalidOutput,semantic_review
from doc_review.workspace import SafetyError,sha,tree
from doc_review.storage import atomic_json
from doc_review.engine import Engine
from test_pipeline import project,setup,DeterministicTestValidator,TEMPLATE

def test_false_pass_with_open_finding_rejected(project,tmp_path):
    e,j,b,v=setup(project,tmp_path);r,_=b.invoke('reviewer',Path(j['workspace']),e.payload(j,'INITIAL'),Path(j['directory'])/'manual');r['decision']='PASS'
    with pytest.raises(InvalidOutput):semantic_review(r,j['article_id'],j['original_sha256'],j['current_sha256'],0,'INITIAL')

def test_missing_resolution_rejected(project,tmp_path):
    e,j,b,v=setup(project,tmp_path);prior=e.call(j,'reviewer','INITIAL')
    j['review']=prior;j['review_round']=1
    r,_=Mock('clean').invoke('reviewer',Path(j['workspace']),e.payload(j,'RE_REVIEW'),Path(j['directory'])/'manual')
    r['resolutions']=[]
    with pytest.raises(InvalidOutput):semantic_review(r,j['article_id'],j['original_sha256'],j['current_sha256'],1,'RE_REVIEW',prior)

def test_source_mutation_during_review_detected(project,tmp_path):
    class BadReviewer(Mock):
        def invoke(self,role,work,payload,directory):
            r,m=super().invoke(role,work,payload,directory)
            (work/payload['target']).write_text('bad',encoding='utf-8');return r,m
    repo,a=project;b=BadReviewer('clean');engine=Engine(repo,tmp_path/'private',b,DeterministicTestValidator(repo))
    j,_=engine.create(a,fixture=True);engine.drive(j)
    assert j['state']=='NEEDS_HUMAN';assert b.calls==['reviewer']

def test_changed_policy_invalidates(project,tmp_path):
    e,j,b,v=setup(project,tmp_path);j['policy_version']='old';e.store.save(j);e.resume()
    assert e.store.all()[0]['state']=='NEEDS_HUMAN';assert not b.calls

def test_backend_mismatch_cannot_resume(project,tmp_path):
    e,j,b,v=setup(project,tmp_path);j['backend']='codex';e.store.save(j)
    with pytest.raises(SafetyError):e.resume()

def test_editor_incomplete_result_is_not_accepted(project,tmp_path):
    class BadEditor(Mock):
        def invoke(self,role,work,payload,directory):
            r,m=super().invoke(role,work,payload,directory)
            if role=='editor':r['handled']=[]
            return r,m
    repo,a=project;e=Engine(repo,tmp_path/'private',BadEditor(),DeterministicTestValidator(repo))
    j,_=e.create(a,fixture=True);e.drive(j);assert j['state']=='NEEDS_HUMAN'

def test_whitespace_only_edit_is_not_progress(project,tmp_path):
    e,j,b,v=setup(project,tmp_path,'unresolved',3);e.drive(j)
    assert j['review_round']==2;assert j['stagnant_rounds']==2

def test_state_json_mirrors_sqlite(project,tmp_path):
    e,j,b,v=setup(project,tmp_path);e.drive(j)
    saved=json.loads((Path(j['directory'])/'state.json').read_text(encoding='utf-8'))
    assert saved==e.store.all()[0]

def test_quarantine_has_out_of_scope_diff(project,tmp_path):
    e,j,b,v=setup(project,tmp_path,'out_of_scope');e.drive(j)
    diffs=json.loads((Path(j['directory'])/'quarantine-diff.json').read_text(encoding='utf-8'))
    assert any(x['path']=='UNAUTHORIZED.txt' and 'bad' in x['diff'] for x in diffs)

def test_failure_does_not_block_next_article(project,tmp_path):
    repo,a=project
    (repo/'docs/articles/second.md').write_text(TEMPLATE.replace('id: demo-tools','id: second-tools'),encoding='utf-8')
    b=Mock('unresolved');e=Engine(repo,tmp_path/'private',b,DeterministicTestValidator(repo),1)
    first,_=e.create(a,fixture=True);second,_=e.create({'id':'second-tools','path':'docs/articles/second.md'},fixture=True)
    e.drive(first);b.scenario='clean';e.drive(second)
    assert first['state']=='NEEDS_HUMAN';assert second['state']=='PASS_FOR_HUMAN'

def test_cli_schema_every_node_has_explicit_type():
    from doc_review.schemas import REVIEW,EDIT
    def walk(s):
        assert 'type' in s
        if s['type']=='object':
            assert s['additionalProperties'] is False
            assert set(s['required'])==set(s['properties'])
            for sub in s['properties'].values():walk(sub)
        elif s['type']=='array':walk(s['items'])
    walk(REVIEW);walk(EDIT)

def test_builtin_provider_is_not_overridden():
    from doc_review.agents import Codex
    args=Codex(executable='codex.exe').command('workspace','reviewer','schema','result')
    assert not any(x.startswith('model_providers.openai.') for x in args)

def test_completed_cache_does_not_apply_to_another_backend(project,tmp_path):
    e,j,b,v=setup(project,tmp_path);e.drive(j);assert e.cached(project[1],True)
    j['backend']='codex';e.store.save(j)
    assert e.cached(project[1],True) is None

def test_role_models_and_efforts_are_explicit():
    from doc_review.agents import Codex
    cli=Codex(executable='codex.exe')
    for role,effort in [('reviewer','high'),('editor','medium')]:
        args=cli.command('workspace',role,'schema','result')
        assert args[args.index('--model')+1]=='gpt-6.1-sol'
        assert 'model_reasoning_effort="'+effort+'"' in args

def test_agent_configuration_cannot_mutate_a_checkpoint():
    from doc_review.agents import Codex
    cli=Codex(executable='codex.exe');saved=cli.configuration();cli.role_settings['reviewer']['effort']='medium'
    assert saved['roles']['reviewer']['effort']=='high'

def test_write_allowlist_does_not_restrict_authorized_reads(project,tmp_path):
    e,j,b,v=setup(project,tmp_path);payload=e.payload(j,'INITIAL')
    assert payload['write_allowlist']==[j['article_path']]
    assert 'docs/public/**' in payload['read_allowlist']
    assert 'allowed_files' not in payload


def test_windows_backend_survives_ignore_user_config(monkeypatch):
    from doc_review import agents
    monkeypatch.setattr(agents.os, 'name', 'nt')
    for role in ['reviewer','editor']:
        args=agents.Codex(executable='codex.exe').command('workspace',role,'schema','result')
        assert 'windows.sandbox="unelevated"' in args
        assert '--ignore-user-config' in args
        assert args[args.index('--sandbox')+1]==('read-only' if role=='reviewer' else 'workspace-write')

def test_exec_policy_denial_stops_queue():
    from doc_review.agents import classify
    assert classify('Rejected: blocked by policy')=='PERMISSION'

def test_review_requires_all_eight_dimensions(project,tmp_path):
    e,j,b,v=setup(project,tmp_path,'clean')
    r,_=b.invoke('reviewer',Path(j['workspace']),e.payload(j,'INITIAL'),Path(j['directory'])/'manual')
    r['dimension_checks'].pop()
    with pytest.raises(InvalidOutput,match='all eight'):
        semantic_review(r,j['article_id'],j['original_sha256'],j['current_sha256'],0,'INITIAL')

def test_pass_cannot_hide_beginner_gap(project,tmp_path):
    e,j,b,v=setup(project,tmp_path,'clean')
    r,_=b.invoke('reviewer',Path(j['workspace']),e.payload(j,'INITIAL'),Path(j['directory'])/'manual')
    r['dimension_checks'][1]['verdict']='ISSUE'
    with pytest.raises(InvalidOutput,match='dimension check'):
        semantic_review(r,j['article_id'],j['original_sha256'],j['current_sha256'],0,'INITIAL')

def test_both_roles_receive_beginner_rubric():
    from doc_review.agents import make_prompt
    from doc_review.schemas import DIMENSIONS
    for role in ['reviewer','editor']:
        prompt=make_prompt(role,{})
        assert all(d in prompt for d in DIMENSIONS)
        assert 'new to this article' in prompt
        assert 'decision must be BLOCKED' in prompt
