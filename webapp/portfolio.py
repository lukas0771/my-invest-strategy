"""持仓跟踪与再平衡计算：读 portfolio 表 → 最新价估值 → 偏离与调仓金额。"""
import re

import pandas as pd

from src import universe
from src.data import store


def _ts_fund_nav(code: str) -> tuple[float, str] | None:
    """tushare 基金净值（场外 .OF / 场内 .SH/.SZ），有 token 才可用；结果缓存入 fund_nav 表。"""
    from src.data.ts_source import TushareSource
    try:
        ts = TushareSource()
        if not ts.available:
            return None
        suffixes = [".OF"] if not code.startswith(("5", "1")) else [".SH", ".SZ", ".OF"]
        for suf in suffixes:
            try:
                df = ts._call("fund_nav", ts_code=code + suf)
            except Exception:
                continue
            if df is not None and not df.empty:
                df = df.sort_values("nav_date")
                last = df.iloc[-1]
                out = df[["ts_code", "nav_date", "unit_nav", "accum_nav"]].dropna(subset=["unit_nav"])
                out["ts_code"] = code  # 统一裸代码入库
                store.upsert_df("fund_nav", out, ["ts_code", "nav_date"])
                return float(last["unit_nav"]), last["nav_date"]
    except Exception:
        return None
    return None


def _latest_price(code: str, asset_key: str) -> tuple[float, str]:
    """价格解析：6位基金代码 → 基金净值/基金日线（绝不混用指数点位）；
    其他/留空 → 按资产映射取指数最新收盘价。"""
    code = str(code).strip()
    if re.fullmatch(r"\d{6}", code):
        df = store.read_df("fund_daily", f"ts_code='{code}'", order="trade_date DESC")
        if not df.empty:
            return float(df["close"].iloc[0]), df["trade_date"].iloc[0]
        df = store.read_df("fund_nav", f"ts_code='{code}'", order="nav_date DESC")
        if not df.empty:
            return float(df["unit_nav"].iloc[0]), df["nav_date"].iloc[0]
        nav = _ts_fund_nav(code)
        if nav:
            return nav
        return 0.0, ""  # 无基金价格数据 → 回退按成本估值
    asset = universe.ASSETS_BY_KEY.get(asset_key)
    if asset:
        for kwargs in ({"ts_code": asset.ts_index}, {"ts_global": asset.ts_global}, {"etf": asset.etf}):
            if any(kwargs.values()):
                px = store.load_price(as_series=False, **kwargs)
                if not px.empty:
                    row = px.sort_values("date").iloc[-1]
                    return float(row["close"]), row["trade_date"]
    return 0.0, ""


def portfolio_view() -> dict:
    holdings = store.read_portfolio()
    plan_sigs = {s.key: s for s in _current_signals()}
    plan = _current_plan()
    rows, total_value = [], 0.0
    for _, h in holdings.iterrows():
        price, pdate = _latest_price(str(h["code"]), str(h["asset_key"]))
        value = price * float(h["shares"]) if price else float(h["cost"]) * float(h["shares"])
        total_value += value
        rows.append({"id": int(h["id"]), "code": h["code"], "name": h["name"],
                     "asset_key": h["asset_key"], "shares": h["shares"], "cost": h["cost"],
                     "price": price, "price_date": pdate, "value": round(value, 2),
                     "pl": round(value - float(h["cost"]) * float(h["shares"]), 2),
                     "pl_pct": round((price / float(h["cost"]) - 1) * 100, 2)
                     if price and float(h["cost"]) > 0 else None})
    # 权重与再平衡
    rebalance = []
    if total_value > 0 and rows:
        cur_by_key: dict[str, float] = {}
        for r in rows:
            cur_by_key[r["asset_key"]] = cur_by_key.get(r["asset_key"], 0) + r["value"]
        for key, w in plan.get("weights", {}).items():
            target_val = w / 100 * total_value
            cur_val = cur_by_key.get(key, 0.0)
            cur_w = cur_val / total_value * 100
            dev = cur_w - w
            sig = plan_sigs.get(key)
            rebalance.append({
                "key": key, "name": sig.name if sig else key,
                "cur_weight": round(cur_w, 1), "target_weight": w,
                "dev": round(dev, 1), "cur_value": round(cur_val, 2),
                "target_value": round(target_val, 2),
                "trade": round(target_val - cur_val, 0),
                "trigger": abs(dev) >= 5.0})
    return {"rows": rows, "total_value": round(total_value, 2),
            "rebalance": rebalance,
            "rebalance_note": "偏离 ≥ ±5pp 的行会标记触发；trade>0 表示需买入金额，<0 表示需卖出金额（元）"}


_CACHE = {"ts": None, "sigs": None, "plan": None}


def _current_signals():
    from src.engine import scorer
    now = pd.Timestamp.now()
    if _CACHE["ts"] is None or (now - _CACHE["ts"]).seconds > 300:
        _CACHE["sigs"] = scorer.score_all()
        _CACHE["plan"] = scorer.build_plan(_CACHE["sigs"])
        _CACHE["ts"] = now
    return _CACHE["sigs"]


def _current_plan():
    _current_signals()
    return _CACHE["plan"]
