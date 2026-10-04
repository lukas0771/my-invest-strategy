"""FastAPI 策略网站后端：静态托管 + API + 每日定时刷新。

启动（项目根目录）：uvicorn webapp.main:app --host 127.0.0.1 --port 8000
"""
import datetime
import threading

import pandas as pd
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src import config, universe
from src.data import store
from src.engine import scorer

app = FastAPI(title="四维信号投资策略系统", docs_url="/api/docs")

REFRESH = {"running": False, "started": "", "finished": "", "log": []}
SCHED_INFO = {"enabled": False, "next_run": None, "cron": "交易日 16:30"}


# ---------------------------------------------------------------- 工具
def _monthly(s: pd.Series, years: int | None = None, last_n: int | None = None) -> list:
    """序列按月取末值并转 [date, value] 列表（可选近 N 年）。"""
    if s is None or len(s) == 0:
        return []
    s = s.dropna()
    if years:
        s = s[s.index >= s.index[-1] - pd.DateOffset(years=years)]
    if last_n:
        s = s.iloc[-last_n:]
    m = s.groupby(s.index.to_period("M")).last()
    return [[str(k), round(float(v), 4)] for k, v in m.items()]


def _ma200_series(close: pd.Series, years: int = 6) -> list:
    s = close.dropna()
    if len(s) < config.MA_LONG:
        return []
    ma = s.rolling(config.MA_LONG).mean()
    df = pd.DataFrame({"close": s, "ma200": ma}).last(f"{years}Y").dropna()
    return [[d.strftime("%Y-%m-%d"), round(r.close, 2),
             None if pd.isna(r.ma200) else round(r.ma200, 2)] for d, r in df.iterrows()]


