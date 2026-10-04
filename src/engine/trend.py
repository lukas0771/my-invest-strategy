"""趋势/技术维度：200日均线牛熊界 + 12-1月动量（剔除近月，学术标准动量因子）。"""
import math

import pandas as pd

from src import config


def ma_long_flag(close: pd.Series, window: int = config.MA_LONG) -> bool | None:
    s = close.dropna()
    if len(s) < window:
        return None
    return bool(s.iloc[-1] > s.rolling(window).mean().iloc[-1])


def momentum_12_1(close: pd.Series) -> tuple[float | None, bool]:
    """12-1 月动量（过去12个月剔除最近21日）。历史不足252日但≥120日时退化为 6-1 动量。
    返回 (动量值, 是否短窗口)。"""
    s = close.dropna()
    need = config.MOMENTUM_LOOKBACK_DAYS + config.MOMENTUM_SKIP_DAYS
    if len(s) >= need:
        m = s.iloc[-1 - config.MOMENTUM_SKIP_DAYS] / s.iloc[-need] - 1
        return float(m), False
    if len(s) >= 120 + config.MOMENTUM_SKIP_DAYS:
        m = s.iloc[-1 - config.MOMENTUM_SKIP_DAYS] / s.iloc[-120 - config.MOMENTUM_SKIP_DAYS] - 1
        return float(m), True
    return None, False


def trend_score(close: pd.Series) -> tuple[float | None, dict]:
    """趋势分 0-100：均线位置 60 分 + 动量强度 40 分。"""
    s = close.dropna()
    above = ma_long_flag(s)
    m, short = momentum_12_1(s)
    detail = {"above_ma200": above, "momentum": None if m is None else round(m, 4),
              "momentum_short_window": short}
    if above is None and m is None:
        return None, detail
    ma_comp = {True: 60.0, False: 35.0, None: 30.0}[above]
    mom_comp = 40.0 * (0.5 + 0.5 * math.tanh(m / 0.25)) if m is not None else 20.0
    return round(ma_comp + mom_comp, 1), detail


def rank_by_momentum(scores: dict[str, float]) -> list[str]:
    """按趋势分降序排列的 key 列表（用于卫星轮动排名）。"""
    return sorted(scores, key=lambda k: scores.get(k, -1), reverse=True)
