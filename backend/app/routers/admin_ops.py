"""管理员运营后台端点（独立于普通用户工作台）。

定位：面向未来的对外公测运营，当前以「自用/内测够用」为度。
与 routers/auth.py 里的 admin_router 互补——auth.py 只管「用户(列表/封禁)」，
本文件补齐「内容运营(项目/报告/任务治理) + 运营看板聚合 + 系统状态」。

关键设计：
- 所有端点统一 `Depends(require_admin)` 鉴权，非 admin 一律 403（与普通用户隔离）。
- **跨用户豁免**：admin 端点直接查库，不经过 task_owned/project_owned（那些是普通
  用户 owner 隔离用的）。但删除仍走「先归档软删，硬删除需显式 confirm」的成熟模式，
  复用 projects.py 的文件清理级联，避免重复逻辑。
- 时间口径：与 auth.py list_users 一致，凡与 SQLite 读回的 naive(UTC) 时间比较，
  一律把 aware 压成 naive 再比，避免时区炸。
- 未来扩展点（本次不做，留 TODO）：细分配置 role、用量配额、支付/发票、封禁理由审计。
"""
import logging
import os
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.audit import client_ip, record_audit
from app.auth import RESET_TTL_MINUTES, build_reset_url, issue_reset_token, require_admin
from app.db import SessionLocal
from app.models import AuditLog, Material, Project, ReportVersion, Task, User, _now
from app.routers.projects import _cleanup_task_files

logger = logging.getLogger(__name__)

admin_router = APIRouter(prefix="/api/admin")


def _naive(dt):
    """把可能带 tzinfo 的 datetime 统一压成 naive UTC；None 原样返回。"""
    if dt is None:
        return None
    from datetime import timezone
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


# ---------------------------------------------------------------------------
# 用户运营：单用户明细（辅助识别刷子号 / 僵尸号 / 重点账号）
# ---------------------------------------------------------------------------
class _UserStats:
    """一个账号在平台上的内容足迹。"""


@admin_router.get("/users/{uid}")
def user_detail(uid: str, _admin: dict = Depends(require_admin)):
    with SessionLocal() as db:
        u = db.get(User, uid)
        if u is None:
            raise HTTPException(status_code=404, detail={"status": "not_found", "message": "用户不存在"})
        project_count = db.query(Project).filter(Project.owner_id == uid).count()
        task_count = db.query(Task).filter(Task.owner_id == uid).count()
        done_count = db.query(Task).filter(Task.owner_id == uid, Task.status == "done").count()
        error_count = db.query(Task).filter(Task.owner_id == uid, Task.status == "error").count()
        material_count = db.query(Material).filter(Material.owner_id == uid).count()
        recent_tasks = (
            db.query(Task)
            .filter(Task.owner_id == uid)
            .order_by(Task.created_at.desc())
            .limit(10)
            .all()
        )
        return {
            "status": "ok",
            "user": {
                "id": u.id,
                "email": u.email,
                "display_name": u.display_name,
                "role": u.role or "user",
                "is_banned": u.is_banned or 0,
                "email_verified": bool(u.email_verified) if u.email_verified is not None else False,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "last_seen_at": u.last_seen_at.isoformat() if u.last_seen_at else None,
            },
            "counts": {
                "projects": project_count,
                "tasks": task_count,
                "tasks_done": done_count,
                "tasks_error": error_count,
                "materials": material_count,
            },
            "recent_tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "status": t.status,
                    "analysis_type": t.analysis_type,
                    "mode": t.mode,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in recent_tasks
            ],
        }


# ---------------------------------------------------------------------------
# 项目运营：跨用户查看 / 归档 / 硬删除（内容治理）
# ---------------------------------------------------------------------------
def _project_admin_dict(p: Project, db) -> dict:
    owner = db.get(User, p.owner_id) if p.owner_id else None
    task_count = db.query(Task).filter(Task.project_id == p.id).count()
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "status": p.status,
        "owner_id": p.owner_id,
        "owner_email": owner.email if owner else None,
        "owner_display": owner.display_name if owner else None,
        "is_archived": p.is_archived or 0,
        "archived_at": p.archived_at.isoformat() if p.archived_at else None,
        "task_count": task_count,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@admin_router.get("/projects")
def admin_projects(
    include_archived: bool = False,
    limit: int = 200,
    _admin: dict = Depends(require_admin),
):
    """全部项目（跨用户，含归属）。内容治理用。"""
    with SessionLocal() as db:
        q = db.query(Project).order_by(Project.updated_at.desc())
        if not include_archived:
            q = q.filter(Project.is_archived == 0)
        projects = q.limit(min(limit, 1000)).all()
        return {
            "status": "ok",
            "projects": [_project_admin_dict(p, db) for p in projects],
            "total": len(projects),
        }


