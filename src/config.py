"""全局配置：路径、数据源参数、打分卡权重、纪律规则。"""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"
DB_PATH = DATA_DIR / "invest.db"
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(ENV_FILE)
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "").strip()


def reload_env() -> str:
    """重读 .env（每次数据刷新前调用，token 改动无需重启服务）。"""
    global TUSHARE_TOKEN
    load_dotenv(ENV_FILE, override=True)
    TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "").strip()
    return TUSHARE_TOKEN

# ---- 打分卡权重（总和为 1；某维度缺数据时按剩余权重归一化）----
WEIGHTS = {"valuation": 0.40, "trend": 0.30, "flows": 0.15, "macro": 0.15}

# ---- 估值分位 → 定投倍数（手册规则，单一事实来源）----
DCA_BANDS = [
    (0.20, 2.0),   # 分位 < 20%  → 双倍投
    (0.40, 1.5),   # 20% ~ 40%   → 1.5 倍
    (0.60, 1.0),   # 40% ~ 60%   → 正常
    (0.80, 0.5),   # 60% ~ 80%   → 减半
    (1.01, 0.0),   # >= 80%      → 停投（止盈观察区）
]
QDII_PREMIUM_LIMIT = 3.0        # QDII 溢价率超 3% 拒买
REBALANCE_TRIGGER_PP = 5.0      # 单资产偏离目标 ±5 个百分点触发再平衡
DRAWDOWN_LADDER = [0.15, 0.25, 0.35]  # 回撤加仓网格

# ---- 战术仓位覆盖：沪深300 估值分位 → 股票仓位上限 ----
EQUITY_CAP_BANDS = [
    (0.80, 0.60),   # 分位 >= 80% → 股票上限 60%
    (0.60, 0.70),
    (0.40, 0.80),
    (0.00, 0.85),   # 低估时最多 85%
]

# ---- 回测 / 信号参数 ----
VALUATION_WINDOW_DAYS = 365 * 10
VALUATION_MIN_OBS = 750         # 估值分位最少样本（约3年）
MA_LONG = 200
MOMENTUM_SKIP_DAYS = 21         # 12-1 动量：剔除最近一个月
MOMENTUM_LOOKBACK_DAYS = 252
BACKTEST_START = "2015-01-01"
BACKTEST_RF = 0.02              # 夏普比率无风险利率

# ---- 卫星仓规则 ----
SATELLITE_INDUSTRY_BUDGET = 10.0   # 行业卫星总预算（%）
SATELLITE_REGION_BUDGET = 15.0     # 国别卫星总预算（%）
INDUSTRY_SLOTS = [(4.0, 4.0, 2.0)]  # 动量前2名各4%、第3名2%
TREND_GATE_SCORE = 50.0            # 趋势分低于此值不入选卫星

# ---- 数据刷新 ----
TS_RATE_LIMIT_SLEEP = 0.35      # tushare 2000 分限频保护
TS_MAX_RETRIES = 2
REFRESH_CRON_HOUR = 16          # 每个交易日 16:30 自动刷新
REFRESH_CRON_MINUTE = 30
