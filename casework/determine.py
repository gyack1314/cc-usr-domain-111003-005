"""HB-26 来文效力裁决与有效条款归并引擎。

设计原则：
- 输入只来自浏览器取证 evidence.json（门户附件下载件）与显式规程参数，
  不直接读取 portal_data 种子，不按下载顺序/文件修改时间判断；
- 仅执行 materials/policy.md 载明的成文规则，工具不臆造统一口径、不做审批；
- 领域计算复用 workbench.domain（patch / differences / referenced_targets）；
- 同权限、同生效时点、无明确取代关系的冲突保留为 open_conflicts，阻止封版；
- 截止后生效与未授权来文进 quarantine，独立去向，不参与有效条款；
- 全部输出确定性（键排序、无时间戳），重复运行不叠加文本；
- 输出清单含输入指纹，来文变化时 recheck.py 可识别需重审的副本。

用法：
  python3 -I casework/determine.py <evidence.json> <policy.json> <输出目录>
"""
import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from workbench.domain import patch, differences, referenced_targets  # noqa: E402
from workbench.evidence import atomic_json  # noqa: E402

POLICY_RULES = [
    "R1 正式发文单位唯一：仅 HB招标中心 的来文具备替代效力；供应商沟通、未盖章问答不产生替代效力（policy.md）。",
    "R2 内部封版截止 2026-11-10T12:00:00+08:00：生效时点晚于该时刻的变更不得进入封版口径，进独立去向（policy.md）。",
    "R3 按生效时点与明确替代关系处理，不按上传/下载顺序或文件修改时间全序覆盖（policy.md）。",
    "R4 撤回只作用于明确目标（target）；被撤回的来文自撤回生效时起不产生替代效力（policy.md）。",
    "R5 一份来文只替代其 replaces 中明确指向的条款/附件，不覆盖未提到的附件或条款（policy.md）。",
    "R6 附件独立编号，正文变更不自动替代附件；附件更换须有明确指向（policy.md）。",
    "R7 同权限、无明确取代关系的冲突保留并标记，由人工裁决，不得臆造统一口径（policy.md）。",
    "R8 禁止自动签章或投递；草稿恒为待人工审批（policy.md / 门户接口）。",
]


