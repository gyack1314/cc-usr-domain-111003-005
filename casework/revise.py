"""HB-26 响应材料修订生成器。

- 输入：现存草稿（materials/response.json、materials/appendix.csv）、裁决结果、浏览器证据；
- 输出到交付目录，绝不回写 materials 原始资料；
- 用 domain.differences 生成逐条修订记录，冲突字段冻结并加显眼待确认标记；
- 全部确定性生成、原子写入、重复运行不叠加文本；
- 同步生成交付物指纹清单，配合 recheck.py 识别来文变化后需重审的副本。

用法：
  python3 -I casework/revise.py <materials目录> <determination.json> <evidence.json> <交付目录>
"""
import argparse
import csv
import hashlib
import io
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from workbench.domain import differences  # noqa: E402
from workbench.evidence import atomic_json, manifest  # noqa: E402

BANNER = "【待负责人确认·阻止封版】"


def load_inputs(mat_dir: Path, det_path: Path, ev_path: Path):
    response = json.loads((mat_dir / "response.json").read_text(encoding="utf-8"))
    appendix_rows = list(csv.DictReader((mat_dir / "appendix.csv").read_text(
        encoding="utf-8").splitlines()))
    det = json.loads(det_path.read_text(encoding="utf-8"))
    ev = json.loads(ev_path.read_text(encoding="utf-8"))
    return response, appendix_rows, det, ev


def build_revision(response, appendix, det, ev):
    merged = det["merge"]["merged"]
    conflict_targets = set(det["merge"]["conflict_targets"])
    active_attachment = det["attachment"]["active_attachment"]
    refs = {r["id"]: r["reference"] for r in ev["records"]}

    # ---- 正文修订：以现存草稿为 before，有效口径为 after ----
    before_body = {k: response[k] for k in
                   ("delivery", "warranty", "acceptance", "currency")}
    after_body = {k: merged[k] for k in before_body}
    body_diff = differences(before_body, after_body)

    revised = dict(response)  # 不修改原对象
    pending_marks = []
    clause_sources = []
    # 字段级来源链
    source_map = {
        "delivery": ["T0", "A1"],
        "warranty": ["T0", "A2"],      # A6/A7 冲突冻结，不计入确认值
        "acceptance": ["T0"],          # A4 被 W4 撤回
        "currency": ["T0"],            # A5 截止后生效被隔离
    }
    for key, after in after_body.items():
        revised[key] = after
        if key in conflict_targets:
            pending_marks.append({
                "field": key,
                "frozen_value": after,
                "conflict": {c["target"]: c["claimed_values"]
                             for c in det["merge"]["open_conflicts"]
                             if c["target"] == key},
                "block_locations": [loc for c in det["merge"]["open_conflicts"]
                                    for loc in c["block_locations"]
                                    if c["target"] == key],
                "mark": BANNER + f"{key} 存在同权限未决冲突，暂冻结为 {after}，"
                                  "禁止在负责人裁决前签章",
            })
        chain = [refs[i] for i in source_map[key]]
        clause_sources.append({"field": key, "value": after,
                               "source_chain": chain,
                               "status": "UNCONFIRMED" if key in conflict_targets
                               else "CONFIRMED"})
    # 附件更换
    revised["attachment"] = active_attachment
    revised["signed"] = False  # 恒不签章
    revised["seal_status"] = "BLOCKED" if det["seal_decision"]["blocked"] else "READY"
    revised["pending_confirmation"] = [m["mark"] for m in pending_marks]
    revised["source_references"] = sorted({ref for c in clause_sources
                                           for ref in c["source_chain"]}
                                          | {refs[active_attachment], refs["A3"]})

    # ---- 附件修订：旧 ANN-1 行 -> 现行 ANN-2 字段（来自门户附件证据） ----
    ann2 = next(r for r in ev["records"] if r["id"] == active_attachment)
    old_row = next(r for r in appendix if r["id"] == "ANN-1")
    new_row = {"id": active_attachment,
               "delivery": ann2["fields"]["delivery"],
               "warranty": ann2["fields"]["warranty"],
               "currency": ann2["fields"]["currency"]}
    attachment_diff = differences(
        {k: old_row[k] for k in ("delivery", "warranty", "currency")},
        {k: new_row[k] for k in ("delivery", "warranty", "currency")})
    attachment_pending = []
    if "warranty" in conflict_targets:
        attachment_pending.append({
            "column": "warranty",
            "frozen_value": new_row["warranty"],
            "mark": BANNER + "附件 warranty 与正文同受 R7 冲突阻止，数值维持 "
                             f"{new_row['warranty']}，裁决后须同步换版",
            "source_attachment_ref": refs[active_attachment],
        })

    revision_log = {
        "project": det["project"],
        "basis": {
            "policy": "materials/policy.md",
            "determination": "state/hb26/analysis/determination.json",
            "evidence": "evidence/hb26/evidence.json（浏览器逐页取证）",
        },
        "body_revision": {
            "file": "materials/response.json",
            "before": before_body,
            "after": after_body,
            "domain_differences": body_diff,
            "per_field_source_chain": clause_sources,
            "attachment_change": {
                "before": response["attachment"], "after": active_attachment,
                "by_ref": refs["A3"],
                "note": "A3 仅明确指向 ANN-1→ANN-2，不覆盖其他材料（R5/R6）",
            },
        },
        "attachment_revision": {
            "file": "materials/appendix.csv",
            "before_row": old_row, "after_row": new_row,
            "domain_differences": attachment_diff,
            "after_attachment_ref": refs[active_attachment],
        },
        "pending_marks": pending_marks,
        "attachment_pending_marks": attachment_pending,
        "seal": {
            "blocked": det["seal_decision"]["blocked"],
            "signed": False,
            "rule": "R8 禁止自动签章或投递；本副本仅供负责人最终签章前审阅",
        },
        "quarantine_not_applied": [
            {"id": q["id"], "reason": q["reason"], "reference": q["reference"]}
            for q in det["quarantine"]],
    }
    return revised, new_row, revision_log


