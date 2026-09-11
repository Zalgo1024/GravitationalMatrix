"""项目管理接口：创建 / 编辑 / 归档 / 恢复 / 删除，及项目页聚合详情。"""
import logging
import os
import shutil
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth import get_current_user, project_owned
from app.db import SessionLocal
from app.models import Material, Project, ReportVersion, Task, _now
from app.routers.materials import _material_meta
from app.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter()


def _project_dict(r: Project) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "description": r.description,
        "status": r.status,
        "subjects": r.subjects,
        "interests": r.interests,
        "chapters": r.chapters,
        "progress": r.progress,
        "owner_name": r.owner_name,
        "owner_id": r.owner_id,
        "is_archived": r.is_archived,
        "archived_at": r.archived_at.isoformat() if r.archived_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


class ProjectCreate(BaseModel):
    id: str | None = None  # 可选自定义 id；省略则自动生成
    name: str
    description: str | None = None
    status: str = "进行中"
    subjects: str = "0"
    interests: str = "0"
    chapters: str = "0"
    progress: str = "0"
    owner_name: str | None = None
    owner_id: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    subjects: str | None = None
    interests: str | None = None
    chapters: str | None = None
    progress: str | None = None
    owner_name: str | None = None
    owner_id: str | None = None


@router.post("/api/projects")
def create_project(req: ProjectCreate, current: dict = Depends(get_current_user)):
    pid = (req.id or uuid.uuid4().hex)[:64]
    with SessionLocal() as db:
        if db.get(Project, pid):
            return JSONResponse({"error": "project_id_exists", "id": pid}, status_code=409)
        p = Project(
            id=pid,
            name=req.name,
            description=req.description,
            status=req.status,
            subjects=req.subjects,
            interests=req.interests,
            chapters=req.chapters,
            progress=req.progress,
            # 默认归属人取自可配置项（settings.default_owner_*），避免硬编码；
            # 公共模式下归属强制为当前登录用户（防止伪造 owner_id 越权归属）
            owner_name=req.owner_name or settings.default_owner_name,
            owner_id=(
                current["id"] if settings.public_mode
                else (req.owner_id or settings.default_owner_id)
            ),
            is_archived=0,
        )
        db.add(p)
        db.commit()
        return _project_dict(p)


@router.put("/api/projects/{pid}")
def update_project(pid: str, req: ProjectUpdate, current: dict = Depends(get_current_user)):
    with SessionLocal() as db:
        p = project_owned(db, pid, current)
        if not p:
            return {"status": "not_found"}
        for f in (
            "name", "description", "status", "subjects", "interests",
            "chapters", "progress", "owner_name", "owner_id",
        ):
            v = getattr(req, f)
            if v is not None:
                setattr(p, f, v)
        db.commit()
        return _project_dict(p)


@router.patch("/api/projects/{pid}/archive")
def archive_project(pid: str, current: dict = Depends(get_current_user)):
    """归档（软删除）：项目标记 is_archived，关联任务与材料保留，可随时恢复。"""
    with SessionLocal() as db:
        p = project_owned(db, pid, current)
        if not p:
            return {"status": "not_found"}
        p.is_archived = 1
        p.archived_at = _now()
        db.commit()
        return _project_dict(p)


@router.patch("/api/projects/{pid}/restore")
def restore_project(pid: str, current: dict = Depends(get_current_user)):
    """从归档恢复为活跃项目。"""
    with SessionLocal() as db:
        p = project_owned(db, pid, current)
        if not p:
            return {"status": "not_found"}
        p.is_archived = 0
        p.archived_at = None
        db.commit()
        return _project_dict(p)


