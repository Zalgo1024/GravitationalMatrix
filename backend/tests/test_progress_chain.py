"""阶段八（测试与验证）：6 步分析进度链的自动化用例。

专注验证「分析界面优化」新增的、此前未被覆盖的可观察行为：

1. 6 步 phase 序列（inspect→search_skipped/search→decompose→network→organize→output→done）
   及其进度百分比，逐阶段精确推进；
2. 未配置搜索 API 时第 2 步自动 search_skipped（不报错、不卡死）；
3. 已配置搜索 API 时第 2 步进入 search（"搜索中"分支可达）；
4. poll / GET /api/analyze/{id} 返回 phase 与 progress_pct（WS 断线重连恢复）；
5. 失败任务的 error_phase 精确落在 6 步链中（导出失败→output；拆解崩溃→按关键词校正）；
6. 重试端点返回新 task_id + retry_of + attempt_no（阶段七 闭环）。

为避免域引擎 / 文件锁 / 安全删除屏障影响，本文件用 monkeypatch 把 export_report 与
diagnose_pdf 替换为无副作用的桩，专注验证「进度编排」逻辑本身
（真实引擎已由 test_e2e.py / test_api.py::test_analyze_rule_pipeline 覆盖）。

注意：所有 app.* 导入都延迟到函数/夹具内部，确保绑定到 conftest 打过补丁的
（隔离临时库的）模块，而不是在收集阶段抢先绑定到真实开发库。
"""
import threading
import uuid

import pytest

from app.models import Task  # Task 仅依赖 Base（补丁不替换），可在顶层导入


class _Collect:
    """线程安全的进度收集器，模拟 WS 订阅队列（仅实现 put_nowait）。"""

    def __init__(self) -> None:
        self.items: list[dict] = []
        self._lock = threading.Lock()

    def put_nowait(self, msg: dict) -> None:
        with self._lock:
            self.items.append(msg)


@pytest.fixture
def subbed():
    """为测试注册内存进度收集器，返回 (tid) -> 收集器。"""
    import app.queue as queue

    registered: dict[str, _Collect] = {}

    def reg(tid: str) -> _Collect:
        c = _Collect()
        # 适配多订阅者结构：{queue: loop}；loop=None 表示同步调用方
        queue._subscribers[tid] = {c: None}
        registered[tid] = c
        return c

    yield reg
    for tid in list(registered):
        queue._subscribers.pop(tid, None)


def _insert_task(**kw) -> str:
    import app.db as dbmod

    tid = "t_" + uuid.uuid4().hex[:12]
    mode = kw.get("mode", "rule")
    structured = kw.get("structured")
    if structured is None and mode == "rule":
        structured = _valid_structured()
    with dbmod.SessionLocal() as db:
        db.add(
            Task(
                id=tid,
                title=kw.get("title", "阶段八验证任务"),
                input_text=kw.get("input_text", "深圳赛格广场晃动事件"),
                analysis_type=kw.get("analysis_type", "case"),
                mode=mode,
                input_mode=kw.get(
                    "input_mode", "structured" if structured is not None else "freeform"
                ),
                requested_engine=kw.get("requested_engine", mode),
                structured=structured,
                status=kw.get("status", "generating"),
                search_enabled=kw.get("search_enabled", None),
                web=kw.get("web", False),
            )
        )
        db.commit()
    return tid


def _valid_structured() -> dict:
    return {
        "title": "阶段八验证任务",
        "analysis_type": "case",
        "event": "某地发生一项涉及公共机构和服务对象的规则调整。",
        "actors": [
            {"name": "公共机构", "interest_types": ["public"]},
            {"name": "服务对象", "interest_types": ["material"]},
        ],
        "relations": [
            {
                "source": "公共机构",
                "target": "服务对象",
                "label": "规则执行",
                "type": "power",
            }
        ],
        "evidence": [
            {
                "content": "公开文件记录了该规则调整。",
                "source": "https://example.com/source",
            }
        ],
        "recommendations": [
            {
                "target": "公共机构",
                "action": "公开规则依据和反馈渠道。",
            }
        ],
    }


def _run(tid: str, timeout: int = 60) -> list[str]:
    """在独立线程跑 queue._process，返回其中抛出的异常摘要列表。"""
    import app.queue as queue

    errs: list[str] = []

    def _runner() -> None:
        try:
            queue._process(tid)
        except Exception as e:  # noqa: BLE001
            errs.append(repr(e))

    th = threading.Thread(target=_runner)
    th.start()
    th.join(timeout)
    return errs


