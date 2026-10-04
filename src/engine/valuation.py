"""估值维度：PE/PB（或价格）历史分位 → 估值分 / 定投倍数 / 高低温区。"""
import pandas as pd

from src import config


def rolling_percentile(series: pd.Series, window_days: int = config.VALUATION_WINDOW_DAYS,
                       min_obs: int = config.VALUATION_MIN_OBS) -> float | None:
    """最新值在过去 window_days 自然日内的分位（0~1）。样本不足返回 None。"""
    s = series.dropna()
    if len(s) < min_obs:
        return None
    cut = s.index[-1] - pd.Timedelta(days=window_days)
    win = s[s.index >= cut]
    if len(win) < min_obs:
        return None
    return float((win <= win.iloc[-1]).mean())


def valuation_score(pct: float | None) -> float | None:
    """分位越低越便宜 → 分越高。pct=0.1 → 90 分；pct=0.9 → 10 分。"""
    return None if pct is None else round((1.0 - pct) * 100, 1)


def dca_multiplier(pct: float | None) -> float | None:
    """估值分位 → 定投倍数（手册规则）。None 表示无估值数据，按 1 倍处理。"""
    if pct is None:
        return None
    for upper, mult in config.DCA_BANDS:
        if pct < upper:
            return mult
    return 0.0


def value_zone(pct: float | None) -> str:
    if pct is None:
        return "数据不足"
    if pct < 0.2:
        return "低估"
    if pct < 0.4:
        return "合理偏低"
    if pct < 0.6:
        return "合理"
    if pct < 0.8:
        return "合理偏高"
    return "高估"
