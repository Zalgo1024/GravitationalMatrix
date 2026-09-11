"""报告版本接口：原始生成版 / 人工修订版 的读写、列表、AI 再改与回滚（T13）。

版本语义：
- version_no 从 1 起；original 恒为 v1（edited_by='ai'）；
- 手动保存 edited_by='human'；AI 再改 edited_by='ai'；
- is_current=1 表示当前版本（回滚即切换该标记），回滚后立即重渲产物到
  backend/generated/{task_id}_v{n}/，历史版本产物不删除。
"""
import logging
import os
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import get_current_user, task_owned
from app.db import SessionLocal
from app.generator import ReportGenerator
from app.models import Project, ReportVersion, Task
from app.report_version_service import (
    create_report_version,
    ensure_original_version,
    set_current_version,
)
from app.research_changes import compare_research_ledgers
from app.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter()


def _version_meta(v: ReportVersion, current_id: str | None) -> dict:
    return {
        "id": v.id,
        "version_no": v.version_no or 1,
        "kind": v.kind,
        "edited_by": v.edited_by or "ai",
        "summary": v.summary,
        "note": v.note,
        "editor": v.editor,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "is_current": v.id == current_id,
        "research_status": v.research_status or "unavailable",
    }


def _ensure_original_version(db, task: Task) -> ReportVersion:
    """首次访问时，把生成引擎产出的 Markdown 播种为 kind='original' 版本（v1），确保原始稿不丢。"""
    return ensure_original_version(db, task)


def _current_version(db, task_id: str) -> ReportVersion | None:
    """取当前版本（is_current=1；无标记时取最新一条）。"""
    v = (
        db.query(ReportVersion)
        .filter(ReportVersion.task_id == task_id, ReportVersion.is_current == 1)
        .order_by(ReportVersion.version_no.desc())
        .first()
    )
    if v:
        return v
    return (
        db.query(ReportVersion)
        .filter(ReportVersion.task_id == task_id)
        .order_by(ReportVersion.created_at.asc())
        .first()
    )


@router.get("/api/reports/{task_id}")
def get_report_versions(task_id: str, current: dict = Depends(get_current_user)):
    """报告版本列表。首次访问自动播种 original 版本。返回当前版本 + versions 数组。"""
    with SessionLocal() as db:
        t = task_owned(db, task_id, current)
        if not t:
            return {"status": "not_found"}
        _ensure_original_version(db, t)
        cur = _current_version(db, task_id)
        rows = (
            db.query(ReportVersion)
            .filter(ReportVersion.task_id == task_id)
            .order_by(ReportVersion.version_no.asc(), ReportVersion.created_at.asc())
            .all()
        )
        return {
            "task_id": task_id,
            "title": t.title,
            "current_version_id": cur.id if cur else None,
            "versions": [_version_meta(r, cur.id if cur else None) for r in rows],
        }


@router.get("/api/reports/{task_id}/research")
def get_report_research(task_id: str, version_id: str | None = None, current: dict = Depends(get_current_user)):
    """Return the evidence-to-judgment snapshot bound to one report version."""
    with SessionLocal() as db:
        task = task_owned(db, task_id, current)
        if not task:
            return {"status": "not_found"}
        _ensure_original_version(db, task)
        if version_id:
            version = (
                db.query(ReportVersion)
                .filter(ReportVersion.id == version_id, ReportVersion.task_id == task_id)
                .first()
            )
        else:
            version = _current_version(db, task_id)
        if version is None:
            return {"status": "not_found"}
        return {
            "task_id": task_id,
            "version_id": version.id,
            "version_no": version.version_no or 1,
            "research_status": version.research_status or "unavailable",
            "research": version.research_snapshot,
        }


@router.get("/api/reports/{task_id}/changes")
def get_report_changes(
    task_id: str,
    from_version_id: str | None = None,
    to_version_id: str | None = None,
    current: dict = Depends(get_current_user),
):
    """Compare two version-bound research snapshots without asking the LLM."""
    with SessionLocal() as db:
        task = task_owned(db, task_id, current)
        if not task:
            return {"status": "not_found"}
        _ensure_original_version(db, task)
        rows = (
            db.query(ReportVersion)
            .filter(ReportVersion.task_id == task_id)
            .order_by(ReportVersion.version_no.asc(), ReportVersion.created_at.asc())
            .all()
        )
        if not rows:
            return {"status": "not_found"}
        by_id = {row.id: row for row in rows}
        target = by_id.get(to_version_id) if to_version_id else _current_version(db, task_id)
        if target is None:
            return {"status": "not_found"}
        if from_version_id:
            source = by_id.get(from_version_id)
        else:
            earlier = [row for row in rows if (row.version_no or 1) < (target.version_no or 1)]
            source = earlier[-1] if earlier else None
        changes = compare_research_ledgers(
            source.research_snapshot if source else None,
            target.research_snapshot,
        )
        return {
            "task_id": task_id,
            "from_version_id": source.id if source else None,
            "to_version_id": target.id,
            "changes": changes,
        }


