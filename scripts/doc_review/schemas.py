"""Strict JSON Schemas shared by Codex and the deterministic boundary."""
import json
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker

POLICY = 'doc-review-v1.1'
DIMENSIONS=('technical_accuracy','concept_explanation','mechanism_depth','examples_reasoning',
            'learning_order','practice_validation','diagram_quality','sources')
def obj(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
def arr(items):return {'type':'array','items':items}
def enum(*values):return {'type':'string','enum':list(values)}
TEXT={'type':'string','minLength':1}
HASH={'type':'string','pattern':'^[0-9a-f]{64}$'}
SOURCE=obj({'url':{'type':'string','pattern':'^https?://[^\\s]+$'},'version':TEXT,'checked_at':{'type':'string','pattern':'^20[0-9]{2}-[0-9]{2}-[0-9]{2}$'},
            'verification':enum('SUPPORTED','INSUFFICIENT','CONFLICT','UNVERIFIED'),'basis':TEXT})
FINDING=obj({'finding_id':{'type':'string','pattern':'^P[012]-[0-9]{3,}$'},'severity':enum('P0','P1','P2'),
 'category':enum('technical_accuracy','beginner_clarity','examples','diagrams','organization','sources','format'),
 'section':TEXT,'location':obj({'line_start':{'type':'integer','minimum':1},'line_end':{'type':'integer','minimum':1},'quote':TEXT}),
 'problem':TEXT,'evidence':TEXT,'sources':arr(SOURCE),'suggested_fix':TEXT,'acceptance':TEXT,
 'risk':enum('LOW','MEDIUM','HIGH'),'requires_human':{'type':'boolean'}})
REVIEW=obj({'article_id':TEXT,'original_sha256':HASH,'current_sha256':HASH,'policy_version':{'type':'string','enum':[POLICY]},
 'round':{'type':'integer','minimum':0,'maximum':3},'phase':enum('INITIAL','RE_REVIEW'),
 'decision':enum('PASS','FAIL','BLOCKED'),'summary':TEXT,
 'dimension_checks':arr(obj({'dimension':enum(*DIMENSIONS),'verdict':enum('PASS','ISSUE','UNVERIFIED','NOT_APPLICABLE'),'evidence':TEXT})),
 'findings':arr(FINDING),
 'resolutions':arr(obj({'finding_id':TEXT,'status':enum('RESOLVED','UNRESOLVED','INTRODUCED','HUMAN_REQUIRED'),'reason':TEXT})),
 'diagram_requests':arr(TEXT),'limitations':arr(TEXT)})
EDIT=obj({'article_id':TEXT,'original_sha256':HASH,'input_sha256':HASH,'policy_version':{'type':'string','enum':[POLICY]},
 'round':{'type':'integer','minimum':1,'maximum':3},'summary':TEXT,
 'handled':arr(obj({'finding_id':TEXT,'status':enum('CHANGED','SKIPPED','HUMAN_REQUIRED'),'reason':TEXT})),
 'changed_files':arr(TEXT),'diagram_requests':arr(TEXT)})

class InvalidOutput(ValueError):pass
def validate(value,schema):
    errors=sorted(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(value),key=lambda e:str(e.path))
    if errors:raise InvalidOutput('; '.join(f'{list(e.path)}: {e.message}' for e in errors[:6]))
    return value
def parse_json(path,schema):
    if not Path(path).is_file() or Path(path).stat().st_size>4_000_000:raise InvalidOutput('missing/oversized JSON output')
    def pairs(items):
        result={}
        for k,v in items:
            if k in result:raise InvalidOutput('duplicate JSON field')
            result[k]=v
        return result
    try:return validate(json.loads(Path(path).read_text(encoding='utf-8-sig'),object_pairs_hook=pairs),schema)
    except (UnicodeError,json.JSONDecodeError) as e:raise InvalidOutput(str(e)) from e
def semantic_review(r,article_id,original,current,round_,phase,previous=None):
    validate(r,REVIEW)
    expected={'article_id':article_id,'original_sha256':original,'current_sha256':current,'round':round_,'phase':phase,'policy_version':POLICY}
    if any(r[k]!=v for k,v in expected.items()):raise InvalidOutput('review identity/hash/policy/round mismatch')
    checked=[x['dimension'] for x in r['dimension_checks']]
    if len(checked)!=len(DIMENSIONS) or set(checked)!=set(DIMENSIONS):raise InvalidOutput('all eight review dimensions must be checked exactly once')
    if r['decision']=='PASS' and any(x['verdict'] in {'ISSUE','UNVERIFIED'} for x in r['dimension_checks']):raise InvalidOutput('PASS with unresolved dimension check')
    ids=[f['finding_id'] for f in r['findings']]
    if len(ids)!=len(set(ids)):raise InvalidOutput('duplicate finding ID')
    for f in r['findings']:
        prior_ids={x['finding_id'] for x in (previous or {}).get('findings',[])}
        if (f['finding_id'] not in prior_ids and not f['finding_id'].startswith(f['severity']+'-')) or f['location']['line_end']<f['location']['line_start']:raise InvalidOutput('invalid finding location/severity')
        if f['severity']=='P0' and not any(s['verification'] in {'SUPPORTED','CONFLICT'} for s in f['sources']) and not f['requires_human']:raise InvalidOutput('unverified P0 must require human')
        if f['category']=='diagrams' and f['risk']!='LOW' and not f['requires_human']:raise InvalidOutput('semantic diagram changes require human')
        if f['category']=='technical_accuracy' and not any(s['verification'] in {'SUPPORTED','CONFLICT'} for s in f['sources']) and not f['requires_human']:raise InvalidOutput('unverified factual correction must require human')
        for s in f['sources']:
            from urllib.parse import urlsplit
            from datetime import date
            u=urlsplit(s['url'])
            if u.scheme not in {'http','https'} or not u.hostname:raise InvalidOutput('evidence source must be an HTTP(S) URL')
            try:date.fromisoformat(s['checked_at'])
            except ValueError:raise InvalidOutput('invalid evidence verification date')
    if r['decision']=='PASS' and (r['findings'] or r['diagram_requests']):raise InvalidOutput('PASS with outstanding findings')
    if r['decision']=='FAIL' and not r['findings']:raise InvalidOutput('FAIL without findings')
    if any(f['requires_human'] for f in r['findings']) and r['decision']!='BLOCKED':raise InvalidOutput('human finding must block')
    if previous:
        previous_ids={f['finding_id'] for f in previous['findings']}
        resolutions=r['resolutions'];resolution_ids=[x['finding_id'] for x in resolutions]
        if len(resolution_ids)!=len(set(resolution_ids)):raise InvalidOutput('duplicate resolution')
        if not previous_ids.issubset(set(resolution_ids)):raise InvalidOutput('missing prior finding resolution')
        remaining={x['finding_id'] for x in resolutions if x['status'] in {'UNRESOLVED','HUMAN_REQUIRED','INTRODUCED'}}
        if remaining!=set(ids):raise InvalidOutput('remaining findings must exactly match resolutions')
        for f in r['findings']:
            status=next(x['status'] for x in resolutions if x['finding_id']==f['finding_id'])
            if f['finding_id'] not in previous_ids and status!='INTRODUCED':raise InvalidOutput('new finding not INTRODUCED')
            if f['finding_id'] in previous_ids and status=='INTRODUCED':raise InvalidOutput('prior finding ID reused as new')
        if r['decision']=='PASS' and any(x['status']!='RESOLVED' for x in resolutions):raise InvalidOutput('PASS without resolved prior findings')
    elif r['resolutions']:raise InvalidOutput('initial review cannot have resolutions')
    return r
