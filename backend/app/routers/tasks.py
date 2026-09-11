"""任务列表接口：GET /api/tasks（T7）。

响应对齐前端 TaskDTO（frontend/lib/api.ts:295-302）：
{task_id, title, status: queued|generating|done|error, analysis_type, project_id, created_at}
支持 Query：project_id / status / limit（默认 50，created_at desc）。
"""
import logging

from fastapi import APIRouter, Depends, Query

from app.auth import get_current_user
from app.db import SessionLocal
from app.models import Task
from app.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter()

# 合法 status（与前端 TaskDTO 联合类型一致）
_VALID_STATUS = {"queued", "generating", "done", "error"}


@router.get("/api/tasks")
def list_tasks(
    project_id: str | None = Query(None, description="按项目过滤"),
    status: str | None = Query(None, description="按状态过滤 queued|generating|done|error"),
    limit: int = Query(50, ge=1, le=200, description="返回条数上限（默认 50）"),
    current: dict = Depends(get_current_user),
):
    """返回 tasks 表数据映射为 TaskDTO 数组（created_at desc）。"""
    with SessionLocal() as db:
        q = db.query(Task)
        if settings.public_mode:
            q = q.filter(Task.owner_id == current["id"])
        if project_id:
            q = q.filter(Task.project_id == project_id)
        if status:
            if status in _VALID_STATUS:
                q = q.filter(Task.status == status)
            else:
                # 非法 status 不静默：返回空列表（前端不会因此崩溃）
                return []
        rows = q.order_by(Task.created_at.desc()).limit(limit).all()
        # 直接携带 phase/progress/engine 字段，消除前端"逐任务 poll"的 N+1 请求
        return [
            {
                "task_id": t.id,
                "title": t.title,
                "status": t.status,
                "analysis_type": t.analysis_type,
                "project_id": t.project_id,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "phase": t.phase,
                "progress_pct": t.progress_pct,
                "engine_used": (t.result or {}).get("engine_used") if isinstance(t.result, dict) else None,
                "material_ids": t.material_ids,
                "error": t.error if t.status == "error" else None,
                "error_phase": t.error_phase if t.status == "error" else None,
                "quality": t.quality_result,
            }
            for t in rows
        ]
