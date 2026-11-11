"""HB-26 门户浏览器取证驱动。

只通过真实 Chromium 页面浏览与下载取证：
- 从门户首页逐页翻取资料目录，点击进入详情页，不直接读取 portal_data 种子文件；
- 详情页提取 编号@SHA256 引用，下载原始材料 JSON 与文书副本，各自独立目录；
- 输出证据清单 evidence.json，供裁决脚本在不接触服务端种子的情况下使用。

用法（隔离模式，路径以参数传入）：
  python3 -I casework/collect.py <门户地址> <证据输出目录>
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description="门户浏览器取证")
    parser.add_argument("base_url")
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    out = args.out_dir.resolve()
    attach_dir = out / "attachments"
    document_dir = out / "documents"
    page_dir = out / "pages"
    for d in (attach_dir, document_dir, page_dir):
        d.mkdir(parents=True, exist_ok=True)

    evidence = {"base_url": base, "records": [], "catalog_pages": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1280, "height": 900},
                                accept_downloads=True)
        # 1) 真实翻页浏览目录，收集详情页链接
        page.goto(base + "/", wait_until="domcontentloaded")
        detail_links = []
        page_no = 0
        while True:
            page_no += 1
            page.screenshot(path=str(page_dir / f"catalog-p{page_no}.png"),
                            full_page=True)
            rows = page.locator("tr[data-record-id]")
            count = rows.count()
            evidence["catalog_pages"].append({
                "page": page_no,
                "count_text": page.get_by_test_id("count").inner_text(),
                "row_count": count,
            })
            for i in range(count):
                rid = rows.nth(i).get_attribute("data-record-id")
                href = rows.nth(i).locator("a").first.get_attribute("href")
                detail_links.append((rid, href))
            next_no = page_no + 1
            next_link = page.get_by_role("link", name=f"第{next_no}页", exact=True)
            if next_link.count() == 0:
                break
            next_link.first.click()
            page.wait_for_load_state("domcontentloaded")

        # 2) 逐条进入详情页取证
        for rid, href in detail_links:
            page.goto(base + href, wait_until="domcontentloaded")
            rec_id = page.get_by_test_id("record-id").inner_text().strip()
            assert rec_id == rid, f"目录编号与详情不一致：{rid} != {rec_id}"
            reference = page.get_by_test_id("reference").inner_text().strip()
            digest_on_page = page.get_by_test_id("digest").inner_text().strip()
            fields_text = page.get_by_test_id("fields").inner_text()
            title = page.locator("h1").inner_text().strip()
            page.screenshot(path=str(page_dir / f"record-{rid}.png"),
                            full_page=True)

            # 下载原始材料 JSON（独立目录）
            with page.expect_download() as ev:
                page.get_by_role("link", name="下载原始材料").click()
            slot = attach_dir / rid
            slot.mkdir(parents=True, exist_ok=True)
            json_path = slot / ev.value.suggested_filename
            ev.value.save_as(str(json_path))
            json_bytes = json_path.read_bytes()
            json_sha = hashlib.sha256(json_bytes).hexdigest()
            record = json.loads(json_bytes.decode("utf-8"))

            # 下载文书/扫描副本（独立目录）
            with page.expect_download() as ev2:
                page.get_by_role("link", name="下载文书或扫描副本").click()
            dslot = document_dir / rid
            dslot.mkdir(parents=True, exist_ok=True)
            doc_path = dslot / ev2.value.suggested_filename
            ev2.value.save_as(str(doc_path))
            doc_sha = sha256_file(doc_path)

            # 页面引用必须与下载字节指纹一致（接口契约：附件即摘要原文）
            expected_ref = f"{rid}@{json_sha}"
            assert reference == expected_ref, f"引用与下载指纹不符：{rid}"
            assert digest_on_page == json_sha, f"页面摘要与下载不符：{rid}"
            assert re.fullmatch(r"[0-9a-f]{64}", digest_on_page)

            evidence["records"].append({
                "id": rid,
                "title": title,
                "category": record["category"],
                "revision": record["revision"],
                "fields": record["fields"],
                "reference": reference,
                "record_json_sha256": json_sha,
                "record_json_path": str(json_path.relative_to(out)),
                "record_json_size": len(json_bytes),
                "document_path": str(doc_path.relative_to(out)),
                "document_sha256": doc_sha,
                "detail_url": base + href,
                "fields_seen_on_page": fields_text,
            })
        browser.close()

    evidence["records"].sort(key=lambda r: r["id"])
    out_path = out / "evidence.json"
    out_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(json.dumps({"records": len(evidence["records"]),
                      "catalog_pages": evidence["catalog_pages"],
                      "evidence": str(out_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
