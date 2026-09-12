"""多平台采集接口（F1）。

- POST /api/collect/preview：按查询词跑 L1 渠道，返回去重后的候选条目（不入库）；
- POST /api/collect/save：把用户勾选的条目落成 Material（source_type='collect'），
  与既有素材同库，可被新建分析直接勾选，也让 F15 来源证据表天然带上采集来源。

合规边界：只采集公开可检索内容；L2 社交平台不在此实现（外部适配器 + 默认 OFF）。
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.connectors.base import CollectedItem, dedupe_items
from app.db import SessionLocal
from app.models import Material
from app.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_QUERY = 200
_MAX_ITEMS = 60


class CollectPreviewRequest(BaseModel):
    query: str
    kinds: list[str] = Field(default_factory=lambda: ["websearch", "govdoc"])
    rss: bool = False  # rss/hotlist 依赖环境配置；显式请求才尝试
    hotlist: bool = False


class CollectSaveRequest(BaseModel):
    items: list[dict]
    project_id: str | None = None
    tags: str | None = None


def _run_channel(kind: str, query: str) -> tuple[list[CollectedItem], str | None]:
    """单渠道执行；渠道内部异常兜底为降级说明（绝不拖垮整个预览）。"""
    try:
        if kind == "websearch":
            from app.connectors.websearch import collect_websearch

            return collect_websearch(query, max_results=12)
        if kind == "govdoc":
            from app.connectors.govdoc import collect_govdoc

            return collect_govdoc(query, max_results=8)
        if kind == "rss":
            from app.connectors.rss import collect_rss

            return collect_rss()
        if kind == "hotlist":
            from app.connectors.hotlist import collect_hotlist

            return collect_hotlist()
    except Exception as exc:  # noqa: BLE001
        logger.warning("采集渠道 %s 失败：%s", kind, exc)
        return [], f"{kind} 渠道异常：{exc}"
    return [], f"未知渠道：{kind}"


@router.post("/api/collect/preview")
def collect_preview(req: CollectPreviewRequest, current: dict = Depends(get_current_user)):
    """按渠道并行采集候选来源（只读，不入库）。"""
    query = (req.query or "").strip()[:_MAX_QUERY]
    if not query:
        return {"error": "query_required", "message": "请输入采集关键词。"}
    kinds = [k for k in req.kinds if k in ("websearch", "govdoc")]
    if req.rss:
        kinds.append("rss")
    if req.hotlist:
        kinds.append("hotlist")
    if not kinds:
        kinds = ["websearch", "govdoc"]

    items: list[CollectedItem] = []
    degraded: list[str] = []
    for kind in kinds:
        got, note = _run_channel(kind, query)
        items.extend(got)
        if note:
            degraded.append(f"{kind}：{note}")
    # 判重条目直接从预览中剔除（同链/同文只保留首条，前端不再展示重复行）
    items = [it for it in dedupe_items(items) if not it.duplicate_of][:_MAX_ITEMS]
    return {
        "query": query,
        "kinds": kinds,
        "items": [item.to_row() for item in items],
        "independent_sources": len({item.independence_group for item in items if not item.duplicate_of and item.independence_group}),
        "degraded": degraded or None,
    }


def _save_row_as_material(db, item: dict, owner_id: str, project_id: str | None, tags: str | None) -> Material:
    text = str(item.get("content_text") or "").strip()
    snippet = str(item.get("snippet") or "").strip()
    body = text or (f"{snippet}\n\n（来源：{item.get('url', '')}）" if snippet else f"（来源：{item.get('url', '')}）")
    title = str(item.get("title") or "未命名采集")[:200]
    platform = str(item.get("platform") or item.get("kind") or "collect")
    return Material(
        id=uuid.uuid4().hex,
        project_id=project_id or None,
        owner_id=owner_id,
        title=title,
        content_text=body[:200_000],
        source_type="collect",
        source=str(item.get("url") or "")[:500] or None,
        tags=tags,
        char_count=len(body),
        warnings=[f"collect_channel:{platform}"],
    )


@router.post("/api/collect/save")
def collect_save(req: CollectSaveRequest, current: dict = Depends(get_current_user)):
    """把勾选条目保存为素材。按 URL 去重：与库内既有素材（含历史采集）同链即跳过。"""
    if not req.items:
        return {"error": "items_required", "message": "没有勾选任何条目。"}
    saved: list[dict] = []
    skipped: list[dict] = []
    with SessionLocal() as db:
        existing_urls = {
            (row.source or "").strip().rstrip("/")
            for row in db.query(Material.source).all()
            if row.source
        }
        seen_in_batch: set[str] = set()
        for item in req.items[:_MAX_ITEMS]:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url.startswith("http"):
                skipped.append({"title": str(item.get("title") or ""), "reason": "missing_url"})
                continue
            key = url.rstrip("/")
            if key in existing_urls or key in seen_in_batch:
                skipped.append({"title": str(item.get("title") or ""), "reason": "duplicate"})
                continue
            seen_in_batch.add(key)
            m = _save_row_as_material(db, item, current["id"], req.project_id, req.tags)
            db.add(m)
            saved.append({"id": m.id, "title": m.title, "url": m.source})
        if saved:
            db.commit()
    return {
        "saved": saved,
        "saved_count": len(saved),
        "skipped": skipped,
        "skipped_count": len(skipped),
        "public_mode_note": None if not settings.public_mode else "素材已按账号隔离保存",
    }
