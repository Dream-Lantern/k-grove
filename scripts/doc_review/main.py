#!/usr/bin/env python3
"""CLI entry point. Defaults to simulated articles, never promotes candidates."""
import argparse,json,os,shutil,signal,subprocess,sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
try:
    from doc_review.agents import Codex,Mock,AgentError
    from doc_review.engine import Engine
    from doc_review.validator import Validator
    from doc_review.workspace import discover,sha,safe_path,SafetyError,git_files
    from doc_review.storage import atomic_json,load,now
    from doc_review.schemas import POLICY,REVIEW,EDIT
    from doc_review.doctor import doctor
    from doc_review.continuous import create_queue,drain,launch,retry_environment
except ImportError as e:
    raise SystemExit('Missing dependency. Use Python 3.12+ venv and: python -m pip install -r scripts/doc_review/requirements.txt\n'+str(e))

REPO=Path(__file__).resolve().parents[2]
PRIVATE=Path.home()/'Documents/Codex/doc-review-runs' if os.name=='nt' else Path.home()/'.local/state/doc-review'
def authenticate(backend,private):
    try:backend.auth()
    except (AgentError,OSError,subprocess.SubprocessError) as e:
        atomic_json(private/'preflight'/('auth-'+uuid.uuid4().hex+'.json'),{'at':now(),'state':'NEEDS_HUMAN','kind':getattr(e,'kind','AUTH'),'error':str(e)})
        raise
def live_ready(backend,private):
    authenticate(backend,private)
    att=private/'sandbox-attestation.json'
    if not att.is_file() or not load(att).get('ok'):raise SafetyError('run doctor --probe-sandbox successfully before any live pipeline call')
    version=subprocess.run([backend.executable,'--version'],capture_output=True,timeout=30).stdout.decode('utf-8').strip()
    if load(att)['cli_version'].splitlines()[-1]!=version.splitlines()[-1]:raise SafetyError('CLI version changed; repeat sandbox probe')
