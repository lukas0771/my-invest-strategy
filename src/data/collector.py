"""数据采集编排：三源协同 + 逐步降级（tushare → 中证官网 → akshare/新浪），失败不影响其余步骤。"""
import datetime

import pandas as pd

from src import config, universe
from src.data import official_source, store
from src.data.ak_source import AkshareSource
from src.data.ts_source import TushareSource

DEFAULT_START = "20100101"  # 估值分位需要尽量长的历史

QDII_NAMES = {"513100": "纳指100", "513500": "标普500", "513180": "恒生科技",
              "513880": "日经225", "159920": "恒生ETF", "513000": "日经东证"}


def _csindex_start(ts_code: str) -> str:
    """csindex 增量起点：库内最新日期前 10 天（避免每次全量拉 16 年触发官网限流）。"""
    px = store.read_df("index_daily", f"ts_code='{ts_code}'", order="trade_date DESC")
    if px.empty:
        return DEFAULT_START
    import pandas as pd
    last = pd.Timestamp(px["trade_date"].iloc[0]) - pd.Timedelta(days=10)
    return last.strftime("%Y%m%d")


def _qdii_premium_via_nav(ts: TushareSource, watch: list[tuple[str, str]]) -> int:
    """有 token 时：QDII 溢价 ≈ ETF收盘价 / 最新基金净值 - 1（净值T-1，近似值）。"""
    rows = []
    for code, name in watch:
        suffix = ".SH" if code.startswith("5") else ".SZ"
        try:
            df = ts._call("fund_nav", ts_code=code + suffix)
        except Exception:
            continue
        if df is None or df.empty:
            continue
        df = df.dropna(subset=["unit_nav"]).sort_values("nav_date")
        if df.empty:
            continue
        nav = float(df["unit_nav"].iloc[-1])
        nav_date = str(df["nav_date"].iloc[-1])
        px = store.read_df("fund_daily", f"ts_code='{code}'", order="trade_date DESC")
        if px.empty or nav <= 0:
            continue
        price = float(px["close"].iloc[0])
        rows.append({"ts_code": code,
                     "name": QDII_NAMES.get(code, name),
                     "premium": round((price / nav - 1) * 100, 2),
                     "updated": f"{datetime.datetime.now().isoformat(timespec='seconds')} (净值{nav_date})"})
    if not rows:
        return 0
    return store.upsert_df("qdii_premium", pd.DataFrame(rows), ["ts_code"])