class SaveVersionRequest(BaseModel):
    content_html: str = ""
    content_markdown: str = ""
    note: str | None = None


@router.post("/api/reports/{task_id}/versions")
def save_report_version(task_id: str, req: SaveVersionRequest, current: dict = Depends(get_current_user)):
    """保存一次人工修订版（kind='revised'，edited_by='human'）。会自动先确保 original 版本存在。

    新版本 version_no = 当前最大 + 1；保存后 is_current=1（其余置 0）。
    editor 取当前默认归属人（本地单用户模式；多用户时从会话获取，见 settings.default_owner_name）。
    """
    with SessionLocal() as db:
        t = task_owned(db, task_id, current)
        if not t:
            return {"status": "not_found"}
        _ensure_original_version(db, t)
        v = create_report_version(
            db,
            task_id=task_id,
            content_markdown=req.content_markdown or "",
            content_html=req.content_html or None,
            note=req.note or None,
            edited_by="human",
            editor=settings.default_owner_name,
        )
        return _version_meta(v, v.id)


class ReviseRequest(BaseModel):
    instruction: str
    llm_config: dict | None = None


class EnrichmentRequest(BaseModel):
    instruction: str = "核验并补充当前报告的证据缺口"
    material_ids: list[str] = Field(default_factory=list)
    web: bool = False
    source_urls: list[str] = Field(default_factory=list)
    llm_config: dict | None = None


@router.post("/api/reports/{task_id}/enrichments", status_code=202)
def create_enrichment_job(task_id: str, req: EnrichmentRequest, current: dict = Depends(get_current_user)):
    """Queue an evidence-enrichment job bound to the report's current version."""
    if not req.material_ids and not req.web and not req.source_urls:
        return JSONResponse(
            {
                "error": "evidence_required",
                "message": "请至少选择一份材料，或开启联网检索。",
            },
            status_code=422,
        )

    with SessionLocal() as db:
        target = task_owned(db, task_id, current)
        if target is None:
            return JSONResponse(
                {"error": "task_not_found", "message": "报告不存在。"},
                status_code=404,
            )
        if target.status != "done":
            return JSONResponse(
                {"error": "report_not_ready", "message": "报告尚未完成，暂时不能补充证据。"},
                status_code=409,
            )
        _ensure_original_version(db, target)
        cur = _current_version(db, task_id)
        if cur is None:
            return JSONResponse(
                {"error": "version_not_found", "message": "当前报告版本不存在。"},
                status_code=404,
            )
        effective_config = req.llm_config or target.llm_config

        from app.llm_settings_store import resolve_config

        if not effective_config or not resolve_config(effective_config).get("api_key"):
            return JSONResponse(
                {
                    "error": "llm_not_configured",
                    "message": "证据补充需要你的 AI API，请先到设置页保存连接。",
                },
                status_code=422,
            )

        job_id = uuid.uuid4().hex
        job = Task(
            id=job_id,
            title=f"补充证据：{target.title}",
            input_text=req.instruction.strip() or "核验并补充当前报告的证据缺口",
            analysis_type=target.analysis_type,
            status="queued",
            phase="inspect",
            progress_pct=0,
            mode="llm",
            input_mode="freeform",
            requested_engine="llm",
            llm_config=effective_config,
            material_ids=req.material_ids,
            web=bool(req.web or req.source_urls),
            source_urls=req.source_urls or None,
            owner_id=target.owner_id,
            project_id=target.project_id,
            operation="enrichment",
            target_task_id=target.id,
            base_version_id=cur.id,
        )
        db.add(job)
        db.commit()
        return {
            "job_task_id": job_id,
            "target_task_id": target.id,
            "base_version_id": cur.id,
            "status": "queued",
        }


