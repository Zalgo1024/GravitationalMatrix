"""S2 采集服务：RSS + 热榜两轮采集入库（方案 (1) S1/S2/S5 最小闭环）。

- 单源失效隔离：某源异常只记 FeedCollectRun.error，不拖垮整轮、不抛异常；
- 未配置源 = degraded 说明，不报错；
- 调度由 monitoring._scheduler 挂钩（内存时间戳节流，单进程红线），
  本模块不自行起线程。
"""
from __future__ import annotations

import logging
import time

from app.db import SessionLocal
from app.feed_store import insert_items, record_run
from app.settings import settings

logger = logging.getLogger(__name__)

# 进程内节流时间戳（单进程部署下天然安全；多进程属既有部署红线，不在此兜）
_feed_last_run: float | None = None


def collect_feed_round() -> dict:
    """跑一轮完整采集（RSS + 热榜），返回轮次摘要。绝不抛异常。"""
    from datetime import datetime, timezone

    from app.connectors.hotlist import collect_hotlist
    from app.connectors.rss import collect_rss
    from app.connectors.base import dedupe_items

    summary: dict = {"sources": {}, "inserted": 0, "deduped": 0, "degraded": []}
    for source, collect_fn in (("rss", collect_rss), ("hotlist", collect_hotlist)):
        started = datetime.now(timezone.utc)
        try:
            items, degraded = collect_fn()
        except Exception as exc:  # noqa: BLE001 —— 单源失败不拖垮整轮
            logger.warning("feed 采集源 %s 异常：%s", source, exc)
            items, degraded = [], f"采集异常：{exc}"
        with SessionLocal() as db:
            inserted, deduped = insert_items(db, dedupe_items(items))
            record_run(
                db,
                source,
                fetched=len(items),
                inserted=inserted,
                deduped=deduped,
                error=degraded,
                started_at=started,
            )
        summary["sources"][source] = {"fetched": len(items), "inserted": inserted, "deduped": deduped}
        summary["inserted"] += inserted
        summary["deduped"] += deduped
        if degraded:
            summary["degraded"].append(f"{source}：{degraded}")
    return summary


def feed_tick() -> dict | None:
    """调度入口：FEED_INTERVAL_MIN 节流；未到间隔返回 None。"""
    global _feed_last_run
    if not settings.feed_enabled:
        return None
    now = time.monotonic()
    if (
        _feed_last_run is not None
        and now - _feed_last_run < settings.feed_interval_min * 60
    ):
        return None
    _feed_last_run = now
    try:
        return collect_feed_round()
    except Exception:  # noqa: BLE001 —— 采集失败绝不影响主调度循环
        logger.exception("feed 采集轮次异常")
        return None
