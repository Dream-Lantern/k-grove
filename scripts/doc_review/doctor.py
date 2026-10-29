import json,os,platform,shutil,subprocess,sys,uuid
from pathlib import Path
from .agents import Codex,run_command,clean_env,AgentError,classify
from .storage import atomic_json,now,sha
from .workspace import safe_path
from .schemas import obj,arr,enum

def doctor(repo,private,node,probe=False):
    repo=safe_path(repo);private=safe_path(private);folder=private/'doctor'/uuid.uuid4().hex;folder.mkdir(parents=True)
    report={'at':now(),'python':sys.version,'python_ok':sys.version_info>=(3,12),'platform':platform.platform(),'repo':str(repo),'private_root':str(private),'errors':[],'sandbox_probe':'NOT_RUN'}
    for label,args in [('git_status',['git','-C',str(repo),'status','--porcelain=v1']),('node',[node,'--version'])]:
        if label=='node' and not node:report['errors'].append('Node executable missing');continue
        p=subprocess.run(args,capture_output=True,timeout=30,env=clean_env());report[label]=(p.stdout+p.stderr).decode('utf-8',errors='replace')
        if p.returncode:report['errors'].append(label+' failed')
    try:
        cli=Codex()
        for label,args in [('codex_version',[cli.executable,'--version']),('codex_exec_help',[cli.executable,'exec','--help']),('codex_login',[cli.executable,'login','status'])]:
            p=subprocess.run(args,capture_output=True,timeout=30,env=clean_env());text=(p.stdout+p.stderr).decode('utf-8',errors='replace');report[label]=text
            if p.returncode:report['errors'].append(label+' failed')
        for flag in ['--sandbox','--output-schema','--output-last-message','--json','--ephemeral','--ignore-user-config']:
            if flag not in report.get('codex_exec_help',''):report['errors'].append('CLI missing '+flag)
        cli.auth();report['authentication']='ChatGPT only'
        if probe and not report['errors']:
            report['sandbox_probe']=sandbox_probe(cli,folder/'probe')
            if not report['sandbox_probe']['ok']:report['errors'].append('sandbox probe failed; live pipeline disabled; inspect private probe logs')
    except (AgentError,subprocess.SubprocessError,OSError,ValueError) as e:report['errors'].append(str(e))
    report['ok']=report['python_ok'] and not report['errors'] and (not probe or isinstance(report['sandbox_probe'],dict) and report['sandbox_probe'].get('ok',False))
    atomic_json(folder/'doctor.json',report);report['report_path']=str(folder/'doctor.json')
    if probe and report['ok']:
        atomic_json(private/'sandbox-attestation.json',{'cli_version':report['codex_version'].strip(),'at':now(),'probe_path':str(folder/'probe'),'ok':True})
    return report