# ---------------------------------------------------------------- 数据刷新
def _run_refresh():
    try:
        from src.data.collector import refresh_all
        REFRESH["running"] = True
        REFRESH["started"] = datetime.datetime.now().isoformat(timespec="seconds")
        logs = []
        for r in refresh_all(verbose=False):
            logs.append(f"[{r['status']}] {r['source']}:{r['target']} "
                        + (str(r.get('rows', '')) if r['status'] == 'ok' else r.get('error', '')[:80]))
        from src.report import generate
        generate()
        REFRESH["log"] = logs
        REFRESH["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
    except Exception as e:  # noqa: BLE001
        REFRESH["log"].append(f"[error] {e}")
    finally:
        REFRESH["running"] = False


@app.post("/api/refresh")
def start_refresh():
    if REFRESH["running"]:
        return {"status": "already_running"}
    threading.Thread(target=_run_refresh, daemon=True).start()
    return {"status": "started"}


@app.get("/api/refresh/status")
def refresh_status():
    return REFRESH


# ---------------------------------------------------------------- API
# ---------------------------------------------------------------- 行情指数条
TICKER_KEYS = ["hs300", "zz500", "cyb", "hstech", "spx", "ndx", "gold"]


@app.get("/api/ticker")
def api_ticker():
    out = []
    for k in TICKER_KEYS:
        a = universe.ASSETS_BY_KEY[k]
        px = store.load_price(ts_code=a.ts_index, ts_global=a.ts_global, etf=a.etf, as_series=False)
        if px.empty:
            continue
        close = px.sort_values("date")["close"].astype(float)
        last, prev = float(close.iloc[-1]), float(close.iloc[-2]) if len(close) > 1 else float(close.iloc[-1])
        chg = (last / prev - 1) * 100 if prev else 0.0
        out.append({"key": k, "name": a.name, "close": round(last, 2),
                    "chg": round(chg, 2), "date": px.sort_values("date")["date"].iloc[-1].strftime("%m-%d")})
    return {"ticker": out}


# ---------------------------------------------------------------- 财经新闻
@app.get("/api/news")
def api_news():
    from webapp.news import get_news
    try:
        return get_news()
    except Exception as e:  # noqa: BLE001
        return {"source": "", "items": [], "error": str(e)[:100]}


# ---------------------------------------------------------------- 自选清单
@app.get("/api/watchlist")
def api_watchlist():
    from webapp.portfolio import _latest_price
    rows = []
    for _, w in store.watchlist_all().iterrows():
        code = str(w["code"])
        price, pdate = _latest_price(code, "")
        # 近1月涨跌：优先基金日线，其次净值表
        base = chg1m = None
        df = store.read_df("fund_daily", f"ts_code='{code}'", order="trade_date DESC").head(25)
        if len(df) >= 2:
            s = df.sort_values("trade_date")["close"].astype(float)
            base, chg1m = float(s.iloc[-1]), round((float(s.iloc[-1]) / float(s.iloc[0]) - 1) * 100, 2)
            pdate = df["trade_date"].iloc[0]  # DESC 序首行即最新
        navdf = store.read_df("fund_nav", f"ts_code LIKE '{code}%'", order="nav_date DESC").head(25)
        if len(navdf) >= 2 and base is None:
            s = navdf.sort_values("nav_date")["unit_nav"].astype(float)
            base, chg1m = float(s.iloc[-1]), round((float(s.iloc[-1]) / float(s.iloc[0]) - 1) * 100, 2)
            pdate = str(navdf["nav_date"].iloc[-1])
        prem = store.read_df("qdii_premium", f"ts_code='{code}'")
        rows.append({"code": code, "name": w["name"] or (prem["name"].iloc[0] if not prem.empty else ""),
                     "price": base, "chg1m": chg1m, "price_date": pdate,
                     "premium": None if prem.empty else float(prem["premium"].iloc[0])})
    return {"rows": rows}


@app.post("/api/watchlist")
def api_watchlist_add(item: dict):
    code = str(item.get("code", "")).strip()
    if not code.isdigit() or len(code) != 6:
        return JSONResponse({"error": "请输入6位数字基金/ETF代码"}, status_code=400)
    store.watchlist_add(code, str(item.get("name", "")))
    return api_watchlist()


@app.delete("/api/watchlist/{code}")
def api_watchlist_del(code: str):
    store.watchlist_remove(code)
    return api_watchlist()


# ---------------------------------------------------------------- 自动化
@app.get("/api/automation")
def api_automation():
    log = store.read_df("refresh_log", order="ts DESC").head(120)
    sched = SCHED_INFO or {"enabled": False, "next_run": None, "cron": "交易日 16:30"}
    return {"log": [{"ts": r["ts"], "source": r["source"], "target": r["target"],
                     "status": r["status"], "detail": str(r["detail"])[:120]}
                    for _, r in log.iterrows()],
            "scheduler": sched,
            "last_refresh": store.get_meta("last_refresh")}


@app.get("/api/system")
def api_system():
    """系统状态：tushare 配置、数据源健康（refresh_log 聚合）。"""
    from src import config as cfg
    log = store.read_df("refresh_log", order="ts DESC").head(300)
    latest: dict = {}
    for _, r in log.iterrows():
        key = (str(r["source"]), str(r["target"]))
        if key not in latest:
            latest[key] = r
    sources = [{"source": k[0], "target": k[1], "status": v["status"],
                "ts": v["ts"], "detail": str(v["detail"])[:120]}
               for k, v in sorted(latest.items(), key=lambda kv: kv[1]["ts"], reverse=True)]
    return {"tushare_configured": bool(cfg.TUSHARE_TOKEN),
            "tushare_used_last": store.get_meta("tushare_used") == "1",
            "last_refresh": store.get_meta("last_refresh"),
            "sources": sources}


@app.get("/api/summary")
def api_summary():
    last = store.get_meta("last_refresh")
    sigs = scorer.score_all()
    plan = scorer.build_plan(sigs)
    alerts = []
    for s in sigs:
        for f in s.flags:
            if any(k in f for k in ("溢价", "缺失", "不足", "压缩")):
                alerts.append({"asset": s.name, "text": f})
        if s.stale:
            alerts.append({"asset": s.name, "text": f"数据陈旧（最后交易日 {s.last_date}）"})
    return {"last_refresh": last, "regime": plan["regime"],
            "equity_weight": plan["equity_weight"], "notes": plan["notes"],
            "alerts": alerts,
            "n_assets": len([s for s in sigs if s.total is not None]),
            "n_assets_total": len(sigs)}


@app.get("/api/assets")
def api_assets():
    sigs = scorer.score_all()
    plan = scorer.build_plan(sigs)
    out = []
    for s in sigs:
        d = s.to_dict()
        d["target_weight"] = plan["weights"].get(s.key, 0)
        out.append(d)
    return {"assets": out, "regime": plan["regime"], "notes": plan["notes"],
            "equity_weight": plan["equity_weight"]}


@app.get("/api/valuation")
def api_valuation():
    out = []
    for a in universe.ASSETS:
        if a.valuation == "none":
            continue
        val = store.load_valuation(a.ts_index) if a.ts_index else pd.DataFrame()
        pe, vtype = pd.Series(dtype=float), a.valuation
        if not val.empty and "pe_ttm" in val.columns:
            pe = val["pe_ttm"].astype(float).dropna()
        if a.valuation == "shiller":
            pe = store.load_macro("sp500_shiller_pe")
        if pe.empty:  # 无官方PE → 价格分位（与引擎兜底一致）
            pe = store.load_price(ts_code=a.ts_index, ts_global=a.ts_global, etf=a.etf)
            vtype = "价格分位"
        pct = None
        if not pe.empty:
            yrs = 15 if a.valuation == "shiller" else 10
            win = pe[pe.index >= pe.index[-1] - pd.DateOffset(years=yrs)]
            if len(win) >= 100:
                pct = float((win <= win.iloc[-1]).mean())
        out.append({"key": a.key, "name": a.name, "type": vtype,
                    "current_pe": None if pe.empty else round(float(pe.iloc[-1]), 2),
                    "pct": pct, "history": _monthly(pe, last_n=130)})
    return {"valuation": out}


def _kline_data(close: pd.Series, px_df: pd.DataFrame, has_ohlc: bool,
                bars: int = 250) -> dict:
    """K线数据：A股指数有完整 OHLC → candlestick；全球指数只有 close → line。
    附 MA20/60/200。"""
    df = px_df.sort_values("date").tail(bars)
    closes = df.set_index("date")["close"].astype(float)
    ma = {w: closes.rolling(w).mean().round(2) for w in (20, 60, 200)}
    out = {"mode": "candle" if has_ohlc else "line",
           "dates": [d.strftime("%Y-%m-%d") for d in df["date"]],
           "ma20": [None if pd.isna(v) else v for v in ma[20]],
           "ma60": [None if pd.isna(v) else v for v in ma[60]],
           "ma200": [None if pd.isna(v) else v for v in ma[200]]}
    if has_ohlc:
        out["kline"] = df[["open", "close", "low", "high"]].round(2).values.tolist()
    else:
        out["line"] = closes.round(2).tolist()
    return out


@app.get("/api/trend")
def api_trend():
    assets = []
    for a in universe.ASSETS:
        if a.key == "cash":
            continue
        px = store.load_price(ts_code=a.ts_index, ts_global=a.ts_global, etf=a.etf, as_series=False)
        if px.empty:
            continue
        close = px.set_index("date")["close"].astype(float)
        from src.engine import trend as tr
        score, detail = tr.trend_score(close)
        has_ohlc = bool(a.ts_index) and "high" in px.columns and px["high"].notna().sum() > 60
        assets.append({"key": a.key, "name": a.name, "trend_score": score,
                       "momentum": detail.get("momentum"), "above_ma200": detail.get("above_ma200"),
                       "series": _ma200_series(close),
                       "kline": _kline_data(close, px, has_ohlc)})
    assets.sort(key=lambda x: -(x["momentum"] or -9))
    for i, x in enumerate(assets):
        x["momentum_rank"] = i + 1
    return {"trend": assets}


@app.get("/api/flows")
def api_flows():
    margin = store.read_df("margin", order="trade_date")
    hsgt = store.read_df("hsgt", order="trade_date")
    prem = store.read_df("qdii_premium")
    from src.engine import flows as fl
    margin_series = []
    if not margin.empty:
        s = margin.set_index("trade_date")["rzye"].astype(float)
        s.index = pd.to_datetime(s.index)
        s = s.last("3Y")
        # 丢弃末尾不完整行（当日仅单交易所披露时余额约为正常值一半）
        if len(s) >= 6 and s.iloc[-1] < s.iloc[-6:-1].median() * 0.7:
            s = s.iloc[:-1]
        margin_series = [[d.strftime("%Y-%m-%d"), round(v / 1e8, 1)]
                         for d, v in s.items()]
    out_prem = []
    for _, r in prem.iterrows():
        out_prem.append({"code": r["ts_code"], "name": r["name"], "premium": r["premium"],
                         "over_limit": bool(r["premium"] > config.QDII_PREMIUM_LIMIT),
                         "updated": r["updated"]})
    vols = []
    for a in universe.ASSETS:
        if a.asset_class not in ("equity_cn", "equity_global") or a.key == "cash":
            continue
        px = store.load_price(ts_code=a.ts_index, ts_global=a.ts_global, etf=a.etf, as_series=False)
        vr = fl.volume_ratio(px)
        if vr is not None:
            vols.append({"key": a.key, "name": a.name, "volume_ratio": round(vr, 2)})
    return {"margin_index": margin_series, "hsgt_rows": len(hsgt), "premiums": out_prem,
            "volume_ratios": vols,
            "note": "北向资金2024-08后停止实时披露；两融数据需tushare token"}


@app.get("/api/macro")
def api_macro():
    def pack(series, **kw):
        return _monthly(store.load_macro(series), **kw)
    m1, m2 = store.load_macro("m1_yoy"), store.load_macro("m2_yoy")
    gap = (m1 - m2).dropna() if len(m1) and len(m2) else pd.Series(dtype=float)
    return {"pmi": pack("pmi", years=8), "ppi": pack("ppi_yoy", years=8),
            "m1_m2_gap": _monthly(gap, years=8), "sf": pack("sf_12m", years=8),
            "us10y": pack("us10y", years=8), "cn10y": pack("cn10y", years=8),
            "shiller": pack("sp500_shiller_pe")}


@app.get("/api/strategy")
def api_strategy():
    from src.report import generate
    payload = generate()
    payload.pop("report_md", None)
    return payload


@app.get("/api/report")
def api_report():
    p = config.OUTPUT_DIR / "latest.md"
    if not p.exists():
        from src.report import generate
        generate()
    return {"md": p.read_text(encoding="utf-8")}


@app.get("/api/backtest")
def api_backtest():
    p = config.OUTPUT_DIR / "backtest.json"
    if not p.exists():
        return JSONResponse({"error": "尚未运行回测，请点击“运行回测”"}, status_code=404)
    import json
    return json.loads(p.read_text(encoding="utf-8"))


@app.post("/api/backtest/run")
def api_backtest_run():
    from src import backtest
    result = backtest.run(verbose=False)
    return {k: v for k, v in result.items() if k != "weights_history"}


# ---------------------------------------------------------------- 持仓
@app.get("/api/portfolio")
def api_portfolio():
    from webapp.portfolio import portfolio_view
    return portfolio_view()


@app.post("/api/portfolio")
def api_portfolio_save(holdings: list[dict]):
    store.save_portfolio(holdings)
    from webapp.portfolio import portfolio_view
    return portfolio_view()


# ---------------------------------------------------------------- 静态页
app.mount("/", StaticFiles(directory="webapp/static", html=True), name="static")


# ---------------------------------------------------------------- 定时刷新
@app.on_event("startup")
def startup():
    global SCHED_INFO
    try:
        from src.webapp.scheduler import start_scheduler  # noqa: F401
    except ImportError:
        pass
    try:
        from webapp.scheduler import start_scheduler
        SCHED_INFO = start_scheduler() or SCHED_INFO
    except Exception as e:  # noqa: BLE001
        print("scheduler 未启动:", e)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
