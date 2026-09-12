"""分析任务接口：提交分析 / 取结果 / 轮询 / 重试 / 实时进度（WebSocket）/ 下载产物。"""
import logging
import os
import re
import uuid
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.auth import get_current_user, rate_limiter, task_owned, user_from_ws_cookies
from app.db import SessionLocal
from app import queue as taskq
from app import rule_engine
from app.generation_routing import GenerationRouteError, decide_generation_route
from app.llm_settings_store import resolve_config
from app.models import ReportVersion, Task, _now
from app.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# 应用层 DoS / 滥用防护（S1 限流 + S2 用户配额 + S3 全局闸门）
# 仅 PUBLIC_MODE=1（公网）生效；本地模式不设闸，保证「本地零回归」。
# ---------------------------------------------------------------------------
_ACTIVE_STATUS = ("queued", "generating")   # 占用 worker 的任务状态
_RATE_LIMIT, _RATE_WINDOW = 12, 60          # S1 每用户 60s 最多提交 12 个任务
_MAX_USER_ACTIVE = 5                        # S2 每用户同时 queued/generating ≤ 5
_MAX_GLOBAL_QUEUE = 200                     # S3 全局排队上限


def _guard_enqueue(db, uid: str) -> None:
    """提交/重试前调用：公网下检查用户并发配额 + 全局排队水位，超限抛 429。

    本地模式（settings.public_mode=False）直接放行，不干扰本机调试。
    纯内存限流不跨进程共享；配合 worker=1 的单进程部署足够（见部署说明）。
    """
    if not settings.public_mode:
        return
    uid_active = (
        db.query(Task)
        .filter(Task.owner_id == uid, Task.status.in_(_ACTIVE_STATUS))
        .count()
    )
    if uid_active >= _MAX_USER_ACTIVE:
        raise HTTPException(
            status_code=429,
            detail={
                "status": "rate_limited",
                "message": f"您同时进行的任务已达上限（{_MAX_USER_ACTIVE} 个），请等待完成后再提交",
            },
        )
    global_queued = db.query(Task).filter(Task.status == "queued").count()
    if global_queued >= _MAX_GLOBAL_QUEUE:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "queue_full",
                "message": "系统当前繁忙（队列已满），请稍后再试",
            },
        )


def _check_rate_limit(uid: str, ip: str) -> None:
    """S1 提交频率限流：公网下每用户每 IP 60s 内 ≤ 阈值，超限抛 429。"""
    if not settings.public_mode:
        return
    key = f"analyze:{uid}:{ip}"
    if not rate_limiter.allow(key, limit=_RATE_LIMIT, window_sec=_RATE_WINDOW):
        raise HTTPException(
            status_code=429,
            detail={
                "status": "rate_limited",
                "message": "提交过于频繁，请稍后再试",
            },
        )


class AnalyzeRequest(BaseModel):
    title: str
    input_text: str = ""
    analysis_type: str = "case"  # case | policy | org | opinion | combo
    project_id: str | None = None  # 预留（阶段三接入），可选
    mode: str | None = None  # 旧客户端兼容字段
    input_mode: str | None = None  # freeform | structured
    requested_engine: str | None = None  # auto | rule | llm
    structured: dict | None = None  # rule 模式：结构化输入
    # llm 模式：每请求仅携带模型/温度/提示词版本 —— 不含 api_key（密钥只在后端，
    # 来自 data/llm_settings.json 或 .env，详见 /api/settings/llm）。
    llm_config: dict | None = None
    material_ids: list[str] | None = None  # 阶段三：本次分析使用的材料（证据出处）
    search: bool | None = None  # 阶段五：搜索开关 None=自动 | True=强制搜索 | False=跳过（保留兼容）
    web: bool = True  # 自由输入默认联网检索；用户可显式传 false 跳过
    source_urls: list[str] | None = None  # T8：用户勾选来源白名单（null=自动检索全部）
    auto_collect: bool = False  # F2：本次分析附带多平台采集入库（前端默认传 false）


def llm_is_available(llm_config: dict | None = None) -> bool:
    """公共分析任务只认浏览器自己的 BYOK 配置，不使用服务器默认密钥。"""
    if not llm_config or not llm_config.get("profile_id"):
        return False
    return bool(resolve_config(llm_config).get("api_key"))


