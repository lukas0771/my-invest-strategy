"""月度调仓回测：打分卡策略 vs 基准（指数层面模拟，不含申赎费与跟踪误差）。

防未来函数：每个调仓月末 t 只用 t 及之前的数据算信号，权重作用于下月收益。
"""
import json
import math

import numpy as np
import pandas as pd

from src import config, universe
from src.data import store
from src.engine import scorer

CASH_RATE = 0.02  # 现金年化（简化）


def load_price_matrix(start: str = config.BACKTEST_START) -> pd.DataFrame:
    cols = {}
    for a in universe.ASSETS:
        if a.key == "cash":
            continue
        px = store.load_price(ts_code=a.ts_index, ts_global=a.ts_global, etf=a.etf, start=start)
        if not px.empty:
            cols[a.key] = px
    df = pd.DataFrame(cols).sort_index()
    df = df.ffill(limit=5)  # 跨市场日历对齐（美股/港股假日）
    return df.dropna(how="all")


def _plan_at(t: pd.Timestamp, px_hist: pd.DataFrame) -> dict | None:
    sigs = scorer.score_all(as_of=t.strftime("%Y-%m-%d"))
    have_data = sum(1 for s in sigs if s.total is not None)
    if have_data < 6:  # 信号体系尚未成熟（估值历史不足）
        return None
    return scorer.build_plan(sigs)


def run(start: str = config.BACKTEST_START, end: str | None = None, verbose: bool = True) -> dict:
    """自选区间回测。start 为交易起点；数据加载会向 earlier 预热约4年，
    保证起点当月的估值分位/均线信号仍有效（否则信号会退化）。"""
    start_ts = pd.Timestamp(start)
    warmup = max(pd.Timestamp("2010-01-01"), start_ts - pd.DateOffset(years=4))
    px = load_price_matrix(warmup.strftime("%Y-%m-%d"))
    if px.empty:
        raise RuntimeError("无价格数据，请先执行数据刷新")
    rets = px.pct_change(fill_method=None)
    base_weights = {a.key: a.target_weight for a in universe.ASSETS}
    # 每月最后一个"实际交易日"（resample 的日历月末大多不是交易日，会 KeyError）
    month_ends = pd.DatetimeIndex(
        px.index.to_series().groupby(px.index.to_period("M")).max().sort_values())
    month_ends = month_ends[month_ends >= start_ts]
    if end:
        month_ends = month_ends[month_ends <= pd.Timestamp(end)]
    if len(month_ends) < 7:
        raise RuntimeError(f"回测区间太短（{start} ~ {end or '最新'}），至少需要约6个月")

    strategies = {"score_card": [], "core_fixed": [], "hs300_bh": [], "sixty_forty": []}
    dates_out, weights_out = [], []
    for i in range(len(month_ends) - 1):
        t = month_ends[i]
        nxt = month_ends[i + 1]
        # 信号只用 t 及以前的数据；信号体系未成熟期视为持币
        plan = _plan_at(t, px)
        # 下月各资产收益（月末收盘价之比）
        try:
            p0, p1 = px.loc[t], px.loc[nxt]
        except KeyError:
            continue
        r = (p1 / p0 - 1).fillna(0.0)
        r["cash"] = (1 + CASH_RATE) ** ((nxt - t).days / 365) - 1

        w_score = {k: float(v) / 100 for k, v in plan["weights"].items()} if plan else {"cash": 1.0}
        strategies["score_card"].append(sum(w_score.get(k, 0) * r.get(k, 0) for k in w_score))
        if plan:
            dates_out.append(nxt.strftime("%Y-%m"))
            weights_out.append({"month": nxt.strftime("%Y-%m"), "weights": plan["weights"]})

        w_core = {k: base_weights.get(k, 0) for k in px.columns}
        w_core = {k: v / 100 for k, v in w_core.items()}
        w_core["cash"] = w_core.get("cash", 0) + max(0.0, 1 - sum(w_core.values()))
        strategies["core_fixed"].append(sum(w_core[k] * r.get(k, 0) for k in w_core))

        r_hs = r.get("hs300", 0.0)
        r_bond = r.get("bond", 0.0)
        strategies["hs300_bh"].append(r_hs)
        strategies["sixty_forty"].append(0.6 * r_hs + 0.4 * r_bond + 0.0)

    def equity_curve(monthly_rets: list[float]) -> pd.Series:
        idx = month_ends[1:1 + len(monthly_rets)]
        return pd.Series([math.prod(1 + x for x in monthly_rets[:i + 1]) for i in range(len(monthly_rets))], index=idx)

    def metrics(monthly_rets: list[float]) -> dict:
        r = np.array(monthly_rets)
        if len(r) == 0:
            return {}
        curve = equity_curve(monthly_rets)
        years = len(r) / 12
        cagr = curve.iloc[-1] ** (1 / years) - 1 if curve.iloc[-1] > 0 else -1.0
        vol = float(r.std(ddof=1) * math.sqrt(12))
        dd = float((curve / curve.cummax() - 1).min())
        sharpe = float((r.mean() * 12 - config.BACKTEST_RF) / vol) if vol > 0 else 0.0
        yearly = {}
        for y, grp in pd.Series(r, index=curve.index).groupby(curve.index.year):
            yearly[int(y)] = round(float((1 + grp).prod() - 1), 4)
        return {"cagr": round(cagr, 4), "vol": round(vol, 4), "max_drawdown": round(dd, 4),
                "sharpe": round(sharpe, 2), "months": len(r), "yearly": yearly,
                "curve": {d.strftime("%Y-%m"): round(v, 4) for d, v in curve.items()}}

    result = {
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "start": month_ends[0].strftime("%Y-%m"), "end": month_ends[-1].strftime("%Y-%m"),
        "range": {"start": start, "end": end or "最新"},
        "note": "指数层面月度调仓模拟：不含申赎费/跟踪误差/汇率损益；信号仅用调仓月末及以前数据"
                f"（数据自 {warmup.strftime('%Y-%m')} 预热，起点当月信号已成熟）",
        "strategies": {k: metrics(v) for k, v in strategies.items()},
        "strategy_names": {"score_card": "四维打分卡(核心-卫星+估值上限)",
                           "core_fixed": "核心固定(无卫星/无择时)",
                           "hs300_bh": "沪深300买入持有", "sixty_forty": "60/40股债"},
        "weights_history": weights_out,
    }
    out = config.OUTPUT_DIR / "backtest.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    # 区间缓存：同一区间重复回测直接读文件
    tag = f"{month_ends[0].strftime('%Y%m')}_{month_ends[-1].strftime('%Y%m')}"
    (config.OUTPUT_DIR / f"backtest_{tag}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if verbose:
        for k, m in result["strategies"].items():
            print(f"  {k:12s} 年化{m['cagr']:+.1%} 回撤{m['max_drawdown']:.1%} "
                  f"夏普{m['sharpe']:.2f} ({m['months']}个月)")
    return result


if __name__ == "__main__":
    run()
