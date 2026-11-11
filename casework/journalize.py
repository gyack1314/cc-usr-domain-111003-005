"""HB-26 处理依据进度账（SQLite Journal，幂等）。

- 同一键 + 同一内容重复追加返回原序号，不新增行、不叠加文本；
- 同一键不同内容会被 Journal 拒绝（防止依据被悄悄改写）；
- 账内只记录观察事实、来源地址、指纹与未决问题，效力认定以
  determination.json 与 policy.md 为准，进度账本身不认定业务有效性。

用法：
  python3 -I casework/journalize.py <evidence.json> <determination.json> <草稿回读.json> <journal.sqlite3>
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from workbench.evidence import Journal  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("evidence", type=Path)
    ap.add_argument("determination", type=Path)
    ap.add_argument("draft_readback", type=Path)
    ap.add_argument("journal", type=Path)
    args = ap.parse_args()
    ev = json.loads(args.evidence.read_text(encoding="utf-8"))
    det = json.loads(args.determination.read_text(encoding="utf-8"))
    rb = json.loads(args.draft_readback.read_text(encoding="utf-8"))
    j = Journal(args.journal)

    notes = {
        "hb26-01-浏览器取证": {
            "事实": "经真实 Chromium 逐页浏览门户目录（3 页 11 份）并逐条进入详情页下载原始材料与文书副本",
            "门户地址": ev["base_url"],
            "证据目录": "evidence/hb26（每份来文独立子目录）",
            "evidence_sha256": sha(args.evidence),
            "取证方式": "casework/collect.py，未读取 portal_data 种子、未按下载顺序认定效力",
        },
        "hb26-02-规程口径": {
            "事实": "截止与发文权限以 materials/policy.md 为准",
            "封版截止": det["seal_cutoff"],
            "唯一授权发文单位": det["authorized_issuer"],
            "规则": det["policy_rules"],
        },
        "hb26-03-逐条定性": {
            "事实": "每份来文的定性、依据与处置见 determination.json/per_record",
            "摘要": [{"id": x["id"], "状态": x["status"], "依据码": x["reason_code"],
                      "引用": x["reference"]} for x in det["per_record"]],
        },
        "hb26-04-撤回观察": {
            "事实": "W4 明确指向 A4 的撤回在截止前生效，A4 不产生替代效力",
            "撤回映射": det["withdrawals"],
        },
        "hb26-05-隔离观察": {
            "事实": "截止后生效与未授权来文独立留档，未写入封版口径",
            "隔离": [{"id": q["id"], "原因码": q["reason_code"], "引用": q["reference"]}
                    for q in det["quarantine"]],
        },
        "hb26-06-未决冲突": {
            "事实": "A6/A7 同权限同生效时点、无明确取代关系，冲突保留并阻止封版，未臆造统一口径",
            "冲突": det["merge"]["open_conflicts"],
            "未确认字段": det["seal_decision"]["unconfirmed_clauses"],
        },
        "hb26-07-交付副本": {
            "事实": "修订后未签章副本与逐条修订记录生成于 deliverables/HB-26，原始 materials 未回写",
            "已确认字段": det["seal_decision"]["confirmed_clauses"],
            "有效附件": det["seal_decision"]["active_attachment"],
            "signed": False, "submitted": False,
        },
        "hb26-08-门户草稿回读": {
            "事实": "封版意见经浏览器表单保存为门户草稿并回读核验",
            "回读": rb,
            "草稿状态恒为": "待人工审批",
        },
    }
    before = len(j.read())
    seqs = {key: j.append(key, payload) for key, payload in notes.items()}
    after = len(j.read())
    print(json.dumps({"journal": str(args.journal), "追加序号": seqs,
                      "本次新增条数": after - before, "总条数": after},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