def _cleanup_task_files(task_row) -> int:
    """删除某任务生成的产物文件（docx/图），返回删除个数。

    仅删文件，不碰数据库行；材料纯文本不删。
    """
    removed = 0
    res = task_row.result or {}
    candidates = []
    if res.get("word") and os.path.exists(res["word"]):
        candidates.append(res["word"])
    if res.get("pdf") and os.path.exists(res["pdf"]):
        candidates.append(res["pdf"])
    for d in res.get("diagrams") or []:
        if not isinstance(d, dict):
            continue
        for k in ("png", "html"):
            if d.get(k) and os.path.exists(d[k]):
                candidates.append(d[k])
    for c in candidates:
        try:
            os.remove(c)
            removed += 1
        except OSError:
            logger.warning("删除产物文件失败（忽略）：%s", c)
    # 生成的独立子目录（slug=task_id）若为空则一并移除
    folder = res.get("folder")
    if folder and os.path.isdir(folder):
        try:
            shutil.rmtree(folder, ignore_errors=True)
            removed += 1
        except OSError:
            logger.warning("删除产物目录失败（忽略）：%s", folder)
    return removed


class BulkDeleteRequest(BaseModel):
    ids: list[str]
    confirm: bool = False


def _hard_delete_project(db, pid, current: dict) -> dict | None:
    """硬删除单个项目的级联逻辑：删任务+报告版本+产物文件、解绑材料；**不提交**，由调用方统一提交。

    返回受影响统计；项目不存在（或不属于当前用户）返回 None。单删与批量删共用，避免逻辑分叉。
    """
    p = project_owned(db, pid, current)
    if not p:
        return None
    tasks = db.query(Task).filter(Task.project_id == pid).all()
    files_removed = 0
    versions_removed = 0
    for t in tasks:
        files_removed += _cleanup_task_files(t)
        versions_removed += (
            db.query(ReportVersion).filter(ReportVersion.task_id == t.id).delete()
        )
    task_count = len(tasks)
    for t in tasks:
        db.delete(t)
    # 材料保留内容，仅解绑
    materials = db.query(Material).filter(Material.project_id == pid).all()
    for m in materials:
        m.project_id = None
    material_count = len(materials)
    db.delete(p)
    return {
        "tasks_deleted": task_count,
        "report_versions_deleted": versions_removed,
        "files_removed": files_removed,
        "materials_unlinked": material_count,
    }


@router.delete("/api/projects/{pid}")
def delete_project(pid: str, confirm: bool = False, current: dict = Depends(get_current_user)):
    """硬删除单个项目，需 confirm=true 显式确认（默认拒绝，避免误删任务）。

    - 关联任务（含其报告版本，级联）一并删除，并清理其生成文件；
    - 关联材料保留（project_id 置空），仅解除与项目的绑定，不丢内容；
    - 返回受影响统计；归档项目同样适用本接口。
    """
    if not confirm:
        return JSONResponse(
            {
                "error": "confirm_required",
                "message": "硬删除将一并删除关联任务并清理文件，请带 ?confirm=true 再次调用。",
            },
            status_code=409,
        )
    with SessionLocal() as db:
        stats = _hard_delete_project(db, pid, current)
        if stats is None:
            return {"status": "not_found"}
        db.commit()
        return {"ok": True, "project_id": pid, **stats}


@router.delete("/api/projects")
def delete_projects(req: BulkDeleteRequest, current: dict = Depends(get_current_user)):
    """批量硬删除多个项目：ids 数组 + confirm=true。

    - 单次请求内统一提交（DB 层原子）；文件清理失败仅告警不阻断；
    - 不存在的 id 计入 failed(not_found)，删除异常计入 failed(delete_error)；
    - 返回 deleted/failed 明细与 deleted_count，便于前端核对。
    """
    if not req.confirm:
        return JSONResponse(
            {
                "error": "confirm_required",
                "message": "批量硬删除将一并删除关联任务并清理文件，请带 confirm=true 再次调用。",
            },
            status_code=409,
        )
    if not req.ids:
        return JSONResponse(
            {"error": "no_ids", "message": "未提供任何项目 id"},
            status_code=400,
        )
    deleted: list[dict] = []
    failed: list[dict] = []
    with SessionLocal() as db:
        for pid in req.ids:
            try:
                stats = _hard_delete_project(db, pid, current)
                if stats is None:
                    failed.append({"id": pid, "reason": "not_found"})
                else:
                    deleted.append({"id": pid, **stats})
            except Exception:
                logger.exception("批量删除项目失败: %s", pid)
                failed.append({"id": pid, "reason": "delete_error"})
        db.commit()
    return {"ok": True, "deleted": deleted, "failed": failed, "deleted_count": len(deleted)}


