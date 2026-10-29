"""No writes to source articles; immutable baseline + disposable editor copy."""
import difflib, os, re, shutil, subprocess
from pathlib import Path
import yaml
from .storage import sha, atomic_json

FORBIDDEN=Path('E:/51_tech_note')
class SafetyError(RuntimeError):pass
def safe_path(path):
    p=Path(path).resolve()
    if p==FORBIDDEN or p.is_relative_to(FORBIDDEN):raise SafetyError('private historical notes are forbidden')
    return p
def inside(path,root):
    p=safe_path(path)
    if not p.is_relative_to(safe_path(root)):raise SafetyError('path escapes allowed root')
    return p
def is_link(p):return p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction())
def tree(root):
    root=safe_path(root);result={}
    for base,dirs,names in os.walk(root,followlinks=False):
        for name in dirs+names:
            p=Path(base,name)
            if is_link(p):raise SafetyError(f'link/reparse point forbidden: {p.relative_to(root)}')
            if p.is_file():
                if p.stat().st_nlink>1:raise SafetyError('hardlinked workspace file')
                result[p.relative_to(root).as_posix()]=sha(p)
    return result
def git_files(repo):
    repo=safe_path(repo)
    r=subprocess.run(['git','-C',str(repo),'ls-files','-c','-o','--exclude-standard','-z'],capture_output=True,check=True)
    result={}
    for item in r.stdout.decode('utf-8').split('\0'):
        if not item:continue
        p=inside(repo/item,repo)
        if any(part in {'.git','.codex','node_modules','.tools','.tmp','artifacts','__pycache__','.pytest_cache'} for part in Path(item).parts):continue
        if p.name.startswith('.env') or p.suffix in {'.pem','.key'}:raise SafetyError('tracked secret-like file in source snapshot')
        if not p.is_file():continue
        current=p
        while current!=repo:
            if is_link(current):raise SafetyError('source snapshot contains reparse point')
            current=current.parent
        result[item.replace('\\','/')]=sha(p)
    return result
def make_snapshot(repo,root):
    repo=safe_path(repo);root=safe_path(root);files=git_files(repo)
    for rel in files:
        out=root/rel;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(repo/rel,out)
    if files!=git_files(repo) or files!=tree(root):raise SafetyError('source changed during snapshot')
    return files
class UniqueLoader(yaml.SafeLoader):pass
def unique_mapping(loader,node,deep=False):
    out={}
    for k,v in node.value:
        key=loader.construct_object(k,deep=deep)
        if key in out:raise SafetyError('duplicate frontmatter key')
        out[key]=loader.construct_object(v,deep=deep)
    return out
UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,unique_mapping)
def markdown(path):
    text=Path(path).read_text(encoding='utf-8-sig')
    m=re.match(r'^---\r?\n([\s\S]*?)\r?\n---\r?\n',text)
    if not m:raise SafetyError('missing YAML frontmatter')
    data=yaml.load(m[1],Loader=UniqueLoader)
    if not isinstance(data,dict):raise SafetyError('frontmatter must be a map')
    return data,text[m.end():]
IDENTITY=('id','date','category','collection','series','order','draft','source','layout','permalink','url','slug')
def discover(repo,collection=None,article_id=None):
    records=[]
    for p in sorted((safe_path(repo)/'docs/articles').glob('*.md')):
        fm,_=markdown(p)
        if (not collection or fm.get('collection')==collection) and (not article_id or fm.get('id')==article_id):
            records.append(dict(id=fm['id'],path=p.relative_to(repo).as_posix(),order=fm.get('order',1000),collection=fm.get('collection')))
    if len({r['id'] for r in records})!=len(records):raise SafetyError('duplicate article IDs')
    return sorted(records,key=lambda r:(r['order'],r['id']))
def changes(before,after):return sorted(k for k in set(before)|set(after) if before.get(k)!=after.get(k))
def archive_diff(base,work,target,output):
    a=(base/target).read_text(encoding='utf-8').splitlines(True);b=(work/target).read_text(encoding='utf-8').splitlines(True)
    diff=''.join(difflib.unified_diff(a,b,fromfile='a/'+target,tofile='b/'+target))
    Path(output).write_text(diff,encoding='utf-8');return diff
def check_scope(before,root,allowed):
    after=tree(root);changed=changes(before,after)
    bad=[p for p in changed if p not in allowed]
    if bad:raise SafetyError('out-of-scope changes: '+', '.join(bad))
    for p in allowed:
        if p in before and p not in after:raise SafetyError('deletion of article/resource forbidden')
    return changed,after
