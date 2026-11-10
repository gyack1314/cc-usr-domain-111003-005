import json,tempfile,unittest
from pathlib import Path
from workbench.domain import TOOLS
from workbench.evidence import Journal,atomic_json,digest,manifest,verify
from workbench.store import Store,Conflict,record_digest
ROOT=Path(__file__).resolve().parents[1]

class BaseTests(unittest.TestCase):
    def test_domain_examples(self):
        for name,payload,expected in json.loads((ROOT/'examples/tool_calls.json').read_text(encoding='utf-8')):
            with self.subTest(tool=name):self.assertEqual(TOOLS[name](**payload),expected)
    def test_manifest_detects_change(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'一.txt';p.write_text('甲',encoding='utf-8');entries=manifest(root)
            self.assertEqual(verify(root,entries),[]);p.write_text('乙',encoding='utf-8');self.assertEqual(verify(root,entries),['一.txt'])
            with self.assertRaises(ValueError):verify(root,[{'path':'../escape','sha256':'x'}])
    def test_journal_restart_idempotency(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'j.sqlite3';j=Journal(path);seq=j.append('p1',{'source':'a'})
            self.assertEqual(Journal(path).append('p1',{'source':'a'}),seq)
            with self.assertRaises(ValueError):j.append('p1',{'source':'b'})
            self.assertEqual(len(j.read()),1)
    def test_atomic_json(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'nested/a.json';atomic_json(path,{'中文':1});atomic_json(path,{'中文':2})
            self.assertEqual(json.loads(path.read_text()),{'中文':2});self.assertEqual(list(path.parent.glob('.stage-*')),[])
    def test_draft_evidence_and_version(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(ROOT,d);r=next(iter(store.records.values()));ref=r['id']+'@'+record_digest(r)
            draft=store.save('sample',0,'样例','内容',[ref]);self.assertEqual(draft['version'],1)
            self.assertEqual(Store(ROOT,d).save('sample',0,'样例','内容',[ref])['version'],1)
            with self.assertRaises(Conflict):store.save('sample',0,'样例','其他内容',[ref])
            with self.assertRaises(Conflict):store.save('bad',0,'样例','内容',[r['id']+'@bad'])
            with self.assertRaises(ValueError):store.save('bad',0,'样例','内容',[])
            self.assertEqual(store.draft('sample')['status'],'待人工审批')
    def test_document_identity_and_serialization(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(ROOT,d)
            self.assertGreater(len(store.records),8)
            for r in store.records.values():
                self.assertEqual(len(record_digest(r)),64);self.assertTrue(r['fields']);self.assertIn(r['category'],store.config['categories'])
if __name__=='__main__':unittest.main()
