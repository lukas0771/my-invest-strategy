"""财经新闻：多源降级（东财个股资讯 → 央视新闻联播），内存缓存 10 分钟。"""
import datetime

_CACHE = {"ts": None, "items": [], "source": ""}


def _norm_em(df) -> list[dict]:
    items = []
    for _, r in df.iterrows():
        items.append({"title": str(r.get("新闻标题", ""))[:80],
                      "summary": str(r.get("新闻内容", ""))[:120],
                      "time": str(r.get("发布时间", ""))[:16],
                      "source": str(r.get("文章来源", ""))})
    return items


def _norm_cctv(df) -> list[dict]:
    items = []
    for _, r in df.iterrows():
        items.append({"title": str(r.get("title", ""))[:80],
                      "summary": str(r.get("content", ""))[:120],
                      "time": str(r.get("date", ""))[:16],
                      "source": "新闻联播"})
    return items


def get_news(limit: int = 10) -> dict:
    now = datetime.datetime.now()
    if _CACHE["ts"] and (now - _CACHE["ts"]).total_seconds() < 600 and _CACHE["items"]:
        return {"source": _CACHE["source"], "items": _CACHE["items"][:limit]}
    import akshare as ak
    items, source = [], ""
    for keyword in ("A股", "股市", "美联储"):
        try:
            df = ak.stock_news_em(symbol=keyword)
            if df is not None and not df.empty:
                items, source = _norm_em(df), f"东财资讯·{keyword}"
                break
        except Exception:
            continue
    if not items:
        try:
            df = ak.news_cctv()
            if df is not None and not df.empty:
                items, source = _norm_cctv(df), "新闻联播"
        except Exception:
            pass
    _CACHE.update({"ts": now, "items": items, "source": source})
    return {"source": source, "items": items[:limit]}
