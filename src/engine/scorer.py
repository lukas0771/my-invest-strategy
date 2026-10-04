"""打分卡引擎：四维信号加权 → 每资产 0-100 分 → 操作建议 + 组合目标权重。

维度：估值 40% / 趋势 30% / 资金 15% / 宏观 15%；缺项自动按剩余权重归一。
组合层：行业卫星按动量排名选 3 名（4%/4%/2%），国别卫星趋势门槛制，
股票总仓位受沪深300估值分位上限约束，超限部分回流债券(70%)+现金(30%)。
"""
import math
from dataclasses import dataclass, field, asdict

import pandas as pd

from src import config
from src import universe
from src.data import store
from src.engine import flows, macro, trend, valuation


@dataclass
class AssetSignal:
    key: str
    name: str
    role: str
    asset_class: str
    target_weight: float = 0.0
    close: float | None = None
    last_date: str = ""
    val_pct: float | None = None
    val_score: float | None = None
    val_zone: str = "数据不足"
    dca_multiplier: float | None = None
    trend_score: float | None = None
    trend_detail: dict = field(default_factory=dict)
    flows_score: float | None = None
    flows_detail: dict = field(default_factory=dict)
    macro_score: float | None = None
    total: float | None = None
    action: str = ""
    flags: list[str] = field(default_factory=list)
    stale: bool = False

    def to_dict(self):
        return asdict(self)


def _val_percentile(asset, cutoff: str | None = None) -> tuple[float | None, list[str]]:
    flags = []
    if asset.valuation in ("pe_ttm", "pb_only"):
        df = store.load_valuation(asset.ts_index,
                                  start=(pd.Timestamp.today() - pd.Timedelta(days=3650 + 30)).strftime("%Y-%m-%d"))
        if cutoff and not df.empty:
            df = df[df.index <= pd.Timestamp(cutoff)]
        pct = None
        if not df.empty:
            if asset.valuation == "pb_only":
                pct = valuation.rolling_percentile(df["pb"].astype(float))
                if pct is not None:
                    return pct, flags
                pct = valuation.rolling_percentile(df["pe_ttm"].astype(float))
                if pct is not None:
                    flags.append("PB缺失改用PE分位")
                    return pct, flags
            else:
                pct = valuation.rolling_percentile(df["pe_ttm"].astype(float))
                if pct is not None:
                    return pct, flags
                pct = valuation.rolling_percentile(df["pb"].astype(float))
                if pct is not None:
                    flags.append("PE缺失改用PB分位")
                    return pct, flags
        # 兜底：PE/PB 均不可得 → 价格分位（明确标注弱假设）
        pxf = store.load_price(ts_code=asset.ts_index, ts_global=asset.ts_global, etf=asset.etf,
                               start=(pd.Timestamp.today() - pd.Timedelta(days=3650 + 30)).strftime("%Y-%m-%d"))
        if cutoff:
            pxf = pxf[pxf.index <= pd.Timestamp(cutoff)]
        pct = valuation.rolling_percentile(pxf)
        if pct is not None:
            flags.append("PE/PB缺失，用价格分位替代")
            return pct, flags
        return None, flags + ["估值历史不足"]
    if asset.valuation == "shiller":
        s = store.load_macro("sp500_shiller_pe")
        if cutoff:
            s = s[s.index <= pd.Timestamp(cutoff)]
        if s.empty:
            return None, ["Shiller PE 数据缺失"]
        win = s[s.index >= s.index[-1] - pd.DateOffset(years=15)]
        if len(win) < 120:
            return None, ["Shiller PE 历史不足"]
        return float((win <= win.iloc[-1]).mean()), flags
    if asset.valuation == "price_fallback":
        px = store.load_price(ts_code=asset.ts_index, ts_global=asset.ts_global, etf=asset.etf,
                              start=(pd.Timestamp.today() - pd.Timedelta(days=3650 + 30)).strftime("%Y-%m-%d"))
        if cutoff:
            px = px[px.index <= pd.Timestamp(cutoff)]
        pct = valuation.rolling_percentile(px)
        if pct is None:
            return None, flags
        flags.append("价格分位替代PE（弱均值回归假设）")
        return pct, flags
    return None, flags