def refresh_all(verbose: bool = True) -> list[dict]:
    store.init_db()
    results: list[dict] = []
    token = config.reload_env()  # 热重载 .env，token 改动无需重启
    ts = TushareSource()
    try:
        ak = AkshareSource()
    except Exception as e:  # noqa: BLE001
        ak = None
        store.log_refresh("akshare", "init", "fail", str(e))
    results.append({"source": "system", "target": "tushare_token",
                    "status": "ok" if ts.available else "skip",
                    "rows": 1 if ts.available else 0})
    store.log_refresh("system", "tushare", "ok" if ts.available else "skip",
                      "token已加载" if ts.available else
                      ("token为空（.env 未配置或为空）" if token == "" else "token加载失败"))

    def step(source: str, target: str, fn) -> bool:
        try:
            n = fn()
            results.append({"source": source, "target": target, "status": "ok", "rows": n})
            store.log_refresh(source, target, "ok", f"{n} rows")
            if verbose:
                print(f"  [ok] {source:9s} {target:28s} {n} rows")
            return n > 0
        except Exception as e:  # noqa: BLE001
            results.append({"source": source, "target": target, "status": "fail", "error": str(e)})
            store.log_refresh(source, target, "fail", str(e))
            if verbose:
                print(f"  [fail] {source:9s} {target:28s} {e}")
            return False

    print("== 开始数据刷新 ==")
    for a in universe.ASSETS:
        # ---- A股指数行情 + 估值：tushare → 中证官网(含滚动PE) → 新浪(仅价格) ----
        if a.ts_index:
            ok = False
            if ts.available:
                ok = step("tushare", f"index_daily:{a.ts_index}",
                          lambda a=a: ts.fetch_index_daily(a.ts_index, DEFAULT_START))
                step("tushare", f"index_val:{a.ts_index}",
                     lambda a=a: ts.fetch_index_val(a.ts_index, DEFAULT_START))
            if not ok:  # 中证官网（权威，自带PE；创业板指399006除外）
                ok = step("official", f"csindex:{a.ts_index}",
                          lambda a=a: official_source.fetch_csindex_daily(a.ts_index, _csindex_start(a.ts_index)))
            if not ok and ak:
                step("akshare", f"index_daily:{a.ts_index}",
                     lambda a=a: ak.fetch_index_daily(a.ts_index, a.ak_symbol, DEFAULT_START))
                step("akshare", f"index_val:{a.ts_index}",
                     lambda a=a: ak.fetch_index_val(a.ts_index))
        # ---- 海外指数：tushare → akshare(新浪美股/港股) ----
        if a.ts_global:
            ok = False
            if ts.available:
                ok = step("tushare", f"global:{a.ts_global}",
                          lambda a=a: ts.fetch_global(a.ts_global, DEFAULT_START))
            if not ok and ak:
                if a.ts_global in ("SPX", "NDX"):
                    step("akshare", f"global:{a.ts_global}",
                         lambda a=a: ak.fetch_us_index(a.ts_global, DEFAULT_START))
                elif a.ts_global == "HSTECH":
                    step("akshare", f"global:{a.ts_global}",
                         lambda a=a: ak.fetch_hk_index(a.ts_global, a.ak_hk, DEFAULT_START))
        # ---- 黄金ETF价格代理 ----
        if a.key == "gold" and a.etf:
            ok = False
            if ts.available:
                ok = step("tushare", f"fund_daily:{a.etf}",
                          lambda a=a: ts.fetch_fund_daily(a.etf, DEFAULT_START))
            if not ok and ak:
                step("akshare", f"fund_daily:{a.etf}",
                     lambda a=a: ak.fetch_fund_daily(a.etf, DEFAULT_START))

    # ---- 资金面（tushare 专属；无 token 时资金分自动退化为量能单项）----
    if ts.available:
        step("tushare", "margin", lambda: ts.fetch_margin(DEFAULT_START))
        step("tushare", "hsgt", lambda: ts.fetch_hsgt("20180101"))

    # ---- 宏观 ----
    if ts.available:
        step("tushare", "macro", lambda: ts.fetch_macro("20060101"))
    if ak:
        step("akshare", "macro", lambda: ak.fetch_macro())
    step("official", "us10y_fred", official_source.fetch_us10y_fred)
    step("official", "shiller_pe", official_source.fetch_shiller_pe)

    # ---- QDII 溢价：优先 tushare 净值近似计算；无 token 时尝试东财实时接口 ----
    watch = sorted({a.etf for a in universe.ASSETS if a.etf} &
                   {"513100", "513500", "513180", "513880", "159920", "513000"})
    if ts.available:
        # 先补齐这些 ETF 的日线（溢价 = 价格/净值）
        for code in watch:
            step("tushare", f"fund_daily:{code}",
                 lambda c=code: ts.fetch_fund_daily(c, "20240101"))
        step("tushare", "qdii_premium_nav",
             lambda: _qdii_premium_via_nav(ts, [(c, QDII_NAMES.get(c, "")) for c in watch]))
    elif ak:
        step("akshare", "qdii_premium", lambda: ak.fetch_qdii_premium(watch))

    store.set_meta("last_refresh", datetime.datetime.now().isoformat(timespec="seconds"))
    store.set_meta("tushare_used", "1" if ts.available else "0")
    n_ok = sum(1 for r in results if r["status"] == "ok")
    print(f"== 刷新完成：{n_ok}/{len(results)} 步成功 ==")
    return results
