"""S2 全局舆情流入库与查询（方案 (1) S2）。

职责：把 connectors 采集到的 CollectedItem 去重落库到 feed_items，并提供
第二阶段页面所需的只读查询（信息流 / 热榜 / 聚合统计 / 地域聚合）。

红线：
- 去重口径与 connectors/base 一致（content_fingerprint 优先、canonical_url 兜底）；
- 地域识别不出一律 unknown，且不进任何聚合统计（不编造）；
- 情感标注走 feed_sentiment 词典法（S4），source=lexicon，只供辅助展示。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.connectors.base import CollectedItem
from app.feed_sentiment import annotate_text
from app.models import FeedItem, FeedCollectRun, _now


def _parse_published(value: str | None) -> datetime | None:
    """宽松解析采集器给出的时间字符串（RSS/Atom 格式不一），失败返回 None。"""
    raw = (value or "").strip()
    if not raw:
        return None
    from email.utils import parsedate_to_datetime

    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _dedup_key_for(item: CollectedItem) -> str:
    """dedup_key：content_fingerprint 优先（同文异链），空则 canonical_url 哈希。"""
    if item.content_fingerprint:
        return item.content_fingerprint
    if item.canonical_url:
        import hashlib

        return hashlib.sha1(item.canonical_url.encode("utf-8")).hexdigest()
    return ""


def insert_items(db: Session, items: list[CollectedItem]) -> tuple[int, int]:
    """去重入库一批采集结果，返回 (inserted, deduped)。

    库内查重：dedup_key 已存在即跳过（跨轮去重）；批内由调用方先用
    dedupe_items 预筛（duplicate_of 非空的不入库）。
    """
    if not items:
        return 0, 0
    candidates = [it for it in items if not it.duplicate_of]
    existing_keys = {
        row[0]
        for row in db.query(FeedItem.dedup_key)
        .filter(FeedItem.dedup_key.in_([k for k in (_dedup_key_for(i) for i in candidates) if k]))
        .all()
    }
    inserted = deduped = 0
    for item in candidates:
        key = _dedup_key_for(item)
        if key and key in existing_keys:
            deduped += 1
            continue
        sentiment = annotate_text(f"{item.title}\n{item.snippet or ''}")
        db.add(
            FeedItem(
                title=(item.title or "未命名条目")[:500],
                url=(item.url or "")[:1000] or None,
                canonical_url=(item.canonical_url or "")[:1000] or None,
                content_fingerprint=item.content_fingerprint or None,
                dedup_key=key or None,
                independence_group=(item.independence_group or "")[:200] or None,
                platform=(item.platform or item.kind or "")[:80] or None,
                kind=(item.kind or "")[:16] or None,
                category="通用",
                published_at=_parse_published(item.published_at),
                summary=(item.snippet or "")[:2000] or None,
                hot_score=item.engagement,
                sentiment=sentiment["sentiment"],
                sentiment_score=sentiment["sentiment_score"],
                sentiment_source=sentiment["sentiment_source"],
                region_code=item.region_code,
                city_code=item.city_code,
                city_name=item.city_name,
                region_source=item.region_source or "unknown",
                raw_meta={"region_name": item.region_name} if item.region_name else None,
            )
        )
        if key:
            existing_keys.add(key)
        inserted += 1
    db.commit()
    return inserted, deduped


def record_run(
    db: Session,
    source: str,
    *,
    fetched: int,
    inserted: int,
    deduped: int,
    error: str | None,
    started_at: datetime,
) -> None:
    db.add(
        FeedCollectRun(
            source=source[:32],
            started_at=started_at,
            finished_at=_now(),
            fetched=fetched,
            inserted=inserted,
            deduped=deduped,
            error=(error or "")[:500] or None,
        )
    )
    db.commit()


def _window_cutoff(window_hours: int) -> datetime:
    return _now() - timedelta(hours=max(1, int(window_hours)))


def query_items(
    db: Session,
    *,
    category: str | None = None,
    platform: str | None = None,
    q: str | None = None,
    sentiment: str | None = None,
    window_hours: int = 72,
    limit: int = 50,
    offset: int = 0,
) -> list[FeedItem]:
    """信息流查询：时间倒序 + 多维筛选（sentiment ∈ positive/neutral/negative）。"""
    query = db.query(FeedItem).filter(FeedItem.collected_at >= _window_cutoff(window_hours))
    if category:
        query = query.filter(FeedItem.category == category[:32])
    if platform:
        query = query.filter(FeedItem.platform.like(f"{platform[:32]}%"))
    if q:
        like = f"%{q.strip()[:100]}%"
        query = query.filter(FeedItem.title.like(like) | FeedItem.summary.like(like))
    if sentiment:
        query = query.filter(FeedItem.sentiment == sentiment.strip()[:16])
    return (
        query.order_by(FeedItem.collected_at.desc(), FeedItem.hot_score.desc().nullslast())
        .offset(max(0, offset))
        .limit(min(200, max(1, limit)))
        .all()
    )


def query_hotlist(
    db: Session, *, window_hours: int = 24, limit: int = 30
) -> list[FeedItem]:
    """今日热榜：kind=hotlist 按热度倒序。"""
    return (
        db.query(FeedItem)
        .filter(FeedItem.kind == "hotlist", FeedItem.collected_at >= _window_cutoff(window_hours))
        .order_by(FeedItem.hot_score.desc().nullslast(), FeedItem.collected_at.desc())
        .limit(min(100, max(1, limit)))
        .all()
    )


def feed_stats(db: Session, *, window_hours: int = 24) -> dict:
    """聚合统计：来源/分类/情感计数 + 独立源数（同一 independence_group 算一条）。"""
    cutoff = _window_cutoff(window_hours)
    rows = (
        db.query(
            FeedItem.platform,
            FeedItem.category,
            FeedItem.independence_group,
            FeedItem.sentiment,
        )
        .filter(FeedItem.collected_at >= cutoff)
        .all()
    )
    by_platform: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_sentiment: dict[str, int] = {}
    groups: set[str] = set()
    total = 0
    for platform, category, group, sentiment in rows:
        total += 1
        if platform:
            by_platform[platform] = by_platform.get(platform, 0) + 1
        if category:
            by_category[category] = by_category.get(category, 0) + 1
        if sentiment:
            by_sentiment[sentiment] = by_sentiment.get(sentiment, 0) + 1
        if group:
            groups.add(group)
    return {
        "window_hours": window_hours,
        "total": total,
        "independent_sources": len(groups),
        "by_platform": dict(sorted(by_platform.items(), key=lambda kv: -kv[1])),
        "by_category": dict(sorted(by_category.items(), key=lambda kv: -kv[1])),
        "by_sentiment": dict(sorted(by_sentiment.items(), key=lambda kv: -kv[1])),
    }


def feed_geo(db: Session, *, window_hours: int = 72) -> list[dict]:
    """地域聚合（region_code 非空条目按省计数）。

    红线：region_source=unknown 的条目**不进统计**（不编造）。
    """
    cutoff = _window_cutoff(window_hours)
    rows = (
        db.query(FeedItem.region_code, FeedItem.independence_group)
        .filter(
            FeedItem.collected_at >= cutoff,
            FeedItem.region_code.isnot(None),
            FeedItem.region_source != "unknown",
        )
        .all()
    )
    by_region: dict[str, dict[str, int]] = {}
    for code, group in rows:
        bucket = by_region.setdefault(code, {"items": 0, "groups": 0})
        bucket["items"] += 1
    for code in by_region:
        by_region[code]["groups"] = len(
            {g for (c, g) in rows if c == code and g}
        )
    return [
        {"region_code": code, **counts}
        for code, counts in sorted(by_region.items(), key=lambda kv: -kv[1]["items"])
    ]


def feed_geo_cities(db: Session, *, window_hours: int = 72) -> list[dict]:
    """市级聚合（S3，供 /map 事件落点）：city_code 非空条目按市计数。

    红线与省级口径一致：region_source=unknown 的条目不进统计。
    region_code 为该市所属省码（市级命中时 regions 识别即给省码）。
    """
    cutoff = _window_cutoff(window_hours)
    rows = (
        db.query(FeedItem.city_code, FeedItem.city_name, FeedItem.region_code)
        .filter(
            FeedItem.collected_at >= cutoff,
            FeedItem.city_code.isnot(None),
            FeedItem.region_source != "unknown",
        )
        .all()
    )
    by_city: dict[str, dict] = {}
    for city_code, city_name, region_code in rows:
        bucket = by_city.setdefault(
            city_code,
            {"city_name": city_name, "region_code": region_code, "items": 0},
        )
        bucket["items"] += 1
    return [
        {"city_code": code, **info}
        for code, info in sorted(by_city.items(), key=lambda kv: -kv[1]["items"])
    ]


def purge_expired(db: Session, *, keep_days: int = 90) -> int:
    """保留期清理（默认 90 天），返回删除条数。"""
    cutoff = _now() - timedelta(days=keep_days)
    deleted = (
        db.query(FeedItem)
        .filter(FeedItem.collected_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted
