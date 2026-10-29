import json, os, re, shutil, subprocess
import yaml
from pathlib import Path
from .agents import run_command, AgentError, clean_env, classify
from .storage import atomic_json,sha
from .workspace import markdown,IDENTITY,check_scope,tree,changes,SafetyError,inside

class Validator:
    def __init__(self,repo,node=None,timeout=300,cancel=None,build=True):
        self.repo=Path(repo);self.node=node or shutil.which('node.exe') or shutil.which('node');self.timeout=timeout;self.cancel=cancel;self.build=build
    def __call__(self,job,directory):
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True);errors=[];results={}
        work=Path(job['workspace']);base=Path(job['baseline']);target=job['article_path']
        try:
            changed,after=check_scope(job['baseline_manifest'],work,{target})
            results['changed_files']=changed
            old,_=markdown(base/target);new,body=markdown(work/target)
            for key in IDENTITY:
                if old.get(key)!=new.get(key):errors.append('identity/publication metadata changed: '+key)
            old_headings=re.findall(r'^#{1,6}\s+(.+)$',markdown(base/target)[1],re.M)
            new_headings=re.findall(r'^#{1,6}\s+(.+)$',body,re.M)
            # Existing headings retain their anchors/order; new subheadings may be added.
            cursor=0
            for heading in old_headings:
                try:cursor=new_headings.index(heading,cursor)+1
                except ValueError:errors.append('existing heading/anchor removed or renamed: '+heading)
            old_refs=[s.rstrip('。，；、') for s in re.findall(r'https?://[^\s<>)\"\'`]+',(base/target).read_text(encoding='utf-8'))]
            new_text=(work/target).read_text(encoding='utf-8')
            if any(x not in new_text for x in old_refs):errors.append('original external reference removed')
            diagram_ref=r'!?\[[^\]\n]*\]\(([^)\n]+\.(?:svg|png|jpe?g|webp|gif|mmd|drawio|dot)(?:[?#][^)\n]*)?)\)'
            if re.findall(diagram_ref,(base/target).read_text(encoding='utf-8'))!=re.findall(diagram_ref,new_text):errors.append('diagram/image references changed without human confirmation')
            old_diagrams=re.findall(r'```mermaid[^\n]*\n[\s\S]*?\n```',markdown(base/target)[1])
            new_diagrams=re.findall(r'```mermaid[^\n]*\n[\s\S]*?\n```',body)
            if old_diagrams!=new_diagrams:errors.append('Mermaid diagram changed without human authorization')
            opened=None
            for line in body.splitlines():
                m=re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$',line)
                if m:
                    if not opened:opened=m[1]
                    elif m[1][0]==opened[0] and len(m[1])>=len(opened) and not m[2].strip():opened=None
            if opened:errors.append('unclosed fenced code block')
            if any(pat in body for pat in ['E:\\51_tech_note','E:/51_tech_note']):errors.append('private historical path in article')
        except (SafetyError,ValueError,OSError,yaml.YAMLError) as e:errors.append(str(e))
        if not errors:
            rc=run_command([self.node,str(self.repo/'scripts/doc_review/inspect.mjs'),str(work),target],work,directory/'markdown',self.timeout,self.cancel)
            try:
                check=json.loads((directory/'markdown/stdout.log').read_text(encoding='utf-8-sig'));results['markdown']=check
                if rc or not check['ok']:errors.extend(check.get('errors',['Markdown validator failed']))
            except (ValueError,KeyError):errors.append('Markdown validator returned invalid output')
        if not errors and self.build:
            results['build']=self.build_site(work,directory/'build')
            if results['build']['exit_code']:errors.append('VitePress/npm docs:build failed; see private build logs')
        elif not self.build:results['build']={'status':'NOT_RUN_TEST_DOUBLE'}
        hard_markers=['out-of-scope','identity/publication','original external reference','diagram/image references','Mermaid diagram changed','existing heading/anchor','link/reparse','hardlinked','deletion','duplicate frontmatter','missing YAML','不存在的资源']
        results.update(ok=not errors,errors=errors,hard_failure=any(any(marker in e for marker in hard_markers) for e in errors))
        atomic_json(directory/'validation.json',results);return results
    def build_site(self,work,directory):
        # Build has its own copy. Neither agents nor build scripts write source repo.
        directory=Path(directory);build=directory/'site';directory.mkdir(parents=True,exist_ok=True)
        shutil.copytree(work,build)
        deps=self.repo/'node_modules'
        if not deps.is_dir():return {'exit_code':1,'error':'repository dependencies missing'}
        link=build/'node_modules'
        if os.name=='nt':
            # Exact trusted paths only. Junction is confined to validator copy, never agent workspace.
            if any(re.search(r'[&|<>^%!\r\n]',str(p)) for p in [link,deps]):return {'exit_code':1,'error':'unsafe Windows junction path; refusing shell metacharacters'}
            p=subprocess.run(['cmd.exe','/d','/c','mklink','/J',str(link),str(deps)],capture_output=True)
            if p.returncode:return {'exit_code':1,'error':'cannot prepare validation dependency junction'}
        else:link.symlink_to(deps,target_is_directory=True)
        npm=self.repo/'.tools/package/bin/npm-cli.js'
        if not npm.is_file():
            npmcmd=shutil.which('npm')
            if not npmcmd:return {'exit_code':1,'error':'npm missing'}
            args=[npmcmd,'run','docs:build']
        else:args=[self.node,str(npm),'run','docs:build']
        env=clean_env();env['PATH']=str(Path(self.node).parent)+os.pathsep+str(self.repo/'.tools/bin')+os.pathsep+env.get('PATH','')
        env['TEMP']=str(directory);env['TMP']=str(directory);env['BLOG_BASE']='/k-grove/'
        rc=run_command(args,build,directory/'process',self.timeout,self.cancel,env=env)
        stdout=(directory/'process/stdout.log').read_text(encoding='utf-8',errors='replace')[-12000:]
        stderr=(directory/'process/stderr.log').read_text(encoding='utf-8',errors='replace')[-12000:]
        return {'exit_code':rc,'site':str(build),'logs':str(directory/'process'),'base':'/k-grove/','stdout_tail':stdout,'stderr_tail':stderr,'error_kind':'PERMISSION' if rc and classify(stderr)=='PERMISSION' else None}