@router.post("/api/analyze")
async def analyze(
    req: AnalyzeRequest,
    request: Request,
    current: dict = Depends(get_current_user),
):
    # S1 提交频率限流（公网有效；本地放行）
    _ip = request.client.host if request.client else "unknown"
    _check_rate_limit(str(current.get("id")), _ip)
    requested_engine = req.requested_engine or req.mode or "auto"
    try:
        decision = decide_generation_route(
            input_mode=req.input_mode,
            requested_engine=requested_engine,
            structured=req.structured,
            llm_available=llm_is_available(req.llm_config),
        )
    except GenerationRouteError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "phase": "input_validation",
                    "details": [],
                }
            },
        )
    if decision.input_mode == "structured":
        validation = rule_engine.validate_structured_input(req.structured or {})
        if not validation.valid:
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": "invalid_structured_input",
                        "message": "结构化录入缺少生成正式报告所需的数据。",
                        "phase": "input_validation",
                        "details": validation.missing_fields,
                    }
                },
            )
    task_id = uuid.uuid4().hex
    with SessionLocal() as db:
        # S2 用户并发配额 + S3 全局排队闸门（公网有效；本地放行）
        _guard_enqueue(db, str(current.get("id")))
        db.add(
            Task(
                id=task_id,
                title=req.title,
                input_text=req.input_text,
                analysis_type=req.analysis_type,
                project_id=req.project_id,
                owner_id=current["id"],
                mode=decision.selected_engine,
                input_mode=decision.input_mode,
                requested_engine=decision.requested_engine,
                structured=req.structured,
                llm_config=req.llm_config,
                material_ids=req.material_ids or None,
                search_enabled=req.search,
                web=req.web,
                source_urls=req.source_urls or None,
                auto_collect=bool(req.auto_collect),
                status="queued",
            )
        )
        db.commit()
    # 工人池会认领并执行；客户端通过 WS 收进度
    return {"task_id": task_id}


@router.get("/api/analyze/{task_id}")
def get_result(task_id: str, current: dict = Depends(get_current_user)):
    with SessionLocal() as db:
        t = task_owned(db, task_id, current)
        if not t:
            return {"status": "not_found"}
        data = (
            t.result
            if t.status == "done"
            else (t.error if t.status == "error" else None)
        )
        # 历史报告在「来源标识」功能加入前未存 engine_used，用 Task.mode 兜底，
        # 保证旧的 rule/llm 报告也能在展示页正确显示「模型生成 / AI 生成」。
        data_dict = data if isinstance(data, dict) else None
        if data_dict is not None and not data_dict.get("engine_used"):
            data_dict = {**data_dict, "engine_used": t.mode or "rule"}
        return {
            "status": t.status,
            "data": data,
            "material_ids": t.material_ids or [],
            "engine_used": data_dict.get("engine_used") if data_dict else (t.mode or None),
            "degraded_from_llm": bool(data_dict.get("degraded_from_llm")) if data_dict else False,
            "degrade_reason": data_dict.get("degrade_reason") if data_dict else None,
            "prompt_version": t.prompt_version,
            "llm_model": t.llm_model,
            "phase": t.phase,
            "progress_pct": t.progress_pct or 0,
            "search_results": t.search_results,
            "quality": t.quality_result,
        }


@router.post("/api/analyze/{task_id}/retry")
def retry_task(
    task_id: str,
    request: Request,
    current: dict = Depends(get_current_user),
):
    """为失败/成功的任务创建一条新的重试任务（保留原任务历史，不覆盖）。

    - 仅当原任务存在时允许；
    - 新任务继承原 project_id / 输入 / 模式 / structured / llm_config；
    - attempt_no = 原 attempt_no + 1，retry_of 指向原任务；
    - 立即入队（status='queued'），由工人池认领。
    返回新任务 id。
    """
    # S1 提交频率限流（公网有效；本地放行）
    _rip = request.client.host if request.client else "unknown"
    _check_rate_limit(str(current.get("id")), _rip)
    with SessionLocal() as db:
        t = task_owned(db, task_id, current)
        if not t:
            return {"status": "not_found"}
        # 互斥：原任务仍在排队/执行时拒绝重复重试，避免生成多份重复副本互相覆盖
        if t.status in ("queued", "generating"):
            return {"status": "busy", "message": "任务仍在执行中，请等待完成后再重试"}
        # S2 用户并发配额 + S3 全局排队闸门（重试同样入队，需一并约束）
        _guard_enqueue(db, str(current.get("id")))
        new_id = uuid.uuid4().hex
        new_task = Task(
            id=new_id,
            title=t.title,
            input_text=t.input_text,
            analysis_type=t.analysis_type,
            project_id=t.project_id,
            mode=t.mode or "rule",
            input_mode=t.input_mode,
            requested_engine=t.requested_engine or t.mode or "auto",
            structured=t.structured,
            llm_config=t.llm_config,
            owner_id=t.owner_id,
            status="queued",
            attempt_no=(t.attempt_no or 1) + 1,
            retry_of=t.id,
            material_ids=t.material_ids,  # 继承原任务使用的材料
            search_enabled=t.search_enabled,  # 继承搜索开关
            web=t.web,  # 继承联网开关
            source_urls=t.source_urls,  # 继承来源白名单
            auto_collect=t.auto_collect,  # 继承自动取证开关
        )
        db.add(new_task)
        db.commit()
        return {"new_task_id": new_id, "retry_of": t.id, "attempt_no": new_task.attempt_no}


