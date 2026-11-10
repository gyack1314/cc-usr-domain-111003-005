import contextlib,json,sqlite3
from pathlib import Path
from .evidence import digest

def record_bytes(record):return (json.dumps(record,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
def record_digest(record):return digest(record_bytes(record))

class Conflict(ValueError):pass
class Store:
    def __init__(self,root,state):
        self.root=Path(root);self.state=Path(state);self.state.mkdir(parents=True,exist_ok=True)
        records=json.loads((self.root/'portal_data/records.json').read_text(encoding='utf-8'))
        self.records={r['id']:r for r in records}
        if len(self.records)!=len(records):raise ValueError('资料编号重复')
        self.config=json.loads((self.root/'portal_data/config.json').read_text(encoding='utf-8'))
        with self.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS drafts (draft_key TEXT PRIMARY KEY, version INTEGER NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, refs TEXT NOT NULL, status TEXT NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS history (draft_key TEXT NOT NULL,version INTEGER NOT NULL,body TEXT NOT NULL,refs TEXT NOT NULL,PRIMARY KEY(draft_key,version))')
    @contextlib.contextmanager
    def connect(self):
        c=sqlite3.connect(self.state/'portal.sqlite3',timeout=10);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()
    def validate_refs(self,refs):
        if not refs:raise ValueError('草稿至少引用一份资料')
        for ref in refs:
            id,sep,sha=ref.partition('@')
            if not sep or id not in self.records:raise ValueError('引用编号不存在')
            if record_digest(self.records[id])!=sha:raise Conflict('资料摘要已经变化')
        if len(refs)!=len(set(refs)):raise ValueError('引用重复')
    def save(self,key,version,title,body,refs):
        if not key or len(key)>80 or not title.strip() or not body.strip():raise ValueError('草稿编号、标题及内容不能为空')
        if len(body)>100000:raise ValueError('草稿正文超出限制')
        self.validate_refs(refs)
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM drafts WHERE draft_key=?',(key,)).fetchone()
            if row and row['title']==title and row['body']==body and json.loads(row['refs'])==refs:return dict(row)
            current=row['version'] if row else 0
            if current!=version:raise Conflict('草稿版本冲突，请重新读取')
            n=current+1
            c.execute('INSERT INTO drafts VALUES(?,?,?,?,?,?) ON CONFLICT(draft_key) DO UPDATE SET version=excluded.version,title=excluded.title,body=excluded.body,refs=excluded.refs,status=excluded.status',(key,n,title,body,json.dumps(refs),'待人工审批'))
            c.execute('INSERT INTO history VALUES(?,?,?,?)',(key,n,body,json.dumps(refs)))
            return dict(c.execute('SELECT * FROM drafts WHERE draft_key=?',(key,)).fetchone())
    def drafts(self):
        with self.connect() as c:return [dict(r) for r in c.execute('SELECT * FROM drafts ORDER BY draft_key')]
    def draft(self,key):
        return next((d for d in self.drafts() if d['draft_key']==key),None)
