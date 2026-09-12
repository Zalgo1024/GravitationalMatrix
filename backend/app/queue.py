"""任务队列（排班）— Phase 2.2。

设计：数据库即队列。任务行 status='queued' 即在排队；N 个工人协程持续认领（claim）
最旧的 queued 任务，置为 generating 后在线程池里跑生成，完成后写回 done/error，
并通过内存 progress_queues 推送给正在监听的 WebSocket。

崩溃恢复：服务启动时把所有 stuck 在 generating 的任务重置回 queued，由工人重新接单。

并发上限：WORKER_COUNT 控制同时跑几道菜（默认 3），避免本机 LLM/CPU 打满。
"""
import asyncio
import logging
import re
import threading
import time

from app.db import SessionLocal
from app.generator import ReportGenerator
from app.llm_client import create_llm
from app.search import should_search
from app.settings import settings

logger = logging.getLogger(__name__)

WORKER_COUNT = 6  # 6 并发：缓解连续多任务排队，体感不再"卡住"（本机 LLM 走远程 API，CPU 不是瓶颈）

# 实时进度订阅（仅存在于有客户端连 WS 期间，ephemeral，非持久）
# 同一任务允许多个客户端各自订阅（每个 client 一个 queue），互不顶掉；
# 并记录订阅者所在事件循环，供 worker 线程跨线程安全推送。
_subscribers: dict[str, dict[asyncio.Queue, asyncio.AbstractEventLoop | None]] = {}
_claim_lock = threading.Lock()
_workers: list[asyncio.Task] = []


