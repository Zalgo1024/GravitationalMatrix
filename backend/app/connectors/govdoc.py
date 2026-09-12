"""govdoc 采集器：政策文件定向检索。

实现：对 query 追加「政策/通知/公告」语境词 + site:gov.cn 域过滤的检索（复用 app.search），
只保留 *.gov.cn（含各级地方政府）结果。政府文件是政策分析链路的第一手证据，
单独成渠道便于 F15「政策条款表」后续直接复用。
"""
from __future__ import annotations

from urllib.parse import urlsplit

from app.connectors.base import CollectedItem
from app.connectors.regions import recognize_region

_GOV_SUFFIXES = (".gov.cn", ".gov")


def _is_gov(url: str) -> bool:
    try:
        host = urlsplit(url).netloc.lower()
    except ValueError:
        return False
    return any(host == s.lstrip(".") or host.endswith(s) for s in _GOV_SUFFIXES)


def collect_govdoc(query: str, max_results: int = 8) -> tuple[list[CollectedItem], str | None]:
    """检索政府站点内的政策文件；返回 (条目, 降级说明)。"""
    from app.search import search_web

    boosted = f"{query} 政策 通知 公告 site:gov.cn"
    result = search_web(boosted, max_results=max_results * 2)
    if result is None:
        return [], "检索源不可用"
    items: list[CollectedItem] = []
    for hit in result.hits:
        url = (hit.url or "").strip()
        if not url or not _is_gov(url):
            continue
        title = (hit.title or "").strip() or url
        region = recognize_region(f"{title}\n{hit.snippet or ''}")
        # 政府站点归属地不明时，站点本身在哪个省不可靠——region_source 保持 unknown 优先级不覆盖正文识别
        items.append(
            CollectedItem(
                kind="govdoc",
                platform="govdoc:检索",
                title=title[:200],
                url=url,
                snippet=(hit.snippet or "").strip(),
                **region,
            )
        )
        if len(items) >= max_results:
            break
    degraded = result.degraded
    if not items and not degraded:
        degraded = "本次检索未命中 gov.cn 域内结果"
    return items, degraded
