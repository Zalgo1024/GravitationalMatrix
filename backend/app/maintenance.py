"""产物维护 — 即时导出物的磁盘回收（Phase 4）。

背景：/api/download 的 pptx / zip 下载每次都往 generated/ 写
`pptx_{task_id}/`、`bundle_{task_id}/` 目录（含即时生成的 pptx、图 PNG、
zip 包）。这些产物**随时可以从报告版本重新导出**，但此前只有删除任务
才会级联清理——公网开放后磁盘只增不减。

本模块提供：
- cleanup_stale_exports(max_age_days)：按目录 mtime 清理超龄的即时导出目录。
- maybe_cleanup()：供调度循环每分钟调用的入口，内部节流为每 24h 真正执行一次。

清理范围（保守红线）：只动 `bundle_*` / `pptx_*` 前缀的目录——它们是
按需再生产物。引擎主产物（`标题_时间戳` 目录、任务 result 里登记的
word/pdf 路径）一律不碰，避免破坏已有任务的下载。
"""
from __future__ import annotations

import logging
import os
import shutil
import time

from app.settings import settings

logger = logging.getLogger(__name__)

# 可再生产物目录的前缀白名单（只清这两类，其余一律不碰）
_TEMP_EXPORT_PREFIXES = ("bundle_", "pptx_")
_MAX_AGE_DAYS = 7
_CLEANUP_INTERVAL_SEC = 24 * 3600

_last_cleanup_at: float | None = None


def _is_stale(path: str, cutoff: float) -> bool:
    try:
        return os.path.getmtime(path) < cutoff
    except OSError:
        return False


def cleanup_stale_exports(max_age_days: int = _MAX_AGE_DAYS) -> int:
    """清理 generated/ 下超龄的即时导出目录，返回删除的目录数。

    单个目录删除失败（文件被占用等）只记日志，不影响其余目录。
    """
    base = settings.generated_dir
    if not os.path.isdir(base):
        return 0
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    try:
        entries = os.listdir(base)
    except OSError:
        return 0
    for name in entries:
        if not name.startswith(_TEMP_EXPORT_PREFIXES):
            continue
        full = os.path.join(base, name)
        if not os.path.isdir(full) or not _is_stale(full, cutoff):
            continue
        try:
            shutil.rmtree(full, ignore_errors=True)
            removed += 1
            logger.info("[maintenance] 已清理超龄即时导出目录：%s", name)
        except OSError:
            logger.warning("[maintenance] 清理失败（跳过）：%s", name, exc_info=True)
    return removed


def maybe_cleanup() -> int:
    """调度循环入口：每 24h 真正执行一次，其余调用直接跳过。"""
    global _last_cleanup_at
    now = time.monotonic()
    if _last_cleanup_at is not None and now - _last_cleanup_at < _CLEANUP_INTERVAL_SEC:
        return 0
    _last_cleanup_at = now
    try:
        removed = cleanup_stale_exports()
    except Exception:  # noqa: BLE001 — 维护失败绝不影响主流程
        logger.exception("[maintenance] 即时导出清理循环异常")
        removed = 0
    # S2 feed_items 保留期清理（默认 90 天；开关关闭时跳过，零回归）
    if settings.feed_enabled:
        try:
            from app.db import SessionLocal
            from app.feed_store import purge_expired

            with SessionLocal() as db:
                purge_expired(db)
        except Exception:  # noqa: BLE001
            logger.exception("[maintenance] feed_items 保留期清理异常")
    return removed