@router.post("/api/reports/{task_id}/revise")
def revise_report(task_id: str, req: ReviseRequest, current: dict = Depends(get_current_user)):
    """T13 AI 再改：基于当前版本全文 + 指令，调用 generator.revise 生成新 Markdown，
    新增版本（edited_by='ai'，is_current=1，旧版置 0），并即时重渲产物到
    backend/generated/{task_id}_v{n}/。

    返回：{id, version_no, kind, edited_by, summary, created_at, is_current,
          word, pdf_available}
    """
    with SessionLocal() as db:
        t = task_owned(db, task_id, current)
        if not t:
            return {"status": "not_found"}
        _ensure_original_version(db, t)
        cur = _current_version(db, task_id)
        if not cur:
            return {"error": "version_not_found", "message": "当前版本不存在"}
        prev_md = cur.content_markdown
        title = t.title
        analysis_type = t.analysis_type
        task_llm_config = t.llm_config

    effective_llm_config = req.llm_config or task_llm_config
    from app.llm_settings_store import resolve_config

    if not effective_llm_config or not effective_llm_config.get("profile_id"):
        return JSONResponse(
            {"error": "llm_not_configured", "message": "请先在设置中配置你自己的 AI API 连接。"},
            status_code=422,
        )
    if not resolve_config(effective_llm_config).get("api_key"):
        return JSONResponse(
            {"error": "llm_not_configured", "message": "当前浏览器的 AI API 连接不可用，请重新配置。"},
            status_code=422,
        )

    try:
        gen = ReportGenerator(
            None, analysis_type=analysis_type, mode="llm", llm_config=effective_llm_config
        )
        new_md = gen.revise(prev_md, req.instruction, title)
    except ValueError as e:
        return {"error": "llm_unavailable", "message": str(e)}
    except Exception as e:  # noqa: BLE001
        logger.exception("AI 再改失败 task=%s", task_id)
        return {"error": "revise_failed", "message": f"AI 再改失败：{e}"}

    with SessionLocal() as db:
        t = task_owned(db, task_id, current)
        if t is None:
            return {"error": "task_gone", "message": "任务已不存在"}
        v = create_report_version(            db,
            task_id=task_id,
            content_markdown=new_md,
            content_html=None,
            note=req.instruction,
            edited_by="ai",
            editor="系统",
            summary=req.instruction,
        )
        version_id = v.id
        version_no = v.version_no
        version_created_at = v.created_at

    # 即时重渲产物到实际分配的版本目录（失败不阻塞版本保存）。
    render_warning: str | None = None
    try:
        exp = gen.export(new_md, title, settings.generated_dir, slug=f"{task_id}_v{version_no}")
    except Exception as e:  # noqa: BLE001
        logger.warning("revise 重渲失败（版本仍保存）task=%s：%s", task_id, e)
        render_warning = f"重渲失败：{e}"
        exp = {"word": None, "pdf": None, "pdf_available": False}
    with SessionLocal() as db:
        t = task_owned(db, task_id, current)
        if t is None:
            return {"error": "task_gone", "message": "任务已不存在"}
        cur = _current_version(db, task_id)
        if cur is not None and cur.id == version_id:
            # 只有仍为当前版本时才更新默认下载产物，避免较慢的并发渲染覆盖新版本。
            safe = {k: val for k, val in (t.result or {}).items() if k != "folder"}
            safe.update(
                {
                    "markdown": new_md,
                    "title": title,
                    "word": exp.get("word"),
                    "pdf": exp.get("pdf"),
                    "pdf_available": exp.get("pdf_available", False),
                    "research": cur.research_snapshot,
                    "research_status": cur.research_status or "unavailable",
                }
            )
            t.result = safe
            db.commit()
    resp = {
        "id": version_id,
        "version_no": version_no,
        "kind": "revised",
        "edited_by": "ai",
        "summary": req.instruction,
        "created_at": version_created_at.isoformat() if version_created_at else None,
        "is_current": True,
        "word": f"/api/download/{task_id}?kind=word" if exp.get("word") else None,
        "pdf_available": exp.get("pdf_available", False),
    }
    if render_warning:
        resp["render_warning"] = render_warning
    return resp