def subscribe(task_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    _subscribers.setdefault(task_id, {})[q] = loop
    return q


def unsubscribe(task_id: str, q: asyncio.Queue | None = None) -> None:
    """移除某个客户端的订阅；q 为空时移除该任务的全部订阅（旧调用兼容）。"""
    subs = _subscribers.get(task_id)
    if subs is None:
        return
    if q is None:
        _subscribers.pop(task_id, None)
        return
    subs.pop(q, None)
    if not subs:
        _subscribers.pop(task_id, None)


def _emit(task_id: str, status: str, data=None, *, phase: str | None = None, progress_pct: int | None = None) -> None:
    subs = _subscribers.get(task_id)
    if not subs:
        return
    msg = {"status": status, "data": data}
    if phase is not None:
        msg["phase"] = phase
    if progress_pct is not None:
        msg["progress_pct"] = progress_pct
    for q, loop in list(subs.items()):
        try:
            if loop is not None:
                # worker 线程跨线程推送：线程安全地交给订阅者所在事件循环
                loop.call_soon_threadsafe(q.put_nowait, msg)
            else:
                q.put_nowait(msg)
        except (RuntimeError, Exception):  # noqa: BLE001 - loop 已关闭等
            pass


def recover_interrupted() -> None:
    """启动时把卡在 generating 的任务放回队列（程序崩溃/重启后的孤儿任务）。"""
    from app.models import Task

    with SessionLocal() as db:
        stuck = db.query(Task).filter(Task.status == "generating").all()
        for r in stuck:
            r.status = "queued"
        if stuck:
            db.commit()


# 错误堆栈脱敏：去掉本地绝对路径与可能的密钥片段，避免敏感信息落库/外泄
_SENSITIVE = ("api_key", "secret", "token", "password", "sk-", "Bearer ")
_PATH_RE = __import__("re").compile(r"[A-Za-z]:\\[^\"'\n]{0,200}|/(?:Users|home|root)/[^\"'\n]{0,200}")


def _safe_error_text(e: Exception) -> str:
    """人类可读错误摘要（不含完整堆栈，避免本地路径/密钥外泄）。"""
    msg = str(e)
    for s in _SENSITIVE:
        if s.lower() in msg.lower():
            # 仅把敏感词本身替换为脱敏标记，保留前后上下文（如"第几步失败"）
            msg = re.sub(re.escape(s), "[已脱敏]", msg, flags=re.IGNORECASE)
    msg = _PATH_RE.sub("[path]", msg)
    return (msg or e.__class__.__name__)[:1500]


# 6 步分析链：phase 字符串 -> (第几步, 名称)，用于错误时告知前端"第 X ���失败"
PHASE_STEP: dict[str, tuple[int, str]] = {
    "inspect": (1, "检查分析目标"),
    "search": (2, "全网搜索相关信息"),
    "fetch": (2, "抓取网页正文"),
    "search_skipped": (2, "全网搜索相关信息"),
    "decompose": (3, "对目标进行拆解分析"),
    "network": (4, "利益关系网络拆解"),
    "organize": (5, "整理分析结果"),
    "output": (6, "输出分析结果"),
}

# phase 顺序（用于"关键词定位不早于当前阶段"的校正，避免倒退误报）
_PHASE_ORDER = ["inspect", "search", "fetch", "search_skipped", "decompose", "network", "organize", "output"]


def _classify_error(e: Exception, current_phase: str | None = None) -> tuple[str, str]:
    """把失败定位到 6 步分析链中的具体一步（替换旧的 validate/generate/export 三档）。

    优先用「当前已达阶段」current_phase（最准确：就是崩溃时停在哪一步）；
    仅当错误文本关键词能定位到「不早于当前阶段」的更具体步骤时才采用，
    例如导出阶段报 docx 错误、整理阶段报 contract 错误，避免倒退误报。
    """
    if getattr(e, "code", None) == "quality_gate":
        return e.__class__.__name__, "quality_gate"
    msg = str(e).lower()
    forced: str | None = None
    if "diagram" in msg or "network" in msg:
        forced = "network"
    elif "docx" in msg or "pdf" in msg or "export" in msg:
        forced = "output"
    elif "schema" in msg or "validation" in msg or "contract" in msg:
        forced = "organize"
    cur = current_phase or "organize"
    if forced and _PHASE_ORDER.index(forced) >= _PHASE_ORDER.index(cur):
        return e.__class__.__name__, forced
    return e.__class__.__name__, cur


def _process_enrichment(job_id: str) -> None:
    """Enrich one existing report from new local/web evidence and create a version."""
    from app import materials
    from app.models import Material, ReportVersion, Task
    from app.report_version_service import create_report_version
    from app.search import (
        dedupe_hits,
        derive_analogue_query,
        derive_query,
        fetch_and_clean,
        search_primary_and_analogue,
    )

    started = time.monotonic()

    def update(phase: str, pct: int) -> None:
        with SessionLocal() as db:
            job = db.get(Task, job_id)
            if job is not None:
                job.phase = phase
                job.progress_pct = pct
                db.commit()
        _emit(job_id, "generating", phase=phase, progress_pct=pct)

    def finish(result: dict) -> None:
        result.setdefault("timings", {})["total_seconds"] = round(
            time.monotonic() - started, 3
        )
        with SessionLocal() as db:
            job = db.get(Task, job_id)
            if job is None:
                return
            job.status = "done"
            job.phase = "output"
            job.progress_pct = 100
            job.result = result
            job.error = None
            db.commit()
        _emit(job_id, "done", result, phase="output", progress_pct=100)

    try:
        update("inspect", 5)
        with SessionLocal() as db:
            job = db.get(Task, job_id)
            if job is None:
                return
            target = db.get(Task, job.target_task_id)
            base = db.get(ReportVersion, job.base_version_id)
            if target is None or base is None or base.task_id != target.id:
                raise ValueError("待补充的报告或基准版本不存在")
            rows = (
                db.query(Material).filter(Material.id.in_(job.material_ids or [])).all()
                if job.material_ids
                else []
            )
            instruction = job.input_text or "核验并补充当前报告的证据缺口"
            web = bool(job.web)
            source_urls = job.source_urls or []
            llm_config = job.llm_config or target.llm_config
            title = target.title
            analysis_type = target.analysis_type
            target_input = target.input_text
            base_markdown = base.content_markdown
            base_version_id = base.id
            target_task_id = target.id

        bundle = materials.bundle_from_material_rows(rows)
        search_seconds = 0.0
        if web:
            update("search", 15)
            search_started = time.monotonic()
            hits = []
            degraded = None
            if source_urls:
                update("fetch", 22)
                fetched = fetch_and_clean(source_urls)
            else:
                query_input = f"{target_input}\n{instruction}".strip()
                primary, analogue = search_primary_and_analogue(
                    derive_query(query_input),
                    derive_analogue_query(query_input),
                    settings.search_max_results,
                )
                if primary is not None:
                    hits.extend(primary.hits)
                    degraded = primary.degraded
                if analogue is not None:
                    hits.extend(analogue.hits)
                    degraded = degraded or analogue.degraded
                hits = dedupe_hits(hits)[: settings.search_max_results]
                update("fetch", 22)
                fetched = fetch_and_clean([hit.url for hit in hits])
            web_bundle = materials.build_materials(hits, fetched, set())
            bundle = materials.merge_bundles(bundle, web_bundle)
            search_seconds = time.monotonic() - search_started
        else:
            update("search_skipped", 15)
            degraded = None

        usable_items = [
            item for item in bundle.items if item.get("kept", True) and item.get("text")
        ]
        if not usable_items:
            finish(
                {
                    "operation": "enrichment",
                    "outcome": "no_evidence",
                    "target_task_id": target_task_id,
                    "base_version_id": base_version_id,
                    "message": degraded or "没有读到可核验的新增材料，未创建报告版本。",
                    "timings": {"search_seconds": round(search_seconds, 3)},
                }
            )
            return

        update("decompose", 35)
        gen = ReportGenerator(
            None,
            analysis_type=analysis_type,
            mode="llm",
            llm_config=llm_config,
            web_mode=True,
            materials=bundle.__dict__,
        )
        generation_started = time.monotonic()
        new_markdown = gen.enrich(base_markdown, instruction, title)
        generation_seconds = time.monotonic() - generation_started
        update("network", 60)
        network = gen.extract_network(new_markdown)
        research_started = time.monotonic()
        research = gen.build_research_ledger(new_markdown, target_input)
        research_seconds = time.monotonic() - research_started
        update("organize", 78)

        with SessionLocal() as db:
            current = (
                db.query(ReportVersion)
                .filter(ReportVersion.task_id == target_task_id, ReportVersion.is_current == 1)
                .first()
            )
            make_current = bool(current and current.id == base_version_id)
            version = create_report_version(
                db,
                task_id=target_task_id,
                content_markdown=new_markdown,
                content_html=None,
                note=instruction,
                edited_by="ai",
                editor="系统",
                summary=f"补充证据：{instruction[:180]}",
                research_snapshot=research.model_dump(),
                research_status=research.status,
                kind="enriched",
                make_current=make_current,
            )
            version_id = version.id
            version_no = version.version_no

        update("output", 88)
        export_started = time.monotonic()
        try:
            exported = gen.export(
                new_markdown,
                title,
                settings.generated_dir,
                slug=f"{target_task_id}_v{version_no}",
            )
            export_warning = None
        except Exception as exc:  # noqa: BLE001
            exported = {"word": None, "pdf": None, "pdf_available": False}
            export_warning = f"报告版本已保存，但导出失败：{_safe_error_text(exc)}"
        export_seconds = time.monotonic() - export_started

        if make_current:
            with SessionLocal() as db:
                target = db.get(Task, target_task_id)
                if target is not None:
                    safe = dict(target.result or {})
                    safe.update(
                        {
                            "markdown": new_markdown,
                            "network": network,
                            "research": research.model_dump(),
                            "research_status": research.status,
                            "word": exported.get("word"),
                            "pdf": exported.get("pdf"),
                            "pdf_available": exported.get("pdf_available", False),
                        }
                    )
                    target.result = safe
                    db.commit()

        finish(
            {
                "operation": "enrichment",
                "outcome": "created",
                "target_task_id": target_task_id,
                "base_version_id": base_version_id,
                "version_id": version_id,
                "version_no": version_no,
                "is_current": make_current,
                "message": (
                    "证据补充版本已设为当前版本。"
                    if make_current
                    else "报告在补充期间已发生变化，新结果已保存为候选版本，未覆盖当前稿。"
                ),
                "render_warning": export_warning,
                "timings": {
                    "search_seconds": round(search_seconds, 3),
                    "generate_seconds": round(generation_seconds, 3),
                    "research_seconds": round(research_seconds, 3),
                    "export_seconds": round(export_seconds, 3),
                },
            }
        )
    except Exception as exc:  # noqa: BLE001
        message = _safe_error_text(exc)
        with SessionLocal() as db:
            job = db.get(Task, job_id)
            if job is not None:
                job.status = "error"
                job.error = message
                job.error_type = exc.__class__.__name__
                job.error_phase = job.phase or "inspect"
                job.error_detail = message
                db.commit()
        _emit(job_id, "error", {"message": message}, phase="organize", progress_pct=0)


def _process(task_id: str) -> None:
    """在线程池里执行单条任务的生成与导出，并把结果写回数据库。

    6 步分析进度链：
        1. inspect  (5%)  — 检查分析目标（解析输入）
        2. search   (15%) — 全网搜索相关信息（可选增强：灰度开放且已配置 API 时执行，否则跳过）
        3. decompose(25%) — 对目标进行拆解分析
        4. network  (55%) — 利益关系网络拆解
        5. organize (75%) — 整理分析结果
        6. output   (85%) — 输出分析结果（导出）
    完成时 progress_pct=100。
    """
    from app.models import Material, Task

    # 先取出任务字段（session 关闭后 detached 实例不可再懒加载）
    with SessionLocal() as db:
        t = db.get(Task, task_id)
        if t is None or t.status != "generating":
            return
        title = t.title
        input_text = t.input_text
        analysis_type = t.analysis_type
        mode = t.mode or "rule"
        structured = t.structured
        llm_config = t.llm_config
        search_enabled = t.search_enabled  # None=自动 | True=强制 | False=跳过
        web = bool(t.web)  # T8：联网写报告
        source_urls = t.source_urls or []  # T8：用户勾选白名单
        material_ids = t.material_ids or []
        auto_collect = bool(t.auto_collect)  # F2：自动取证
        owner_id_val = t.owner_id  # 采集素材归属（detached 后仍可读已加载属性）
        project_id_val = t.project_id
        operation = t.operation or "analysis"

        if operation == "enrichment":
            _process_enrichment(task_id)
            return

        local_rows = (
            db.query(Material).filter(Material.id.in_(material_ids)).all()
            if material_ids
            else []
        )

    from app import materials

    local_bundle = materials.bundle_from_material_rows(local_rows)

    def _update_phase(phase: str, pct: int):
        """更新 DB 中的阶段字段并推送给 WS 订阅者；同时记录"当前已达阶段"。"""
        last_phase["v"] = phase
        with SessionLocal() as db:
            t = db.get(Task, task_id)
            if t is not None:
                t.phase = phase
                t.progress_pct = pct
                db.commit()
        _emit(task_id, "generating", phase=phase, progress_pct=pct)

    # 记录"当前已达阶段"，用于失败时精确告知用户卡在第几步
    last_phase = {"v": "inspect"}

    # —— 步骤 1：检查分析目标 ——
    _update_phase("inspect", 5)

    # —— 步骤 2：联网检索/抓取素材（T1/T8，替代旧 search 分支）——
    # 判定：web 开关（或旧 search 兼容）开启 且 灰度未关停 且 输入值得搜。
    web_on = (
        (web or search_enabled is True)
        and settings.search_enabled != "off"
        and should_search(input_text)
    )
    bundle = local_bundle if local_bundle.items else None
    search_seconds = 0.0
    if web_on:
        _update_phase("search", 15)
        search_started = time.monotonic()
        try:
            from app.search import (
                dedupe_hits,
                derive_analogue_query,
                derive_query,
                fetch_and_clean,
                search_primary_and_analogue,
            )

            query = derive_query(input_text)
            analogue_query = derive_analogue_query(input_text)
            hits = []
            degraded: str | None = None
            provider: str | None = None
            if source_urls:
                # 用户勾选白名单 → 直接抓取（不检索）
                _update_phase("fetch", 18)
                fetched = fetch_and_clean(source_urls)
                degraded = None
            else:
                # 无白名单 → 检索 + 去重 + 抓取
                result, analogue_result = search_primary_and_analogue(
                    query,
                    analogue_query,
                    settings.search_max_results,
                )
                if result is None:
                    degraded = "检索源不可用"
                    fetched = []
                else:
                    provider = result.provider
                    degraded = result.degraded
                    hits = result.hits
                    analogue_hits = analogue_result.hits if analogue_result is not None else []
                    if analogue_result is not None and analogue_result.degraded and not degraded:
                        degraded = f"历史对照检索降级：{analogue_result.degraded}"
                    # Interleave the primary and historical result sets so a full
                    # primary page cannot crowd all comparison evidence out.
                    merged_hits = []
                    for index in range(max(len(hits), len(analogue_hits))):
                        if index < len(hits):
                            merged_hits.append(hits[index])
                        if index < len(analogue_hits):
                            merged_hits.append(analogue_hits[index])
                    hits = dedupe_hits(merged_hits)[: settings.search_max_results]
                    _update_phase("fetch", 18)
                    fetched = fetch_and_clean([h.url for h in hits[: settings.search_max_results]])
            web_bundle = materials.build_materials(hits, fetched, set())
            bundle = materials.merge_bundles(local_bundle, web_bundle)
            # 结果落库（含 degraded，不静默），随 done 载荷推给前端
            # snippets 为旧前端兼容字段（旧 AnalysisEngine 读 search_results.snippets）
            with SessionLocal() as db:
                t2 = db.get(Task, task_id)
                if t2 is not None:
                    t2.search_results = {
                        "query": query,
                        "analogue_query": analogue_query,
                        "provider": provider or "duckduckgo",
                        "hits": [
                            {"title": h.title, "url": h.url, "snippet": h.snippet} for h in hits
                        ],
                        "snippets": [
                            (h.snippet or h.title) if h.title else (h.snippet or "")
                            for h in hits
                        ],
                        "degraded": degraded,
                        "sources": [
                            {"title": s.title, "url": s.url} for s in bundle.sources
                        ],
                    }
                    db.commit()
        except Exception as e:  # noqa: BLE001
            # 检索/抓取失败：降级标记，不影响后续分析
            logger.warning("联网检索/抓取失败（已降级标记）：%s", _safe_error_text(e))
            with SessionLocal() as db:
                t2 = db.get(Task, task_id)
                if t2 is not None:
                    t2.search_results = {
                        "query": derive_query(input_text),
                        "provider": "duckduckgo",
                        "hits": [],
                        "degraded": f"检索/抓取失败：{_safe_error_text(e)}",
                        "sources": [],
                    }
                    db.commit()
        finally:
            search_seconds = time.monotonic() - search_started
    else:
        _update_phase("search_skipped", 15)

    # —— F2：自动取证（多平台采集 → 去重 → 入库素材 → 并入证据包）——
    # 失败只降级不中断：采集是增强项，绝不能拖垮分析主链路。
    collect_info: dict | None = None
    if auto_collect:
        _update_phase("search", 18)
        collect_started = time.monotonic()
        try:
            from uuid import uuid4 as _uuid4

            from app.connectors.base import dedupe_items
            from app.connectors.govdoc import collect_govdoc
            from app.connectors.hotlist import collect_hotlist
            from app.connectors.rss import collect_rss
            from app.connectors.websearch import collect_websearch

            collect_query = (input_text or title or "").strip()[:200]
            raw_items: list = []
            degraded: list[str] = []
            for runner in (
                lambda: collect_websearch(collect_query, max_results=10),
                lambda: collect_govdoc(collect_query, max_results=6),
                collect_rss,
                collect_hotlist,
            ):
                got, note = runner()
                raw_items.extend(got)
                if note:
                    degraded.append(note)
            items = [it for it in dedupe_items(raw_items) if not it.duplicate_of]
            new_rows: list = []
            with SessionLocal() as db2:
                existing_urls = {
                    (row.source or "").strip().rstrip("/")
                    for row in db2.query(Material.source).all()
                    if row.source
                }
                seen_urls: set[str] = set()
                for it in items[:20]:
                    key = (it.canonical_url or it.url).rstrip("/")
                    if not key or key in existing_urls or key in seen_urls:
                        continue
                    seen_urls.add(key)
                    body = (it.content_text or it.snippet or "").strip()
                    if not body:
                        body = f"（来源：{it.url}）"
                    else:
                        body = f"{body}\n\n（来源：{it.url}）"
                    m = Material(
                        id=_uuid4().hex,
                        project_id=project_id_val,
                        owner_id=owner_id_val,
                        title=(it.title or "自动取证来源")[:200],
                        content_text=body[:100_000],
                        source_type="collect",
                        source=it.url[:500] or None,
                        tags="自动取证",
                        char_count=len(body),
                        warnings=[f"collect_channel:{it.platform}"],
                    )
                    db2.add(m)
                    new_rows.append(m)
                if new_rows:
                    db2.commit()
            new_ids = [m.id for m in new_rows]
            # 并入证据包（bundle 可能是 None：纯采集场景也要有素材可分析）
            if new_rows:
                collected_bundle = materials.bundle_from_material_rows(new_rows)
                bundle = materials.merge_bundles(bundle, collected_bundle)
                material_ids = list(material_ids) + new_ids
                with SessionLocal() as db2:
                    t2 = db2.get(Task, task_id)
                    if t2 is not None:
                        t2.material_ids = material_ids
                        db2.commit()
            collect_info = {
                "channels": ["websearch", "govdoc", "rss", "hotlist"],
                "collected": len(items),
                "saved": len(new_rows),
                "independent_sources": len(
                    {it.independence_group for it in items if it.independence_group}
                ),
                "degraded": degraded or None,
            }
            logger.info(
                "自动取证完成 task=%s collected=%s saved=%s", task_id, len(items), len(new_rows)
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("自动取证失败（已降级，不影响分析）：%s", _safe_error_text(e))
            collect_info = {"error": _safe_error_text(e)}
        finally:
            collect_seconds = round(time.monotonic() - collect_started, 3)
            if isinstance(collect_info, dict):
                collect_info["seconds"] = collect_seconds

    _emit(task_id, "generating")
    try:
        # web 素材包（bundle 为 MaterialBundle；web_on 但无素材时仍传 web_mode=True 加引用约束）
        bundle_dict = bundle.__dict__ if bundle is not None else None
        evidence_mode = bool(bundle and bundle.items)
        if mode == "rule":
            # 内置规则引擎：纯本地、不需要任何 LLM / key
            gen = ReportGenerator(
                None, analysis_type=analysis_type, mode="rule", structured=structured,
                web_mode=evidence_mode, materials=bundle_dict,
            )
        else:
            # 可选 LLM 插件：优先用每请求配置，回退 backend .env，再回退 Mock
            from app.llm_client import create_llm_from_config

            llm = create_llm_from_config(llm_config)
            gen = ReportGenerator(
                llm, analysis_type=analysis_type, mode="llm", llm_config=llm_config,
                structured=structured, web_mode=evidence_mode, materials=bundle_dict,
            )

        # on_phase 回调由 generator 在 generate/export 关键节点调用
        def _on_phase(phase: str, pct: int):
            _update_phase(phase, pct)

        # 导出瞬时故障由 generator 仅重试 export 阶段，绝不重复调用模型与证据提取。
        out = gen.generate_and_export(
            input_text, title, settings.generated_dir,
            slug=task_id, on_phase=_on_phase,
        )
        # 去掉绝对路径 folder 字段，避免外泄本地路径
        safe = {k: v for k, v in out.items() if k != "folder"}
        timings = safe.setdefault("timings", {})
        timings["search_seconds"] = round(search_seconds, 3)
        if collect_info:
            safe["collect"] = collect_info
        # raw_response 仅落库（诊断用），不推给前端/WS
        raw_response = safe.pop("raw_response", None)
        with SessionLocal() as db:
            t = db.get(Task, task_id)
            if t is None:
                return
            t.status = "done"
            t.phase = "output"
            t.progress_pct = 100
            t.result = safe
            t.error = None
            # 把搜索结果一并带出，前端 WS done 载荷即可直接展示（无需再轮询）
            safe["search_results"] = t.search_results
            # 阶段四：持久化 LLM 增强元信息
            t.llm_model = safe.get("llm_model")
            t.llm_temperature = safe.get("llm_temperature")
            t.prompt_version = safe.get("prompt_version")
            t.llm_raw_response = raw_response
            quality = safe.get("quality") or None
            t.quality_score = quality.get("score") if isinstance(quality, dict) else None
            t.quality_result = quality
            db.commit()
            # 阶段六·需求1：自动生成项目完成记录（日志）。若任务已归属某项目则更新其
            # 摘要/完成时间；否则按「每篇报告=一个已完成项目」自动建档，确保每次分析
            # 完成都有可追溯的项目记录（完成时间/名称/摘要/引擎来源/字数）。
            _auto_project_record(db, t, safe)
        from app.monitoring import record_monitor_completion

        record_monitor_completion(task_id)
        _emit(task_id, "done", safe, phase="output", progress_pct=100)
    except Exception as e:  # noqa: BLE001
        etype, ephase = _classify_error(e, last_phase["v"])
        err_msg = _safe_error_text(e)
        with SessionLocal() as db:
            t = db.get(Task, task_id)
            if t is not None:
                t.status = "error"
                t.error = err_msg
                t.error_type = etype
                t.error_phase = ephase
                t.error_detail = err_msg
                quality_result = getattr(e, "result", None)
                if quality_result is not None:
                    quality = quality_result.model_dump()
                    t.quality_score = quality.get("score")
                    t.quality_result = quality
                db.commit()
        from app.monitoring import record_monitor_completion

        record_monitor_completion(task_id)
        # 注意：必须在上面 with 块关闭前把要推送的字段取到局部变量；
        # 否则 t 已脱离 Session，访问 t.error 会抛 DetachedInstanceError，
        # 导致 WS 实时错误推送直接崩溃（前端收不到失败原因，只能靠 poll 兜底）。
        _emit(task_id, "error", {"message": err_msg, "type": etype, "phase": ephase})


def _auto_project_record(db, task, safe: dict) -> None:
    """分析完成时自动生成/更新项目记录（需求1：项目完成日志）。

    - 若任务已归属某项目（task.project_id）：更新该项目的完成时间、最新摘要、
      章节数、字数、引擎来源，使其始终反映最新一次分析成果。
    - 若未归属项目：自动以「task_id 派生项目」建档（每个已完成报告 = 一个独立已完成项目），
      名称取报告标题，描述取 Markdown 首段摘要，确保任何分析都有可追溯记录。
    """
    from app.models import Project

    md: str = safe.get("markdown") or ""
    # 内容摘要：取 Markdown 首个非空段落（去掉标题 # 号），截断 200 字
    summary = ""
    for para in md.split("\n\n"):
        p = para.strip().lstrip("#").strip()
        if len(p) > 4:
            summary = p[:200]
            break
    if not summary:
        summary = (task.input_text or task.title or "（无摘要）")[:200]
    char_count = len(md)
    # 章节数：统计 Markdown 二级及以下标题数量
    chapters = str(len([l for l in md.splitlines() if l.strip().startswith("##")]))
    engine_label = "AI模型增强生成" if safe.get("engine_used") == "llm" else "规则引擎生成"
    subjects = str(len(safe.get("network", {}).get("nodes", [])))

    if task.project_id:
        p = db.get(Project, task.project_id)
        if p is not None:
            p.description = summary
            p.status = "已完成"
            p.chapters = chapters
            p.subjects = subjects
            p.progress = "100%"
            p.updated_at = _now()
            db.commit()
            return
    # 未归属：自动建档（项目 id 与 task_id 解耦，避免与既有种子项目冲突）
    pid = f"auto_{task.id}"
    existing = db.get(Project, pid)
    if existing is None:
        p = Project(
            id=pid,
            name=task.title or "未命名分析",
            description=summary,
            status="已完成",
            subjects=subjects,
            interests=str(len(safe.get("network", {}).get("edges", []))),
            chapters=chapters,
            progress="100%",
            owner_name=settings.default_owner_name,
            owner_id=settings.default_owner_id,
            is_archived=0,
        )
        db.add(p)
        # 把任务挂到自动项目，便于项目详情聚合
        task.project_id = pid
    else:
        existing.description = summary
        existing.status = "已完成"
        existing.chapters = chapters
        existing.subjects = subjects
        existing.progress = "100%"
        existing.updated_at = _now()
        task.project_id = pid
    db.commit()


async def _worker(worker_id: int) -> None:
    from app.models import Task

    while True:
        tid = None
        # 认领：串行加锁，确保同一任务只被一个工人取走
        with _claim_lock:
            with SessionLocal() as db:
                t = (
                    db.query(Task)
                    .filter(Task.status == "queued")
                    .order_by(Task.created_at.asc())
                    .first()
                )
                if t is not None:
                    tid = t.id
                    t.status = "generating"
                    db.commit()
        if tid is not None:
            try:
                await asyncio.to_thread(_process, tid)
            except Exception:  # noqa: BLE001 - 单任务失败绝不能拖死整个 worker 池
                logger.exception("worker %s 处理任务 %s 时异常（已跳过，继续接单）", worker_id, tid)
        else:
            await asyncio.sleep(1.0)


def start_workers() -> None:
    """启动工人池（应用生命周期内常驻）。"""
    global _workers
    if _workers:
        return
    _workers = [asyncio.create_task(_worker(i)) for i in range(WORKER_COUNT)]
