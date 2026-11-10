import argparse,contextlib,html,json,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs,urlparse,quote
from .store import Store,Conflict,record_digest,record_bytes

def esc(value):return html.escape(str(value),quote=True)
def page(title,content):
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(title)+'</title><style>'
    'body{font:16px/24px "Geist","Microsoft YaHei",sans-serif;margin:0;color:#1e293b;background:#f8fafc}header{padding:24px 32px;border-bottom:1px solid #cbd5e1;background:white}main{max-width:1120px;margin:32px auto;padding:0 24px}h1{font-size:24px;line-height:32px}h2{font-size:20px;line-height:32px}a{color:#1d4ed8}nav{display:flex;gap:16px;flex-wrap:wrap}table{border-collapse:collapse;width:100%;background:white}td,th{padding:12px;text-align:left;border-bottom:1px solid #e2e8f0}input,textarea,select,button{font:inherit;padding:8px;border:1px solid #64748b;border-radius:4px}label{display:block;margin:16px 0}input,textarea{max-width:100%;box-sizing:border-box}textarea{width:100%;min-height:160px}button{cursor:pointer;background:#1d4ed8;color:white}*:focus-visible{outline:3px solid #f59e0b;outline-offset:4px}pre{white-space:pre-wrap;word-break:break-word;padding:16px;background:white;border:1px solid #cbd5e1}small{color:#475569}'
    '</style><header><nav><a href="/">资料目录</a><a href="/drafts">预审草稿</a></nav><small>本地合成业务门户 · 资料引用保留内容指纹 · 审批由负责人执行</small></header><main><h1>'+esc(title)+'</h1>'+content+'</main></html>').encode()

