"""资金面维度：两融余额、成交额趋势、QDII 溢价、美债利率对海外资产的压力。

注：北向资金当日净买入自 2024-08 起停止实时披露，本体系改用
两融 + ETF/指数成交趋势 + 港通持股存量（如可得）作为风险偏好代理。
"""
import math

import pandas as pd

from src import config
from src.data import store


def margin_chg(margin_df: pd.DataFrame, window: int = 20) -> float | None:
    """融资余额近 window 个交易日的涨跌幅。"""
    if margin_df.empty or len(margin_df) < window + 1:
        return None
    s = margin_df.set_index("trade_date")["rzye"].astype(float).sort_index()
    s.index = pd.to_datetime(s.index)
    return float(s.iloc[-1] / s.iloc[-1 - window] - 1)


def volume_ratio(price_df: pd.DataFrame, short: int = 20, long: int = 120) -> float | None:
    """短期成交额（缺失时用成交量）相对长期均值倍数。"""
    if price_df.empty:
        return None
    col = "amount" if "amount" in price_df.columns and price_df["amount"].notna().sum() > long else "vol"
    if col not in price_df.columns:
        return None
    s = pd.to_numeric(price_df[col], errors="coerce").dropna()
    if len(s) < long + 1:
        return None
    return float(s.iloc[-short:].mean() / s.iloc[-long:].mean())


def us10y_chg(months: int = 3, cutoff: str | None = None) -> float | None:
    s = store.load_macro("us10y")
    if cutoff and not s.empty:
        s = s[s.index <= pd.Timestamp(cutoff)]
    if len(s) < 30:
        return None
    last = s.iloc[-1]
    base = s[s.index >= s.index[-1] - pd.DateOffset(months=months)]
    if len(base) < 5:
        return None
    return float(last - base.iloc[0])


def qdii_premiums() -> dict[str, dict]:
    df = store.read_df("qdii_premium")
    return {r["ts_code"]: {"name": r["name"], "premium": r["premium"], "updated": r["updated"]}
            for _, r in df.iterrows()}


def flows_score(asset, price_df: pd.DataFrame, margin_chg20: float | None,
                us10y_chg3m: float | None) -> tuple[float | None, dict]:
    """资金面分 0-100。中股看两融+量能；海外看美债利率方向；债/金看量能。"""
    detail = {}
    vr = volume_ratio(price_df)
    detail["volume_ratio"] = None if vr is None else round(vr, 2)
    if asset.asset_class == "equity_cn":
        detail["margin_chg20"] = None if margin_chg20 is None else round(margin_chg20, 4)
        if margin_chg20 is None and vr is None:
            return None, detail
        score = 50.0
        if margin_chg20 is not None:
            score += 30 * math.tanh(margin_chg20 / 0.02)
        if vr is not None:
            score += 20 * math.tanh((vr - 1) / 0.3)
        return round(min(max(score, 0), 100), 1), detail
    if asset.asset_class == "equity_global":
        detail["us10y_chg3m"] = None if us10y_chg3m is None else round(us10y_chg3m, 2)
        score = 50.0
        if us10y_chg3m is not None:  # 利率下行利多成长股
            score += 30 * math.tanh(-us10y_chg3m / 0.4)
        if vr is not None:
            score += 15 * math.tanh((vr - 1) / 0.3)
        return round(min(max(score, 0), 100), 1), detail
    if vr is None:
        return None, detail
    return round(50 + 25 * math.tanh((vr - 1) / 0.3), 1), detail


def premium_flag(asset, premiums: dict[str, dict]) -> tuple[bool, float | None]:
    """QDII 溢价检查：True 表示溢价超限应拒买。"""
    if not asset.etf or asset.etf not in premiums:
        return False, None
    p = premiums[asset.etf].get("premium")
    if p is None:
        return False, None
    return p > config.QDII_PREMIUM_LIMIT, p
