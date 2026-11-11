"""HB-26 可重复流水线：取证 → 裁决 → 修订 → 进度账（草稿单独经浏览器保存）。

每一步都是确定性、幂等的：
- 浏览器取证重复运行会覆盖同一证据目录（内容相同则字节一致）；
- 裁决/修订为原子写入且不含时间戳，重复运行不叠加文本；
- 进度账同键同内容幂等，不同内容拒绝覆盖。

草稿保存（casework/save_draft.py）涉及门户写操作，单独执行以便人工把关，
本脚本不自动签章、不提交、不投递。

用法（均以绝对/相对路径传参，python -I 隔离运行）：
  python3 -I casework/run_pipeline.py \
      --base-url http://127.0.0.1:8765 \
      --evidence evidence/hb26 \
      --policy casework/params/policy.json \
      --analysis state/hb26/analysis \
      --deliverables deliverables/HB-26 \
      --materials materials \
      --journal state/hb26/journal.sqlite3
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def step(title, argv):
    print(f"\n=== {title} ===", flush=True)
    proc = subprocess.run([sys.executable, "-I", *argv], cwd=ROOT)
    if proc.returncode != 0:
        raise SystemExit(f"步骤失败：{title}（退出码 {proc.returncode}）")


def main():
    ap = argparse.ArgumentParser(description="HB-26 可重复处理流水线")
    ap.add_argument("--base-url", default="http://127.0.0.1:8765")
    ap.add_argument("--evidence", default="evidence/hb26")
    ap.add_argument("--policy", default="casework/params/policy.json")
    ap.add_argument("--analysis", default="state/hb26/analysis")
    ap.add_argument("--deliverables", default="deliverables/HB-26")
    ap.add_argument("--materials", default="materials")
    ap.add_argument("--journal", default="state/hb26/journal.sqlite3")
    args = ap.parse_args()
    ev_dir = ROOT / args.evidence
    ev_json = ev_dir / "evidence.json"
    det_json = ROOT / args.analysis / "determination.json"
    readback = ev_dir / "draft" / "draft-readback.json"

    step("1/4 浏览器取证（真实 Chromium）",
         ["casework/collect.py", args.base_url, str(ev_dir)])
    step("2/4 效力裁决与条款归并",
         ["casework/determine.py", str(ev_json),
          str(ROOT / args.policy), str(ROOT / args.analysis)])
    step("3/4 生成修订后未签章副本",
         ["casework/revise.py", str(ROOT / args.materials), str(det_json),
          str(ev_json), str(ROOT / args.deliverables)])
    if readback.exists():
        step("4/4 进度账（幂等追加）",
             ["casework/journalize.py", str(ev_json), str(det_json),
              str(readback), str(ROOT / args.journal)])
    else:
        print("\n[跳过 4/4] 尚未保存门户草稿；请先运行 save_draft.py 再记账。")
    det = json.loads(det_json.read_text(encoding="utf-8"))
    print("\n流水线完成。封版放行：",
          "否（BLOCKED，待负责人裁决）" if det["seal_decision"]["blocked"]
          else "是", "｜自动签章：否")


if __name__ == "__main__":
    main()
