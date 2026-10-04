"""权威官方网站兜底源：中证指数官网（行情+滚动PE）、FRED（美债）、multpl（席勒PE）。

均为免费公开数据；任一失败不影响主流程。
"""
import io
import time

import pandas as pd
import requests

from src.data import store

UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.csindex.com.cn/"}


def fetch_us10y_fred() -> int:
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df = df.rename(columns={"observation_date": "date", "DGS10": "value"})
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    out = pd.DataFrame({"series": "us10y", "period": df["date"].astype(str),
                        "value": df["value"]})
    return store.upsert_df("macro_series", out, ["series", "period"])


def fetch_shiller_pe() -> int:
    """标普500 席勒PE 月度历史（multpl.com 官方表格页）。"""
    url = "https://www.multpl.com/shiller-pe/table/by-month"
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    tables = pd.read_html(io.StringIO(r.text))
    df = max(tables, key=len)
    df.columns = [str(c).strip().lower() for c in df.columns]
    date_col = next(c for c in df.columns if "date" in c)
    val_col = next(c for c in df.columns if "value" in c)
    df = df.rename(columns={date_col: "date", val_col: "value"})
    df["period"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    out = pd.DataFrame({"series": "sp500_shiller_pe", "period": df["period"],
                        "value": df["value"]})
    return store.upsert_df("macro_series", out, ["series", "period"])


# ---------------------------------------------------------------- 中证指数官网
CSINDEX_URL = "https://www.csindex.com.cn/csindex-home/perf/index-perf"


def fetch_csindex_daily(ts_code: str, default_start: str, chunk_years: int = 5) -> int:
    """中证官网指数行情+滚动PE（字段 peg 即滚动市盈率），按年分段拉取。

    覆盖全部中证系指数（沪深300/中证500/红利/行业/国债000012等）；
    创业板指(399006)属深证系列不在此接口。
    """
    code = ts_code.split(".")[0]
    total = 0
    today = pd.Timestamp.today()
    cur = pd.Timestamp(default_start)
    while cur <= today:
        end = min(cur + pd.DateOffset(years=chunk_years) - pd.Timedelta(days=1), today)
        r = requests.get(CSINDEX_URL, params={
            "indexCode": code,
            "startDate": cur.strftime("%Y%m%d"), "endDate": end.strftime("%Y%m%d"),
        }, headers=UA, timeout=30)
        r.raise_for_status()
        data = (r.json() or {}).get("data") or []
        if data:
            df = pd.DataFrame(data)
            df["trade_date"] = df["tradeDate"].astype(str).map(
                lambda s: f"{s[:4]}-{s[4:6]}-{s[6:8]}")
            px = pd.DataFrame({
                "ts_code": ts_code, "trade_date": df["trade_date"],
                "open": pd.to_numeric(df.get("open"), errors="coerce"),
                "high": pd.to_numeric(df.get("high"), errors="coerce"),
                "low": pd.to_numeric(df.get("low"), errors="coerce"),
                "close": pd.to_numeric(df.get("close"), errors="coerce"),
                "vol": pd.to_numeric(df.get("tradingVol"), errors="coerce"),
                "amount": pd.to_numeric(df.get("tradingValue"), errors="coerce") * 1e8,
            })
            total += store.upsert_df("index_daily", px, ["ts_code", "trade_date"])
            if "peg" in df.columns:
                val = pd.DataFrame({
                    "ts_code": ts_code, "trade_date": df["trade_date"],
                    "pe_ttm": pd.to_numeric(df["peg"], errors="coerce")})
                val = val.dropna(subset=["pe_ttm"])
                total += store.upsert_df("index_val", val, ["ts_code", "trade_date"])
        cur = end + pd.Timedelta(days=1)
        time.sleep(0.4)  # 对官网保持礼貌
    return total
