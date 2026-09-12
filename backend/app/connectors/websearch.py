"""websearch 采集器：复用 app.search 的检索链（BING→BRAVE→DDG/必应网页版/搜狗）。

只做「检索结果 → CollectedItem」的契约转换，不重复实现任何检索逻辑；
不抓正文（正文抓取仍走分析链路里的 fetch_and_clean，避免采集预览变慢）。
"""
from __future__ import annotations

from app.connectors.base import CollectedItem
from app.connectors.regions import recognize_region


def collect_websearch(query: str, max_results: int = 10) -> tuple[list[CollectedItem], str | None]:
    """返回 (条目列表, 降级说明)。降级不抛异常，与 app.search 的「不静默」约定一致。"""
    from app.search import search_web

    result = search_web(query, max_results=max_results)
    items: list[CollectedItem] = []
    if result is None:
        return [], "检索源不可用"
    for hit in result.hits:
        title = (hit.title or "").strip() or (hit.url or "").strip()
        if not title or not (hit.url or "").strip():
            continue
        region = recognize_region(f"{title}\n{hit.snippet or ''}")
        items.append(
            CollectedItem(
                kind="websearch",
                platform=f"websearch:{result.provider}",
                title=title[:200],
                url=hit.url.strip(),
                snippet=(hit.snippet or "").strip(),
                **region,
            )
        )
    return items, result.degraded
