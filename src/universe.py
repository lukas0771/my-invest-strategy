"""资产池定义：核心-卫星结构、信号适用的数据通道、代表性基金示例。

所有权重为战略基准（%，合计 100）；卫星仓实际配置由动量排名与趋势门槛动态决定，
未选中的卫星预算自动回流现金/短债。
基金/ETF 代码仅为代表性示例，购买前务必自查最新费率、规模与跟踪误差。
"""
from dataclasses import dataclass, field


@dataclass
class Asset:
    key: str                     # 内部标识
    name: str                    # 展示名
    role: str                    # core / industry / region / defensive / cash
    asset_class: str             # equity_cn / equity_global / bond / gold / cash
    target_weight: float         # 战略基准权重 %
    ts_index: str = ""           # tushare 指数代码（index_daily / index_dailybasic）
    ts_global: str = ""          # tushare index_global 代码
    ak_symbol: str = ""          # akshare index_zh_a_hist 代码（东财口径）
    ak_sina: str = ""            # akshare stock_zh_index_daily（新浪口径）
    ak_hk: str = ""              # akshare stock_hk_index_daily_em 代码
    etf: str = ""                # 代表性场内 ETF（溢价检查/价格代理）
    otc: str = ""                # 代表性场外基金示例
    valuation: str = "none"      # pe_ttm / shiller / none
    needs_macro: str = "cn"      # 宏观打分适用市场：cn / us / none
    notes: str = ""


ASSETS: list[Asset] = [
    # ================= 核心（75%） =================
    Asset("hs300", "沪深300", "core", "equity_cn", 12.0,
          ts_index="000300.SH", ak_symbol="000300",
          etf="510300", otc="110020 易方达沪深300ETF联接A", valuation="pe_ttm",
          notes="A股核心宽基"),
    Asset("zz500", "中证500", "core", "equity_cn", 8.0,
          ts_index="000905.SH", ak_symbol="000905",
          etf="510500", otc="510500联接/160022 富国中证500", valuation="pe_ttm",
          notes="中盘；可用中证A500替代（历史不足3年，引擎暂不覆盖）"),
    Asset("cyb", "创业板指", "core", "equity_cn", 5.0,
          ts_index="399006.SZ", ak_symbol="399006",
          etf="159915", otc="159915联接/110026 易方达创业板联接A", valuation="pe_ttm",
          notes="成长风格"),
    Asset("dividend", "中证红利", "defensive", "equity_cn", 5.0,
          ts_index="000922.CSI", ak_symbol="000922",
          etf="510880", otc="100032 富国中证红利", valuation="pe_ttm",
          notes="防守型股票，熊市缓冲"),
    Asset("spx", "标普500", "core", "equity_global", 12.0,
          ts_global="SPX", valuation="shiller",
          etf="513500", otc="050025 博时标普500ETF联接A",
          notes="估值用 Shiller PE 分位（multpl 官网数据）"),
    Asset("ndx", "纳指100", "core", "equity_global", 8.0,
          ts_global="NDX", valuation="price_fallback",
          etf="513100", otc="040046 华安纳斯达克100",
          notes="无长期PE官方源时用价格分位替代并标注"),
    Asset("bond", "国债/纯债", "core", "bond", 15.0,
          ak_sina="sh000012", ts_index="000012.SH",
          etf="511260", otc="短债/中长债纯债基金",
          notes="上证国债指数作回测代理；实盘用纯债基金"),
    Asset("gold", "黄金", "core", "gold", 8.0,
          etf="518880", otc="518880联接/000217 华安黄金易ETF联接A",
          notes="以黄金ETF 518880 价格为代理；不做估值分位"),
    Asset("cash", "现金/货基", "cash", "cash", 2.0,
          otc="货币基金（如天弘余额宝 000198）",
          notes="回测按年化2%计；同时承接未选中的卫星预算"),
    # ================= 行业卫星（预算10%，动量前2名各4%、第3名2%） =================
    Asset("baijiu", "中证白酒", "industry", "equity_cn", 0.0,
          ts_index="399997.SZ", ak_symbol="399997", etf="512690",
          otc="161725 招商中证白酒(LOF)", valuation="pe_ttm"),
    Asset("pharma", "全指医药", "industry", "equity_cn", 0.0,
          ts_index="000991.CSI", ak_symbol="000991", etf="512010",
          otc="001550 天弘中证医药100", valuation="pe_ttm"),
    Asset("info", "全指信息", "industry", "equity_cn", 0.0,
          ts_index="000993.CSI", ak_symbol="000993", etf="512480",
          otc="001630 天弘中证计算机", valuation="pe_ttm"),
    Asset("consumer", "中证消费", "industry", "equity_cn", 0.0,
          ts_index="000932.CSI", ak_symbol="000932", etf="159928",
          otc="000248 汇添富中证消费ETF联接", valuation="pe_ttm"),
    Asset("military", "中证军工", "industry", "equity_cn", 0.0,
          ts_index="399967.SZ", ak_symbol="399967", etf="512660",
          otc="161024 富国中证军工(LOF)", valuation="pe_ttm"),
    Asset("broker", "证券公司", "industry", "equity_cn", 0.0,
          ts_index="399975.SZ", ak_symbol="399975", etf="512000",
          otc="券商类指数基金（场内512000更常用）", valuation="pe_ttm"),
    Asset("nev", "新能源车", "industry", "equity_cn", 0.0,
          ts_index="930997.CSI", ak_symbol="930997", etf="515030",
          otc="501057? 建议场内515030", valuation="pe_ttm"),
    # ================= 国别卫星（预算15%） =================
    Asset("hstech", "恒生科技", "region", "equity_global", 8.0,
          ts_global="HSTECH", ak_hk="HSTECH",
          etf="513180", otc="012348 天弘恒生科技(QDII)", valuation="price_fallback"),
    Asset("n225", "日经225", "region", "equity_global", 7.0,
          ts_global="N225", valuation="price_fallback",
          etf="513880", otc="513880联接/008707 华夏野村日经225"),
]

ASSETS_BY_KEY = {a.key: a for a in ASSETS}

# 回测中现金之外的资产价格序列来源优先级：
# tushare index_daily(ts_index) > tushare fund_daily(etf) > akshare(ak_symbol/ak_sina/ak_hk)
CORE_KEYS = [a.key for a in ASSETS if a.role in ("core", "defensive", "cash")]
INDUSTRY_KEYS = [a.key for a in ASSETS if a.role == "industry"]
REGION_KEYS = [a.key for a in ASSETS if a.role == "region"]