def score_all(as_of: str | None = None) -> list[AssetSignal]:
    """as_of=None 用最新数据；给定日期则截断到该时点（回测防未来函数）。"""
    store.init_db()
    margin_df = store.read_df("margin", order="trade_date")
    if as_of:
        margin_df = margin_df[margin_df["trade_date"] <= as_of]
    m_chg = flows.margin_chg(margin_df)
    u_chg = flows.us10y_chg(cutoff=as_of)
    cn_score, cn_detail = macro.cn_macro_score(cutoff=as_of)
    us_score, us_detail = macro.us_macro_score(cutoff=as_of)
    premiums = flows.qdii_premiums() if not as_of else {}
    today = pd.Timestamp(as_of) if as_of else pd.Timestamp.today()
    out = []
    for a in universe.ASSETS:
        px = store.load_price(ts_code=a.ts_index, ts_global=a.ts_global, etf=a.etf,
                              as_series=False)
        if as_of and not px.empty:
            px = px[px["date"] <= pd.Timestamp(as_of)]
        sig = AssetSignal(key=a.key, name=a.name, role=a.role, asset_class=a.asset_class,
                          target_weight=a.target_weight)
        if a.key == "cash":
            sig.action = "现金池：承接未选中的卫星预算与止盈资金"
            out.append(sig)
            continue
        if px.empty:
            sig.action = "无数据（待刷新/数据源不可用）"
            sig.flags.append("价格序列缺失")
            out.append(sig)
            continue
        close = px.set_index("date")["close"].astype(float)
        sig.close = round(float(close.iloc[-1]), 2)
        sig.last_date = close.index[-1].strftime("%Y-%m-%d")
        sig.stale = (today - close.index[-1]).days > 10
        # 四维
        pct, vflags = _val_percentile(a, as_of)
        sig.val_pct = pct
        sig.val_score = valuation.valuation_score(pct)
        sig.val_zone = valuation.value_zone(pct)
        sig.dca_multiplier = valuation.dca_multiplier(pct)
        sig.trend_score, sig.trend_detail = trend.trend_score(close)
        sig.flows_score, sig.flows_detail = flows.flows_score(a, px, m_chg, u_chg)
        if a.needs_macro == "cn":
            sig.macro_score, sig.flows_detail["macro_detail"] = cn_score, cn_detail
        elif a.needs_macro == "us":
            sig.macro_score, sig.flows_detail["macro_detail"] = us_score, us_detail
        sig.flags += vflags
        # 加权总分（缺项归一）
        parts = {"valuation": sig.val_score, "trend": sig.trend_score,
                 "flows": sig.flows_score, "macro": sig.macro_score}
        num = den = 0.0
        for k, v in parts.items():
            if v is not None:
                num += config.WEIGHTS[k] * v
                den += config.WEIGHTS[k]
        sig.total = round(num / den, 1) if den > 0 else None
        # 操作建议
        prem_bad, prem = flows.premium_flag(a, premiums)
        if prem_bad:
            sig.flags.append(f"QDII溢价{prem:.1f}%>{config.QDII_PREMIUM_LIMIT}%，暂拒买")
            sig.action = "溢价超限，暂停买入"
        if a.role in ("industry", "region"):
            sig.action = ""  # 由 build_plan 决定入选与否
        elif sig.val_zone == "高估":
            sig.action = "止盈观察区：停投，分批止盈"
        elif sig.total is not None and sig.total >= 65:
            sig.action = "偏多：按倍数定投/持有"
        elif sig.total is not None and sig.total <= 40:
            sig.action = "偏空：控制仓位，等企稳"
        else:
            sig.action = "中性：按计划定投"
        out.append(sig)
    return out


