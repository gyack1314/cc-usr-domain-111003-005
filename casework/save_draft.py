"""通过真实浏览器在门户保存 HB-26 封版意见草稿，并回读校验。

- 仅使用门户页面表单（GET /draft/new、POST /draft/save），不直接写 SQLite；
- 草稿正文含已确认条款、阻止封版冲突、隔离去向与显眼待确认标记；
- 引用全部使用浏览器取证得到的 编号@SHA256，保存后回读并逐条比对本地证据；
- 重复运行：若草稿已存在则先回读当前版本号再提交（门户对相同内容幂等）。

用法：
  python3 -I casework/save_draft.py <门户地址> <evidence.json> <determination.json> <草稿key> <截图目录>
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def build_body(det: dict) -> str:
    sd = det["seal_decision"]
    lines = [
        f"项目 {det['project']} 封版意见（预审草稿·未签章·未投递）",
        f"封版截止：{det['seal_cutoff']}；唯一正式发文单位：{det['authorized_issuer']}",
        "",
        "【封版结论】阻止封版 BLOCKED：存在同权限、同生效时点且无明确取代关系的未决冲突，"
        "须投标负责人人工裁决后方可签章；系统不自动签章、不提交、不宣称中标（R7/R8）。",
        "",
        "一、已确认有效要求（来源链见文末引用）：",
    ]
    for k, v in sorted(sd["confirmed_clauses"].items()):
        lines.append(f"  - {k} = {v}")
    lines += [f"  - 现行报价附件 = {sd['active_attachment']}（ANN-1 由 A3 明确更换）",
              "",
              "二、阻止封版的具体位置（保留冲突，不臆造统一口径）："]
    for c in det["merge"]["open_conflicts"]:
        vals = "；".join(f"{i} 主张 {v}" for i, v in c["claimed_values"].items())
        lines.append(f"  - 冲突条款 {c['target']}（生效 {c['effective']}）：{vals}")
        for loc in c["block_locations"]:
            lines.append(f"      阻止位置：{loc}")
        lines.append("      【待负责人确认·阻止封版】裁决前正文与附件的 warranty 一律冻结，"
                     "不得签章；裁决后须同步重出两份副本。")
    lines += ["", "三、独立去向（不写入本次封版口径）："]
    for q in det["quarantine"]:
        lines.append(f"  - {q['id']}｜{q['title']}：{q['reason']}；去向：{q['effect']}")
    lines += ["", "四、撤回链：",
              "  - W4 在截止前明确撤回 A4，A4 不产生效力，acceptance 维持 T0 现场验收（R4）。",
              "",
              "五、效力边界：",
              "  - Q1 为未盖章供应商问答，无替代效力（R1）；A5 截止后才生效（R2）。",
              "  - 本草稿恒为“待人工审批”，不构成审批、发布或中标结果。"]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base_url")
    ap.add_argument("evidence", type=Path)
    ap.add_argument("determination", type=Path)
    ap.add_argument("draft_key")
    ap.add_argument("shot_dir", type=Path)
    args = ap.parse_args()
    base = args.base_url.rstrip("/")
    ev = json.loads(args.evidence.read_text(encoding="utf-8"))
    det = json.loads(args.determination.read_text(encoding="utf-8"))
    refs = sorted(r["reference"] for r in ev["records"])
    body = build_body(det)
    args.shot_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1280, "height": 1000})
        # 先回读已存在草稿拿版本号；不存在（404 提示页）则用 /draft/new（version=0）
        page.goto(f"{base}/draft/{args.draft_key}", wait_until="domcontentloaded")
        existing = page.locator("input[name=key]").count() > 0
        if existing:
            version = page.locator("input[name=version]").input_value()
        else:
            page.goto(f"{base}/draft/new", wait_until="domcontentloaded")
            version = "0"
        key_input = page.get_by_label("草稿编号")
        if key_input.is_editable():
            key_input.fill(args.draft_key)
        page.get_by_label("标题", exact=True).fill(
            f"{det['project']} 封版意见（阻止封版·待负责人确认）")
        page.get_by_label("正文", exact=True).fill(body)
        page.get_by_label("资料引用，每行一项 编号@摘要").fill("\n".join(refs))
        page.screenshot(path=str(args.shot_dir / "draft-before-save.png"),
                        full_page=True)
        page.get_by_role("button", name="保存预审草稿").click()
        page.wait_for_load_state("domcontentloaded")

        # 回读
        status = page.get_by_test_id("draft-status").inner_text()
        saved_key = page.locator("input[name=key]").input_value()
        saved_version = page.locator("input[name=version]").input_value()
        saved_body = page.get_by_label("正文", exact=True).input_value()
        saved_refs = [x for x in page.get_by_label(
            "资料引用，每行一项 编号@摘要").input_value().splitlines() if x]
        page.screenshot(path=str(args.shot_dir / "draft-after-save.png"),
                        full_page=True)
        browser.close()

    assert saved_key == args.draft_key
    assert status == "待人工审批", f"草稿状态异常：{status}"
    assert saved_body == body, "回读正文与提交不一致"
    assert sorted(saved_refs) == refs, "回读引用与取证引用不一致"
    # 与本地证据指纹逐条核对
    local_refs = {r["id"]: r["reference"] for r in ev["records"]}
    for ref in saved_refs:
        rid, sha = ref.split("@", 1)
        assert local_refs[rid] == ref and hashlib.sha256(
            (Path("/workspace/evidence/hb26/attachments") / rid /
             f"{rid}.json").read_bytes()).hexdigest() == sha, f"引用指纹核验失败 {rid}"
    result = {"draft_key": saved_key, "version": int(saved_version),
              "status": status, "ref_count": len(saved_refs),
              "refs_verified_against_local_evidence": True,
              "signed": False, "submitted": False}
    out = args.shot_dir / "draft-readback.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