def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['doctor','review','run','start','resume','status','report','cancel'])
    parser.add_argument('--repo',type=Path,default=REPO)
    parser.add_argument('--state-dir',type=Path,default=PRIVATE)
    parser.add_argument('--collection');parser.add_argument('--article-id');parser.add_argument('--limit',type=int,default=3)
    parser.add_argument('--max-rounds',type=int,choices=[1,2,3],default=2)
    parser.add_argument('--backend',choices=['codex','mock'],default='codex')
    parser.add_argument('--scenario',choices=['clean','p1','p0','p2','unverified','diagram','unresolved','introduced','out_of_scope','invalid_json','timeout','quota','auth','cancel','permission'],default='p1')
    parser.add_argument('--real',action='store_true',help='discover real docs/articles, not fixtures')
    parser.add_argument('--allow-real-edit',action='store_true',help='explicitly authorize isolated candidate edits for exact selected article/manifest')
    parser.add_argument('--batch-manifest',type=Path,help='confirmed exact article IDs with SHA256; never broad real edits')
    parser.add_argument('--probe-sandbox',action='store_true')
    parser.add_argument('--until-complete',action='store_true',help='drain a frozen, explicitly confirmed manifest in batches <=3')
    parser.add_argument('--retry-environment',action='store_true',help='explicit retry after fixing environment; never overwrite unconfirmed writes')
    parser.add_argument('--reviewer-model',default='gpt-6.1-sol');parser.add_argument('--editor-model',default='gpt-6.1-sol')
    parser.add_argument('--reviewer-effort',choices=['low','medium','high','xhigh','max'],default='high')
    parser.add_argument('--editor-effort',choices=['low','medium','high','xhigh','max'],default='medium')
    parser.add_argument('--timeout',type=int,default=600);parser.add_argument('--node',default=shutil.which('node.exe') or shutil.which('node'))
    args=parser.parse_args(argv)
    if not 1<=args.limit<=3:parser.error('V1 batch limit is 1..3')
    if not 10<=args.timeout<=1800:parser.error('timeout must be 10..1800 seconds')
    repo=safe_path(args.repo);private=safe_path(args.state_dir)
    if private.is_relative_to(repo):parser.error('state/logs must live OUTSIDE website repository')
    private.mkdir(parents=True,exist_ok=True)
    if args.command=='start':
        if not args.until_complete or not args.batch_manifest:raise SafetyError('persistent start requires --until-complete and an explicitly confirmed manifest')
        original=list(sys.argv[1:] if argv is None else argv)
        print(json.dumps(launch(repo,private,original[1:]),ensure_ascii=False,indent=2));return 0
    if args.command=='cancel':
        atomic_json(private/'cancel.json',{'cancel':True});print('Cancellation requested; owned child process tree will stop.');return 0
    cancelled=False
    def on_signal(*_):
        nonlocal cancelled
        cancelled=True
    signal.signal(signal.SIGINT,on_signal)
    if hasattr(signal,'SIGTERM'):signal.signal(signal.SIGTERM,on_signal)
    cancel=lambda:cancelled or (private/'cancel.json').exists()
    if args.command=='doctor':
        result=doctor(repo,private,args.node,args.probe_sandbox);print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['ok'] else 2
    backend=Mock(args.scenario) if args.backend=='mock' or args.command in {'status','report'} else Codex(timeout=args.timeout,cancel=cancel,reviewer_model=args.reviewer_model,editor_model=args.editor_model,reviewer_effort=args.reviewer_effort,editor_effort=args.editor_effort)
    validator=Validator(repo,args.node,min(args.timeout,600),cancel)
    engine=Engine(repo,private,backend,validator,args.max_rounds,cancel)
    if args.command=='status':
        if (private/'active-queue.json').is_file():
            q=load(private/'active-queue.json');print(json.dumps({'queue':q['id'],'state':q['state'],'total':len(q['articles']),'pending':len(q['pending']),'counts':dict(__import__('collections').Counter(r['state'] for r in q['results'].values())),'paused_reason':q.get('paused_reason')},ensure_ascii=False,indent=2))
        print(json.dumps([{'id':j['id'],'article_id':j['article_id'],'state':j['state'],'round':j['review_round'],'source_changed':not (repo/j['article_path']).is_file() or sha(repo/j['article_path'])!=j['original_sha256']} for j in engine.store.all()],ensure_ascii=False,indent=2));return 0
    if args.command=='report':print(engine.report());return 0
    with engine.store.lock():
        if cancel():raise SafetyError('cancel latch present; inspect pending state, then explicitly remove private cancel.json before continuing')
        if args.command=='resume':
            # Resume respects the persisted mode; mock cannot resume real jobs.
            if args.backend=='mock' and any(not j['fixture'] and j['state'] not in {'NEEDS_HUMAN','PASS_FOR_HUMAN'} for j in engine.store.all()):raise SafetyError('mock backend cannot process real articles')
            if args.backend=='codex':live_ready(backend,private)
            if args.until_complete:
                q=load(private/'active-queue.json')
                if args.retry_environment:retry_environment(engine,q)
                result=drain(engine,q);return 2 if result['state']=='PAUSED' else 0
            results=engine.resume()
        else:
            real=args.real or bool(args.article_id) or bool(args.batch_manifest)
            records=discover(repo,args.collection,args.article_id) if real else discover_fixtures(repo,args.collection,args.article_id)
            if not records:raise SafetyError('no matching articles; use real metadata IDs, not assumed filename aliases')
            confirmed=None
            if args.batch_manifest:
                confirmation=load(args.batch_manifest)
                if confirmation.get('policy_version')!=POLICY or confirmation.get('confirmed') is not True:raise SafetyError('batch manifest not explicitly confirmed for current policy')
                confirmed={r['article_id']:r['sha256'] for r in confirmation['articles']}
                if len(confirmed)!=len(confirmation['articles']):raise SafetyError('duplicate manifest IDs')
                records=[r for r in records if r['id'] in confirmed]
                if {r['id'] for r in records}!=set(confirmed):raise SafetyError('manifest article not found')
                if any(sha(repo/r['path'])!=confirmed[r['id']] for r in records):raise SafetyError('confirmed batch SHA256 changed')
                by_id={r['id']:r for r in records};records=[by_id[r['article_id']] for r in confirmation['articles']]
            if real and args.backend=='mock':raise SafetyError('mock backend is prohibited for real articles')
            if real and args.command=='run' and (not args.allow_real_edit or not (args.article_id or confirmed)):raise SafetyError('real edits require --allow-real-edit plus exact article ID or confirmed SHA256 manifest')
            if args.backend=='codex':
                live_ready(backend,private)
            if args.until_complete:
                if real and not args.batch_manifest:raise SafetyError('continuous real execution requires an explicit frozen confirmed manifest')
                q=create_queue(engine,records,not real,args.limit,args.command=='review');result=drain(engine,q)
                return 2 if result['state']=='PAUSED' else 0
            results=[]
            # Persist the complete bounded queue before any paid model call.
            selected=[];skipped_count=0
            for r in records:
                if engine.cached(r,fixture=not real):skipped_count+=1;continue
                selected.append(r)
                if len(selected)==args.limit:break
            if skipped_count:print(json.dumps({'skipped_completed':skipped_count},ensure_ascii=False),flush=True)
            jobs=[]
            for r in selected:
                job,skipped=engine.create(r,args.command=='review',fixture=not real)
                jobs.append((job,skipped))
            for job,skipped in jobs:
                if skipped:results.append(job);continue
                print(json.dumps({'article_id':job['article_id'],'state':'START','mode':'REAL_READ_ONLY' if real and args.command=='review' else 'ISOLATED_CANDIDATE'},ensure_ascii=False),flush=True)
                results.append(engine.drive(job))
                print(json.dumps({'article_id':job['article_id'],'state':job['state'],'round':job['review_round']},ensure_ascii=False),flush=True)
                if job.get('stop_batch'):break
        print(engine.report())
        return 2 if any(j['state']=='NEEDS_HUMAN' for j in results) else 0

def discover_fixtures(repo,collection=None,article_id=None):
    from doc_review.workspace import markdown
    records=[]
    for p in sorted((repo/'scripts/doc_review/fixtures').glob('*.md')):
        fm,_=markdown(p)
        if (not collection or fm.get('collection')==collection) and (not article_id or fm['id']==article_id):records.append({'id':fm['id'],'path':p.relative_to(repo).as_posix(),'order':0})
    return records

if __name__=='__main__':
    try:raise SystemExit(main())
    except (AgentError,SafetyError,ValueError,OSError,RuntimeError,subprocess.SubprocessError) as e:
        print(json.dumps({'state':'NEEDS_HUMAN','error':str(e)},ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