def build_plan(signals: list[AssetSignal]) -> dict:
    """战略基准 + 卫星轮动 + 估值仓位上限 → 组合目标权重与说明。"""
    by_key = {s.key: s for s in signals}
    weights = {a.key: a.target_weight for a in universe.ASSETS}
    notes: list[str] = []

    # 1) 行业卫星：动量排名 + 趋势门槛
    ind_scores = {}
    for k in universe.INDUSTRY_KEYS:
        s = by_key.get(k)
        if s and s.trend_score is not None and s.trend_score >= config.TREND_GATE_SCORE:
            mom = s.trend_detail.get("momentum")
            ind_scores[k] = (mom if mom is not None else -9) + (s.trend_score or 0) / 1000
    picked = sorted(ind_scores, key=ind_scores.get, reverse=True)[:3]
    slot_w = [4.0, 4.0, 2.0]
    used_ind = 0.0
    for i, k in enumerate(picked):
        weights[k] = slot_w[i]
        used_ind += slot_w[i]
        by_key[k].action = f"入选行业卫星（动量第{i + 1}，配{slot_w[i]:.0f}%）"
    for k in universe.INDUSTRY_KEYS:
        if k not in picked:
            weights[k] = 0.0
            if by_key.get(k):
                by_key[k].action = "未入选卫星（动量/趋势不达标）"
    freed = max(0.0, config.SATELLITE_INDUSTRY_BUDGET - used_ind)
    if freed > 0:
        notes.append(f"行业卫星仅用{used_ind:.0f}%/预算{config.SATELLITE_INDUSTRY_BUDGET:.0f}%，"
                     f"差额{freed:.0f}%回流现金")

    # 2) 国别卫星：趋势门槛，不达标回流现金
    for k in universe.REGION_KEYS:
        s = by_key.get(k)
        if s and (s.trend_score is None or s.trend_score < config.TREND_GATE_SCORE):
            freed += weights[k]
            weights[k] = 0.0
            if s:
                s.action = "未入选卫星（趋势不达标，预算回流现金）"
        elif s and not s.action:
            s.action = "持有（国别卫星）"
    if freed > 0:
        weights["cash"] = round(weights.get("cash", 0) + freed, 2)

    # 3) 股票仓位上限（沪深300估值分位）
    hs = by_key.get("hs300")
    equity_cap = 0.85
    if hs and hs.val_pct is not None:
        for lo, cap in config.EQUITY_CAP_BANDS:
            if hs.val_pct >= lo:
                equity_cap = cap
                break
        notes.append(f"沪深300估值分位{hs.val_pct:.0%} → 股票仓位上限{equity_cap:.0%}")
    equity_keys = [a.key for a in universe.ASSETS
                   if a.asset_class in ("equity_cn", "equity_global")]
    equity_total = sum(weights[k] for k in equity_keys)
    if equity_total > equity_cap * 100:
        scale = equity_cap * 100 / equity_total
        excess = 0.0
        for k in equity_keys:
            new_w = weights[k] * scale
            excess += weights[k] - new_w
            weights[k] = round(new_w, 2)
            by_key[k].flags.append("受估值仓位上限压缩")
        weights["bond"] = round(weights.get("bond", 0) + excess * 0.7, 2)
        weights["cash"] = round(weights.get("cash", 0) + excess * 0.3, 2)
        notes.append(f"股票仓位{equity_total:.0f}%超上限，已压缩至{equity_cap * 100:.0f}%，"
                     f"超出部分70%入债/30%入现金")

    # 4) 汇总
    total = sum(weights.values())
    assert abs(total - 100) < 0.5, f"权重合计异常: {total}"
    regime = "未知"
    if hs and hs.trend_detail.get("above_ma200") is not None:
        regime = "偏多（沪深300在200日线上方）" if hs.trend_detail["above_ma200"] else \
                 "偏空（沪深300在200日线下方）"
    return {"weights": weights, "notes": notes, "regime": regime,
            "equity_weight": round(sum(weights[k] for k in equity_keys), 1),
            "regime_detail": {"cn_macro": by_key.get("hs300", AssetSignal("", "", "", "")).flows_detail.get("macro_detail", {})}}