@pytest.fixture
def mock_export(monkeypatch):
    """把导出与 PDF 诊断替换为无副作用桩（不写文件、不触引擎）。"""

    def fake_export(title, markdown, output_dir=None, slug=None, data_tables=None):
        return {"word": "fake.docx", "diagrams": ["d1"], "title": title}

    monkeypatch.setattr("app.generator.export_report", fake_export)
    monkeypatch.setattr(
        "app.engine_bridge.diagnose_pdf",
        lambda: {"libreoffice": False, "pandoc": False, "word_com": False},
    )


def test_six_step_phase_sequence(client, subbed, mock_export):
    """核心：6 步 phase 严格按序推进，进度百分比匹配方案。"""
    tid = _insert_task(input_text="某纯线下事件描述文本")
    coll = subbed(tid)
    errs = _run(tid)
    assert not errs, f"_process 抛异常: {errs}"

    # 仅取 status=generating 的 6 步阶段标记（done/error 消息也带 phase，需排除）
    seq = [
        (m.get("phase"), m.get("progress_pct"))
        for m in coll.items
        if m.get("status") == "generating" and m.get("phase")
    ]
    assert seq == [
        ("inspect", 5),
        ("search_skipped", 15),
        ("decompose", 25),
        ("network", 55),
        ("organize", 75),
        ("output", 85),
    ], seq

    done = [m for m in coll.items if m.get("status") == "done"]
    assert done, "应收到 done 消息"
    assert done[-1]["progress_pct"] == 100
    assert done[-1]["phase"] == "output"


def test_url_input_without_key_still_skips(client, subbed, mock_export):
    """含链接但无搜索 key 时，第 2 步应优雅跳过，而非卡死或报错。"""
    tid = _insert_task(input_text="https://news.example.com/saige 某事件")
    coll = subbed(tid)
    _run(tid)

    phases = [m.get("phase") for m in coll.items if m.get("phase")]
    assert "search_skipped" in phases, "无搜索 key 时含链接也应优雅跳过"
    assert not any(m.get("status") == "error" for m in coll.items)


def test_search_active_when_configured(client, subbed, mock_export, monkeypatch):
    """T1/T8：web 开启时，第 2 步应进入 search→fetch（"检索/抓取"分支可达）。"""
    from app.search import SearchHit, SearchResult

    monkeypatch.setattr(
        "app.search.search_web",
        lambda q, max_results=5: SearchResult(
            query=q,
            hits=[SearchHit(title="测试标题", url="https://example.com/a", snippet="摘要1")],
            provider="duckduckgo",
        ),
    )
    monkeypatch.setattr(
        "app.search.fetch_and_clean",
        lambda urls, max_chars=8000: [
            {"title": "测试标题", "url": "https://example.com/a", "text": "正文内容正文内容正文内容", "snippet": "摘要1"}
        ],
    )

    tid = _insert_task(input_text="某事件", web=True)
    coll = subbed(tid)
    _run(tid)

    phases = [m.get("phase") for m in coll.items if m.get("phase")]
    assert "search" in phases, "web 开启时应进入 search 阶段而非跳过"
    assert "search_skipped" not in phases


def test_poll_recovers_phase_and_progress(client, subbed, mock_export):
    """WS 断线后可用 poll 恢复最新 phase / progress_pct。"""
    tid = _insert_task(input_text="夜间经济新规分析")
    _run(tid)

    r = client.get(f"/api/analyze/{tid}/poll")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "done"
    assert body["phase"] == "output"
    assert body["progress_pct"] == 100
    assert "server_time" in body

    # 顶层 /api/analyze 也应透出 phase / progress_pct
    r2 = client.get(f"/api/analyze/{tid}")
    assert r2.json()["phase"] == "output"
    assert r2.json()["progress_pct"] == 100


def test_error_phase_classified_to_six_steps(client, subbed, monkeypatch):
    """导出失败时，error_phase 精确落在第 6 步 output（而非笼统的 export）。"""
    def boom(title, markdown, output_dir=None, slug=None, data_tables=None):  # noqa: ANN001
        raise RuntimeError("docx export failed: disk full")

    monkeypatch.setattr("app.generator.export_report", boom)

    tid = _insert_task(input_text="某事件")
    coll = subbed(tid)
    _run(tid)

    err_msgs = [m for m in coll.items if m.get("status") == "error"]
    assert err_msgs, "应收到 error 消息"
    err = err_msgs[-1]["data"]
    assert err["phase"] == "output", err
    assert err["type"] == "RuntimeError"

    r = client.get(f"/api/analyze/{tid}/poll")
    assert r.json()["data"]["phase"] == "output"


