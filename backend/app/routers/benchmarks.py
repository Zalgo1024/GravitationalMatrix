"""Repeatable same-task comparison API for research outputs."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.auth import get_current_user, task_owned
from app.benchmarking import evaluate_candidates, generate_general_baseline
from app.db import SessionLocal
from app.models import BenchmarkRun, ReportVersion, Task
from app.report_version_service import ensure_original_version
from app.research_ledger import normalize_research_ledger


router = APIRouter()


class BenchmarkWrite(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version_id: str | None = None
    general_snapshot: dict | None = None
    human_snapshot: dict | None = None
    audits: dict = Field(default_factory=dict)
    durations: dict = Field(default_factory=dict)
    candidate_metadata: dict = Field(default_factory=dict)
    preference: str = "unset"
    notes: str = ""


class GeneralBaselineRequest(BaseModel):
    version_id: str | None = None


def _current_version(db, task_id: str) -> ReportVersion | None:
    return (
        db.query(ReportVersion)
        .filter(ReportVersion.task_id == task_id, ReportVersion.is_current == 1)
        .order_by(ReportVersion.version_no.desc())
        .first()
        or db.query(ReportVersion)
        .filter(ReportVersion.task_id == task_id)
        .order_by(ReportVersion.version_no.desc())
        .first()
    )


def _serialize(row: BenchmarkRun) -> dict:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "version_id": row.version_id,
        "general_snapshot": row.general_snapshot,
        "human_snapshot": row.human_snapshot,
        "audits": row.audits or {},
        "durations": row.durations or {},
        "candidate_metadata": row.candidate_metadata or {},
        "preference": row.preference or "unset",
        "notes": row.notes or "",
        "result": row.result,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/api/reports/{task_id}/benchmarks")
def list_benchmarks(task_id: str, current: dict = Depends(get_current_user)):
    with SessionLocal() as db:
        if task_owned(db, task_id, current) is None:
            return {"status": "not_found"}
        rows = (
            db.query(BenchmarkRun)
            .filter(BenchmarkRun.task_id == task_id)
            .order_by(BenchmarkRun.created_at.desc())
            .all()
        )
        return {"task_id": task_id, "items": [_serialize(row) for row in rows]}


@router.post("/api/reports/{task_id}/benchmarks")
def create_benchmark(task_id: str, req: BenchmarkWrite):
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if task is None:
            return {"status": "not_found"}
        ensure_original_version(db, task)
        version = db.get(ReportVersion, req.version_id) if req.version_id else _current_version(db, task_id)
        if version is None or version.task_id != task_id or not isinstance(version.research_snapshot, dict):
            return {"error": "research_snapshot_unavailable", "message": "当前报告版本没有可比较的研究快照"}
        preference = req.preference if req.preference in {"system", "general", "human", "tie", "unset"} else "unset"
        durations = dict(req.durations)
        if "system" not in durations and task.created_at and task.updated_at:
            durations["system"] = max(0.0, round((task.updated_at - task.created_at).total_seconds(), 2))
        general_snapshot = normalize_research_ledger(req.general_snapshot).model_dump() if req.general_snapshot else None
        human_snapshot = normalize_research_ledger(req.human_snapshot).model_dump() if req.human_snapshot else None
        result = evaluate_candidates(
            system_snapshot=version.research_snapshot,
            general_snapshot=general_snapshot,
            human_snapshot=human_snapshot,
            audits=req.audits,
            durations=durations,
            preference=preference,
        )
        row = BenchmarkRun(
            task_id=task_id,
            version_id=version.id,
            system_snapshot=version.research_snapshot,
            general_snapshot=general_snapshot,
            human_snapshot=human_snapshot,
            audits=req.audits,
            durations=durations,
            candidate_metadata=req.candidate_metadata,
            preference=preference,
            notes=req.notes,
            result=result,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize(row)


@router.post("/api/reports/{task_id}/benchmarks/general-baseline")
def run_general_baseline(task_id: str, req: GeneralBaselineRequest, current: dict = Depends(get_current_user)):
    """Generate a theory-free baseline with the currently configured model and same sources."""
    from app.llm_client import create_llm_from_config
    from app.llm_settings_store import resolve_config

    with SessionLocal() as db:
        task = task_owned(db, task_id, current)
        if task is None:
            return {"status": "not_found"}
        ensure_original_version(db, task)
        version = db.get(ReportVersion, req.version_id) if req.version_id else _current_version(db, task_id)
        if version is None or version.task_id != task_id or not isinstance(version.research_snapshot, dict):
            return JSONResponse({"error": "research_snapshot_unavailable", "message": "当前报告版本没有研究快照"}, status_code=422)
        config = resolve_config(task.llm_config)
        if not config.get("api_key"):
            return JSONResponse({"error": "llm_not_configured", "message": "请先在设置中配置通用模型 API，或手动导入候选账本"}, status_code=422)
        started = time.monotonic()
        try:
            snapshot = generate_general_baseline(
                input_text=task.input_text,
                system_snapshot=version.research_snapshot,
                llm=create_llm_from_config(task.llm_config),
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": "general_baseline_failed", "message": str(exc)[:300]}, status_code=502)
        return {
            "snapshot": snapshot,
            "duration_seconds": round(time.monotonic() - started, 2),
            "model": config.get("model") or "未命名模型",
            "provider_source": config.get("source") or "unknown",
            "method": "neutral_prompt_same_sources",
        }


@router.put("/api/benchmarks/{benchmark_id}")
def update_benchmark(benchmark_id: str, req: BenchmarkWrite):
    with SessionLocal() as db:
        row = db.get(BenchmarkRun, benchmark_id)
        if row is None:
            return {"status": "not_found"}
        if req.general_snapshot is not None:
            row.general_snapshot = normalize_research_ledger(req.general_snapshot).model_dump()
        if req.human_snapshot is not None:
            row.human_snapshot = normalize_research_ledger(req.human_snapshot).model_dump()
        row.audits = req.audits
        row.durations = req.durations
        row.candidate_metadata = req.candidate_metadata
        row.preference = req.preference if req.preference in {"system", "general", "human", "tie", "unset"} else "unset"
        row.notes = req.notes
        row.result = evaluate_candidates(
            system_snapshot=row.system_snapshot,
            general_snapshot=row.general_snapshot,
            human_snapshot=row.human_snapshot,
            audits=row.audits,
            durations=row.durations,
            preference=row.preference,
        )
        db.commit()
        db.refresh(row)
        return _serialize(row)