def handler(store):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,status,body,kind='text/html; charset=utf-8',attachment=None):
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store')
            if attachment:self.send_header('Content-Disposition','attachment; filename="'+attachment+'"')
            self.end_headers();self.wfile.write(body)
        def error(self,status,message):self.send(status,page('操作未完成','<p role="alert">'+esc(message)+'</p>'))
        def do_GET(self):
            p=urlparse(self.path);params=parse_qs(p.query);path=p.path
            if path=='/health':return self.send(200,b'{"ready":true}','application/json')
            if path=='/':
                category=params.get('category',[''])[0];query=params.get('q',[''])[0]
                try:index=max(1,int(params.get('page',['1'])[0]))
                except ValueError:return self.error(400,'页码无效')
                rows=[r for r in store.records.values() if (not category or r['category']==category) and (not query or query.lower() in json.dumps(r,ensure_ascii=False).lower())]
                options='<option value="">全部栏目</option>'+''.join('<option'+(' selected' if category==c else '')+'>'+esc(c)+'</option>' for c in store.config['categories'])
                body='<form method="get"><label>资料检索 <input name="q" value="'+esc(query)+'"></label><label>栏目 <select name="category">'+options+'</select></label><button>查找资料</button></form><p data-testid="count">共 '+str(len(rows))+' 份资料</p><table><tr><th>编号</th><th>栏目</th><th>资料标题</th></tr>'
                for r in rows[(index-1)*5:index*5]:body+='<tr data-record-id="'+esc(r['id'])+'"><td>'+esc(r['id'])+'</td><td>'+esc(r['category'])+'</td><td><a href="/record/'+quote(r['id'])+'">'+esc(r['title'])+'</a></td></tr>'
                body+='</table><nav aria-label="资料分页">'
                from urllib.parse import urlencode
                for n in range(1,(len(rows)+4)//5+1):body+='<a href="/?'+esc(urlencode({'q':query,'category':category,'page':n}))+'">第'+str(n)+'页</a>'
                return self.send(200,page(store.config['name'],body+'</nav>'))
            if path.startswith('/document/'):
                id=path.rsplit('/',1)[1]
                if id not in store.records:return self.error(404,'资料不存在')
                base=store.root/'portal_data/documents'
                suffix='.svg' if (base/(id+'.svg')).is_file() else '.txt'
                file=base/(id+suffix)
                return self.send(200,file.read_bytes(),'image/svg+xml' if suffix=='.svg' else 'text/plain; charset=utf-8',id+suffix)
            if path.startswith('/record/') or path.startswith('/attachment/'):
                id=path.rsplit('/',1)[1];r=store.records.get(id)
                if not r:return self.error(404,'资料不存在')
                if path.startswith('/attachment/'):return self.send(200,record_bytes(r),'application/json; charset=utf-8',id+'.json')
                body='<dl><dt>资料编号</dt><dd data-testid="record-id">'+esc(id)+'</dd><dt>修订</dt><dd>'+str(r['revision'])+'</dd><dt>内容摘要</dt><dd data-testid="digest">'+record_digest(r)+'</dd><dt>草稿引用</dt><dd data-testid="reference">'+esc(id)+'@'+record_digest(r)+'</dd></dl><pre data-testid="fields">'+esc(json.dumps(r['fields'],ensure_ascii=False,indent=2))+'</pre><a href="/attachment/'+quote(id)+'" download>下载原始材料</a>'
                body+='<p><a href="/document/'+quote(id)+'" download>下载文书或扫描副本</a></p>'
                return self.send(200,page(r['title'],body))
            if path=='/drafts':
                body='<p>预审草稿不构成审批、对外发布或业务确认。</p><a href="/draft/new">新建草稿</a><ul>'
                for d in store.drafts():body+='<li><a href="/draft/'+quote(d['draft_key'])+'">'+esc(d['title'])+'</a> · '+esc(d['status'])+' · 版本'+str(d['version'])+'</li>'
                return self.send(200,page('预审草稿',body+'</ul>'))
            if path.startswith('/draft/'):
                key=path.rsplit('/',1)[1];d=store.draft(key) if key!='new' else None
                if key!='new' and not d:return self.error(404,'草稿不存在')
                body='<p data-testid="draft-status">'+esc(d['status'] if d else '尚未保存')+'</p><form method="post" action="/draft/save"><label>草稿编号 <input required name="key" value="'+esc(d['draft_key'] if d else '')+'"'+(' readonly' if d else '')+'></label><input type="hidden" name="version" value="'+str(d['version'] if d else 0)+'"><label>标题 <input required name="title" value="'+esc(d['title'] if d else '')+'"></label><label>正文 <textarea required name="body" aria-label="正文">'+esc(d['body'] if d else '')+'</textarea></label><label>资料引用，每行一项 编号@摘要 <textarea required name="refs" aria-label="资料引用，每行一项 编号@摘要">'+esc('\n'.join(json.loads(d['refs'])) if d else '')+'</textarea></label><button>保存预审草稿</button></form>'
                return self.send(200,page('草稿详情',body))
            return self.error(404,'页面不存在')
        def do_POST(self):
            if self.path!='/draft/save':return self.error(404,'不支持该操作')
            try:
                size=int(self.headers.get('Content-Length','0'))
                if size<=0 or size>200000:raise ValueError('表单大小无效')
                form=parse_qs(self.rfile.read(size).decode('utf-8'),keep_blank_values=True)
                value=lambda k:form[k][0]
                refs=[r.strip() for r in value('refs').splitlines() if r.strip()]
                result=store.save(value('key'),int(value('version')),value('title'),value('body'),refs)
                self.send_response(303);self.send_header('Location','/draft/'+quote(result['draft_key']));self.end_headers()
            except Conflict as exc:self.error(409,str(exc))
            except (ValueError,KeyError,UnicodeError) as exc:self.error(400,str(exc))
    return Handler

@contextlib.contextmanager
def serving(root,state,host='127.0.0.1',port=0):
    server=ThreadingHTTPServer((host,port),handler(Store(root,state)));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield 'http://'+host+':'+str(server.server_port)
    finally:server.shutdown();server.server_close();thread.join()

def main():
    parser=argparse.ArgumentParser(description='本地业务门户');parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8765);parser.add_argument('--state',default='state/portal')
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    with serving(root,args.state,args.host,args.port) as url:
        print('门户已启动 '+url,flush=True)
        try:threading.Event().wait()
        except KeyboardInterrupt:pass
if __name__=='__main__':main()
