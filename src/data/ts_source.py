"""Tushare Pro 数据源（用户 2000 分权限，主数据源）。

2000 分限频保护：调用间 sleep + 失败退避重试；增量拉取（只取库内最新日期之后）。
"""
import time

import pandas as pd

from src import config
from src.data import store


def _norm_date(s: str) -> str:
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if s and "-" not in s else (s or "")


class TushareSource:
    def __init__(self, token: str | None = None):
        self.token = (token or config.TUSHARE_TOKEN).strip()
        self.available = bool(self.token)
        self._pro = None
        if self.available:
            import tushare as ts
            ts.set_token(self.token)
            self._pro = ts.pro_api()

    def _call(self, api_name: str, **kwargs) -> pd.DataFrame:
        if not self.available:
            raise RuntimeError("TUSHARE_TOKEN 未配置")
        delay = config.TS_RATE_LIMIT_SLEEP
        last_err = None
        for attempt in range(config.TS_MAX_RETRIES + 1):
            try:
                time.sleep(delay)
                df = getattr(self._pro, api_name)(**kwargs)
                if df is None or df.empty:
                    return pd.DataFrame()
                return df
            except Exception as e:  # noqa: BLE001 - 限频/网络异常统一退避
                last_err = e
                delay = min(delay * 4, 20)
        raise RuntimeError(f"tushare {api_name} 失败: {last_err}")

    @staticmethod
    def _start(store_table: str, ts_code: str, default_start: str, date_col: str = "trade_date") -> str:
        """增量起点：库内最新日期次日；无数据则用 default_start。"""
        df = store.read_df(store_table, f"ts_code='{ts_code}'" if store_table != "margin" else "",
                           order=f"{date_col} DESC")
        if df.empty:
            return default_start.replace("-", "")
        last = df[date_col].iloc[0].replace("-", "")
        return last

    # ---------- 各表增量抓取并入库 ----------
    def fetch_index_daily(self, ts_code: str, default_start: str) -> int:
        start = self._start("index_daily", ts_code, default_start)
        df = self._call("index_daily", ts_code=ts_code, start_date=start,
                        end_date="20991231")
        if df.empty:
            return 0
        df["trade_date"] = df["trade_date"].map(_norm_date)
        cols = ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"]
        return store.upsert_df("index_daily", df[cols], ["ts_code", "trade_date"])

    def fetch_index_val(self, ts_code: str, default_start: str) -> int:
        # index_dailybasic 单次最多约 2000 行，按 1500 日分段
        start = self._start("index_val", ts_code, default_start)
        total = 0
        cur = pd.Timestamp(start)
        today = pd.Timestamp.today()
        while cur < today:
            chunk_end = min(cur + pd.Timedelta(days=1500), today)
            df = self._call("index_dailybasic", ts_code=ts_code,
                            start_date=cur.strftime("%Y%m%d"),
                            end_date=chunk_end.strftime("%Y%m%d"))
            if not df.empty:
                df["trade_date"] = df["trade_date"].map(_norm_date)
                out = df[["ts_code", "trade_date", "pe_ttm", "pb", "turnover_rate", "total_mv"]]
                total += store.upsert_df("index_val", out, ["ts_code", "trade_date"])
            cur = chunk_end + pd.Timedelta(days=1)
        return total

    def fetch_global(self, ts_global: str, default_start: str) -> int:
        start = self._start("global_daily", ts_global, default_start)
        df = self._call("index_global", ts_code=ts_global, start_date=start, end_date="20991231")
        if df.empty:
            return 0
        df["trade_date"] = df["trade_date"].map(_norm_date)
        return store.upsert_df("global_daily", df[["ts_code", "trade_date", "open", "close"]],
                               ["ts_code", "trade_date"])

    def fetch_fund_daily(self, etf: str, default_start: str) -> int:
        """统一以裸 6 位代码入库（akshare/持仓读取端均用裸代码）。"""
        bare = etf.split(".")[0]
        ts_code = bare + (".SH" if bare.startswith(("5", "6")) else ".SZ")
        start = self._start("fund_daily", bare, default_start)
        df = self._call("fund_daily", ts_code=ts_code, start_date=start, end_date="20991231")
        if df.empty:
            return 0
        df["trade_date"] = df["trade_date"].map(_norm_date)
        df["ts_code"] = bare
        return store.upsert_df("fund_daily", df[["ts_code", "trade_date", "open", "close", "amount"]],
                               ["ts_code", "trade_date"])

    def fetch_margin(self, default_start: str) -> int:
        df = store.read_df("margin", order="trade_date DESC")
        start = df["trade_date"].iloc[0].replace("-", "") if not df.empty else default_start.replace("-", "")
        cur = pd.Timestamp(start)
        today = pd.Timestamp.today()
        total = 0
        while cur < today:
            chunk_end = min(cur + pd.Timedelta(days=1200), today)  # 每日2行，限2400行内
            d = self._call("margin", start_date=cur.strftime("%Y%m%d"),
                           end_date=chunk_end.strftime("%Y%m%d"))
            if not d.empty:
                g = d.groupby("trade_date", as_index=False).agg(
                    rzye=("rzye", "sum"), rzrqye=("rzrqye", "sum"))
                g["trade_date"] = g["trade_date"].map(_norm_date)
                total += store.upsert_df("margin", g, ["trade_date"])
            cur = chunk_end + pd.Timedelta(days=1)
        return total

    def fetch_hsgt(self, default_start: str) -> int:
        df = store.read_df("hsgt", order="trade_date DESC")
        start = df["trade_date"].iloc[0].replace("-", "") if not df.empty else default_start.replace("-", "")
        d = self._call("moneyflow_hsgt", start_date=start, end_date="20991231")
        if d.empty:
            return 0
        d["trade_date"] = d["trade_date"].map(_norm_date)
        d = d.drop_duplicates(subset="trade_date", keep="last")
        return store.upsert_df("hsgt", d[["trade_date", "north_money", "south_money"]], ["trade_date"])

    # ---------- 宏观 ----------
    def fetch_macro(self, default_start: str = "20060101") -> int:
        y0 = int(default_start[:4])
        total = 0
        jobs = [
            ("cn_pmi", "pmi", "month", "pmi"),
            ("cn_cpi", "cpi_yoy", "month", "nt_yoy"),
            ("cn_ppi", "ppi_yoy", "month", "nt_yoy"),
            ("cn_m", "m1_yoy", "month", "m1_yoy"),
            ("cn_m", "m2_yoy", "month", "m2_yoy"),
            ("cn_sf", "sf_12m", "month", "inc"),  # 社融增量，宏观点做成12个月滚动
        ]
        for api, series, pk, col in jobs:
            try:
                d = self._call(api, start_m=f"{y0}01")
            except Exception:
                try:  # 部分接口参数名不同
                    d = self._call(api)
                except Exception:
                    store.log_refresh("tushare", api, "fail", "接口不可用/无权限")
                    continue
            if d.empty:
                continue
            if series == "sf_12m":  # 社融：滚动12个月增量（亿元）
                d = d.sort_values("month")
                d["value"] = pd.to_numeric(d.get("inc"), errors="coerce").rolling(12).sum()
                d = d.dropna(subset=["value"])
                d["value"] = d["value"].pct_change(12) * 100  # 同比增速%
            else:
                d["value"] = pd.to_numeric(d.get(col), errors="coerce")
                d = d.dropna(subset=["value"])
            if d.empty:
                continue
            out = pd.DataFrame({"series": series, "period": d["month"].astype(str),
                                "value": d["value"]})
            total += store.upsert_df("macro_series", out, ["series", "period"])
        return total
