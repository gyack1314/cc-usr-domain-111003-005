import argparse,json,tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from workbench.portal import serving
ROOT=Path(__file__).resolve().parents[1]

def run(screenshot=None):
    with tempfile.TemporaryDirectory() as d,serving(ROOT,Path(d)/'state') as url,sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox']);ctx=browser.new_context(viewport={'width':1280,'height':720},accept_downloads=True)
        page=ctx.new_page();page.goto(url);expect(page.locator('h1')).to_be_visible()
        if screenshot:page.screenshot(path=str(screenshot),full_page=True)
        expect(page.get_by_role('navigation',name='资料分页')).to_be_visible()
        page.get_by_role('link',name='第2页',exact=True).click();expect(page.locator('tr[data-record-id]')).not_to_have_count(0)
        page.locator('tr[data-record-id] a').first.click();id=page.get_by_test_id('record-id').inner_text();ref=page.get_by_test_id('reference').inner_text()
        with page.expect_download() as event:page.get_by_role('link',name='下载原始材料').click()
        f=Path(d)/'source.json';event.value.save_as(f);download=json.loads(f.read_text())
        assert download['id']==id
        import hashlib
        assert ref==id+'@'+hashlib.sha256(f.read_bytes()).hexdigest()
        with page.expect_download() as document_event:page.get_by_role('link',name='下载文书或扫描副本').click()
        document_path=Path(d)/document_event.value.suggested_filename;document_event.value.save_as(document_path);assert document_path.stat().st_size>20
        page.goto(url);page.get_by_label('资料检索').fill(id);page.get_by_role('button',name='查找资料').click()
        expect(page.locator('tr[data-record-id="'+id+'"]')).to_have_count(1)
        page.goto(url+'/draft/new');page.get_by_label('草稿编号').fill('sample');page.get_by_label('标题',exact=True).fill('浏览器样例草稿');page.get_by_label('正文',exact=True).fill('<script>无执行</script>');page.get_by_label('资料引用，每行一项 编号@摘要').fill(ref);page.get_by_role('button',name='保存预审草稿').click()
        expect(page.get_by_test_id('draft-status')).to_have_text('待人工审批');expect(page.get_by_label('正文',exact=True)).to_have_value('<script>无执行</script>')
        other=ctx.new_page();other.goto(url+'/draft/sample');page.get_by_label('正文',exact=True).fill('第一版修订');page.get_by_role('button',name='保存预审草稿').click()
        other.get_by_label('正文',exact=True).fill('过时修订');other.get_by_role('button',name='保存预审草稿').click();expect(other.get_by_role('alert')).to_contain_text('版本冲突')
        page.reload();expect(page.get_by_label('正文',exact=True)).to_have_value('第一版修订')
        page.goto(url+'/draft/new');page.get_by_label('草稿编号').fill('invalid');page.get_by_label('标题',exact=True).fill('无效引用');page.get_by_label('正文',exact=True).fill('样例');page.get_by_label('资料引用，每行一项 编号@摘要').fill(id+'@bad');page.get_by_role('button',name='保存预审草稿').click();expect(page.get_by_role('alert')).to_contain_text('摘要已经变化')
        page.goto(url+'/drafts');expect(page.get_by_role('link',name='浏览器样例草稿')).to_have_count(1);expect(page.get_by_role('link',name='无效引用')).to_have_count(0)
        result={'browser':browser.version,'checks':['目录分页','检索与编号','详情下载摘要一致','草稿持久化','HTML转义','并发编辑冲突','失效引用拒绝','无审批副作用']}
        browser.close();return result
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--screenshot',type=Path);args=parser.parse_args();print(json.dumps(run(args.screenshot),ensure_ascii=False))