@router.get("/api/projects")
def list_projects(include_archived: bool = False, current: dict = Depends(get_current_user)):
    """项目列表。默认只返回活跃项目；include_archived=true 含已归档。"""
    with SessionLocal() as db:
        q = db.query(Project)
        if settings.public_mode:
            q = q.filter(Project.owner_id == current["id"])
        if not include_archived:
            q = q.filter(Project.is_archived == 0)
        return [_project_dict(r) for r in q.order_by(Project.updated_at.desc()).all()]


@router.get("/api/projects/{pid}")
def get_project(pid: str, current: dict = Depends(get_current_user)):
    with SessionLocal() as db:
        r = project_owned(db, pid, current)
        if not r:
            return {"status": "not_found"}
        return _project_dict(r)


# ============================ 项目页聚合：任务历史 + 报告版本 + 材料 ============================


@router.get("/api/projects/{pid}/detail")
def project_detail(pid: str, include_archived: bool = True, current: dict = Depends(get_current_user)):
    """项目页一站式数据：元信息 + 任务历史（含状态/错误/版本摘要）+ 报告版本 + 关联材料。

    - include_archived=true（默认）：任务历史含已归档任务；
      传 false 仅返回活跃任务。
    - 报告版本采用一次性 IN 批量查询（消除原 N+1 循环查询）。
    """
    with SessionLocal() as db:
        p = project_owned(db, pid, current)
        if not p:
            return {"status": "not_found"}
        q = db.query(Task).filter(Task.project_id == pid)
        if not include_archived:
            q = q.filter(Task.status != "archived")
        tasks = q.order_by(Task.created_at.desc()).all()

        # —— 批量加载本项目全部任务的报告版本（单次 IN 查询，消除 N+1）——
        task_ids = [t.id for t in tasks]
        versions_by_task: dict[str, list] = {}
        if task_ids:
            all_versions = (
                db.query(ReportVersion)
                .filter(ReportVersion.task_id.in_(task_ids))
                .order_by(ReportVersion.created_at.asc())
                .all()
            )
            for v in all_versions:
                versions_by_task.setdefault(v.task_id, []).append(v)

        task_history = []
        for r in tasks:
            versions = versions_by_task.get(r.id, [])
            revised = [v for v in versions if v.kind == "revised"]
            cur = revised[-1] if revised else (versions[0] if versions else None)
            task_history.append(
                {
                    "task_id": r.id,
                    "title": r.title,
                    "status": r.status,
                    "analysis_type": r.analysis_type,
                    "error": r.error,
                    "error_type": r.error_type,
                    "error_phase": r.error_phase,
                    "retry_of": r.retry_of,
                    "attempt_no": r.attempt_no,
                    "material_ids": r.material_ids or [],
                    # 阶段四：标注本次报告由哪个引擎生成、是否从 LLM 降级
                    "engine_used": (r.result or {}).get("engine_used") if r.result else r.mode,
                    "degraded_from_llm": bool((r.result or {}).get("degraded_from_llm")) if r.result else False,
                    "degrade_reason": (r.result or {}).get("degrade_reason") if r.result else None,
                    "prompt_version": r.prompt_version,
                    "llm_model": r.llm_model,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                    "version_count": len(versions),
                    "current_version_id": cur.id if cur else None,
                    "current_version_kind": cur.kind if cur else None,
                    "has_word": bool((r.result or {}).get("word")),
                    "pdf_available": bool((r.result or {}).get("pdf_available")),
                }
            )

        materials = (
            db.query(Material)
            .filter(Material.project_id == pid)
            .order_by(Material.created_at.desc())
            .all()
        )
        material_list = [_material_meta(m) for m in materials]

        return {
            "project": _project_dict(p),
            "task_count": len(task_history),
            "tasks": task_history,
            "materials": material_list,
        }