class ArchiveIn(BaseModel):
    archived: bool = True


@admin_router.post("/projects/{pid}/archive")
def admin_archive_project(
    pid: str, body: ArchiveIn, request: Request, admin: dict = Depends(require_admin)
):
    """归档/取消归档任意用户的项目（软删，可恢复）。"""
    with SessionLocal() as db:
        p = db.get(Project, pid)
        if p is None:
            raise HTTPException(status_code=404, detail={"status": "not_found", "message": "项目不存在"})
        p.is_archived = 1 if body.archived else 0
        p.archived_at = _now() if body.archived else None
        db.commit()
        record_audit(
            admin,
            "project.archive" if body.archived else "project.unarchive",
            target_type="project",
            target_id=pid,
            detail={"name": p.name, "owner_id": p.owner_id},
            ip=client_ip(request),
        )
        return {"status": "ok", "id": pid, "is_archived": p.is_archived}


class ConfirmBody(BaseModel):
    confirm: bool = False


@admin_router.post("/projects/{pid}/delete")
def admin_delete_project(
    pid: str, body: ConfirmBody, request: Request, admin: dict = Depends(require_admin)
):
    """硬删除任意用户的项目。需 confirm=true（默认拒绝）。

    级联：删关联任务(含其报告版本与产物文件)、解绑材料(project_id 置空，保留内容)。
    逻辑与 projects.py 用户侧硬删除一致，但不受 owner 归属过滤。
    """
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail={"status": "confirm_required", "message": "危险操作：删除项目将连带删除其全部报告与产物文件，需显式 confirm=true"},
        )
    with SessionLocal() as db:
        p = db.get(Project, pid)
        if p is None:
            raise HTTPException(status_code=404, detail={"status": "not_found", "message": "项目不存在"})
        tasks = db.query(Task).filter(Task.project_id == pid).all()
        files_removed = 0
        versions_removed = 0
        for t in tasks:
            files_removed += _cleanup_task_files(t)
            versions_removed += db.query(ReportVersion).filter(ReportVersion.task_id == t.id).delete()
        task_count = len(tasks)
        for t in tasks:
            db.delete(t)
        # 材料保留内容，仅解绑
        for m in db.query(Material).filter(Material.project_id == pid).all():
            m.project_id = None
        pname = p.name
        owner_id = p.owner_id
        db.delete(p)
        db.commit()
        record_audit(
            admin,
            "project.delete",
            target_type="project",
            target_id=pid,
            detail={
                "name": pname,
                "owner_id": owner_id,
                "tasks_deleted": task_count,
                "files_removed": files_removed,
            },
            ip=client_ip(request),
        )
        return {
            "status": "ok",
            "id": pid,
            "tasks_deleted": task_count,
            "report_versions_deleted": versions_removed,
            "files_removed": files_removed,
        }


# ---------------------------------------------------------------------------
# 任务(报告)运营：跨用户查看 / 删除
# ---------------------------------------------------------------------------
def _task_admin_dict(t: Task, db) -> dict:
    owner = db.get(User, t.owner_id) if t.owner_id else None
    version_count = db.query(ReportVersion).filter(ReportVersion.task_id == t.id).count()
    return {
        "id": t.id,
        "title": t.title,
        "status": t.status,
        "phase": t.phase,
        "progress_pct": t.progress_pct,
        "analysis_type": t.analysis_type,
        "mode": t.mode,
        "owner_id": t.owner_id,
        "owner_email": owner.email if owner else None,
        "project_id": t.project_id,
        "version_count": version_count,
        "has_error": bool(t.error),
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


@admin_router.get("/tasks")
def admin_tasks(
    status: str | None = None,
    limit: int = 200,
    _admin: dict = Depends(require_admin),
):
    """全部任务（跨用户）。按状态过滤，内容治理 + 失败概览用。"""
    with SessionLocal() as db:
        q = db.query(Task).order_by(Task.created_at.desc())
        if status and status in {"queued", "generating", "done", "error"}:
            q = q.filter(Task.status == status)
        tasks = q.limit(min(limit, 1000)).all()
        return {
            "status": "ok",
            "tasks": [_task_admin_dict(t, db) for t in tasks],
            "total": len(tasks),
        }


@admin_router.post("/tasks/{task_id}/delete")
def admin_delete_task(
    task_id: str, body: ConfirmBody, request: Request, admin: dict = Depends(require_admin)
):
    """删除任意用户的一篇报告(Task)。需 confirm=true。

    级联：清理产物文件、显式删除 ReportVersion、若归属自动项目且为唯一报告则删孤儿项目。
    逻辑与 reports.py delete_report 一致，但不受 owner 过滤。
    """
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail={"status": "confirm_required", "message": "危险操作：删除任务将连带删除其报告版本与产物文件，需显式 confirm=true"},
        )
    with SessionLocal() as db:
        t = db.get(Task, task_id)
        if t is None:
            raise HTTPException(status_code=404, detail={"status": "not_found", "message": "任务不存在"})

        # 1) 清理产物文件（复用 projects.py 的成熟级联）
        files_removed = _cleanup_task_files(t)

        # 2) 清理孤立的自动项目（仿 reports.py delete_report）
        pid = t.project_id
        if pid and pid.startswith("auto_"):
            remaining = db.query(Task).filter(Task.project_id == pid, Task.id != task_id).count()
            if remaining == 0:
                proj = db.get(Project, pid)
                if proj:
                    db.delete(proj)

        # 3) 删除版本（显式，不依赖 FK cascade）
        versions_removed = db.query(ReportVersion).filter(ReportVersion.task_id == task_id).delete()
        # 4) 删除任务
        ttitle = t.title
        towner = t.owner_id
        db.delete(t)
        db.commit()
        record_audit(
            admin,
            "task.delete",
            target_type="task",
            target_id=task_id,
            detail={
                "title": ttitle,
                "owner_id": towner,
                "report_versions_deleted": versions_removed,
                "files_removed": files_removed,
            },
            ip=client_ip(request),
        )
        return {
            "status": "ok",
            "id": task_id,
            "report_versions_deleted": versions_removed,
            "files_removed": files_removed,
        }


