import contextlib, datetime, hashlib, json, os, sqlite3, uuid
from pathlib import Path

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temp.open('w',encoding='utf-8',newline='\n') as f:
        json.dump(value,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(temp,path)
def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))

class Store:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.root/'state.sqlite',timeout=10)
        self.db.execute('PRAGMA journal_mode=DELETE');self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, article_id TEXT, created TEXT, data TEXT)')
        self.db.commit()
    def save(self,job):
        job['updated_at']=now()
        self.db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?,?,?)',(job['id'],job['article_id'],job['run_started_at'],json.dumps(job,ensure_ascii=False)))
        self.db.commit();atomic_json(Path(job['directory'])/'state.json',job)
    def all(self):return [json.loads(x[0]) for x in self.db.execute('SELECT data FROM jobs ORDER BY created')]
    @contextlib.contextmanager
    def lock(self):
        # OS-backed advisory lock: automatically released even after process death.
        p=self.root/'pipeline.lock';f=p.open('a+b');f.seek(0);f.write(b'0');f.flush();f.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            f.close();raise RuntimeError('another pipeline owns this private state directory')
        try:yield
        finally:
            if os.name=='nt':
                import msvcrt
                f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(f,fcntl.LOCK_UN)
            f.close()
