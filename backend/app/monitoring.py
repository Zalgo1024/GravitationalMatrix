"""Local project monitoring built on the existing database task queue."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta

from app.db import SessionLocal
from app.models import Project, ResearchMonitor, Task, _now
from app.research_changes import compare_research_ledgers

logger = logging.getLogger(__name__)
_scheduler_task: asyncio.Task | None = None


class MonitorBusyError(RuntimeError):
    pass


def monitor_dict(monitor: ResearchMonitor | None, project_id: str) -> dict:
    if monitor is None:
        return {
            "project_id": project_id,
            "configured": False,
            "enabled": False,
            "interval_hours": 24,
            "seed_task_id": None,
            "last_run_at": None,
            "next_run_at": None,
            "last_task_id": None,
            "last_success_task_id": None,
            "latest_change": None,
            "last_error": None,
        }
    return {
        "id": monitor.id,
        "project_id": monitor.project_id,
        "configured": True,
        "enabled": bool(monitor.enabled),
        "interval_hours": monitor.interval_hours or 24,
        "seed_task_id": monitor.seed_task_id,
        "last_run_at": monitor.last_run_at.isoformat() if monitor.last_run_at else None,
        "next_run_at": monitor.next_run_at.isoformat() if monitor.next_run_at else None,
        "last_task_id": monitor.last_task_id,
        "last_success_task_id": monitor.last_success_task_id,
        "latest_change": monitor.latest_change,
        "last_error": monitor.last_error,
    }


def configure_monitor(
    project_id: str,
    *,
    enabled: bool,
    interval_hours: int,
    seed_task_id: str | None = None,
) -> dict | None:
    interval = max(1, min(24 * 30, int(interval_hours or 24)))
    now = _now()
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        if project is None:
            return None
        seed = db.get(Task, seed_task_id) if seed_task_id else None
        if seed is None:
            seed = (
                db.query(Task)
                .filter(Task.project_id == project_id, Task.status == "done")
                .order_by(Task.created_at.desc())
                .first()
            )
        if seed is None or seed.project_id != project_id:
            raise ValueError("项目没有可用于持续追踪的已完成分析任务")
        monitor = db.query(ResearchMonitor).filter(ResearchMonitor.project_id == project_id).first()
        if monitor is None:
            monitor = ResearchMonitor(id=uuid.uuid4().hex, project_id=project_id, seed_task_id=seed.id)
            db.add(monitor)
        monitor.seed_task_id = seed.id
        if not monitor.last_success_task_id:
            monitor.last_success_task_id = seed.id
        monitor.enabled = bool(enabled)
        monitor.interval_hours = interval
        monitor.next_run_at = now + timedelta(hours=interval) if enabled else None
        monitor.updated_at = now
        db.commit()
        db.refresh(monitor)
        return monitor_dict(monitor, project_id)


def _create_monitor_task(db, monitor: ResearchMonitor, now: datetime) -> str:
    if monitor.last_task_id:
        active = db.get(Task, monitor.last_task_id)
        if active is not None and active.status in {"queued", "generating"}:
            raise MonitorBusyError("当前追踪任务仍在执行")
    seed = db.get(Task, monitor.seed_task_id)
    if seed is None:
        raise ValueError("持续追踪的种子任务不存在")
    task_id = uuid.uuid4().hex
    task = Task(
        id=task_id,
        title=seed.title,
        input_text=seed.input_text,
        analysis_type=seed.analysis_type,
        project_id=monitor.project_id,
        mode=seed.mode,
        input_mode=seed.input_mode,
        requested_engine=seed.requested_engine,
        structured=seed.structured,
        llm_config=seed.llm_config,
        owner_id=seed.owner_id,
        status="queued",
        material_ids=seed.material_ids,
        search_enabled=True,
        web=True,
        source_urls=None,
        monitor_id=monitor.id,
    )
    db.add(task)
    monitor.last_task_id = task_id
    monitor.last_run_at = now
    monitor.next_run_at = now + timedelta(hours=monitor.interval_hours or 24)
    monitor.last_error = None
    monitor.updated_at = now
    db.commit()
    return task_id


def trigger_monitor(project_id: str, *, now: datetime | None = None) -> str | None:
    with SessionLocal() as db:
        monitor = db.query(ResearchMonitor).filter(ResearchMonitor.project_id == project_id).first()
        if monitor is None:
            return None
        return _create_monitor_task(db, monitor, now or _now())


def run_due_monitors(*, now: datetime | None = None) -> list[str]:
    current = now or _now()
    with SessionLocal() as db:
        due_ids = [
            monitor.id
            for monitor in db.query(ResearchMonitor)
            .join(Project, Project.id == ResearchMonitor.project_id)
            .filter(
                ResearchMonitor.enabled.is_(True),
                ResearchMonitor.next_run_at.is_not(None),
                ResearchMonitor.next_run_at <= current,
                Project.is_archived == 0,
            )
            .all()
        ]
    created = []
    for monitor_id in due_ids:
        try:
            with SessionLocal() as db:
                monitor = db.get(ResearchMonitor, monitor_id)
                if monitor is not None:
                    created.append(_create_monitor_task(db, monitor, current))
        except MonitorBusyError:
            continue
        except Exception as exc:  # noqa: BLE001
            logger.exception("持续追踪调度失败: %s", monitor_id)
            with SessionLocal() as db:
                monitor = db.get(ResearchMonitor, monitor_id)
                if monitor is not None:
                    monitor.last_error = str(exc)[:1000]
                    db.commit()
    return created


def record_monitor_completion(task_id: str) -> None:
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if task is None or not task.monitor_id:
            return
        monitor = db.get(ResearchMonitor, task.monitor_id)
        if monitor is None:
            return
        if task.status == "error":
            monitor.last_error = task.error or "追踪分析失败"
            monitor.updated_at = _now()
            db.commit()
            return
        if task.status != "done":
            return
        previous = db.get(Task, monitor.last_success_task_id) if monitor.last_success_task_id else None
        before = (previous.result or {}).get("research") if previous else None
        after = (task.result or {}).get("research")
        monitor.latest_change = compare_research_ledgers(before, after)
        monitor.last_success_task_id = task.id
        monitor.last_error = None
        monitor.updated_at = _now()
        db.commit()


async def _scheduler() -> None:
    from app.maintenance import maybe_cleanup

    while True:
        await asyncio.sleep(60)
        # 即时导出物磁盘回收（内部 24h 节流，失败不影响主流程）
        try:
            await asyncio.to_thread(maybe_cleanup)
        except Exception:  # noqa: BLE001
            logger.exception("即时导出清理调度异常")
        try:
            await asyncio.to_thread(run_due_monitors)
        except Exception:  # noqa: BLE001
            logger.exception("持续追踪调度循环异常")


def start_monitor_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(_scheduler())