@router.get("/api/analyze/{task_id}/poll")
def poll_task(task_id: str, current: dict = Depends(get_current_user)):
    """轮询快照（WS 断开后的进度恢复用）。返回带服务端时间戳的权威状态。"""
    with SessionLocal() as db:
        t = task_owned(db, task_id, current)
        if not t:
            return {"status": "not_found"}
        data = (
            t.result
            if t.status == "done"
            else (
                {
                    "message": t.error,
                    "type": t.error_type,
                    "phase": t.error_phase,
                }
                if t.status == "error"
                else None
            )
        )
        # 历史报告未存 engine_used 时回退 Task.mode（与 get_result 保持一致）
        data_dict = data if isinstance(data, dict) else None
        if data_dict is not None and not data_dict.get("engine_used"):
            data_dict = {**data_dict, "engine_used": t.mode or "rule"}
        return {
            "status": t.status,
            "data": data,
            "task_id": task_id,
            "material_ids": t.material_ids or [],
            "engine_used": data_dict.get("engine_used") if data_dict else (t.mode or None),
            "degraded_from_llm": bool(data_dict.get("degraded_from_llm")) if data_dict else False,
            "degrade_reason": data_dict.get("degrade_reason") if data_dict else None,
            "prompt_version": t.prompt_version,
            "llm_model": t.llm_model,
            "phase": t.phase,
            "progress_pct": t.progress_pct or 0,
            "search_results": t.search_results,
            "quality": t.quality_result,
            "server_time": _now().isoformat(),
        }


@router.websocket("/ws/progress/{task_id}")
async def ws_progress(task_id: str, ws: WebSocket):
    await ws.accept()
    ws_user = user_from_ws_cookies(dict(ws.cookies))
    if ws_user is None:
        await ws.send_json({"status": "unauthorized"})
        await ws.close()
        return
    # 先订阅，再以数据库快照为权威当前状态发送（避免漏掉订阅前已发出的进度）
    q = taskq.subscribe(task_id)
    with SessionLocal() as db:
        t = task_owned(db, task_id, current)
        if not t:
            await ws.send_json({"status": "not_found"})
            taskq.unsubscribe(task_id, q)
            return
        snap_status = t.status
        snap_data = (
            t.result
            if t.status == "done"
            else (t.error if t.status == "error" else None)
        )
        snap_phase = t.phase
        snap_pct = t.progress_pct or 0
    snap_msg = {"status": snap_status, "data": snap_data}
    if snap_phase is not None:
        snap_msg["phase"] = snap_phase
        snap_msg["progress_pct"] = snap_pct
    await ws.send_json(snap_msg)
    if snap_status in ("done", "error"):
        taskq.unsubscribe(task_id, q)
        return
    try:
        while True:
            msg = await q.get()
            await ws.send_json(msg)
            if msg["status"] in ("done", "error"):
                break
    except WebSocketDisconnect:
        pass
    finally:
        taskq.unsubscribe(task_id, q)


