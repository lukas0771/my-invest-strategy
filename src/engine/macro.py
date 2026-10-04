"""宏观维度：PMI / 社融滚动同比 / M1-M2 剪刀差 / CPI-PPI（中国），美债10Y方向（海外）。

所有函数支持 cutoff 时点截断（回测防未来函数）；None 表示用最新数据。
"""
import math

import pandas as pd

from src.data import store


def _load(series: str, cutoff: str | None = None) -> pd.Series:
    s = store.load_macro(series)
    if cutoff and not s.empty:
        s = s[s.index <= pd.Timestamp(cutoff)]
    return s


def _trend_sign(s: pd.Series, months: int = 3) -> float:
    base = s[s.index >= s.index[-1] - pd.DateOffset(months=months)]
    if len(base) < 2:
        return 0.0
    return float(s.iloc[-1] - base.iloc[0])


def cn_macro_score(cutoff: str | None = None) -> tuple[float, dict]:
    """中国经济周期分 0-100（越高越利于权益）。缺项自动跳过并归一。"""
    parts: list[float] = []
    detail = {}

    pmi = _load("pmi", cutoff)
    if len(pmi) >= 4:
        v = pmi.iloc[-1]
        sc = 50 + 30 * math.tanh((v - 50) / 2) + 15 * math.tanh(_trend_sign(pmi) / 1.0)
        parts.append(min(max(sc, 0), 100))
        detail["pmi"] = round(float(v), 1)

    m1, m2 = _load("m1_yoy", cutoff), _load("m2_yoy", cutoff)
    if len(m1) >= 4 and len(m2) >= 4:
        gap = float(m1.iloc[-1] - m2.iloc[-1])  # 剪刀差：资金活化程度
        sc = 50 + 35 * math.tanh(gap / 3)
        parts.append(min(max(sc, 0), 100))
        detail["m1_m2_gap"] = round(gap, 1)

    ppi = _load("ppi_yoy", cutoff)
    if len(ppi) >= 4:
        v = ppi.iloc[-1]
        sc = 50 + 25 * math.tanh(v / 2) + 15 * math.tanh(_trend_sign(ppi) / 1.5)
        parts.append(min(max(sc, 0), 100))
        detail["ppi_yoy"] = round(float(v), 1)

    sf = _load("sf_12m", cutoff)
    if len(sf) >= 24:
        v = sf.iloc[-1]
        sc = 50 + 25 * math.tanh(v / 10)
        parts.append(min(max(sc, 0), 100))
        detail["sf_12m_yoy"] = round(float(v), 1)

    if not parts:
        return 50.0, {"note": "宏观数据缺失，按中性50计"}
    return round(sum(parts) / len(parts), 1), detail


def us_macro_score(cutoff: str | None = None) -> tuple[float, dict]:
    """海外分：美债10Y 利率 3 个月变化（下行利多）。"""
    chg = None
    s = _load("us10y", cutoff)
    if len(s) >= 30:
        base = s[s.index >= s.index[-1] - pd.DateOffset(months=3)]
        if len(base) >= 5:
            chg = float(s.iloc[-1] - base.iloc[0])
    detail = {"us10y": round(float(s.iloc[-1]), 2) if len(s) else None,
              "us10y_chg3m": None if chg is None else round(chg, 2)}
    score = 50.0 if chg is None else min(max(50 + 30 * math.tanh(-chg / 0.4), 0), 100)
    return round(score, 1), detail
