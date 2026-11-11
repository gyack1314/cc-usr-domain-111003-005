"""HB-26 案例工作流测试：效力裁决、幂等不叠加、变化重审、进度账。

使用测试自建的合成证据（不读 portal_data、不依赖门户进程），
覆盖 policy.md 的成文规则：授权、截止、撤回、明确替代、附件独立、
同权限同时点冲突保留并阻止封版、禁止臆造统一口径。
"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from casework import determine as det_mod  # noqa: E402  (命名空间包)
from casework import revise as rev_mod      # noqa: E402
from casework import recheck as rc_mod      # noqa: E402
from workbench.evidence import Journal      # noqa: E402

POLICY = {
    "project": "HB-26",
    "seal_cutoff": "2026-11-10T12:00:00+08:00",
    "authorized_issuer": "HB招标中心",
}


def rec(rid, category, title, fields):
    body = {"id": rid, "category": category, "title": title,
            "revision": 1, "fields": fields}
    record_bytes = (json.dumps(body, ensure_ascii=False, sort_keys=True,
                               indent=2) + "\n").encode()
    import hashlib
    sha = hashlib.sha256(record_bytes).hexdigest()
    return {"id": rid, "category": category, "title": title, "revision": 1,
            "fields": fields, "reference": f"{rid}@{sha}",
            "record_json_sha256": sha, "record_json_path": f"attachments/{rid}/{rid}.json",
            "record_json_size": len(record_bytes),
            "document_path": f"documents/{rid}/{rid}.txt",
            "document_sha256": "d" * 64, "detail_url": f"http://x/record/{rid}",
            "fields_seen_on_page": json.dumps(fields, ensure_ascii=False)}


def synthetic_evidence():
    records = [
        rec("T0", "招标", "正式条款", {"issuer": "HB招标中心",
            "effective": "2026-10-20T09:00:00+08:00",
            "clauses": {"delivery": "60天", "warranty": "12个月",
                        "acceptance": "现场验收", "currency": "CNY"}}),
        rec("A1", "补遗", "交期", {"issuer": "HB招标中心",
            "effective": "2026-11-08T09:00:00+08:00",
            "replaces": {"T0.delivery": "45天"}}),
        rec("A2", "补遗", "质保", {"issuer": "HB招标中心",
            "effective": "2026-11-09T09:00:00+08:00",
            "replaces": {"T0.warranty": "24个月"}}),
        rec("A3", "补遗", "附件更正", {"issuer": "HB招标中心",
            "effective": "2026-11-09T10:00:00+08:00",
            "replaces": {"ANN-1": "ANN-2"}, "clauses": {}}),
        rec("ANN-2", "附件", "新报价附件", {"delivery": "45天",
            "warranty": "24个月", "currency": "CNY"}),
        rec("A4", "补遗", "验收", {"issuer": "HB招标中心",
            "effective": "2026-11-09T11:00:00+08:00",
            "replaces": {"T0.acceptance": "远程验收"}}),
        rec("W4", "撤回", "撤回A4", {"issuer": "HB招标中心", "target": "A4",
            "effective": "2026-11-10T08:00:00+08:00"}),
        rec("A5", "补遗", "截止后币种", {"issuer": "HB招标中心",
            "effective": "2026-11-11T00:00:00+08:00",
            "replaces": {"T0.currency": "USD"}}),
        rec("A6", "补遗", "质保甲", {"issuer": "HB招标中心",
            "effective": "2026-11-10T09:00:00+08:00",
            "replaces": {"A2.warranty": "18个月"}}),
        rec("A7", "补遗", "质保乙", {"issuer": "HB招标中心",
            "effective": "2026-11-10T09:00:00+08:00",
            "replaces": {"A2.warranty": "30个月"}}),
        rec("Q1", "问答", "供应商答复", {"issuer": "供货商助理",
            "sealed": False, "clauses": {"delivery": "30天"}}),
    ]
    return {"base_url": "http://test", "records": records,
            "catalog_pages": [{"page": 1, "count_text": "共 11 份资料",
                               "row_count": 11}]}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


class HB26WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.ev_path = self.base / "evidence.json"
        self.pol_path = self.base / "policy.json"
        self.analysis = self.base / "analysis"
        self.deliver = self.base / "deliver"
        self.materials = self.base / "materials"
        self.materials.mkdir()
        write_json(self.ev_path, synthetic_evidence())
        write_json(self.pol_path, POLICY)
        write_json(self.materials / "response.json", {
            "project": "HB-26", "delivery": "60天", "warranty": "12个月",
            "acceptance": "现场验收", "currency": "CNY",
            "attachment": "ANN-1", "signed": False})
        (self.materials / "appendix.csv").write_text(
            "id,delivery,warranty,currency\nANN-1,60天,12个月,CNY\n",
            encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _determine(self):
        return det_mod.build(self.pol_path, self.ev_path, self.analysis)

    def test_rules_and_blocked_seal(self):
        d = self._determine()
        status = {x["id"]: x["status"] for x in d["per_record"]}
        self.assertEqual(status["A1"], "effective")
        self.assertEqual(status["A4"], "withdrawn")
        self.assertEqual(status["W4"], "effective")
        self.assertEqual(status["T0"], "baseline")
        self.assertEqual(status["ANN-2"], "attachment")
        self.assertCountEqual([q["id"] for q in d["quarantine"]], ["A5", "Q1"])
        reasons = {q["id"]: q["reason_code"] for q in d["quarantine"]}
        self.assertEqual(reasons["A5"], "AFTER_CUTOFF_CHANGE")
        self.assertEqual(reasons["Q1"], "UNAUTHORIZED")
        # 验收维持现场（A4 被撤回）；币种维持 CNY（A5 截止后隔离）
        self.assertEqual(d["merge"]["merged"]["acceptance"], "现场验收")
        self.assertEqual(d["merge"]["merged"]["currency"], "CNY")
        self.assertEqual(d["merge"]["merged"]["delivery"], "45天")
        # 冲突：A6/A7 同时点同权限，质保冻结在 A2 的 24个月，不选 18/30
        self.assertTrue(d["seal_decision"]["blocked"])
        self.assertEqual(d["seal_decision"]["unconfirmed_clauses"], ["warranty"])
        self.assertEqual(d["merge"]["merged"]["warranty"], "24个月")
        conflict = d["merge"]["open_conflicts"][0]
        self.assertEqual(conflict["addenda"], ["A6", "A7"])
        self.assertEqual(set(conflict["claimed_values"].values()),
                         {"18个月", "30个月"})
        # 附件仅被明确更换
        self.assertEqual(d["attachment"]["active_attachment"], "ANN-2")
        self.assertIn("ANN-1", d["attachment"]["superseded"])
        # 永不放行自动签章
        self.assertFalse(d["seal_decision"]["may_seal"])

    def test_deterministic_no_text_stacking(self):
        d1 = self._determine()
        first = (self.analysis / "determination.json").read_bytes()
        d2 = self._determine()  # 再跑一次
        second = (self.analysis / "determination.json").read_bytes()
        self.assertEqual(first, second)
        self.assertEqual(d1["merge"]["chain"], d2["merge"]["chain"])
        # 修订副本重复生成字节一致，不叠加
        resp, appendix, det_loaded, ev_loaded = rev_mod.load_inputs(
            self.materials, self.analysis / "determination.json", self.ev_path)
        r1, row1, log1 = rev_mod.build_revision(resp, appendix, d1, ev_loaded)
        rev_mod.write_outputs(self.deliver, r1, row1, copy.deepcopy(log1),
                              d1, ev_loaded)
        before = {p.name: p.read_bytes() for p in self.deliver.iterdir()
                  if p.is_file()}
        resp2, appendix2, _, ev2_loaded = rev_mod.load_inputs(
            self.materials, self.analysis / "determination.json", self.ev_path)
        r2, row2, log2 = rev_mod.build_revision(resp2, appendix2, d2, ev2_loaded)
        rev_mod.write_outputs(self.deliver, r2, row2, log2, d2, ev2_loaded)
        after = {p.name: p.read_bytes() for p in self.deliver.iterdir()
                 if p.is_file()}
        self.assertEqual(set(before), set(after))
        for name in before:
            self.assertEqual(before[name], after[name], f"{name} 重复生成发生变化")
        # 未签章且带显眼标记
        self.assertFalse(r2["signed"])
        self.assertTrue(any("待负责人确认" in m for m in r2["pending_confirmation"]))

    def test_recheck_detects_change_and_impact(self):
        d = self._determine()
        resp, appendix, _det, _ev = rev_mod.load_inputs(
            self.materials, self.analysis / "determination.json", self.ev_path)
        revised, row, log = rev_mod.build_revision(resp, appendix, d, _ev)
        rev_mod.write_outputs(self.deliver, revised, row, log, d, _ev)
        # 无变化时 all_clear
        from workbench.evidence import manifest, atomic_json
        mat_manifest = self.base / "mat.json"
        atomic_json(mat_manifest, manifest(self.materials))
        rc = _run_recheck(self.ev_path,
                          self.analysis / "determination.json", self.deliver,
                          mat_manifest, self.materials)
        self.assertTrue(rc["all_clear"])
        # 篡改 A6 引用 -> 精准定位 warranty 副本需重审
        ev2 = json.loads(self.ev_path.read_text(encoding="utf-8"))
        for r in ev2["records"]:
            if r["id"] == "A6":
                r["reference"] = "A6@" + "f" * 64
        ev2_path = self.base / "evidence2.json"
        write_json(ev2_path, ev2)
        rc2 = _run_recheck(ev2_path,
                           self.analysis / "determination.json", self.deliver,
                           mat_manifest, self.materials)
        self.assertFalse(rc2["all_clear"])
        self.assertEqual(rc2["records_changed"], ["A6"])
        self.assertIn("A6", rc2["copies_requiring_rereview"])
        self.assertTrue(any("warranty" in loc for loc in
                            rc2["copies_requiring_rereview"]["A6"]))

    def test_journal_idempotent_and_append_only(self):
        jpath = self.base / "j.sqlite3"
        j = Journal(jpath)
        seq = j.append("k1", {"a": 1})
        self.assertEqual(Journal(jpath).append("k1", {"a": 1}), seq)
        with self.assertRaises(ValueError):
            j.append("k1", {"a": 2})
        self.assertEqual(len(Journal(jpath).read()), 1)


def _run_recheck(ev, det_path, deliver, mat_manifest, materials):
    import argparse
    evidence = json.loads(Path(ev).read_text(encoding="utf-8"))
    determination = json.loads(Path(det_path).read_text(encoding="utf-8"))
    from workbench.evidence import verify
    baseline = determination["input_fingerprint"]["record_references"]
    current = {r["id"]: r["reference"] for r in evidence["records"]}
    changed = sorted(i for i, ref in current.items()
                     if i in baseline and baseline[i] != ref)
    added = sorted(i for i in current if i not in baseline)
    removed = sorted(i for i in baseline if i not in current)
    impacted = {i: rc_mod.IMPACT_MAP.get(i, []) for i in
                set(changed) | set(added) | set(removed)}
    return {
        "all_clear": not (changed or added or removed or
                          verify(deliver, json.loads((deliver /
                                  "deliverables-manifest.json").read_text(
                                      encoding="utf-8")))),
        "records_changed": changed, "records_added": added,
        "records_removed": removed,
        "copies_requiring_rereview": impacted,
    }


if __name__ == "__main__":
    unittest.main()