def sandbox_probe(cli,root):
    if os.name=='nt':return native_windows_probe(cli,root)
    root=Path(root);root.mkdir(parents=True);results=[]
    schema=obj({'inside':enum('WRITE_SUCCEEDED','WRITE_DENIED'),'outside':enum('WRITE_SUCCEEDED','WRITE_DENIED')})
    for role in ['reviewer','editor']:
        folder=root/role;workspace=folder/'workspace';workspace.mkdir(parents=True)
        outside=folder/'outside.txt';outside.write_text('SENTINEL',encoding='utf-8');inside_file=workspace/'inside.txt'
        atomic_json(folder/'schema.json',schema)
        operations=[]
        for label,p in [('INSIDE',inside_file),('OUTSIDE',outside)]:
            operations.append("try { [System.IO.File]::WriteAllText('"+str(p).replace("'","''")+"','PROBE_WRITE'); Write-Output '"+label+"_WRITE_SUCCEEDED' } catch { Write-Output '"+label+"_WRITE_DENIED' }")
        prompt='Sandbox self-test on owned disposable canaries only. Run exactly these PowerShell write attempts through the shell tool, without requesting elevation or changing permissions. Both paths are authorized disposable probe files. Do not use any other tool to write files. Report observed outcome, not an expectation:\n'+'\n'.join(operations)
        rc=run_command(cli.command(workspace,role,folder/'schema.json',folder/'answer.json'),workspace,folder/'process',180,None,prompt)
        text=(folder/'process/stdout.log').read_text(encoding='utf-8',errors='replace')
        commands=[];session=None
        for line in text.splitlines():
            try:
                e=json.loads(line)
                if e.get('type')=='thread.started':session=e.get('thread_id')
                item=e.get('item',{})
                if item.get('type')=='command_execution':commands.append(item.get('command',''))
            except ValueError:pass
        attempted=any('WriteAllText' in c and str(inside_file).replace('\\','/') in c.replace('\\','/') for c in commands) and any('WriteAllText' in c and str(outside).replace('\\','/') in c.replace('\\','/') for c in commands)
        inside_ok=inside_file.exists() and inside_file.read_text(encoding='utf-8')=='PROBE_WRITE'
        outside_ok=outside.read_text(encoding='utf-8')=='SENTINEL'
        ok=rc==0 and bool(session) and attempted and outside_ok and (inside_ok if role=='editor' else not inside_file.exists())
        stderr=(folder/'process/stderr.log').read_text(encoding='utf-8',errors='replace')
        results.append({'role':role,'ok':ok,'exit_code':rc,'session_id':session,'attempted_both':attempted,'inside_written':inside_ok,'outside_unchanged':outside_ok,'error_kind':classify(stderr) if rc else None,'private_logs':str(folder/'process')})
        if not ok:break
    result={'ok':len(results)==2 and all(r['ok'] for r in results),'results':results}
    atomic_json(root/'probe.json',result);return result

def native_windows_probe(cli,root):
    """Exercise the CLI's restricted-token launcher, not an LLM's assertion."""
    root=Path(root);root.mkdir(parents=True);results=[]
    for role,profile in [('reviewer',':read-only'),('editor',':workspace')]:
        folder=root/role;work=folder/'workspace';work.mkdir(parents=True)
        outside=folder/'outside.txt';outside.write_text('SENTINEL',encoding='utf-8');inside_file=work/'inside.txt'
        operations=[]
        for label,p in [('INSIDE',inside_file),('OUTSIDE',outside)]:
            operations.append("try { [IO.File]::WriteAllText('"+str(p).replace("'","''")+"','PROBE_WRITE'); Write-Output '"+label+"_WRITE_SUCCEEDED' } catch { Write-Output '"+label+"_WRITE_DENIED' }")
        args=[cli.executable,'--config','windows.sandbox="unelevated"','sandbox','--permission-profile',profile,'--include-managed-config','--cd',str(work),'powershell.exe','-NoProfile','-NonInteractive','-Command','; '.join(operations)]
        rc=run_command(args,work,folder/'process',60)
        out=(folder/'process/stdout.log').read_text(encoding='utf-8',errors='replace')
        stderr=(folder/'process/stderr.log').read_text(encoding='utf-8',errors='replace')
        inside_written=inside_file.is_file() and inside_file.read_text(encoding='utf-8')=='PROBE_WRITE'
        outside_unchanged=outside.read_text(encoding='utf-8')=='SENTINEL'
        expected='INSIDE_WRITE_SUCCEEDED' if role=='editor' else 'INSIDE_WRITE_DENIED'
        ok=rc==0 and expected in out and 'OUTSIDE_WRITE_DENIED' in out and outside_unchanged and (inside_written if role=='editor' else not inside_file.exists())
        results.append({'role':role,'profile':profile,'ok':ok,'exit_code':rc,'inside_written':inside_written,'outside_unchanged':outside_unchanged,'error_kind':classify(stderr) if rc else None,'private_logs':str(folder/'process')})
        if not ok:break
    result={'method':'Codex native Windows restricted-token sandbox; no model calls','ok':len(results)==2 and all(r['ok'] for r in results),'results':results}
    atomic_json(root/'probe.json',result);return result
