"""命令行入口：python -m src.cli {fetch|score|report|backtest|all}"""
import argparse
import json
import sys

from src.data.collector import refresh_all
from src.report import generate


def cmd_fetch(args):
    refresh_all(verbose=True)


def cmd_score(args):
    from src.engine import scorer
    sigs = scorer.score_all()
    plan = scorer.build_plan(sigs)
    for s in sorted(sigs, key=lambda x: -(x.total or 0)):
        print(f"{s.name:8s} 总分{s.total if s.total is not None else '—':>5} "
              f"估值{'—' if s.val_pct is None else format(s.val_pct, '.0%'):>4} "
              f"定投{'—' if s.dca_multiplier is None else str(s.dca_multiplier) + 'x':>4} "
              f"趋势{s.trend_score if s.trend_score is not None else '—':>5} "
              f"建议: {s.action}")
    print("\n组合体制:", plan["regime"], "| 股票仓位:", plan["equity_weight"], "%")
    for n in plan["notes"]:
        print(" -", n)


def cmd_report(args):
    payload = generate(save=not args.no_save)
    if args.no_save:
        print(payload["report_md"])
    else:
        print("报告已生成: output/latest.md")


def cmd_backtest(args):
    from src import backtest
    result = backtest.run()
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "curve"}
                      for k, v in result["strategies"].items()},
                     ensure_ascii=False, indent=1))


def main():
    p = argparse.ArgumentParser(prog="invest-strategy")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch", help="刷新全部数据（三源降级）").set_defaults(func=cmd_fetch)
    sub.add_parser("score", help="计算当前信号与组合计划").set_defaults(func=cmd_score)
    rp = sub.add_parser("report", help="生成信号报告")
    rp.add_argument("--no-save", action="store_true", help="仅打印不落盘")
    rp.set_defaults(func=cmd_report)
    sub.add_parser("backtest", help="运行历史回测").set_defaults(func=cmd_backtest)
    allp = sub.add_parser("all", help="刷新→信号→报告→回测 一键执行")
    allp.set_defaults(func=lambda a: (cmd_fetch(a), cmd_score(a), cmd_report(a), cmd_backtest(a)))
    args = p.parse_args()
    try:
        args.func(args)
    except Exception as e:  # noqa: BLE001
        print(f"[错误] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
