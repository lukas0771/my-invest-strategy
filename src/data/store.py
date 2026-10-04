"""SQLite 本地存储：所有数据源的统一落地层（开源、零依赖、可离线复现）。"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from src.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS index_daily (
    ts_code TEXT NOT NULL, trade_date TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, vol REAL, amount REAL,
    PRIMARY KEY (ts_code, trade_date));
CREATE TABLE IF NOT EXISTS global_daily (
    ts_code TEXT NOT NULL, trade_date TEXT NOT NULL,
    open REAL, close REAL,
    PRIMARY KEY (ts_code, trade_date));
CREATE TABLE IF NOT EXISTS fund_daily (
    ts_code TEXT NOT NULL, trade_date TEXT NOT NULL,
    open REAL, close REAL, amount REAL,
    PRIMARY KEY (ts_code, trade_date));
CREATE TABLE IF NOT EXISTS index_val (
    ts_code TEXT NOT NULL, trade_date TEXT NOT NULL,
    pe_ttm REAL, pb REAL, turnover_rate REAL, total_mv REAL,
    PRIMARY KEY (ts_code, trade_date));
CREATE TABLE IF NOT EXISTS macro_series (
    series TEXT NOT NULL, period TEXT NOT NULL, value REAL,
    PRIMARY KEY (series, period));
CREATE TABLE IF NOT EXISTS margin (
    trade_date TEXT PRIMARY KEY, rzye REAL, rzrqye REAL);
CREATE TABLE IF NOT EXISTS hsgt (
    trade_date TEXT PRIMARY KEY, north_money REAL, south_money REAL);
CREATE TABLE IF NOT EXISTS qdii_premium (
    ts_code TEXT PRIMARY KEY, name TEXT, premium REAL, updated TEXT);
CREATE TABLE IF NOT EXISTS portfolio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL, name TEXT DEFAULT '', asset_key TEXT DEFAULT '',
    shares REAL NOT NULL DEFAULT 0, cost REAL NOT NULL DEFAULT 0,
    updated_at TEXT);
CREATE TABLE IF NOT EXISTS fund_nav (
    ts_code TEXT NOT NULL, nav_date TEXT NOT NULL,
    unit_nav REAL, accum_nav REAL,
    PRIMARY KEY (ts_code, nav_date));
CREATE TABLE IF NOT EXISTS watchlist (
    code TEXT PRIMARY KEY, name TEXT DEFAULT '', added_at TEXT);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS refresh_log (
    ts TEXT, source TEXT, target TEXT, status TEXT, detail TEXT);
"""


@contextmanager
def get_conn(db_path: Path | None = None):
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def upsert_df(table: str, df: pd.DataFrame, pk_cols: list[str]):
    """按主键覆盖写入（INSERT OR REPLACE）。df 列需与表列一致。"""
    if df is None or df.empty:
        return 0
    cols = [c for c in df.columns]
    placeholders = ",".join("?" * len(cols))
    sql = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({placeholders})"
    rows = df.where(pd.notnull(df), None).values.tolist()
    with get_conn() as conn:
        conn.executemany(sql, rows)
    return len(rows)


def read_df(table: str, where: str = "", params: tuple = (), order: str = "") -> pd.DataFrame:
    sql = f"SELECT * FROM {table}"
    if where:
        sql += f" WHERE {where}"
    if order:
        sql += f" ORDER BY {order}"
    with get_conn() as conn:
        return pd.read_sql(sql, conn, params=params)


def set_meta(key: str, value: str):
    upsert_df("meta", pd.DataFrame([{"key": key, "value": value}]), ["key"])


def get_meta(key: str, default: str = "") -> str:
    df = read_df("meta", "key=?", (key,))
    return df["value"].iloc[0] if not df.empty else default


def log_refresh(source: str, target: str, status: str, detail: str = ""):
    import datetime
    upsert_df("refresh_log", pd.DataFrame([{
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "source": source, "target": target, "status": status, "detail": detail[:500],
    }]), ["ts"])


# ---------- 组合持仓 ----------
def save_portfolio(holdings: list[dict]) -> int:
    """全量替换持仓。holding: {code, name, asset_key, shares, cost}"""
    import datetime
    with get_conn() as conn:
        conn.execute("DELETE FROM portfolio")
        for h in holdings:
            conn.execute(
                "INSERT INTO portfolio (code,name,asset_key,shares,cost,updated_at) "
                "VALUES (?,?,?,?,?,?)",
                (h.get("code", ""), h.get("name", ""), h.get("asset_key", ""),
                 float(h.get("shares", 0) or 0), float(h.get("cost", 0) or 0),
                 datetime.datetime.now().isoformat(timespec="seconds")))
    return len(holdings)


def read_portfolio() -> pd.DataFrame:
    return read_df("portfolio", order="id")


# ---------- 自选清单 ----------
def watchlist_add(code: str, name: str = "") -> int:
    import datetime
    return upsert_df("watchlist",
                     pd.DataFrame([{"code": code, "name": name,
                                    "added_at": datetime.datetime.now().isoformat(timespec="seconds")}]),
                     ["code"])


def watchlist_remove(code: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM watchlist WHERE code=?", (code,))


def watchlist_all() -> pd.DataFrame:
    return read_df("watchlist", order="added_at DESC")


# ---------- 统一价格读取：A股指数 → 全球指数 → 基金/ETF ----------
def load_price(ts_code: str = "", ts_global: str = "", etf: str = "",
               start: str = "", as_series: bool = True) -> pd.DataFrame | pd.Series:
    frames = []
    if ts_code:
        w = f"ts_code='{ts_code}'" + (f" AND trade_date>='{start}'" if start else "")
        frames.append(read_df("index_daily", w, order="trade_date")
                      .rename(columns={"ts_code": "code"}))
    if ts_global:
        w = f"ts_code='{ts_global}'" + (f" AND trade_date>='{start}'" if start else "")
        frames.append(read_df("global_daily", w, order="trade_date")
                      .rename(columns={"ts_code": "code"}))
    if etf and all(f.empty for f in frames):
        w = f"ts_code='{etf}'" + (f" AND trade_date>='{start}'" if start else "")
        frames.append(read_df("fund_daily", w, order="trade_date")
                      .rename(columns={"ts_code": "code"}))
    non_empty = [f for f in frames if not f.empty]
    df = pd.concat(non_empty, ignore_index=True) if non_empty else pd.DataFrame()
    if df.empty:
        return pd.Series(dtype=float) if as_series else df
    df = df.drop_duplicates(subset="trade_date", keep="first").sort_values("trade_date")
    df["date"] = pd.to_datetime(df["trade_date"])
    if as_series:
        return df.set_index("date")["close"].astype(float)
    return df


def load_valuation(ts_code: str, start: str = "") -> pd.DataFrame:
    w = f"ts_code='{ts_code}'" + (f" AND trade_date>='{start}'" if start else "")
    df = read_df("index_val", w, order="trade_date")
    if not df.empty:
        df["date"] = pd.to_datetime(df["trade_date"])
        df = df.set_index("date")
    return df


def load_macro(series: str, cutoff: str | None = None) -> pd.Series:
    df = read_df("macro_series", f"series='{series}'", order="period")
    if df.empty:
        return pd.Series(dtype=float)
    s = df.set_index("period")["value"].astype(float)
    s.index = pd.to_datetime(s.index)
    s = s.sort_index()
    if cutoff:
        s = s[s.index <= pd.Timestamp(cutoff)]
    return s