def test_classify_error_matrix():
    """_classify_error 的 6 步定位矩阵：不早于当前阶段、关键词可后推、不倒退。"""
    from app.queue import PHASE_STEP, _classify_error

    # 当前阶段 organize，普通错误 -> organize
    assert _classify_error(RuntimeError("x"), "organize") == ("RuntimeError", "organize")
    # docx 错误但当前仅 network -> 关键词后推到 output
    assert _classify_error(RuntimeError("docx broken"), "network") == ("RuntimeError", "output")
    # diagram 错误但当前已在 output -> 不倒退为 network
    assert _classify_error(RuntimeError("diagram lost"), "output") == ("RuntimeError", "output")
    # diagram 错误且当前仅 search_skipped -> 后推到 network
    assert _classify_error(RuntimeError("diagram lost"), "search_skipped") == (
        "RuntimeError",
        "network",
    )
    # 6 步 phase 全部在错误步骤映射中
    for p in ("inspect", "search", "search_skipped", "decompose", "network", "organize", "output"):
        assert p in PHASE_STEP


def test_should_search_rules():
    """搜索判定（真实实现：有文本即搜，真正开关在 _process 的 search_configured）。"""
    from app.search import should_search

    assert should_search("") is False
    assert should_search("短词") is True
    assert should_search("https://a.com/x") is True
    long_offline = (
        "这是一段超过八十个字符的纯线下材料，详细描述了一个事件的来龙去脉，"
        "各方立场与利益诉求，没有任何外链可供检索参考使用。"
    )
    assert should_search(long_offline) is True


def test_retry_endpoint_lineage(client):
    """重试端点返回新 task_id + retry_of + attempt_no（阶段七 闭环）。"""
    import app.db as dbmod

    tid = _insert_task(status="error", input_text="失败任务")
    with dbmod.SessionLocal() as db:
        t = db.get(Task, tid)
        t.error = "boom"
        t.error_phase = "output"
        t.error_type = "RuntimeError"
        db.commit()

    r = client.post(f"/api/analyze/{tid}/retry")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["new_task_id"] and body["new_task_id"] != tid
    assert body["retry_of"] == tid
    assert body["attempt_no"] == 2


def test_search_active_stores_and_surfaces_results(client, subbed, mock_export, monkeypatch):
    """T1/T8 完整联网激活路径：web=True 时第 2 步进入 search，
    检索结果写入 Task.search_results（hits/degraded/sources），并随 done 载荷推给前端。"""
    import app.db as dbmod
    from app.search import SearchHit, SearchResult

    monkeypatch.setattr(
        "app.search.search_web",
        lambda q, max_results=5: SearchResult(
            query=q,
            hits=[SearchHit(title="测试标题", url="https://example.com/a", snippet="摘要1")],
            provider="duckduckgo",
        ),
    )
    monkeypatch.setattr(
        "app.search.fetch_and_clean",
        lambda urls, max_chars=8000: [
            {"title": "测试标题", "url": "https://example.com/a", "text": "正文内容正文内容正文内容", "snippet": "摘要1"}
        ],
    )

    tid = _insert_task(input_text="深圳赛格广场晃动事件", web=True)
    coll = subbed(tid)
    _run(tid)

    phases = [m.get("phase") for m in coll.items if m.get("phase")]
    assert "search" in phases, "web 开启时应进入 search 阶段"
    assert "search_skipped" not in phases

    # 结果落库
    with dbmod.SessionLocal() as db:
        t = db.get(Task, tid)
        sr = t.search_results
    assert sr, "搜索结果应写入 Task.search_results"
    assert sr["provider"] == "duckduckgo"
    assert isinstance(sr["hits"], list) and len(sr["hits"]) > 0
    assert isinstance(sr["sources"], list) and len(sr["sources"]) > 0

    # done 载荷携带 search_results（前端可直展示，无需再轮询）
    done = [m for m in coll.items if m.get("status") == "done"]
    assert done, "应收到 done"
    assert done[-1]["data"].get("search_results") == sr