# ---------------------------------------------------------------------------
# 运营看板：一次性聚合（数字卡 + 趋势 + 产出/成功率/用量）
# ---------------------------------------------------------------------------
@admin_router.get("/stats/overview")
def stats_overview(_admin: dict = Depends(require_admin)):
    """运营看板聚合数据：注册/活跃趋势、内容产出、任务质量、用量。

    趋势用「近 14 日按天分组」。时间口径统一压 naive(UTC)。
    """
    with SessionLocal() as db:
        now = _naive(_now())
        week_ago = now - timedelta(days=7)

        # —— 用户规模 ——
        users = db.query(User).all()
        total_users = len(users)

        def _recent_users(col):
            return sum(1 for u in users if _naive(getattr(u, col)) and _naive(getattr(u, col)) >= week_ago)

        # —— 内容产出 ——
        total_projects = db.query(Project).count()
        active_projects = db.query(Project).filter(Project.is_archived == 0).count()
        total_tasks = db.query(Task).count()
        total_done = db.query(Task).filter(Task.status == "done").count()
        total_error = db.query(Task).filter(Task.status == "error").count()
        total_versions = db.query(ReportVersion).count()
        total_materials = db.query(Material).count()

        # —— 近 14 日按天：注册 / 活跃 / 报告产出 ——
        day_buckets = []
        for i in range(13, -1, -1):
            day = (now - timedelta(days=i)).date()
            day_buckets.append(
                {
                    "date": day.isoformat(),
                    "registered": 0,
                    "active": 0,
                    "reports": 0,
                }
            )
        bucket_by_date = {b["date"]: b for b in day_buckets}

        for u in users:
            ca = _naive(u.created_at)
            if ca and ca.date() in bucket_by_date:
                bucket_by_date[ca.date().isoformat()]["registered"] += 1
            la = _naive(u.last_seen_at)
            if la and la.date() in bucket_by_date:
                bucket_by_date[la.date().isoformat()]["active"] += 1

        for t in db.query(Task).all():
            cta = _naive(t.created_at)
            if cta and cta.date() in bucket_by_date and t.status == "done":
                bucket_by_date[cta.date().isoformat()]["reports"] += 1

        # —— 成功率 ——
        success_rate = round(total_done / total_tasks * 100, 1) if total_tasks else 0.0

        return {
            "status": "ok",
            "users": {
                "total": total_users,
                "admins": sum(1 for u in users if u.role == "admin"),
                "banned": sum(1 for u in users if u.is_banned),
                "verified": sum(1 for u in users if u.email_verified),
                "new_7d": _recent_users("created_at"),
                "active_7d": _recent_users("last_seen_at"),
            },
            "content": {
                "projects": total_projects,
                "active_projects": active_projects,
                "tasks": total_tasks,
                "reports_done": total_done,
                "reports_error": total_error,
                "report_versions": total_versions,
                "materials": total_materials,
            },
            "quality": {
                "task_success_rate": success_rate,
                "task_error_count": total_error,
                "queued_or_generating": db.query(Task)
                .filter(Task.status.in_(["queued", "generating"]))
                .count(),
            },
            "trend_14d": day_buckets,
        }