def write_outputs(out_dir: Path, revised, new_row, revision_log, det, ev):
    out_dir.mkdir(parents=True, exist_ok=True)
    # 修订后未签章响应副本（JSON，显眼待确认标记内嵌）
    atomic_json(out_dir / "response.revised.unsigned.json", revised)

    # 修订后附件副本（CSV + 带标记的人类可读版）
    csv_buf = io.StringIO()
    w = csv.DictWriter(csv_buf, fieldnames=["id", "delivery", "warranty", "currency"])
    w.writeheader(); w.writerow(new_row)
    (out_dir / "appendix.revised.unsigned.csv").write_text(
        csv_buf.getvalue(), encoding="utf-8", newline="")

    marks = "\n".join(f"- {m['mark']}" for m in revision_log["pending_marks"]) \
        + "\n" + "\n".join(f"- {m['mark']}"
                           for m in revision_log["attachment_pending_marks"])
    md = [
        f"# {det['project']} 技术响应（修订后·未签章副本）", "",
        "**本副本未签章、未投递；封版状态："
        f"{'阻止封版（BLOCKED）' if det['seal_decision']['blocked'] else '可提交签章'}**",
        "", "## 显眼待确认标记", "", marks, "",
        "## 响应口径（修订后）", "",
        "| 字段 | 现存草稿 | 修订后 | 状态 | 来源链 |",
        "|---|---|---|---|---|",
    ]
    before = revision_log["body_revision"]["before"]
    for c in revision_log["body_revision"]["per_field_source_chain"]:
        f = c["field"]
        md.append(f"| {f} | {before[f]} | {c['value']} | {c['status']} | "
                  f"{' → '.join(c['source_chain'])} |")
    md += ["", f"报价附件：{revision_log['body_revision']['attachment_change']['before']} "
               f"→ {new_row['id']}（依据 {revision_log['body_revision']['attachment_change']['by_ref']}）",
           "", "## 隔离区来文（未写入本副本）", ""]
    for q in revision_log["quarantine_not_applied"]:
        md.append(f"- {q['id']}：{q['reason']}")
    md += ["", "## 签章限制",
           "- 本材料不得自动签章、提交或宣称中标；签章权归投标负责人（R8）。",
           "- 负责人对 warranty 冲突作出裁决后，须同步重出正文与附件副本再签章。", ""]
    (out_dir / "响应修订副本.未签章.md").write_text("\n".join(md), encoding="utf-8")

    atomic_json(out_dir / "revision-log.json", revision_log)

    # 人类可读修订记录
    log_md = [f"# {det['project']} 针对现存草稿的修订记录", "",
              "## 正文 response.json 逐条差异（domain.differences）", ""]
    for k, v in sorted(revision_log["body_revision"]["domain_differences"].items()):
        log_md.append(f"- {k}: {v['before']} → {v['after']}")
    log_md += ["", "## 附件 appendix.csv 逐条差异", ""]
    for k, v in sorted(revision_log["attachment_revision"]["domain_differences"].items()):
        log_md.append(f"- {k}: {v['before']} → {v['after']}")
    log_md += ["", "## 未采纳的来文（独立去向）", ""]
    for q in revision_log["quarantine_not_applied"]:
        log_md.append(f"- {q['id']}：{q['reason']}")
    (out_dir / "修订记录.md").write_text("\n".join(log_md) + "\n", encoding="utf-8")

    # 交付物指纹清单（清单不包含自身，避免自引用导致重复生成指纹漂移）
    manifest_name = "deliverables-manifest.json"
    files_manifest = [e for e in manifest(out_dir) if e["path"] != manifest_name]
    atomic_json(out_dir / manifest_name, files_manifest)
    return files_manifest


def main():
    ap = argparse.ArgumentParser(description="生成 HB-26 修订后未签章副本")
    ap.add_argument("materials", type=Path)
    ap.add_argument("determination", type=Path)
    ap.add_argument("evidence", type=Path)
    ap.add_argument("out_dir", type=Path)
    args = ap.parse_args()
    response, appendix, det, ev = load_inputs(
        args.materials, args.determination, args.evidence)
    revised, new_row, revision_log = build_revision(response, appendix, det, ev)
    files_manifest = write_outputs(
        args.out_dir, revised, new_row, revision_log, det, ev)
    print(json.dumps({"out_dir": str(args.out_dir),
                      "files": [f["path"] for f in files_manifest],
                      "seal_blocked": det["seal_decision"]["blocked"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
