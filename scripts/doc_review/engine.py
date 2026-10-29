import difflib, json, re, shutil, traceback, uuid
from pathlib import Path
from .storage import Store,atomic_json,load,now,sha
from .workspace import safe_path,inside,make_snapshot,tree,check_scope,git_files,archive_diff,SafetyError,changes
from .schemas import POLICY,InvalidOutput,semantic_review,validate,EDIT
from .agents import AgentError,STOP_BATCH,Mock,classify

TERMINAL={'PASS_FOR_HUMAN','NEEDS_HUMAN'}
class Engine:
    def __init__(self,repo,state_dir,backend,validator,max_rounds=2,cancel=None):
        self.repo=safe_path(repo);self.store=Store(safe_path(state_dir));self.backend=backend;self.validator=validator
        if self.store.root.is_relative_to(self.repo):raise SafetyError('private state must be outside repository')
        if max_rounds not in {1,2,3}:raise ValueError('max-rounds must be 1..3')
        self.max_rounds=max_rounds;self.cancel=cancel or (lambda:False)
    def state(self,job,state,**fields):
        job.update(state=state,**fields);job['history'].append({'state':state,'at':now(),'round':job['review_round']});self.store.save(job)
    def cached(self,article,fixture):
        target=inside(self.repo/article['path'],self.repo)
        current=sha(target);backend_name='mock' if isinstance(self.backend,Mock) else 'codex'
        for old in reversed(self.store.all()):
            if old['article_id']==article['id'] and old['original_sha256']==current and old['policy_version']==POLICY and old['state']=='PASS_FOR_HUMAN' and old['fixture']==fixture and old.get('backend')==backend_name and old.get('agent_configuration')==self.backend.configuration():
                p=Path(old['workspace'])/old['article_path']
                if p.is_file() and sha(p)==old['current_sha256']:return old
        return None
    def create(self,article,review_only=False,fixture=False):
        target=inside(self.repo/article['path'],self.repo)
        if not target.is_file():raise SafetyError('target not found')
        current=sha(target)
        old=self.cached(article,fixture)
        if old:return old,True
        uid=uuid.uuid4().hex;directory=self.store.root/'runs'/uid;directory.mkdir(parents=True)
        job={'id':uid,'article_id':article['id'],'article_path':article['path'],'original_sha256':current,'current_sha256':current,'policy_version':POLICY,
          'review_round':0,'reviewer_session_id':None,'editor_session_id':None,'state':'PENDING','findings':[],'remaining_findings':[],
          'validation_results':[],'run_started_at':now(),'run_finished_at':None,'errors':[],'history':[],'sessions':[],
          'directory':str(directory),'baseline':str(directory/'baseline'),'workspace':str(directory/'workspace'),
          'repo':str(self.repo),'review_only':review_only,'fixture':fixture,'max_rounds':self.max_rounds,'stagnant_rounds':0,'reserved_finding_ids':[]}
        job['backend']='mock' if isinstance(self.backend,Mock) else 'codex'
        job['agent_configuration']=self.backend.configuration()
        snapshot=make_snapshot(self.repo,directory/'baseline');shutil.copytree(directory/'baseline',directory/'workspace')
        job.update(source_manifest=snapshot,baseline_manifest=tree(directory/'baseline'),checkpoint_manifest=tree(directory/'workspace'))
        atomic_json(directory/'source-manifest.json',snapshot);self.state(job,'PENDING');return job,False
    def assert_consistent(self,job):
        if job['policy_version']!=POLICY:raise SafetyError('policy changed; old review invalidated; start a new run')
        if job.get('agent_configuration')!=self.backend.configuration():raise SafetyError('agent configuration changed; use matching role models/efforts')
        target=self.repo/job['article_path']
        if not target.is_file() or sha(target)!=job['original_sha256']:raise SafetyError('source SHA256 changed; old review invalidated')
        if git_files(self.repo)!=job['source_manifest']:raise SafetyError('repository changed/concurrent task detected; use a new snapshot')
        if tree(job['baseline'])!=job['baseline_manifest']:raise SafetyError('original snapshot changed')
        if tree(job['workspace'])!=job['checkpoint_manifest']:raise SafetyError('interrupted/unconfirmed workspace writes detected; preserve for human, never overwrite')
    def payload(self,job,phase):
        return {'article_id':job['article_id'],'target':job['article_path'],'original_sha256':job['original_sha256'],'current_sha256':job['current_sha256'],
          'policy_version':POLICY,'round':job['review_round'],'phase':phase,'write_allowlist':[job['article_path']],
          'read_allowlist':['docs/articles/**','docs/public/**','content-config/**','lib/**','governance/content-guide.md','templates/**',job['article_path']],
          'original_article':(Path(job['baseline'])/job['article_path']).read_text(encoding='utf-8'),
          'review':job.get('review'),'validation':job.get('validation'),'diff':job.get('diff',''),
          'reserved_finding_ids':job['reserved_finding_ids'],'fixture':job['fixture']}
    def call(self,job,role,phase):
        self.assert_consistent(job)
        if self.cancel():raise AgentError('CANCELLED','cancel file/operator signal')
        number=len(job['sessions'])+1;folder=Path(job['directory'])/f'{number:02d}-{role}-r{job["review_round"]}-{uuid.uuid4().hex[:8]}'
        try:result,meta=self.backend.invoke(role,Path(job['workspace']),self.payload(job,phase),folder)
        except BaseException:
            if (folder/'session.json').is_file():
                meta=load(folder/'session.json');meta['directory']=str(folder)
                if meta.get('session_id'):
                    job['sessions'].append(meta);job[role+'_session_id']=meta['session_id'];self.store.save(job)
            raise
        if meta['session_id'] in {s['session_id'] for s in job['sessions']}:raise SafetyError('agent session reused')
        job['sessions'].append(meta);job[role+'_session_id']=meta['session_id']
        # A Reviewer attempting a write must never proceed to Editor.
        if role=='reviewer':
            self.assert_consistent(job)
            semantic_review(result,job['article_id'],job['original_sha256'],job['current_sha256'],job['review_round'],phase,job.get('review') if phase=='RE_REVIEW' else None)
            for finding in result['findings']:
                if finding['finding_id'] in job['reserved_finding_ids'] and not any(f['finding_id']==finding['finding_id'] for f in job.get('review',{}).get('findings',[])):
                    raise InvalidOutput('resolved finding ID reused for a new issue')
            job['reserved_finding_ids']=sorted(set(job['reserved_finding_ids'])|{f['finding_id'] for f in result['findings']})
        else:
            validate(result,EDIT)
            for key,expected in [('article_id',job['article_id']),('original_sha256',job['original_sha256']),('input_sha256',job['current_sha256']),('round',job['review_round'])]:
                if result[key]!=expected:raise InvalidOutput('edit identity/hash mismatch: '+key)
            ids=[h['finding_id'] for h in result['handled']]
            if len(ids)!=len(set(ids)) or set(ids)!={f['finding_id'] for f in job['review']['findings']}:raise InvalidOutput('editor omitted/duplicated finding')
            changed,after=check_scope(job['baseline_manifest'],job['workspace'],{job['article_path']})
            actual=changes(job['checkpoint_manifest'],after)
            if set(result['changed_files'])!=set(actual):raise InvalidOutput('editor changed_files disagrees with actual files')
            job['last_edit']=result;job['checkpoint_manifest']=after;job['current_sha256']=sha(Path(job['workspace'])/job['article_path'])
            job['diff']=archive_diff(Path(job['baseline']),Path(job['workspace']),job['article_path'],Path(job['directory'])/'candidate.patch')
            if result['diagram_requests'] or any(h['status']=='HUMAN_REQUIRED' for h in result['handled']):raise AgentError('HUMAN','editor requested human confirmation')
        self.store.save(job);return result
    def finish(self,job,reason=None):
        if reason:job['errors'].append({'at':now(),'reason':reason})
        if reason:
            # Preserve all changed files, including forbidden ones, for local inspection.
            try:
                after=tree(job['workspace']);changed=changes(job['baseline_manifest'],after)
                audit=[]
                for rel in changed:
                    a=Path(job['baseline'])/rel;b=Path(job['workspace'])/rel
                    item={'path':rel,'before_sha256':job['baseline_manifest'].get(rel),'after_sha256':after.get(rel)}
                    try:
                        if max(a.stat().st_size if a.exists() else 0,b.stat().st_size if b.exists() else 0)<=1_000_000:
                            item['diff']=''.join(difflib.unified_diff(a.read_text(encoding='utf-8').splitlines(True) if a.exists() else [],b.read_text(encoding='utf-8').splitlines(True) if b.exists() else [],fromfile='a/'+rel,tofile='b/'+rel))
                    except UnicodeError:item['binary']=True
                    audit.append(item)
                atomic_json(Path(job['directory'])/'quarantine-diff.json',audit)
            except (SafetyError,OSError) as e:atomic_json(Path(job['directory'])/'quarantine-diff.json',{'inspection_error':str(e)})
        job['run_finished_at']=now();self.state(job,'NEEDS_HUMAN' if reason else 'PASS_FOR_HUMAN')
        atomic_json(Path(job['directory'])/'result.json',job)
        if not reason:
            shutil.copy2(Path(job['workspace'])/job['article_path'],Path(job['directory'])/'candidate.md')
            archive_diff(Path(job['baseline']),Path(job['workspace']),job['article_path'],Path(job['directory'])/'candidate.patch')
    def drive(self,job):
        if job['state'] in TERMINAL:return job
        try:
            self.assert_consistent(job)
            if not job.get('review'):
                self.state(job,'REVIEWING');job['review']=self.call(job,'reviewer','INITIAL')
                job['findings']=job['review']['findings'];job['remaining_findings']=job['findings'];self.state(job,'REVIEWED')
                if job['review']['decision']=='BLOCKED':
                    self.finish(job,'initial reviewer requires human')
                    if classify(' '.join(job['review']['limitations']))=='PERMISSION':job['stop_batch']=True;self.store.save(job)
                    return job
                if job['review_only']:
                    job['run_finished_at']=now();self.store.save(job);return job
            while job['state'] not in TERMINAL:
                self.assert_consistent(job)
                if self.cancel():raise AgentError('CANCELLED','cancel requested')
                continuing=job['state'] in {'VALIDATING','RE_REVIEWING'}
                previous=job['review']
                if not continuing and previous['findings']:
                    if job['review_round']>=job['max_rounds']:self.finish(job,'max automatic edit rounds reached');break
                    job['review_round']+=1;self.state(job,'EDITING')
                    self.call(job,'editor','EDIT');self.state(job,'VALIDATING')
                elif not continuing:self.state(job,'VALIDATING')
                validation_dir=Path(job['directory'])/f'validation-r{job["review_round"]}'
                if job['state']!='RE_REVIEWING':
                    # Fresh unique folder prevents accidentally reusing stale build outputs.
                    validation_dir=validation_dir.with_name(validation_dir.name+'-'+uuid.uuid4().hex[:8])
                    job['validation']=self.validator(job,validation_dir);job['validation_results'].append(job['validation']);self.store.save(job)
                    if job['validation'].get('build',{}).get('error_kind')=='PERMISSION':
                        self.finish(job,'PERMISSION: deterministic build cannot run in current host');job['stop_batch']=True;self.store.save(job);break
                    if not job['validation']['ok'] and job['validation'].get('hard_failure',False):self.finish(job,'deterministic hard safety validation failed');break
                    self.assert_consistent(job);self.state(job,'RE_REVIEWING')
                rereview=self.call(job,'reviewer','RE_REVIEW')
                if rereview['decision']=='PASS' and not job['validation']['ok']:raise InvalidOutput('Reviewer PASS cannot override a failed deterministic Validator')
                old_ids={f['finding_id'] for f in previous['findings']};new_ids={f['finding_id'] for f in rereview['findings']}
                resolved={x['finding_id'] for x in rereview['resolutions'] if x['status']=='RESOLVED'}
                weights={'P0':100,'P1':10,'P2':1}
                before_score=sum(weights[f['severity']] for f in previous['findings'])
                after_score=sum(weights[f['severity']] for f in rereview['findings'])
                if old_ids and (not resolved or after_score>=before_score):job['stagnant_rounds']+=1
                else:job['stagnant_rounds']=0
                job['review']=rereview;job['remaining_findings']=rereview['findings'];self.store.save(job)
                if rereview['decision']=='PASS':self.finish(job);break
                if rereview['decision']=='BLOCKED':
                    self.finish(job,'re-review requires human')
                    if classify(' '.join(rereview['limitations']))=='PERMISSION':job['stop_batch']=True;self.store.save(job)
                    break
                if job['stagnant_rounds']>=2:self.finish(job,'two consecutive rounds without issue resolution');break
                self.state(job,'REVIEWED')
        except (AgentError,InvalidOutput,SafetyError,ValueError,OSError) as e:
            self.finish(job,f'{getattr(e,"kind",type(e).__name__)}: {e}')
            if isinstance(e,AgentError) and e.kind in STOP_BATCH:job['stop_batch']=True;self.store.save(job)
            if isinstance(e,SafetyError) and any(x in str(e) for x in ['source SHA256','repository changed','original snapshot']):job['stop_batch']=True;self.store.save(job)
        return job
    def resume(self):
        results=[]
        for job in self.store.all():
            if job['state'] in TERMINAL or job['review_only'] and job.get('run_finished_at'):continue
            if job['repo']!=str(self.repo):continue
            expected='mock' if isinstance(self.backend,Mock) else 'codex'
            if job.get('backend',expected)!=expected:raise SafetyError('resume backend mismatch; specify the original backend explicitly')
            results.append(self.drive(job))
            if results[-1].get('stop_batch'):break
        return results
    def report(self):
        jobs=self.store.all();folder=self.store.root/'reports';folder.mkdir(exist_ok=True)
        uid=uuid.uuid4().hex;out=folder/(uid+'.md')
        text='# 文档质量流水线报告\n\nPASS_FOR_HUMAN 仅表示候选通过自动门禁，不代表已发布或人工验收。主仓库正文从不自动回写。\n\n| 文章 | 模式 | 状态 | 修订轮次 | 原始 SHA256 | 当前 SHA256 |\n|---|---|---|---:|---|---|\n'
        for j in jobs:text+=f'| {j["article_id"]} | {"fixture" if j["fixture"] else "real"} / {"read-only" if j["review_only"] else "candidate"} | {j["state"]} | {j["review_round"]} | {j["original_sha256"]} | {j["current_sha256"]} |\n'
        for j in jobs:
            text+='\n## '+j['article_id']+' / '+j['id']+'\n\n'+str(Path(j['directory']))+'\n\n'
            for e in j['errors']:text+='- '+e['reason']+'\n'
            for f in j['remaining_findings']:text+=f'- {f["finding_id"]} {f["severity"]} {f["section"]}: {f["problem"]}\n'
            for session in j['sessions']:
                usage=json.dumps(session['usage'],ensure_ascii=False) if session.get('usage') is not None else '未提供可靠 Token 记录（模拟调用不计算）'
                text+=f'- {session["role"]} session `{session["session_id"]}`；usage：{usage}\n'
        out.write_text(text,encoding='utf-8');atomic_json(folder/(uid+'.json'),jobs);atomic_json(self.store.root/'latest-report.json',{'markdown':str(out),'json':str(folder/(uid+'.json'))});return out