# ---------------------------------------------------------------------------
# 系统运行状态（平台级，区别于 monitoring.py 的 per-project 研究监控）
# ---------------------------------------------------------------------------
@admin_router.get("/system")
def admin_system(_admin: dict = Depends(require_admin)):
    """系统运行状态：健康、任务积压、存储、运行模式。"""
    from app.settings import settings

    db_path_actual = ""
    try:
        from sqlalchemy import text as sa_text
        with SessionLocal() as db:
            db_size = 0
            db_path_actual = str(db.bind.url.database) if db.bind.url.database else ""
            if db_path_actual and os.path.exists(db_path_actual):
                db_size = os.path.getsize(db_path_actual)
            # 队列积压
            queued = db.query(Task).filter(Task.status.in_(["queued", "generating"])).count()
            error = db.query(Task).filter(Task.status == "error").count()
            total = db.query(Task).count()
            db.execute(sa_text("SELECT 1"))  # 健康探测
    except Exception as e:  # pragma: no cover - 健康探测失败兜底
        return {"status": "error", "health": "down", "detail": str(e)}

    return {
        "status": "ok",
        "health": "up",
        "public_mode": bool(settings.public_mode),
        "smtp_enabled": bool(settings.smtp_enabled),
        "queue": {"queued_or_generating": queued, "error": error, "total": total},
        "storage": {
            "sqlite_path": db_path_actual,
            "sqlite_bytes": db_size,
            "sqlite_mb": round(db_size / (1024 * 1024), 2) if db_size else 0,
        },
    }


# ---------------------------------------------------------------------------
# 用户治理：角色变更 / 管理员代发重置链接
# ---------------------------------------------------------------------------
class RoleIn(BaseModel):
    role: str


@admin_router.post("/users/{uid}/role")
def admin_set_role(
    uid: str, body: RoleIn, request: Request, admin: dict = Depends(require_admin)
):
    """提升 / 降级用户角色。守卫：不能取消自己；系统必须保留至少一名管理员。"""
    role = (body.role or "").strip().lower()
    if role not in {"user", "admin"}:
        raise HTTPException(
            status_code=400, detail={"status": "invalid", "message": "角色只能是 user 或 admin"}
        )
    with SessionLocal() as db:
        user = db.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail={"status": "not_found", "message": "用户不存在"})
        if uid == admin.get("id") and role != "admin":
            raise HTTPException(
                status_code=400,
                detail={"status": "invalid", "message": "不能取消自己的管理员权限（可让另一位管理员操作）"},
            )
        if (user.role or "user") == "admin" and role != "admin":
            others = db.query(User).filter(User.role == "admin", User.id != uid).count()
            if others == 0:
                raise HTTPException(
                    status_code=400,
                    detail={"status": "invalid", "message": "系统必须保留至少一名管理员"},
                )
        prev = user.role or "user"
        if prev == role:
            return {"status": "ok", "id": uid, "role": role, "changed": False}
        user.role = role
        db.commit()
        record_audit(
            admin,
            "user.role_change",
            target_type="user",
            target_id=uid,
            detail={"email": user.email, "from": prev, "to": role},
            ip=client_ip(request),
        )
        return {"status": "ok", "id": uid, "role": role, "changed": True}


@admin_router.post("/users/{uid}/reset-password")
def admin_reset_password_link(uid: str, request: Request, admin: dict = Depends(require_admin)):
    """管理员为指定用户**代发**一次性重置链接（明文链接仅此一次返回）。

    用途：用户邮箱收不到信时，管理员人工把链接转达给本人。
    """
    with SessionLocal() as db:
        user = db.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail={"status": "not_found", "message": "用户不存在"})
        raw = issue_reset_token(user, db)
        url = build_reset_url(raw)
        record_audit(
            admin,
            "user.reset_password_link",
            target_type="user",
            target_id=uid,
            detail={"email": user.email},
            ip=client_ip(request),
        )
    return {
        "status": "ok",
        "id": uid,
        "reset_url": url,
        "expires_minutes": RESET_TTL_MINUTES,
    }


# ---------------------------------------------------------------------------
# 审计日志查询（运营留痕）
# ---------------------------------------------------------------------------
@admin_router.get("/audit")
def admin_audit(
    action: str | None = None,
    actor_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    _admin: dict = Depends(require_admin),
):
    """审计日志列表（倒序）。可按 action / actor_id 过滤。"""
    with SessionLocal() as db:
        q = db.query(AuditLog)
        if action:
            q = q.filter(AuditLog.action == action)
        if actor_id:
            q = q.filter(AuditLog.actor_id == actor_id)
        total = q.count()
        rows = (
            q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset(max(offset, 0))
            .limit(min(max(limit, 1), 500))
            .all()
        )
        return {
            "status": "ok",
            "total": total,
            "logs": [
                {
                    "id": r.id,
                    "actor_id": r.actor_id,
                    "actor_email": r.actor_email,
                    "action": r.action,
                    "target_type": r.target_type,
                    "target_id": r.target_id,
                    "detail": r.detail,
                    "ip": r.ip,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ],
        }
