import argparse,json
from pathlib import Path
from playwright.sync_api import sync_playwright
from .evidence import atomic_json

def inspect_page(url,directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1280,'height':720},accept_downloads=True);page.goto(url,wait_until='domcontentloaded')
        page.screenshot(path=str(directory/'page.png'),full_page=True)
        result={'url':page.url,'title':page.title(),'text':page.locator('main').inner_text()}
        atomic_json(directory/'page.json',result);browser.close();return result
def main():
    parser=argparse.ArgumentParser(description='单页面阅读存档');parser.add_argument('url');parser.add_argument('directory',type=Path);args=parser.parse_args()
    print(json.dumps(inspect_page(args.url,args.directory),ensure_ascii=False))
if __name__=='__main__':main()