def test_grayscale_off_forces_skip(client, subbed, mock_export, monkeypatch):
    """灰度总开关 SEARCH_ENABLED=off 时，即使 web 开启，第 2 步一律 search_skipped。"""
    import app.queue as queue

    monkeypatch.setattr(queue.settings, "search_enabled", "off")

    tid = _insert_task(input_text="某事件", search_enabled=True, web=True)
    coll = subbed(tid)
    _run(tid)

    phases = [m.get("phase") for m in coll.items if m.get("phase")]
    assert "search_skipped" in phases, "灰度关闭时应全局跳过搜索"
    assert "search" not in phases


def test_search_settings_endpoint(client, monkeypatch):
    """GET /api/settings/search 脱敏返回 available/configured/provider。"""
    import app.queue as queue

    monkeypatch.setattr(type(queue.settings), "search_available", property(lambda self: True))
    monkeypatch.setattr(type(queue.settings), "search_configured", property(lambda self: True))
    monkeypatch.setattr(queue.settings, "search_provider", "mock")

    r = client.get("/api/settings/search")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True
    assert body["configured"] is True
    assert body["provider"] == "mock"
    assert "search_api_key" not in body  # 绝不泄露明文 key


def test_recover_interrupted_resets_stuck_generating(client, monkeypatch):
    """崩溃恢复：启动时把卡在 generating 的孤儿任务重置回 queued，由工人重新接单。"""
    import app.queue as queue
    from app.db import SessionLocal

    tid = _insert_task(input_text="某任务", status="generating", mode="rule")
    queue.recover_interrupted()

    with SessionLocal() as db:
        t = db.get(Task, tid)
        assert t is not None
        assert t.status == "queued", "generating 孤儿任务应被重置回 queued"


def test_search_failure_degrades_without_crashing(client, subbed, mock_export, monkeypatch):
    """联网检索抛异常时必须优雅降级（写 degraded 标记），绝不能让 _process 崩溃。

    回归保护：曾因 queue 未定义 logger，此处 except 分支抛 NameError 使任务卡死。
    """
    import app.queue as queue
    from app.db import SessionLocal

    def boom(q, max_results=5):
        raise RuntimeError("检索源挂了")

    monkeypatch.setattr("app.search.search_web", boom)

    tid = _insert_task(input_text="某事件", web=True)
    coll = subbed(tid)
    errs = _run(tid)
    assert not errs, f"_process 不应因检索失败崩溃: {errs}"

    with SessionLocal() as db:
        t = db.get(Task, tid)
        assert t.status == "done", t.status
        assert t.search_results is not None
        degraded = t.search_results.get("degraded") if isinstance(t.search_results, dict) else None
        assert degraded, "应写入降级标记，而非静默吞掉失败"
    assert not any(m.get("status") == "error" for m in coll.items)


def test_structured_llm_task_passes_rule_fallback_payload(
    client, subbed, monkeypatch
):
    import app.queue as queue

    captured = {}

    class FakeGenerator:
        def __init__(self, llm, **kwargs):
            captured.update(kwargs)

        def generate_and_export(self, input_text, title, output_dir, slug=None, on_phase=None, region_scope=None):
            for phase, pct in (
                ("decompose", 25),
                ("network", 55),
                ("organize", 75),
                ("output", 85),
            ):
                on_phase(phase, pct)
            return {
                "markdown": "## 一、测试\n\n正文内容。",
                "network": {"nodes": [], "edges": []},
                "engine_used": "llm",
            }

    monkeypatch.setattr(queue, "ReportGenerator", FakeGenerator)
    monkeypatch.setattr("app.llm_client.create_llm_from_config", lambda config: object())

    structured = _valid_structured()
    tid = _insert_task(
        mode="llm",
        input_mode="structured",
        requested_engine="llm",
        structured=structured,
    )
    coll = subbed(tid)
    errs = _run(tid)

    assert not errs
    assert captured["structured"] == structured
    assert any(item.get("status") == "done" for item in coll.items)


def test_quality_gate_failure_is_persisted_with_its_own_phase(
    client, subbed, monkeypatch
):
    from app.db import SessionLocal

    monkeypatch.setattr(
        "app.rule_engine.generate",
        lambda _structured: "# 失败报告\n\n## 结论\n\n（未提供分析）",
    )
    tid = _insert_task()
    coll = subbed(tid)

    _run(tid)

    with SessionLocal() as db:
        task = db.get(Task, tid)
        assert task.status == "error"
        assert task.error_phase == "quality_gate"
        assert task.quality_result["valid"] is False
        assert any(
            issue["code"] == "failure_placeholder"
            for issue in task.quality_result["issues"]
        )
    assert any(item.get("status") == "error" for item in coll.items)
