"""信号报告生成：Markdown（+JSON 供网站读取）。"""
import datetime
import json

import pandas as pd

from src import config, universe
from src.data import store
from src.engine import scorer

ROLE_LABEL = {"core": "核心", "defensive": "防守", "industry": "行业卫星", "region": "国别卫星", "cash": "现金"}


def generate(as_of: str | None = None, save: bool = True) -> dict:
    signals = scorer.score_all(as_of=as_of)
    plan = scorer.build_plan(signals)
    premiums = store.read_df("qdii_premium")
    last_refresh = store.get_meta("last_refresh", "")
    src_flag = "tushare主源" if store.get_meta("tushare_used") == "1" else "akshare/官网兜底源"

    by_key = {s.key: s for s in signals}
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# 四维信号报告",
        f"*生成时间 {now} ｜ 数据源：{src_flag} ｜ 最近刷新：{last_refresh or '未刷新'}*",
        "",
        f"**市场体制**：{plan['regime']} ｜ **组合股票仓位**：{plan['equity_weight']:.0f}%",
        "",
        "## 一、当前操作建议（按打分卡）",
        "",
        "| 资产 | 角色 | 收盘 | 估值分位 | 估值区 | 定投倍数 | 趋势 | 资金 | 宏观 | 总分 | 建议 |",
        "|---|---|---:|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    order = sorted(signals, key=lambda s: (s.role != "core", -(s.total or 0)))
    for s in order:
        lines.append(
            f"| {s.name} | {ROLE_LABEL[s.role]} | {s.close or '—'} | "
            f"{'—' if s.val_pct is None else f'{s.val_pct:.0%}'} | {s.val_zone} | "
            f"{'—' if s.dca_multiplier is None else f'{s.dca_multiplier}x'} | "
            f"{'—' if s.trend_score is None else s.trend_score} | "
            f"{'—' if s.flows_score is None else s.flows_score} | "
            f"{'—' if s.macro_score is None else s.macro_score} | "
            f"**{s.total if s.total is not None else '—'}** | {s.action} |")
    flags = [(s.name, f) for s in signals for f in s.flags if "溢价" in f or "拒买" in f or "缺失" in f or "不足" in f or "压缩" in f]
    if flags:
        lines += ["", "### 风险提示"] + [f"- **{n}**：{f}" for n, f in flags]
    lines += ["", "## 二、组合目标权重（含卫星轮动与估值仓位上限）", ""]
    rows = [(by_key[k].name, ROLE_LABEL[by_key[k].role], w) for k, w in plan["weights"].items() if w > 0]
    lines += ["| 资产 | 角色 | 目标权重 |", "|---|---|---:|"]
    lines += [f"| {n} | {r} | {w:.1f}% |" for n, r, w in sorted(rows, key=lambda x: -x[2])]
    if plan["notes"]:
        lines += ["", "**调仓说明**"] + [f"- {n}" for n in plan["notes"]]
    lines += ["", "## 三、定投计划（本月）", ""]
    lines += ["| 资产 | 基准月投（每1万元股票定投额） | 倍数 | 实际金额 |", "|---|---:|---:|---:|"]
    for k, w in plan["weights"].items():
        if w <= 0:
            continue
        s = by_key[k]
        if s.asset_class not in ("equity_cn", "equity_global") or w < 1:
            continue
        base = w / 100 * 10000
        mult = s.dca_multiplier if s.dca_multiplier is not None else 1.0
        lines.append(f"| {s.name} | {base:.0f} | {mult}x | {base * mult:.0f} |")
    lines += ["", "> 定投额以“每月1万元”示例，按你的实际月投金额等比缩放。",
              "", "## 四、资金面与宏观摘要", ""]
    m = by_key.get("hs300")
    if m and m.flows_detail:
        fd = m.flows_detail
        lines.append(f"- 两融余额20日变化：{fd.get('margin_chg20', '—')}"
                     f"（正=风险偏好回升）；量能比：{fd.get('volume_ratio', '—')}")
    qd = [(r["ts_code"], r["name"], r["premium"]) for _, r in premiums.iterrows()]
    if qd:
        lines.append("- QDII 溢价监控：" + "；".join(
            f"{c} {n} {p:+.1f}%" + ("⚠️超限" if p > config.QDII_PREMIUM_LIMIT else "") for c, n, p in qd))
    if m and m.flows_detail.get("macro_detail"):
        d = m.flows_detail["macro_detail"]
        parts = [f"{k}={v}" for k, v in d.items() if k != "note"]
        lines.append(f"- 中国宏观：{('，'.join(parts)) if parts else d.get('note', '—')}")
    u = by_key.get("spx")
    if u and u.flows_detail.get("macro_detail"):
        d = u.flows_detail["macro_detail"]
        lines.append(f"- 海外：美债10Y {d.get('us10y', '—')}%（3个月{d.get('us10y_chg3m', '—')}pp）")
    lines += ["", "## 五、纪律提醒", "",
              "- 再平衡：单资产偏离目标 ±5pp 触发，季度至少检查一次",
              "- 回撤加仓网格：核心宽基自高点 -15%/-25%/-35% 分批各加 10% 弹药",
              "- 单一行业卫星 ≤10%，单只基金 ≤20%，不加杠杆、不追单日热点",
              "", "*本报告由规则引擎自动生成，不构成投资建议。*", ""]
    md = "\n".join(lines)
    payload = {"generated_at": now, "regime": plan["regime"],
               "equity_weight": plan["equity_weight"], "weights": plan["weights"],
               "notes": plan["notes"], "signals": [s.to_dict() for s in signals],
               "report_md": md}
    if save:
        config.OUTPUT_DIR.mkdir(exist_ok=True)
        (config.OUTPUT_DIR / "latest.md").write_text(md, encoding="utf-8")
        stamp = datetime.datetime.now().strftime("%Y%m%d")
        (config.OUTPUT_DIR / f"signal_report_{stamp}.md").write_text(md, encoding="utf-8")
        (config.OUTPUT_DIR / "latest.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload
