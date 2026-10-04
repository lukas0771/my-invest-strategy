"""AKShare 数据源（开源免费，无 token 兜底 / 补充源）。"""
import datetime

import pandas as pd

from src.data import store

SINA_SYMBOLS = {  # ts_code → 新浪指数代码（东财不可用时的行情兜底）
    "000300.SH": "sh000300", "000905.SH": "sh000905", "399006.SZ": "sz399006",
    "000922.CSI": "sh000922", "399997.SZ": "sz399997", "000991.CSI": "sh000991",
    "000993.CSI": "sh000993", "000932.CSI": "sh000932", "399967.SZ": "sz399967",
    "399975.SZ": "sz399975", "000012.SH": "sh000012",
}

FUNDBD_NAMES = {  # 韭圈儿(乐咕)估值接口的指数命名（新版akshare已移除，保留备用）
    "000300.SH": "沪深300", "000905.SH": "中证500", "399006.SZ": "创业板指",
    "000922.CSI": "中证红利", "399997.SZ": "中证白酒", "000991.CSI": "全指医药",
    "000993.CSI": "全指信息", "000932.CSI": "中证消费", "399967.SZ": "中证军工",
    "399975.SZ": "中证全指证券公司指数", "930997.CSI": "中证新能源汽车指数",
}


def _iso(s) -> str:
    s = str(s)[:10].replace("/", "-")
    return s if "-" in s else f"{s[:4]}-{s[4:6]}-{s[6:8]}"


class AkshareSource:
    def __init__(self):
        import akshare as ak
        self.ak = ak

    # ---------- A股指数行情 → index_daily ----------
    def fetch_index_daily(self, ts_code: str, ak_symbol: str, default_start: str) -> int:
        last = store.read_df("index_daily", f"ts_code='{ts_code}'", order="trade_date DESC")
        start = last["trade_date"].iloc[0].replace("-", "") if not last.empty else default_start.replace("-", "")
        d = pd.DataFrame()
        try:  # 东财优先（可用时）
            d = self.ak.index_zh_a_hist(symbol=ak_symbol, period="daily",
                                        start_date=start, end_date="20991231")
            if d is not None and not d.empty:
                d = d.rename(columns={"日期": "trade_date", "开盘": "open", "收盘": "close",
                                      "最高": "high", "最低": "low",
                                      "成交量": "vol", "成交额": "amount"})
        except Exception:
            d = pd.DataFrame()
        if d is None or d.empty:  # 新浪兜底（注意：先标准化日期再过滤）
            sina_symbol = SINA_SYMBOLS.get(ts_code) or \
                (ak_symbol if ak_symbol.startswith(("sh", "sz")) else
                 ("sh" + ak_symbol if ts_code.endswith(".SH") else "sz" + ak_symbol))
            try:
                d = self.ak.stock_zh_index_daily(symbol=sina_symbol)
            except Exception:
                return 0
            d = d.rename(columns={"date": "trade_date", "volume": "vol"})
            d["trade_date"] = d["trade_date"].map(_iso)
            d = d[d["trade_date"] >= f"{start[:4]}-{start[4:6]}-{start[6:8]}"]
        d["trade_date"] = d["trade_date"].map(_iso)
        d["ts_code"] = ts_code
        cols = ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"]
        for c in cols:
            if c not in d.columns:
                d[c] = None
        return store.upsert_df("index_daily", d[cols], ["ts_code", "trade_date"])

    # ---------- 估值（韭圈儿历史PE/PB）→ index_val ----------
    def fetch_index_val(self, ts_code: str) -> int:
        name = FUNDBD_NAMES.get(ts_code)
        if not name:
            return 0
        total = 0
        try:
            pe = self.ak.index_value_hist_funddb(symbol=name, indicator="市盈率")
            if pe is not None and not pe.empty:
                date_col = pe.columns[0]
                cand = [c for c in pe.columns
                        if "市盈率" in str(c) and "分位" not in str(c) and c != date_col]
                val_col = cand[0]
                out = pd.DataFrame({
                    "ts_code": ts_code, "trade_date": pe[date_col].map(_iso),
                    "pe_ttm": pd.to_numeric(pe[val_col], errors="coerce")}).dropna(subset=["pe_ttm"])
                total += store.upsert_df("index_val", out, ["ts_code", "trade_date"])
        except Exception:
            pass
        try:
            pb = self.ak.index_value_hist_funddb(symbol=name, indicator="市净率")
            if pb is not None and not pb.empty:
                date_col = pb.columns[0]
                cand = [c for c in pb.columns
                        if "市净率" in str(c) and "分位" not in str(c) and c != date_col]
                val_col = cand[0]
                out = pd.DataFrame({
                    "ts_code": ts_code, "trade_date": pb[date_col].map(_iso),
                    "pb": pd.to_numeric(pb[val_col], errors="coerce")}).dropna(subset=["pb"])
                total += store.upsert_df("index_val", out, ["ts_code", "trade_date"])
        except Exception:
            pass
        return total

    # ---------- 海外指数 ----------
    def fetch_us_index(self, ts_global: str, default_start: str) -> int:
        sym = {"SPX": ".INX", "NDX": ".NDX"}.get(ts_global)
        if not sym:
            return 0
        last = store.read_df("global_daily", f"ts_code='{ts_global}'", order="trade_date DESC")
        d = self.ak.index_us_stock_sina(symbol=sym)
        if d is None or d.empty:
            return 0
        d = d.rename(columns={"date": "trade_date"})
        d["trade_date"] = d["trade_date"].map(_iso)
        if not last.empty:
            d = d[d["trade_date"] > last["trade_date"].iloc[0]]
        d["ts_code"] = ts_global
        return store.upsert_df("global_daily", d[["ts_code", "trade_date", "open", "close"]],
                               ["ts_code", "trade_date"])

    def fetch_hk_index(self, ts_global: str, ak_hk: str, default_start: str) -> int:
        last = store.read_df("global_daily", f"ts_code='{ts_global}'", order="trade_date DESC")
        d = pd.DataFrame()
        try:  # 东财优先（可用时）
            d = self.ak.stock_hk_index_daily_em(symbol=ak_hk)
            d = d.rename(columns={"日期": "trade_date", "开盘": "open", "收盘": "close"})
        except Exception:
            d = pd.DataFrame()
        if d is None or d.empty:  # 新浪港股兜底（HSTECH 可用）
            d = self.ak.stock_hk_index_daily_sina(symbol=ak_hk)
            d = d.rename(columns={"date": "trade_date"})
        d["trade_date"] = d["trade_date"].map(_iso)
        if not last.empty:
            d = d[d["trade_date"] > last["trade_date"].iloc[0]]
        d["ts_code"] = ts_global
        return store.upsert_df("global_daily", d[["ts_code", "trade_date", "open", "close"]],
                               ["ts_code", "trade_date"])

    # ---------- 黄金ETF价格代理 ----------
    def fetch_fund_daily(self, etf: str, default_start: str) -> int:
        last = store.read_df("fund_daily", f"ts_code='{etf}'", order="trade_date DESC")
        start = last["trade_date"].iloc[0].replace("-", "") if not last.empty else default_start.replace("-", "")
        d = pd.DataFrame()
        try:  # 东财优先
            d = self.ak.fund_etf_hist_em(symbol=etf, period="daily",
                                         start_date=start, end_date="20991231", adjust="")
            d = d.rename(columns={"日期": "trade_date", "开盘": "open", "收盘": "close", "成交额": "amount"})
        except Exception:
            d = pd.DataFrame()
        if d is None or d.empty:  # 新浪兜底
            sina_symbol = ("sh" if etf.startswith("5") else "sz") + etf
            d = self.ak.fund_etf_hist_sina(symbol=sina_symbol)
            d = d.rename(columns={"date": "trade_date", "volume": "amount"})
        d["trade_date"] = d["trade_date"].map(_iso)
        d = d[d["trade_date"] >= f"{start[:4]}-{start[4:6]}-{start[6:8]}"]
        d["ts_code"] = etf
        cols = ["ts_code", "trade_date", "open", "close", "amount"]
        for c in cols:
            if c not in d.columns:
                d[c] = None
        return store.upsert_df("fund_daily", d[cols], ["ts_code", "trade_date"])

    # ---------- 宏观兜底 ----------
    @staticmethod
    def _cn_period(s) -> str:
        """'2026年08月份' → '2026-08'；兼容 '2026-08-01' 等格式。"""
        import re
        m = re.search(r"(\d{4})年(\d{1,2})月", str(s))
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}"
        return _iso(s)[:7]

    def fetch_macro(self) -> int:
        total = 0
        # (series, 接口, 取值列, 备注)  — 列名以 akshare 1.18 实测为准
        jobs = [
            ("pmi", self.ak.macro_china_pmi, "制造业-指数"),
            ("cpi_yoy", self.ak.macro_china_cpi, "全国-同比增长"),
            ("ppi_yoy", self.ak.macro_china_ppi, "当月同比增长"),
            ("m1_yoy", self.ak.macro_china_money_supply, "货币(M1)-同比增长"),
            ("m2_yoy", self.ak.macro_china_money_supply, "货币和准货币(M2)-同比增长"),
        ]
        for series, fn, col in jobs:
            try:
                d = fn()
                if d is None or d.empty or col not in d.columns:
                    continue
                out = pd.DataFrame({
                    "series": series,
                    "period": d["月份"].map(self._cn_period),
                    "value": pd.to_numeric(d[col], errors="coerce")}).dropna()
                out = out.drop_duplicates(subset="period", keep="first")
                total += store.upsert_df("macro_series", out, ["series", "period"])
            except Exception:
                continue
        # 美债/中债10年收益率
        try:
            d = self.ak.bond_zh_us_rate()
            d = d.rename(columns={"日期": "trade_date"})
            for series, col in (("us10y", "美国国债收益率10年"), ("cn10y", "中国国债收益率10年")):
                if col in d.columns:
                    out = pd.DataFrame({
                        "series": series, "period": d["trade_date"].map(_iso),
                        "value": pd.to_numeric(d[col], errors="coerce")}).dropna()
                    total += store.upsert_df("macro_series", out, ["series", "period"])
        except Exception:
            pass
        return total

    # ---------- QDII/ETF 溢价快照 ----------
    def fetch_qdii_premium(self, watch_codes: list[str]) -> int:
        d = self.ak.fund_etf_spot_em()
        if d is None or d.empty:
            return 0
        code_col = "代码" if "代码" in d.columns else d.columns[0]
        d = d[d[code_col].astype(str).isin(watch_codes)]
        iopv_col = next((c for c in d.columns if "IOPV" in str(c)), None)
        price_col = next((c for c in d.columns if "最新价" in str(c)), None)
        if not iopv_col or not price_col:
            return 0
        rows = []
        for _, r in d.iterrows():
            try:
                price, iopv = float(r[price_col]), float(r[iopv_col])
                if iopv > 0:
                    rows.append({"ts_code": str(r[code_col]), "name": str(r.get("名称", "")),
                                 "premium": round((price - iopv) / iopv * 100, 2),
                                 "updated": datetime.datetime.now().isoformat(timespec="seconds")})
            except (TypeError, ValueError):
                continue
        if not rows:
            return 0
        return store.upsert_df("qdii_premium", pd.DataFrame(rows), ["ts_code"])