@router.post("/api/versions/{vid}/rollback")
def rollback_version(vid: str, current: dict = Depends(get_current_user)):
    """T13 回滚：把指定版本设为 is_current=1（其余置 0���，并即时重渲产物到
    backend/generated/{task_id}_v{n}/。

    返回：{ok, current_version_id, version_no, word, pdf_available}
    """
    with SessionLocal() as db:
        v = db.get(ReportVersion, vid)
        if not v:
            return {"error": "version_not_found", "message": "版本不存在"}
        task_id = v.task_id
        t = task_owned(db, task_id, current)
        if not t:
            return {"error": "task_not_found", "message": "任务不存在"}
        title = t.title
        vno = v.version_no or 1

    # 即时重渲产物到 {task_id}_v{n}/（失败不阻塞回滚：版本切换优先，产物可稍后重试）
    render_warning: str | None = None
    try:
        gen = ReportGenerator(
            None, analysis_type=t.analysis_type, mode=t.mode or "rule"
        )
        exp = gen.export(v.content_markdown, title, settings.generated_dir, slug=f"{task_id}_v{vno}")
    except Exception as e:  # noqa: BLE001
        logger.warning("回滚重渲失败（版本已切换）vid=%s：%s", vid, e)
        render_warning = f"重渲失败：{e}"
        exp = {"word": None, "pdf": None, "pdf_available": False}

    with SessionLocal() as db:
        v = set_current_version(db, vid)
        if not v:
            return {"error": "version_not_found", "message": "版本不存在"}
        t = task_owned(db, task_id, current)
        safe = {k: val for k, val in (t.result or {}).items() if k != "folder"}
        safe.update(
            {
                "markdown": v.content_markdown,
                "title": title,
                "word": exp.get("word"),
                "pdf": exp.get("pdf"),
                "pdf_available": exp.get("pdf_available", False),
                "research": v.research_snapshot,
                "research_status": v.research_status or "unavailable",
            }
        )
        t.result = safe
        db.commit()
    resp = {
        "ok": True,
        "current_version_id": vid,
        "version_no": vno,
        "word": f"/api/download/{task_id}?kind=word" if exp.get("word") else None,
        "pdf_available": exp.get("pdf_available", False),
    }
    if render_warning:
        resp["render_warning"] = render_warning
    return resp


@router.get("/api/reports/{task_id}/versions/{vid}")
def get_report_version(task_id: str, vid: str, current: dict = Depends(get_current_user)):
    """取单个版本的完整内容（Markdown + HTML）。"""
    with SessionLocal() as db:
        t = task_owned(db, task_id, current)
        if not t:
            return {"status": "not_found"}
        v = (
            db.query(ReportVersion)
            .filter(ReportVersion.id == vid, ReportVersion.task_id == task_id)
            .first()
        )
        if not v:
            return {"status": "not_found"}
        return {
            "id": v.id,
            "version_no": v.version_no or 1,
            "kind": v.kind,
            "edited_by": v.edited_by or "ai",
            "summary": v.summary,
            "note": v.note,
            "editor": v.editor,
            "created_at": v.created_at.isoformat() if v.created_at else None,
            "is_current": bool(v.is_current),
            "content_markdown": v.content_markdown,
            "content_html": v.content_html,
            "research_status": v.research_status or "unavailable",
            "research": v.research_snapshot,
        }


@router.delete("/api/reports/{task_id}")
def delete_report(task_id: str, current: dict = Depends(get_current_user)):
    """删除整篇报告（Task）及其所有版本、产物文件，并清理孤立的自动项目。

    - 显式删除 ReportVersion（不依赖数据库级 FK cascade，避免残留孤儿行）；
    - 删除生成的 word/pdf 文件（沙箱屏障已中和，真实机器直接删；失败忽略）；
    - 若该报告归属「自动项目」(id 以 auto_ 开头) 且是该项目唯一报告，则一并删除孤儿项目。
    """
    with SessionLocal() as db:
        t = task_owned(db, task_id, current)
        if not t:
            return {"status": "not_found"}

        # 1) 清理产物文件
        for key in ("word", "pdf"):
            p = (t.result or {}).get(key)
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    logger.warning("删除产物文件失败: %s", p)

        # 2) 清理孤立的自动项目
        pid = t.project_id
        if pid and pid.startswith("auto_"):
            remaining = (
                db.query(Task)
                .filter(Task.project_id == pid, Task.id != task_id)
                .count()
            )
            if remaining == 0:
                proj = db.get(Project, pid)
                if proj:
                    db.delete(proj)

        # 3) 删除版本（显式）
        db.query(ReportVersion).filter(ReportVersion.task_id == task_id).delete()
        # 4) 删除任务
        db.delete(t)
        db.commit()
    return {"status": "deleted"}
