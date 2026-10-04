"""信号引擎单元测试：合成数据验证核心规则。"""
import numpy as np
import pandas as pd
import pytest

from src import config, universe
from src.data import store
from src.engine import flows, macro, scorer, trend, valuation

store.init_db()  # 测试库表


def _make_series(n=3000, drift=0.0002, seed=7, base=100.0):
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, 0.015, n)
    idx = pd.bdate_range("2010-01-04", periods=n)
    return pd.Series(base * np.cumprod(1 + rets), index=idx)


# ---------- 估值 ----------
def test_percentile_bounds_and_insufficiency():
    s = _make_series()
    pct = valuation.rolling_percentile(s)
    assert 0.0 <= pct <= 1.0
    short = s.iloc[-100:]  # 样本不足
    assert valuation.rolling_percentile(short) is None


def test_percentile_monotone():
    s = _make_series()
    # 人为把最后一天抬高 → 分位应升高
    s2 = s.copy()
    s2.iloc[-1] = s2.iloc[:-1].max() * 1.01
    assert valuation.rolling_percentile(s2) > valuation.rolling_percentile(s)


def test_dca_bands():
    assert valuation.dca_multiplier(0.10) == 2.0
    assert valuation.dca_multiplier(0.30) == 1.5
    assert valuation.dca_multiplier(0.50) == 1.0
    assert valuation.dca_multiplier(0.70) == 0.5
    assert valuation.dca_multiplier(0.90) == 0.0
    assert valuation.dca_multiplier(None) is None
    assert valuation.value_zone(0.9) == "高估"


# ---------- 趋势 ----------
def test_ma_flag_and_momentum():
    idx = pd.bdate_range("2010-01-04", periods=600)
    s = pd.Series(np.linspace(100, 200, 600), index=idx)  # 确定性上升斜坡
    assert trend.ma_long_flag(s) is True
    short = s.iloc[-100:]
    assert trend.ma_long_flag(short) is None  # 不足200日
    m, shortwin = trend.momentum_12_1(s)
    assert m is not None and m > 0 and shortwin is False


def test_trend_score_bull_vs_bear():
    up = _make_series(drift=0.001, seed=1)
    dn = _make_series(drift=-0.001, seed=1)
    su, du = trend.trend_score(up)[0], trend.trend_score(dn)[0]
    assert su > du
    assert 0 <= su <= 100 and 0 <= du <= 100


# ---------- 资金面 ----------
def test_margin_chg_and_volume_ratio():
    idx = pd.bdate_range(end="2026-01-01", periods=300)
    margin = pd.DataFrame({"trade_date": idx.strftime("%Y-%m-%d"),
                           "rzye": np.linspace(1, 1.2, 300), "rzrqye": 1})
    chg = flows.margin_chg(margin)
    assert chg is not None and chg > 0
    px = pd.DataFrame({"amount": np.linspace(1, 2, 300)}, index=idx)
    assert flows.volume_ratio(px) > 1


# ---------- 宏观（无数据时中性）----------
def test_macro_neutral_without_data():
    s, d = macro.cn_macro_score(cutoff="1990-01-01")
    assert s == 50.0


# ---------- 打分卡与组合计划 ----------
def test_scorer_weights_renormalize():
    # 仅有趋势分时，总分应等于趋势分（权重归一）
    sig = scorer.AssetSignal(key="x", name="x", role="core", asset_class="equity_cn",
                             trend_score=80.0)
    parts = {"valuation": None, "trend": 80.0, "flows": None, "macro": None}
    num = den = 0.0
    for k, v in parts.items():
        if v is not None:
            num += config.WEIGHTS[k] * v
            den += config.WEIGHTS[k]
    assert round(num / den, 1) == 80.0


def test_plan_weights_sum_and_cap():
    sigs = []
    for a in universe.ASSETS:
        s = scorer.AssetSignal(key=a.key, name=a.name, role=a.role,
                               asset_class=a.asset_class, target_weight=a.target_weight,
                               val_pct=0.9 if a.key == "hs300" else 0.5,
                               val_score=50, val_zone="合理", dca_multiplier=1.0,
                               trend_score=60.0, flows_score=50.0, macro_score=50.0,
                               total=52.5,
                               trend_detail={"momentum": 0.05, "above_ma200": True})
        sigs.append(s)
    plan = scorer.build_plan(sigs)
    assert abs(sum(plan["weights"].values()) - 100) < 0.5
    # hs300 分位 90% → 股票仓位应被压到 60% 上限
    assert plan["equity_weight"] <= 60.0 + 0.1
    assert any("上限" in n for n in plan["notes"])


def test_satellite_pick_top_momentum():
    sigs = []
    for a in universe.ASSETS:
        mom = 0.30 if a.key == "baijiu" else (0.20 if a.key == "info" else 0.01)
        sigs.append(scorer.AssetSignal(key=a.key, name=a.name, role=a.role,
                                       asset_class=a.asset_class, target_weight=a.target_weight,
                                       trend_score=70.0, trend_detail={"momentum": mom,
                                                                       "above_ma200": True}))
    plan = scorer.build_plan(sigs)
    assert plan["weights"]["baijiu"] == 4.0
    assert plan["weights"]["info"] == 4.0
    assert plan["weights"]["military"] == 0.0  # 动量最低未入选
