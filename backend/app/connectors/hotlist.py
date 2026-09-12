"""hotlist 采集器：热榜聚合（配置驱动，未配置时优雅降级）。

数据源由环境变量 COLLECT_HOTLIST_URL 指向一个 JSON 端点（自建聚合服务或
兼容 TrendRadar 输出结构的静态 JSON），期望格式（宽松解析，任一可用即可）：
    {"items": [{"title": ..., "url": ..., "hot": 12345, "source": "微博", ...}]}
或直接是上述 items 数组。缺 url 的条目跳过（无法溯源的证据不进账本）。
不内置任何第三方热榜 API 地址：外部端点变动频繁且合规边界需用户自持。
"""
from __future__ import annotations

import json
import os

from app.connectors.base import CollectedItem
from app.connectors.regions import recognize_region
from app.search import _assert_safe_url, _http_get, _safe_msg


def collect_hotlist(max_items: int = 30) -> tuple[list[CollectedItem], str | None]:
    endpoint = os.environ.get("COLLECT_HOTLIST_URL", "").strip()
    if not endpoint:
        return [], "未配置热榜端点（环境变量 COLLECT_HOTLIST_URL）"
    try:
        _assert_safe_url(endpoint)
        raw = _http_get(endpoint, timeout=10)
        payload = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - 外部端点不可用属常态，降级不抛
        return [], f"热榜端点不可用：{_safe_msg(exc)}"
    rows = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return [], "热榜端点返回格式不识别（期望 {items: [...]} 或数组）"
    items: list[CollectedItem] = []
    for row in rows[: max_items * 2]:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        url = str(row.get("url") or row.get("link") or "").strip()
        if not title or not url.startswith("http"):
            continue
        hot = row.get("hot") or row.get("value") or row.get("rank_score")
        try:
            engagement = int(hot) if hot is not None else None
        except (TypeError, ValueError):
            engagement = None
        source_label = str(row.get("source") or row.get("platform") or "热榜").strip()[:20]
        region = recognize_region(f"{title}\n{str(row.get('summary') or '')}")
        items.append(
            CollectedItem(
                kind="hotlist",
                platform=f"hotlist:{source_label}",
                title=title[:200],
                url=url,
                snippet=str(row.get("summary") or row.get("desc") or "").strip()[:400],
                published_at=str(row.get("published_at") or "") or None,
                engagement=engagement,
                **region,
            )
        )
        if len(items) >= max_items:
            break
    return items, None