def load_evidence(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    records = {r["id"]: r for r in data["records"]}
    return data, records


def classify(records, policy):
    """按成文规则对每份来文定性，返回定性列表与隔离区。"""
    issuer_ok = policy["authorized_issuer"]
    cutoff = policy["seal_cutoff"]
    findings, quarantine = [], []
    # 撤回映射：target -> 撤回记录（仅当撤回本身授权且在截止前生效）
    withdrawals = {}
    for rid, r in records.items():
        f = r["fields"]
        if r["category"] == "撤回":
            valid_issuer = f.get("issuer") == issuer_ok
            in_time = f.get("effective", "9999") <= cutoff
            if valid_issuer and in_time:
                withdrawals[f.get("target")] = rid
    for rid, r in sorted(records.items()):
        f = r["fields"]
        cat = r["category"]
        item = {
            "id": rid, "category": cat, "title": r["title"],
            "reference": r["reference"], "issuer": f.get("issuer"),
            "effective": f.get("effective"),
        }
        # R1 未授权
        if f.get("issuer") not in (None, issuer_ok):
            item.update(status="quarantine",
                        reason_code="UNAUTHORIZED",
                        reason=f"发文单位 {f.get('issuer')} 非 {issuer_ok}；{('未盖章问答' if f.get('sealed') is False else '供应商沟通')}不产生替代效力（R1）",
                        effect="隔离：不采信其条款，留档备查，不进入封版口径")
            quarantine.append(item); findings.append(item); continue
        if cat == "撤回":
            target = f.get("target")
            if f.get("effective", "9999") > cutoff:
                item.update(status="quarantine", reason_code="AFTER_CUTOFF_WITHDRAWAL",
                            reason=f"撤回生效 {f.get('effective')} 晚于封版截止 {cutoff}（R2）",
                            effect=f"隔离：截止时撤回尚未生效，目标 {target} 在封版口径中的状态另行说明")
                quarantine.append(item); findings.append(item); continue
            item.update(status="effective", reason_code="WITHDRAWAL_VALID",
                        reason=f"授权单位在截止前撤回，明确指向 {target}（R4）",
                        effect=f"撤回生效：{target} 自 {f.get('effective')} 起不产生替代效力")
            findings.append(item); continue
        if cat == "附件":
            item.update(status="attachment", reason_code="ATTACHMENT_STANDALONE",
                        reason="附件独立编号，本身不替代正文条款；须由补遗明确指向才更换（R6）",
                        effect="作为候选附件留档，是否启用取决于补遗的明确替代关系")
            findings.append(item); continue
        # 补遗/招标的截止判断 R2
        eff = f.get("effective", "9999")
        if eff > cutoff:
            item.update(status="quarantine", reason_code="AFTER_CUTOFF_CHANGE",
                        reason=f"生效时点 {eff} 晚于封版截止 {cutoff}（R2）",
                        effect="隔离：截止后才生效的变更不进入本次封版，独立去向并提示负责人后续处理")
            quarantine.append(item); findings.append(item); continue
        if cat == "招标":
            item.update(status="baseline", reason_code="BASELINE_TENDER",
                        reason="授权单位正式招标文件，构成基线条款（R1/R3）",
                        effect="基线：其条款在被有效且明确的替代前持续有效")
            findings.append(item); continue
        # 补遗：是否已被撤回 R4
        if rid in withdrawals:
            item.update(status="withdrawn", reason_code="WITHDRAWN",
                        reason=f"被 {withdrawals[rid]} 在截止前明确撤回（R4）",
                        effect="不产生替代效力；其拟变更的条款维持撤回前的有效口径")
            findings.append(item); continue
        item.update(status="effective", reason_code="ADDENDUM_VALID",
                    reason="授权单位、截止前生效、未被撤回（R1/R2/R4）",
                    effect="按 replaces 明确指向参与归并（R3/R5）")
        findings.append(item)
    return findings, quarantine, withdrawals


def merge_clauses(records, findings, withdrawals):
    """用 domain.patch 逐步归并有效补遗；检测同权限无取代关系的冲突。"""
    status_by_id = {x["id"]: x["status"] for x in findings}
    tender = records["T0"]["fields"]["clauses"]
    chain = [{"step": 0, "id": "T0", "action": "baseline", "clauses": dict(tender)}]
    current = dict(tender)
    # 有效补遗按生效时点排序（同时点并列，不按下载顺序）
    addenda = [records[i] for i, s in status_by_id.items() if s == "effective"
               and records[i]["category"] == "补遗"]
    addenda.sort(key=lambda r: (r["fields"].get("effective", ""), r["id"]))

    # 先检测同一目标的同时点冲突（R7）：分组 key 为 replaces 的目标条款
    target_groups = {}
    for r in addenda:
        for target in r["fields"].get("replaces", {}):
            # 条款位置按短键归组：T0.warranty 与 A2.warranty 都作用于 warranty 条款位；
            # 附件级键（不含点号）独立成组。
            short_target = target.split(".", 1)[1] if "." in target else target
            target_groups.setdefault(short_target, []).append((r["id"], target))
    conflicts, conflict_targets = [], set()
    for short_target, pairs in sorted(target_groups.items()):
        # R7：同一条款位下，按生效时点再分组；同一时点出现两份及以上同权限来文、
        # 且彼此无明确取代关系，即为未决冲突（不同时点的来文不构成此冲突）。
        by_effective = {}
        for rid, raw in pairs:
            eff = records[rid]["fields"]["effective"]
            by_effective.setdefault(eff, []).append((rid, raw))
        for eff, members in sorted(by_effective.items()):
            ids = sorted({rid for rid, _ in members})
            if len(ids) <= 1:
                continue
            member_raw = sorted({raw for _, raw in members})
            conflict_targets.add(short_target)
            conflicts.append({
                "target": short_target,
                "raw_targets": member_raw,
                "addenda": ids,
                "effective": eff,
                "claimed_values": {rid: records[rid]["fields"]["replaces"][raw]
                                   for rid, raw in members if rid in ids},
                "rule": "R7",
                "resolution": "同权限、同一生效时点、无明确取代关系：保留冲突，不臆造统一口径",
                "block_locations": [
                    f"技术响应正文 {short_target} 字段（门户草稿/修订后响应副本）",
                    f"报价附件 {short_target} 列（修订后附件副本）",
                ],
            })

    # 归并：仅冻结构成同时点冲突的来文成员；更早/更晚时点的唯一来文正常适用
    conflict_member_ids = {rid for c in conflicts for rid in c["addenda"]}
    applied, skipped = [], []
    for r in addenda:
        repl = r["fields"].get("replaces", {})
        use, blocked = {}, {}
        for raw_key, val in repl.items():
            short_key = raw_key.split(".", 1)[1] if "." in raw_key else raw_key
            if short_key in conflict_targets and r["id"] in conflict_member_ids:
                blocked[raw_key] = val
            else:
                use[raw_key] = val
        short = {k.split(".", 1)[1]: v for k, v in use.items() if "." in k}
        attach_replace = {k: v for k, v in use.items() if "." not in k}
        if short:
            try:
                current = patch(current, short)
                chain.append({"step": len(chain), "id": r["id"],
                              "action": "patch", "changes": short,
                              "clauses": dict(current)})
                applied.append({"id": r["id"], "changes": short})
            except ValueError as exc:
                skipped.append({"id": r["id"], "reason": str(exc)})
        if attach_replace:
            chain.append({"step": len(chain), "id": r["id"],
                          "action": "attachment_replace", "changes": attach_replace,
                          "clauses": dict(current)})
            applied.append({"id": r["id"], "attachment_replace": attach_replace})
        if blocked:
            chain.append({"step": len(chain), "id": r["id"],
                          "action": "blocked_by_conflict", "changes": blocked,
                          "clauses": dict(current)})
            skipped.append({"id": r["id"], "blocked": blocked,
                            "reason": "R7 冲突目标，未经人工裁决不得写入"})
    merged = current
    diff = differences(tender, merged)
    referenced = referenced_targets([r["fields"] for r in addenda])
    return {
        "baseline": tender, "merged": merged, "diff_vs_t0": diff,
        "chain": chain, "applied": applied, "skipped": skipped,
        "open_conflicts": conflicts, "conflict_targets": sorted(conflict_targets),
        "referenced_targets": referenced,
    }


def attachment_decision(records, findings, policy):
    """附件口径：仅明确指向的附件更换（R5/R6）。"""
    status_by_id = {x["id"]: x["status"] for x in findings}
    decisions = []
    for x in findings:
        r = records[x["id"]]
        if r["category"] == "补遗" and x["status"] in ("effective",):
            for k, v in r["fields"].get("replaces", {}).items():
                if "." not in k:  # 附件级替代
                    decisions.append({
                        "by": x["id"], "replaces_attachment": k,
                        "with_attachment": v,
                        "valid": v in records,
                        "note": "仅更换明确指向的附件；正文其他附件不被覆盖（R5/R6）",
                    })
    current_attach = "ANN-1"  # 现存草稿引用的旧附件
    for d in decisions:
        if d["valid"] and d["replaces_attachment"] == current_attach:
            current_attach = d["with_attachment"]
    return {"decisions": decisions, "active_attachment": current_attach,
            "superseded": ["ANN-1"] if current_attach != "ANN-1" else []}


def build(policy_path: Path, evidence_path: Path, out_dir: Path):
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    evidence, records = load_evidence(evidence_path)
    findings, quarantine, withdrawals = classify(records, policy)
    merge = merge_clauses(records, findings, withdrawals)
    attach = attachment_decision(records, findings, policy)

    # 正文与附件交叉核对
    active_att = records[attach["active_attachment"]]
    att_fields = active_att["fields"]
    cross = []
    for key in ("delivery", "warranty", "currency"):
        body_val = merge["merged"].get(key)
        att_val = att_fields.get(key)
        if key in merge["conflict_targets"]:
            status = "BLOCKED"
            note = ("R7 未决冲突：正文冻结为最后有效口径 "
                    f"{merge['merged'].get(key)}（附件同为 {att_fields.get(key)}，"
                    "数值相同不代表冲突已解）；A6/A7 主张须人工裁决后才能改值并签章")
        elif body_val == att_val:
            status = "MATCH"; note = "正文与有效附件一致"
        else:
            status = "MISMATCH"; note = "正文与附件不一致，需核对来源链"
        cross.append({"clause": key, "body_value": body_val,
                      "attachment": attach["active_attachment"],
                      "attachment_value": att_val, "status": status, "note": note})
    # 验收仅存在于正文（附件无该列）
    cross.append({"clause": "acceptance", "body_value": merge["merged"].get("acceptance"),
                  "attachment": attach["active_attachment"],
                  "attachment_value": None, "status": "BODY_ONLY",
                  "note": "验收口径仅在招标正文规定，附件无此列；以有效正文为准"})

    blocked = bool(merge["open_conflicts"])
    determination = {
        "project": policy["project"],
        "seal_cutoff": policy["seal_cutoff"],
        "authorized_issuer": policy["authorized_issuer"],
        "policy_rules": POLICY_RULES,
        "input_fingerprint": {
            "evidence_file": evidence_path.name,
            "evidence_sha256": hashlib.sha256(
                evidence_path.read_bytes()).hexdigest(),
            "policy_sha256": hashlib.sha256(
                policy_path.read_bytes()).hexdigest(),
            "record_references": {r["id"]: r["reference"]
                                  for r in evidence["records"]},
        },
        "per_record": findings,
        "withdrawals": {t: w for t, w in withdrawals.items()},
        "quarantine": quarantine,
        "merge": merge,
        "attachment": attach,
        "cross_check": cross,
        "seal_decision": {
            "blocked": blocked,
            "block_reasons": [
                {"target": c["target"], "at": loc,
                 "conflict": {k: c["claimed_values"][k] for k in c["addenda"]}}
                for c in merge["open_conflicts"] for loc in c["block_locations"]
            ],
            "confirmed_clauses": {
                k: v for k, v in merge["merged"].items()
                if k not in merge["conflict_targets"]},
            "unconfirmed_clauses": sorted(merge["conflict_targets"]),
            "active_attachment": attach["active_attachment"],
            "may_seal": False,
            "note": "存在同权限未决冲突，阻止封版；须由投标负责人人工裁决后签章，系统不自动签章/投递（R7/R8）",
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(out_dir / "determination.json", determination)

    # 逐条有效要求与来源链（人类可读 Markdown，确定性生成）
    lines = [f"# {policy['project']} 有效要求与来源链（裁决工作稿）", "",
             f"- 封版截止：{policy['seal_cutoff']}",
             f"- 唯一正式发文单位：{policy['authorized_issuer']}",
             f"- 封版是否放行：{'否（存在未决冲突）' if blocked else '是'}", "",
             "## 适用规程", ""]
    lines += [f"- {r}" for r in POLICY_RULES]
    lines += ["", "## 逐条来文效力定性", ""]
    for x in findings:
        lines += [f"### {x['id']}｜{x['title']}（{x['category']}）",
                  f"- 引用：`{x['reference']}`",
                  f"- 发文单位：{x['issuer']}；生效：{x['effective']}",
                  f"- 定性：{x['status']}（{x['reason_code']}）",
                  f"- 依据：{x['reason']}", f"- 处置：{x['effect']}", ""]
    lines += ["## 有效条款归并（domain.patch 链）", ""]
    for step in merge["chain"]:
        lines.append(f"- 步骤{step['step']} {step['id']} {step['action']} "
                     f"{json.dumps(step.get('changes', {}), ensure_ascii=False)} "
                     f"=> {json.dumps(step['clauses'], ensure_ascii=False)}")
    lines += ["", "### 相对招标基线 T0 的差异（domain.differences）", ""]
    for k, v in sorted(merge["diff_vs_t0"].items()):
        lines.append(f"- {k}: {v['before']} → {v['after']}")
    lines += ["", "## 未决冲突（阻止封版，保留不臆造）", ""]
    for c in merge["open_conflicts"]:
        lines += [f"### 冲突目标 {c['target']}",
                  f"- 涉及来文：{', '.join(c['addenda'])}（同生效时点 {c['effective']}，同权限，无明确取代关系）",
                  f"- 各自主张：{json.dumps(c['claimed_values'], ensure_ascii=False)}",
                  f"- 规则：{c['resolution']}",
                  "- 阻止封版的具体位置："]
        lines += [f"  - {loc}" for loc in c["block_locations"]]
        lines.append("")
    lines += ["## 隔离区（截止后生效 / 未授权，独立去向）", ""]
    for q in quarantine:
        lines.append(f"- {q['id']}｜{q['title']}：{q['reason']}；去向：{q['effect']}")
    lines += ["", "## 附件裁决", "",
              f"- 现行有效附件：{attach['active_attachment']}",
              f"- 被明确替代的旧附件：{', '.join(attach['superseded']) or '无'}"]
    for d in attach["decisions"]:
        lines.append(f"- {d['by']} 明确将 {d['replaces_attachment']} 更换为 {d['with_attachment']}：{d['note']}")
    lines += ["", "## 正文 × 附件交叉核对", ""]
    for c in cross:
        lines.append(f"- {c['clause']}: 正文={c['body_value']} / 附件={c['attachment_value']} [{c['status']}] {c['note']}")
    (out_dir / "有效要求与来源链.md").write_text("\n".join(lines) + "\n",
                                               encoding="utf-8")

    # 来源链 CSV（逐条）
    with (out_dir / "来源链.csv").open("w", encoding="utf-8", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["id", "category", "title", "issuer", "effective",
                    "status", "reason_code", "reference"])
        for x in findings:
            w.writerow([x["id"], x["category"], x["title"], x["issuer"],
                        x["effective"], x["status"], x["reason_code"],
                        x["reference"]])
    return determination


def main():
    ap = argparse.ArgumentParser(description="HB-26 效力裁决与条款归并")
    ap.add_argument("evidence", type=Path)
    ap.add_argument("policy", type=Path)
    ap.add_argument("out_dir", type=Path)
    args = ap.parse_args()
    det = build(args.policy, args.evidence, args.out_dir)
    print(json.dumps({
        "blocked": det["seal_decision"]["blocked"],
        "confirmed": det["seal_decision"]["confirmed_clauses"],
        "unconfirmed": det["seal_decision"]["unconfirmed_clauses"],
        "active_attachment": det["seal_decision"]["active_attachment"],
        "quarantine": [q["id"] for q in det["quarantine"]],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
