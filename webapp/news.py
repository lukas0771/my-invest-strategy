"""财经新闻：华尔街见闻 RSS（主）+ 东财资讯（补充）。

质量原则（宁缺毋滥）：只收录带原文链接的条目；标题去重；按时间倒序；缓存 10 分钟。
"""
import datetime
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import requests

UA = {"User-Agent": "Mozilla/5.0"}
_CACHE = {"ts": None, "items": [], "sources": []}


def _parse_pub(pub: str) -> str:
    try:
        return parsedate_to_datetime(pub).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(pub)[:16]


def _rss_wallstreetcn(limit: int = 20) -> list[dict]:
    """华尔街见闻 RSS：市场与宏观要闻，带原文链接。"""
    r = requests.get("https://dedicated.wallstreetcn.com/rss.xml", headers=UA, timeout=15)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if not (title and link.startswith("http")):
            continue
        desc = re.sub(r"<[^>]+>", "", it.findtext("description") or "")[:130]
        items.append({"title": title[:90], "url": link, "summary": desc,
                      "time": _parse_pub(it.findtext("date") or it.findtext("pubDate") or ""),
                      "source": "华尔街见闻"})
        if len(items) >= limit:
            break
    return items


def _em_news(limit: int = 16) -> list[dict]:
    """东财资讯：多关键词聚合，仅保留带链接条目。"""
    import akshare as ak
    items, seen = [], set()
    for kw in ("A股", "美股", "美联储", "基金", "黄金"):
        try:
            df = ak.stock_news_em(symbol=kw)
        except Exception:
            continue
        if df is None or df.empty or "新闻链接" not in df.columns:
            continue
        for _, r in df.iterrows():
            url = str(r.get("新闻链接", ""))
            title = str(r.get("新闻标题", ""))[:90]
            if not url.startswith("http") or title in seen:
                continue
            seen.add(title)
            items.append({"title": title, "url": url,
                          "summary": str(r.get("新闻内容", ""))[:120],
                          "time": str(r.get("发布时间", ""))[:16],
                          "source": str(r.get("文章来源", "")) or "东财资讯"})
            if len(items) >= limit:
                return items
    return items


def get_news(limit: int = 15) -> dict:
    now = datetime.datetime.now()
    if _CACHE["ts"] and (now - _CACHE["ts"]).total_seconds() < 600 and _CACHE["items"]:
        return {"sources": _CACHE["sources"], "items": _CACHE["items"][:limit]}
    items, sources = [], []
    for fetcher, name in ((_rss_wallstreetcn, "华尔街见闻"), (_em_news, "东财资讯")):
        try:
            got = fetcher()
            if got:
                items += got
                sources.append(name)
        except Exception:
            continue
    seen, uniq = set(), []
    for it in sorted(items, key=lambda x: x["time"], reverse=True):
        if it["title"] in seen:
            continue
        seen.add(it["title"])
        uniq.append(it)
    _CACHE.update({"ts": now, "items": uniq, "sources": sources})
    return {"sources": sources, "items": uniq[:limit]}
