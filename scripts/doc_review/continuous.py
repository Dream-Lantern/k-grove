"""Finite, persistent queue drained in small serial batches; never self-retries forever."""
import collections, json, os, shutil, subprocess, sys, time, uuid
from pathlib import Path
from .storage import atomic_json,load,now,sha
from .workspace import SafetyError,safe_path
from .schemas import POLICY

def save_queue(engine,q):
    q['updated_at']=now();atomic_json(engine.store.root/'active-queue.json',q)
    atomic_json(Path(q['directory'])/'queue.json',q)
def create_queue(engine,records,fixture,batch_size,review_only):
    path=engine.store.root/'active-queue.json'
    if path.is_file() and load(path)['state'] in {'RUNNING','PAUSED'}:raise SafetyError('an unfinished persistent queue already exists; use resume --until-complete')
    uid=uuid.uuid4().hex;directory=engine.store.root/'queues'/uid;directory.mkdir(parents=True)
    q={'id':uid,'directory':str(directory),'created_at':now(),'state':'RUNNING','repo':str(engine.repo),'policy_version':POLICY,
      'agent_configuration':engine.backend.configuration(),'fixture':fixture,'review_only':review_only,'batch_size':batch_size,'max_rounds':engine.max_rounds,
      'articles':[{**r,'sha256':sha(engine.repo/r['path'])} for r in records],'pending':[r['id'] for r in records],
      'current_job':None,'results':{},'batch_number':0,'paused_reason':None}
    save_queue(engine,q);return q
def drain(engine,q):
    if q['repo']!=str(engine.repo) or q['policy_version']!=POLICY or q['agent_configuration']!=engine.backend.configuration() or q['max_rounds']!=engine.max_rounds:raise SafetyError('queue repo/policy/role/round configuration mismatch; never silently switch models')
    rows={r['id']:r for r in q['articles']};q['state']='RUNNING';q['paused_reason']=None;save_queue(engine,q)
    while q['pending']:
        q['batch_number']+=1;save_queue(engine,q)
        batch=q['pending'][:q['batch_size']]
        print(json.dumps({'queue':q['id'],'batch':q['batch_number'],'articles':batch,'remaining':len(q['pending'])},ensure_ascii=False),flush=True)
        for article_id in batch:
            if engine.cancel():return pause(engine,q,'CANCELLED; explicit resume after inspecting cancel latch')
            if shutil.disk_usage(engine.store.root).free<5*1024**3:return pause(engine,q,'DISK_LOW; keep at least 5 GiB free; no automatic deletion')
            article=rows[article_id]
            if not (engine.repo/article['path']).is_file() or sha(engine.repo/article['path'])!=article['sha256']:return pause(engine,q,'confirmed source SHA256 changed: '+article_id)
            if q['current_job']:
                saved=next((j for j in engine.store.all() if j['id']==q['current_job']),None)
                if not saved or saved['article_id']!=article_id:return pause(engine,q,'inconsistent current job; human inspection required')
                job=saved
            else:
                job,skipped=engine.create(article,review_only=q['review_only'],fixture=q['fixture'])
                q['current_job']=job['id'];save_queue(engine,q)
                if skipped:q['results'][article_id]={'job_id':job['id'],'state':'PASS_FOR_HUMAN','skipped_unchanged':True}
            engine.drive(job)
            q['results'][article_id]={'job_id':job['id'],'state':job['state'],'round':job['review_round']}
            print(json.dumps({'article_id':article_id,'state':job['state'],'round':job['review_round']},ensure_ascii=False),flush=True)
            if job.get('stop_batch'):
                # Keep the failed row pending; do not automatically retry it.
                return pause(engine,q,'environment/cancellation gate: '+str(job['errors'][-1] if job['errors'] else job['state']))
            q['pending'].remove(article_id);q['current_job']=None;save_queue(engine,q)
        print(engine.report(),flush=True)
    q['state']='AWAITING_HUMAN' if any(r['state']=='NEEDS_HUMAN' for r in q['results'].values()) else 'PASS_FOR_HUMAN'
    q['finished_at']=now();save_queue(engine,q);print(engine.report(),flush=True);return q
def pause(engine,q,reason):
    q['state']='PAUSED';q['paused_reason']=reason;save_queue(engine,q);print(json.dumps({'queue':q['id'],'state':'PAUSED','reason':reason},ensure_ascii=False),flush=True);return q

def retry_environment(engine,q):
    """Explicit operator retry only; unknown writes remain a human boundary."""
    if q['state']!='PAUSED' or not q['current_job']:return
    job=next((j for j in engine.store.all() if j['id']==q['current_job']),None)
    if not job or not job.get('stop_batch'):raise SafetyError('not an environment-stopped job')
    engine.assert_consistent(job)
    if job['state']=='NEEDS_HUMAN':
        phase=next((h['state'] for h in reversed(job['history']) if h['state'] in {'REVIEWING','EDITING','VALIDATING','RE_REVIEWING'}),None)
        if not phase:raise SafetyError('no safe checkpoint for explicit retry')
        job.pop('stop_batch',None);job['run_finished_at']=None
        if phase=='REVIEWING':job.pop('review',None)
        engine.state(job,phase)
    save_queue(engine,q)

def launch(repo,private,arguments):
    """Detached orchestrator, not detached agent children. No visible console."""
    private=safe_path(private);directory=private/'launches'/uuid.uuid4().hex;directory.mkdir(parents=True)
    args=[sys.executable,'-X','utf8',str(Path(__file__).with_name('main.py')),'run',*arguments]
    kwargs={'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}
    with (directory/'stdout.log').open('wb') as out,(directory/'stderr.log').open('wb') as err:
        proc=subprocess.Popen(args,cwd=repo,stdin=subprocess.DEVNULL,stdout=out,stderr=err,shell=False,**kwargs)
    record={'pid':proc.pid,'arguments':args,'started_at':now(),'stdout':str(directory/'stdout.log'),'stderr':str(directory/'stderr.log')}
    atomic_json(directory/'launch.json',record);atomic_json(private/'latest-launch.json',record);return record
