"""rss 采集器：RSS 2.0 / Atom 订阅源（标准库实现，零依赖）。

订阅源列表由环境变量 COLLECT_RSS_FEEDS 配置（逗号分隔的 URL，可选 `名称=URL` 格式），
未配置时降级说明提示。解析只用 xml.etree，不引入 feedparser 等新依赖。
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET

from app.connectors.base import CollectedItem
from app.connectors.regions import recognize_region
from app.search import _assert_safe_url, _http_get, _safe_msg  # 复用 SSRF 防护与超时 HTTP

_TAG_CLEAN = re.compile(r"<[^>]+>")


def configured_feeds() -> list[tuple[str, str]]:
    """解析 COLLECT_RSS_FEEDS → [(名称, url)]。空配置返回 []。"""
    raw = os.environ.get("COLLECT_RSS_FEEDS", "").strip()
    if not raw:
        return []
    feeds: list[tuple[str, str]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" in part and part.split("=", 1)[0].strip() and part.split("=", 1)[1].strip():
            name, url = part.split("=", 1)
            feeds.append((name.strip()[:40], url.strip()))
        else:
            feeds.append(("rss", part))
    return feeds


def _text(node) -> str:
    if node is None or node.text is None:
        return ""
    return _TAG_CLEAN.sub("", node.text).strip()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_feed(xml_text: str, feed_name: str, limit: int = 15) -> list[CollectedItem]:
    """解析 RSS/Atom XML → 条目。容错：空文档/未知结构返回空列表。"""
    items: list[CollectedItem] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items
    # RSS 2.0: channel/item；Atom: feed/entry
    entries = [el for el in root.iter() if _local(el.tag) in ("item", "entry")]
    for entry in entries[:limit]:
        title = url = snippet = published = ""
        for child in entry:
            tag = _local(child.tag)
            if tag == "title":
                title = _text(child)
            elif tag == "link":
                url = _text(child) or (child.get("href") or "")
            elif tag in ("description", "summary", "content"):
                snippet = snippet or _text(child)
            elif tag in ("pubdate", "published", "updated", "date"):
                published = published or _text(child)
        title, url = title.strip(), (url or "").strip()
        if not title or not url.startswith("http"):
            continue
        region = recognize_region(f"{title}\n{snippet}")
        items.append(
            CollectedItem(
                kind="rss",
                platform=f"rss:{feed_name}",
                title=title[:200],
                url=url,
                snippet=snippet[:400],
                published_at=published or None,
                **region,
            )
        )
    return items


def collect_rss(max_per_feed: int = 15) -> tuple[list[CollectedItem], str | None]:
    """抓取所有已配置订阅源。单源失败不拖垮整体（记入降级说明）。"""
    feeds = configured_feeds()
    if not feeds:
        return [], "未配置订阅源（环境变量 COLLECT_RSS_FEEDS，格式：名称=URL,名称=URL）"
    items: list[CollectedItem] = []
    failures: list[str] = []
    for name, url in feeds:
        try:
            _assert_safe_url(url)
            xml_text = _http_get(url, timeout=10)
            items.extend(parse_feed(xml_text, name, limit=max_per_feed))
        except Exception as exc:  # noqa: BLE001 - 单源失败不拖垮整体
            failures.append(f"{name}：{_safe_msg(exc)}")
    degraded = "; ".join(failures)[:300] if failures else None
    return items, degraded
