import contextlib,hashlib,json,os,sqlite3,tempfile
from pathlib import Path

def digest(data):return hashlib.sha256(data).hexdigest()

def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=path.parent,prefix='.stage-')
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
            json.dump(value,f,ensure_ascii=False,sort_keys=True,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def manifest(root):
    root=Path(root).resolve();result=[]
    for p in sorted(root.rglob('*')):
        if p.is_symlink():raise ValueError('材料目录不能包含符号链接')
        if p.is_file():
            b=p.read_bytes();result.append({'path':p.relative_to(root).as_posix(),'size':len(b),'sha256':digest(b)})
    return result

def verify(root,entries):
    root=Path(root).resolve();issues=[]
    for entry in entries:
        p=(root/entry['path']).resolve()
        if not p.is_relative_to(root):raise ValueError('材料路径越界')
        if not p.is_file() or p.is_symlink() or digest(p.read_bytes())!=entry['sha256']:issues.append(entry['path'])
    return issues

class Journal:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS notes(seq INTEGER PRIMARY KEY,entry_key TEXT UNIQUE NOT NULL,body TEXT NOT NULL,sha TEXT NOT NULL)')
    @contextlib.contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=10)
        try:
            with c:yield c
        finally:c.close()
    def append(self,key,note):
        body=json.dumps(note,ensure_ascii=False,sort_keys=True);sha=digest(body.encode())
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT seq,sha FROM notes WHERE entry_key=?',(key,)).fetchone()
            if row:
                if row[1]!=sha:raise ValueError('同一进度键不能覆盖不同证据')
                return row[0]
            return c.execute('INSERT INTO notes(entry_key,body,sha) VALUES(?,?,?)',(key,body,sha)).lastrowid
    def read(self):
        with self.connect() as c:return [{'seq':r[0],'key':r[1],'note':json.loads(r[2]),'sha256':r[3]} for r in c.execute('SELECT * FROM notes ORDER BY seq')]
