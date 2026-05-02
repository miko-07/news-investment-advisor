"""
新闻抓取模块
支持 RSS (feedparser) 和 JSON API 两种新闻源，并行抓取、去重、截断
"""
import logging
import random
import ssl
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Optional

import feedparser
import requests
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup

from config import (
    NEWS_SOURCES,
    MAX_ARTICLES_PER_SOURCE,
    MAX_TOTAL_ARTICLES,
    NEWS_MAX_AGE_HOURS,
    REQUEST_TIMEOUT,
)

logger = logging.getLogger(__name__)

CST = timezone(timedelta(hours=8))
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    )
}


class _HTTP1Adapter(HTTPAdapter):
    """TLS 1.2+ / HTTP 1.1 only — 避免 HTTP/2 协商触发国内 CDN 的 SSL EOF"""
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.set_alpn_protocols(["http/1.1"])
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


_SESSION = requests.Session()
_SESSION.mount("https://", _HTTP1Adapter())


def _http_get(url: str, timeout: int = REQUEST_TIMEOUT) -> requests.Response:
    """带 SSL 重试的 HTTP GET"""
    last_err = None
    for attempt in range(3):
        try:
            return _SESSION.get(url, timeout=timeout, headers=HEADERS)
        except requests.exceptions.SSLError:
            last_err = sys.exc_info()[1]
            if attempt < 2:
                time.sleep(1.0 + random.random())
    raise last_err


# ═══════════════════════════════════════════════════════════════
# JSON API 解析器（每种源一个函数，按 source name 映射）
# ═══════════════════════════════════════════════════════════════

def _parse_cls(resp: requests.Response) -> list[dict]:
    """财联社电报 JSON"""
    data = resp.json()
    if not isinstance(data, dict):
        return []
    articles = []
    for item in data.get("data", {}).get("roll_data", []):
        title = (item.get("title") or "").strip()
        brief = (item.get("brief") or "").strip()
        if not title:
            continue
        ctime = item.get("ctime", 0)
        published = datetime.fromtimestamp(ctime, tz=CST) if ctime else None
        articles.append({
            "title": title,
            "source": "财联社",
            "url": f"https://www.cls.cn/detail/{item.get('id', '')}" if item.get("id") else "",
            "summary": brief[:300],
            "published": published,
        })
    # CLS 默认按时间倒序
    return articles


def _parse_sina(resp: requests.Response) -> list[dict]:
    """新浪财经 API"""
    data = resp.json()
    if not isinstance(data, dict):
        return []
    articles = []
    for item in data.get("result", {}).get("data", []):
        title = (item.get("title") or "").strip()
        intro = (item.get("intro") or "").strip()
        if not title:
            continue
        ctime_str = item.get("ctime", "")
        published = None
        if ctime_str:
            try:
                published = datetime.fromtimestamp(int(ctime_str), tz=CST)
            except (ValueError, TypeError):
                pass
        articles.append({
            "title": title,
            "source": "新浪财经",
            "url": (item.get("url") or "").strip(),
            "summary": intro[:300],
            "published": published,
        })
    return articles


def _parse_rss(resp: requests.Response) -> list[dict]:
    """通用 RSS/Atom feed 解析"""
    feed = feedparser.parse(resp.content)
    articles = []
    for entry in feed.entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        summary = entry.get("summary") or entry.get("description") or ""
        # 纯文本化
        summary = BeautifulSoup(summary, "lxml").get_text(" ", strip=True)[:300]

        if not title:
            continue

        published = None
        for key in ("published_parsed", "updated_parsed"):
            tp = entry.get(key)
            if tp:
                published = datetime(*tp[:6], tzinfo=timezone.utc)
                break

        articles.append({
            "title": title,
            "source": entry.get("source", {}).get("title", "") if hasattr(entry, "source") else "",
            "url": link,
            "summary": summary,
            "published": published,
        })
    return articles


# JSON 源 → 解析函数的映射
_JSON_PARSERS = {
    "cls.cn": _parse_cls,
    "sina.com.cn": _parse_sina,
}


def _parse_feed(source: dict) -> list[dict]:
    """抓取单个新闻源，返回文章列表"""
    name = source["name"]
    url = source["url"]
    stype = source.get("type", "rss")
    timeout = source.get("timeout", REQUEST_TIMEOUT)
    articles = []

    try:
        resp = _http_get(url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning(f"[{name}] 请求失败: {e}")
        return []
    except Exception as e:
        logger.warning(f"[{name}] 未知错误: {e}")
        return []

    try:
        if stype == "json":
            # 根据域名匹配解析器
            for domain, parser in _JSON_PARSERS.items():
                if domain in url:
                    articles = parser(resp)
                    break
            else:
                logger.warning(f"[{name}] JSON 源无匹配解析器: {url}")
                return []
        else:
            articles = _parse_rss(resp)
    except Exception as e:
        logger.warning(f"[{name}] 解析失败: {e}")
        return []

    # 截断
    articles = articles[:MAX_ARTICLES_PER_SOURCE]
    logger.info(f"[{name}] 抓取 {len(articles)} 篇")
    return articles


def _deduplicate(articles: list[dict]) -> list[dict]:
    """基于标题前15字去重"""
    seen: set[str] = set()
    result = []
    for a in articles:
        key = a["title"][:15].strip()
        if key in seen:
            continue
        seen.add(key)
        result.append(a)
    return result


def fetch_all_news() -> list[dict]:
    """并行抓取所有新闻源，返回去重、按时间倒序的文章列表"""
    all_articles = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_parse_feed, src): src for src in NEWS_SOURCES}
        for future in as_completed(futures):
            try:
                all_articles.extend(future.result())
            except Exception as e:
                src = futures[future]
                logger.error(f"[{src['name']}] 线程异常: {e}")

    # 去重
    all_articles = _deduplicate(all_articles)

    # 过滤掉超过 NEWS_MAX_AGE_HOURS 的旧闻（无发布时间的保留）
    now = datetime.now(CST)
    cutoff = now - timedelta(hours=NEWS_MAX_AGE_HOURS)
    filtered = []
    for a in all_articles:
        t = a.get("published")
        if t is None:
            filtered.append(a)  # 无时间信息的保留
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=CST)
        if t >= cutoff:
            filtered.append(a)
    removed = len(all_articles) - len(filtered)
    if removed > 0:
        logger.info(f"过滤掉 {removed} 条旧闻（超过 {NEWS_MAX_AGE_HOURS} 小时）")
    all_articles = filtered

    # 按发布时间倒序（无时间的排最后）
    def sort_key(a: dict) -> datetime:
        t = a.get("published")
        return t if t else datetime.min.replace(tzinfo=timezone.utc)

    all_articles.sort(key=sort_key, reverse=True)

    # 截断
    all_articles = all_articles[:MAX_TOTAL_ARTICLES]

    logger.info(f"总计抓取 {len(all_articles)} 篇新闻（去重后）")
    return all_articles


def format_news_for_ai(articles: list[dict]) -> str:
    """将文章列表格式化为 AI 可读的文本"""
    lines = []
    for i, a in enumerate(articles, 1):
        t = a["published"]
        if t:
            # 统一转为北京时间
            if t.tzinfo is None:
                t = t.replace(tzinfo=CST)
            time_str = t.astimezone(CST).strftime("%m-%d %H:%M")
        else:
            time_str = "未知时间"
        lines.append(
            f"{i}. [{a['source']}] {a['title']}\n"
            f"   时间: {time_str}\n"
            f"   摘要: {a['summary']}\n"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    articles = fetch_all_news()
    print(format_news_for_ai(articles))
