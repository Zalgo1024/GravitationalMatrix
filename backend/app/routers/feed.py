"""S2 舆情流内部 API（方案 (1) 第四节，供第二阶段页面只读调用）。

- 所有端点受 FEED_ENABLED 门控：关闭时统一返回 {"error": "feed_disabled"}；
- 认证复用既有 get_current_user（本地模式自动放行，公网模式 JWT cookie）；
- POST /api/feed/collect 手动触发一轮：公共模式限 admin；
- S3：条目带 city_code/city_name（市级识别），/geo 返回 regions+cities 双层聚合；
- S4：条目带 sentiment/sentiment_score（词典法标注），/items 支持 sentiment 筛选。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.db import SessionLocal
from app.feed_store import feed_geo, feed_geo_cities, feed_stats, query_hotlist, query_items
from app.settings import settings

router = APIRouter()

_DISABLED = {"error": "feed_disabled", "message": "舆情流未启用（FEED_ENABLED=0）。"}


def _item_row(item) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "url": item.url,
        "canonical_url": item.canonical_url,
        "platform": item.platform,
        "kind": item.kind,
        "category": item.category,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "collected_at": item.collected_at.isoformat() if item.collected_at else None,
        "summary": item.summary,
        "hot_score": item.hot_score,
        "sentiment": item.sentiment,
        "sentiment_score": item.sentiment_score,
        "region_code": item.region_code,
        "city_code": item.city_code,
        "city_name": item.city_name,
        "region_source": item.region_source,
    }


@router.get("/api/feed/items")
def list_feed_items(
    category: str | None = None,
    platform: str | None = None,
    q: str | None = None,
    sentiment: str | None = None,
    window: int = 72,
    limit: int = 50,
    offset: int = 0,
    current: dict = Depends(get_current_user),
):
    if not settings.feed_enabled:
        return _DISABLED
    with SessionLocal() as db:
        rows = query_items(
            db,
            category=category,
            platform=platform,
            q=q,
            sentiment=sentiment,
            window_hours=window,
            limit=limit,
            offset=offset,
        )
        return {"items": [_item_row(r) for r in rows], "count": len(rows)}


@router.get("/api/feed/hotlist")
def feed_hotlist(
    window: int = 24,
    limit: int = 30,
    current: dict = Depends(get_current_user),
):
    if not settings.feed_enabled:
        return _DISABLED
    with SessionLocal() as db:
        rows = query_hotlist(db, window_hours=window, limit=limit)
        return {
            "items": [_item_row(r) for r in rows],
            "count": len(rows),
            "note": "按热度排序；未配置热榜端点时此列表为空。",
        }


@router.get("/api/feed/item/{item_id}")
def feed_item_detail(item_id: str, current: dict = Depends(get_current_user)):
    if not settings.feed_enabled:
        return _DISABLED
    from app.models import FeedItem

    with SessionLocal() as db:
        row = db.get(FeedItem, item_id)
        if row is None:
            return {"status": "not_found"}
        data = _item_row(row)
        data["raw_meta"] = row.raw_meta
        return data


@router.get("/api/feed/stats")
def feed_stats_api(window: int = 24, current: dict = Depends(get_current_user)):
    if not settings.feed_enabled:
        return _DISABLED
    with SessionLocal() as db:
        return feed_stats(db, window_hours=window)


@router.get("/api/feed/geo")
def feed_geo_api(window: int = 72, current: dict = Depends(get_current_user)):
    if not settings.feed_enabled:
        return _DISABLED
    with SessionLocal() as db:
        return {
            "regions": feed_geo(db, window_hours=window),
            "cities": feed_geo_cities(db, window_hours=window),
        }


@router.post("/api/feed/collect")
def feed_collect_now(current: dict = Depends(get_current_user)):
    """手动触发一轮采集（调试 / 立即刷新）。公共模式限 admin。"""
    if not settings.feed_enabled:
        return _DISABLED
    if settings.public_mode and current.get("role") != "admin":
        return {"error": "forbidden", "message": "仅管理员可手动触发采集。"}
    from app.feed_collector import collect_feed_round

    return collect_feed_round()
