"""HB-26 可重复检查 / 来文变化重审识别器。

职责：
1. 用 workbench.evidence.verify 校验本地 materials 与门户证据指纹是否变化；
2. 重新比对当前证据引用与裁决输入指纹，识别变化的来文；
3. 依据来源链映射，指出哪些交付副本/草稿字段需要重审（而非全量重做）；
4. 全流程只读，不改写任何交付物；确定性输出，重复运行结论一致。

用法：
  python3 -I casework/recheck.py <evidence.json> <determination.json> <交付目录> <materials清单.json> <materials目录>
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from workbench.evidence import verify  # noqa: E402

# 来文 -> 受影响的交付位置（来源链依赖映射，用于精准重审）
IMPACT_MAP = {
    "T0": ["response.revised.unsigned.json:全部字段基线",
           "appendix.revised.unsigned.csv", "门户草稿 hb26-seal-opinion"],
    "A1": ["response.revised.unsigned.json:delivery",
           "appendix.revised.unsigned.csv:delivery"],
    "A2": ["response.revised.unsigned.json:warranty",
           "appendix.revised.unsigned.csv:warranty"],
    "A3": ["response.revised.unsigned.json:attachment",
           "appendix.revised.unsigned.csv（附件换版）"],
    "A4": ["response.revised.unsigned.json:acceptance（撤回链）"],
    "W4": ["response.revised.unsigned.json:acceptance（撤回 A4）"],
    "A5": ["隔离区条目；若截止口径变化则影响 currency"],
    "A6": ["response.revised.unsigned.json:warranty（R7 冲突方）",
           "appendix.revised.unsigned.csv:warranty", "门户草稿冲突段"],
    "A7": ["response.revised.unsigned.json:warranty（R7 冲突方）",
           "appendix.revised.unsigned.csv:warranty", "门户草稿冲突段"],
    "Q1": ["隔离区条目（无替代效力，一般不改变副本）"],
    "ANN-2": ["appendix.revised.unsigned.csv（整附件）",
              "response.revised.unsigned.json:source_references"],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("evidence", type=Path)
    ap.add_argument("determination", type=Path)
    ap.add_argument("deliverable_dir", type=Path)
    ap.add_argument("materials_manifest", type=Path)
    ap.add_argument("materials_dir", type=Path)
    args = ap.parse_args()

    ev = json.loads(args.evidence.read_text(encoding="utf-8"))
    det = json.loads(args.determination.read_text(encoding="utf-8"))

    # 1) materials 原始材料是否被改动
    materials_issues = verify(args.materials_dir,
                              json.loads(args.materials_manifest.read_text(
                                  encoding="utf-8")))

    # 2) 来文指纹：当前证据 vs 裁决时记录的输入指纹
    baseline_refs = det["input_fingerprint"]["record_references"]
    current_refs = {r["id"]: r["reference"] for r in ev["records"]}
    changed, added, removed, same = [], [], [], []
    for rid, ref in current_refs.items():
        if rid not in baseline_refs:
            added.append(rid)
        elif baseline_refs[rid] != ref:
            changed.append(rid)
        else:
            same.append(rid)
    for rid in baseline_refs:
        if rid not in current_refs:
            removed.append(rid)

    # 3) 受影响副本映射
    impacted = {}
    for rid in sorted(set(changed) | set(added) | set(removed)):
        impacted[rid] = IMPACT_MAP.get(rid, ["需人工评估影响面"])

    # 4) 交付物自身指纹清单是否仍与磁盘一致
    dm_path = args.deliverable_dir / "deliverables-manifest.json"
    deliverable_issues = verify(args.deliverable_dir,
                                json.loads(dm_path.read_text(encoding="utf-8"))) \
        if dm_path.exists() else ["缺少交付物清单"]

    result = {
        "materials_changed": materials_issues,
        "records_changed": sorted(changed),
        "records_added": sorted(added),
        "records_removed": sorted(removed),
        "records_unchanged_count": len(same),
        "copies_requiring_rereview": impacted,
        "deliverable_files_changed": deliverable_issues,
        "rerun_advice": [
            "若来文变化：先重跑 casework/collect.py 取证，再 determine.py 裁决、"
            "revise.py 重出副本、save_draft.py 升版草稿；",
            "若仅交付文件被改动：以 deliverables-manifest.json 为准重跑 revise.py 复原；",
            "materials 原始材料应保持只读，出现变化先核对是否有人为改写。",
        ],
        "all_clear": not (materials_issues or changed or added or removed
                          or deliverable_issues),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["all_clear"] else 3


if __name__ == "__main__":
    sys.exit(main())
