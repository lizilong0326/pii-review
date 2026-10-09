"""命令行入口。

  python -m pii_review import <file>       # 导入并检测
  python -m pii_review list                # 列出已导入文件
  python -m pii_review review <sha>        # 命令行逐项复核
  python -m pii_review export <sha> [-o d] # 导出脱敏文件 + 审计清单
  python -m pii_review cleanup <sha>       # 清理本机状态
  python -m pii_review regression          # 固定合成题集漏检/误报回归
  python -m pii_review serve [--port]      # 启动本地 Web 复核界面
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .models import PII_TYPE_LABEL
from .pipeline import export_file, import_file, record_decision, run_regression
from .state import cleanup_state, load_index, load_state, unreviewed_count


def _print_candidate(i: int, c) -> None:
    conf = "高把握命中" if c.confidence == "high" else "需人工判断"
    label = PII_TYPE_LABEL.get(c.pii_type, c.pii_type)
    print(f"  [{i}] {label} · {conf} · 第{c.page_no}页")
    print(f"      命中原文：{c.text}")
    print(f"      上下文：…{c.context}…")


def cmd_import(args) -> int:
    try:
        state, dup = import_file(args.file, force=args.force)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 导入失败：{exc}")
        return 1
    if dup:
        print(f"⚠️ 该文件已导入过（sha256 {state.sha256[:16]}…），跳过。可用 --force 重新导入。")
    else:
        print(f"✅ 已导入：{state.title}")
        print(f"   sha256：{state.sha256}")
        print(f"   候选：{len(state.candidates)} 项（高把握 {sum(1 for c in state.candidates if c.confidence=='high')}，"
              f"需人工判断 {sum(1 for c in state.candidates if c.confidence=='low')}）")
        print(f"   未审核：{unreviewed_count(state)} 项")
        for i, c in enumerate(state.candidates, 1):
            _print_candidate(i, c)
    return 0


def cmd_list(args) -> int:
    index = load_index()
    if not index:
        print("（空）尚未导入任何文件。")
        return 0
    for sha, meta in index.items():
        print(f"{sha[:16]}…  {meta.get('title','')}  [{meta.get('status','')}]  "
              f"候选{meta.get('candidate_count',0)} 已审{meta.get('reviewed_count',0)}")
    return 0


def cmd_review(args) -> int:
    state = load_state(args.sha)
    if state is None:
        print("❌ 未找到该文件状态。")
        return 1
    pending = [c for c in state.candidates if c.id not in state.decisions]
    if not pending:
        print("✅ 所有候选均已审核。")
        return 0
    actions = {"1": "redact", "2": "replace", "3": "keep", "4": "false_positive"}
    for c in pending:
        print()
        _print_candidate(1, c)
        while True:
            ans = input("处理方式 [1遮盖 2替换 3保留 4误报，回车跳过]：").strip()
            if not ans:
                break
            if ans not in actions:
                print("请输入 1-4。")
                continue
            reason = input("理由（可空）：").strip()
            record_decision(args.sha, c.id, actions[ans], reason)
            print("   已记录。")
            break
    state = load_state(args.sha)
    print(f"\n完成，剩余未审核：{unreviewed_count(state)} 项。")
    return 0


def cmd_export(args) -> int:
    try:
        audit = export_file(args.sha, args.out)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 导出失败：{exc}")
        return 1
    s = audit["summary"]
    print(f"✅ 已导出到 {args.out}/")
    print(f"   候选 {s['candidate_total']} · 已审核 {s['reviewed']} · "
          f"未处理 {s['unprocessed']} · 解析失败 {s['parse_errors']}")
    return 0


def cmd_cleanup(args) -> int:
    state = load_state(args.sha)
    if state is None:
        print("❌ 未找到该文件状态。")
        return 1
    if not args.yes:
        ans = input(f"确认删除 {state.title} 的本机状态与临时文件？[y/N]：").strip().lower()
        if ans not in ("y", "yes"):
            print("已取消。")
            return 0
    cleanup_state(args.sha)
    print(f"✅ 已清理 {args.sha[:16]}… 的本机状态。")
    return 0


def cmd_regression(args) -> int:
    import json
    gt = json.loads(Path(args.ground_truth).read_text(encoding="utf-8"))
    result = run_regression(args.samples, gt)
    print(f"召回率：{result['recall']:.2%}（{result['total_positive'] - len(result['misses'])}/{result['total_positive']}）")
    print(f"误报率：{result['false_positive_rate']:.2%}（{len(result['false_positives'])}/{result['total_positive']}正例规模）")
    if result["misses"]:
        print("漏检：")
        for m in result["misses"]:
            print(f"  - {m['file']} [{m['type']}] {m['text']}")
    if result["false_positives"]:
        print("误报：")
        for f in result["false_positives"]:
            print(f"  - {f['file']} {f['text']}")
    return 0


def cmd_serve(args) -> int:
    from .webui import run_server
    run_server(port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pii_review", description="个人信息复核器（PII Review）")
    p.add_argument("--version", action="version", version=f"pii_review {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("import", help="导入文档并检测")
    i.add_argument("file")
    i.add_argument("--force", action="store_true", help="重复导入时强制重建")
    i.set_defaults(func=cmd_import)

    sub.add_parser("list", help="列出已导入文件").set_defaults(func=cmd_list)

    r = sub.add_parser("review", help="命令行逐项复核")
    r.add_argument("sha")
    r.set_defaults(func=cmd_review)

    e = sub.add_parser("export", help="导出脱敏文件 + 审计清单")
    e.add_argument("sha")
    e.add_argument("-o", "--out", default="out")
    e.set_defaults(func=cmd_export)

    c = sub.add_parser("cleanup", help="清理本机状态（破坏性）")
    c.add_argument("sha")
    c.add_argument("--yes", action="store_true", help="跳过确认")
    c.set_defaults(func=cmd_cleanup)

    g = sub.add_parser("regression", help="固定合成题集回归")
    g.add_argument("--samples", default="data/samples")
    g.add_argument("--ground-truth", default="data/ground_truth.json")
    g.set_defaults(func=cmd_regression)

    s = sub.add_parser("serve", help="启动本地 Web 复核界面")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(func=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