@router.get("/api/download/{task_id}")
def download(task_id: str, kind: str = "word", version: str | None = None, current: dict = Depends(get_current_user)):
    from app.settings import settings

    with SessionLocal() as db:
        t = task_owned(db, task_id, current)
        if not t:
            return {"error": "not_found"}
        # PPT：用（指定/最新）版本 Markdown 即时生成演示稿
        if kind == "pptx":
            from app.pptx_renderer import export_report_pptx

            q = db.query(ReportVersion).filter(ReportVersion.task_id == task_id)
            if version:
                v = q.filter(ReportVersion.id == version).first()
            else:
                v = q.order_by(ReportVersion.created_at.desc()).first()
            if not v:
                return {"error": "version_not_found"}
            exp = export_report_pptx(
                t.title or "未命名报告",
                v.content_markdown,
                output_dir=settings.generated_dir,
                slug=f"pptx_{task_id}",
            )
            pptx_path = exp.get("pptx")
            if pptx_path and os.path.exists(pptx_path):
                return FileResponse(pptx_path, filename=os.path.basename(pptx_path))
            return {"error": "pptx_generation_failed"}
        # 组合下载：Word + PDF + PPT + Markdown + 利益关系网络图 → 一个 zip 包
        if kind == "zip":
            from app.pptx_renderer import export_report_pptx

            q = db.query(ReportVersion).filter(ReportVersion.task_id == task_id)
            if version:
                v = q.filter(ReportVersion.id == version).first()
            else:
                v = q.order_by(ReportVersion.created_at.desc()).first()
            if not v:
                return {"error": "version_not_found"}
            safe = (
                re.sub(r'[\\/:*?"<>|]', "-", (t.title or "未命名报告").strip())
                or "未命名报告"
            )
            bundle_dir = os.path.join(settings.generated_dir, f"bundle_{task_id}")
            os.makedirs(bundle_dir, exist_ok=True)
            md_path = os.path.join(bundle_dir, f"{safe}.md")
            with open(md_path, "w", encoding="utf-8") as fh:
                fh.write(v.content_markdown or "")
            exp = export_report_pptx(
                t.title or "未命名报告",
                v.content_markdown,
                output_dir=bundle_dir,
                slug="bundle",
            )
            zip_path = os.path.join(bundle_dir, f"{safe}_全套.zip")

            def _zip_add(zf: zipfile.ZipFile, src: str, arcname: str) -> None:
                info = zipfile.ZipInfo(arcname)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.flag_bits |= 0x800  # UTF-8 文件名（Windows 解压不乱码）
                with open(src, "rb") as fh:
                    zf.writestr(info, fh.read())

            with zipfile.ZipFile(zip_path, "w") as zf:
                root = safe
                _zip_add(zf, md_path, f"{root}/{safe}.md")
                for field, ext in (("word", "docx"), ("pdf", "pdf")):
                    stored = (t.result or {}).get(field)
                    if stored and os.path.exists(stored):
                        _zip_add(zf, stored, f"{root}/{safe}.{ext}")
                pptx_path = exp.get("pptx")
                if pptx_path and os.path.exists(pptx_path):
                    _zip_add(zf, pptx_path, f"{root}/{safe}.pptx")
                for i, diag in enumerate(exp.get("diagrams") or [], 1):
                    png = diag.get("png")
                    if png and os.path.exists(png):
                        label = re.sub(
                            r'[\\/:*?"<>|]', "-", str(diag.get("title") or f"图 {i}")
                        )[:60]
                        _zip_add(zf, png, f"{root}/利益关系网络图/{i}-{label}.png")
            if os.path.exists(zip_path):
                return FileResponse(zip_path, filename=os.path.basename(zip_path))
            return {"error": "zip_generation_failed"}
        # 指定版本：用该版本 Markdown 即时导出（人工修订版也能下载）
        if version:
            v = (
                db.query(ReportVersion)
                .filter(
                    ReportVersion.id == version, ReportVersion.task_id == task_id
                )
                .first()
            )
            if not v:
                return {"error": "version_not_found"}
            from app.engine_bridge import export_report

            exp = export_report(t.title or "未命名报告", v.content_markdown)
            if kind == "pdf":
                pdf_path = exp.get("pdf")
                if pdf_path and os.path.exists(pdf_path):
                    return FileResponse(pdf_path, filename=os.path.basename(pdf_path))
                # 修订版 PDF 未生成（本机缺 LibreOffice 等转换引擎）：明确报错
                return JSONResponse(
                    {
                        "error": "pdf_unavailable",
                        "message": "本机未安装 LibreOffice 等转换引擎，PDF 暂不可用。可下载 Word 版本。",
                    },
                    status_code=409,
                )
            path = exp.get("word")
            if path and os.path.exists(path):
                return FileResponse(path, filename=os.path.basename(path))
            return {"error": "file_missing"}
        # 原行为：取生成结果里的文件
        if not t.result:
            return {"error": "not_found"}
        if kind == "pdf":
            pdf_path = t.result.get("pdf")
            if pdf_path and os.path.exists(pdf_path):
                return FileResponse(pdf_path, filename=os.path.basename(pdf_path))
            return JSONResponse(
                {
                    "error": "pdf_unavailable",
                    "message": "本机未安装 LibreOffice 等转换引擎，PDF 暂不可用。可下载 Word 版本。",
                },
                status_code=409,
            )
        path = t.result.get("word")
    if path and os.path.exists(path):
        return FileResponse(path, filename=os.path.basename(path))
    return {"error": "file_missing"}
