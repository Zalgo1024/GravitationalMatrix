"""应用层 DoS / 滥用防护（S1 限流 / S2 用户配额 / S3 全局闸门）测试。

防护实现在 app/routers/analyze.py(_check_rate_limit / _guard_enqueue) 与
app/routers/search.py(search_preview 匿名 IP 限流)。设计要点：
- 仅 PUBLIC_MODE=1 生效；本地(PUBLIC_MODE=0)一律放行，保证「本地零回归」。
- 纯函数级测试直接验证守卫逻辑，不触发真实分析引擎(避免慢/外部依赖)。

复用 test_auth_isolation / test_admin_ops 的隔离策略：
依赖 session 级 client(触发 startup+隔离 DB)，monkeypatch settings.public_mode。
"""
import uuid

import pytest


@pytest.fixture()
def public_mode(client, monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "public_mode", True)
    yield


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    from app.auth import rate_limiter

    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


def _mk_task(db, uid: str, status: str = "queued") -> str:
    from app.models import Task

    tid = uuid.uuid4().hex
    db.add(
        Task(
            id=tid,
            title="t",
            input_text="x",
            analysis_type="case",
            status=status,
            owner_id=uid,
            mode="rule",
        )
    )
    return tid


# ---------------------------------------------------------------------------
# S2 用户并发配额
# ---------------------------------------------------------------------------
def test_user_active_quota_blocks_when_full(client, public_mode, monkeypatch):
    """某用户 queued/generating 达上限时，再入队应被拒(429)；未满放行。"""
    from app.routers.analyze import _MAX_USER_ACTIVE, _guard_enqueue

    from app.db import SessionLocal
    from app.models import User

    uid = uuid.uuid4().hex
    monkeypatch.setattr("app.routers.analyze._MAX_USER_ACTIVE", 3)
    with SessionLocal() as db:
        db.add(User(id=uid, email=f"{uid}@t.local", hashed_password="x", role="user"))
        for _ in range(3):
            _mk_task(db, uid, "queued")
        db.commit()

        # 已达上限 → 429
        with pytest.raises(Exception) as ei:
            _guard_enqueue(db, uid)
        assert getattr(ei.value, "status_code", None) == 429

        # 清掉一个 → 可入队
        from app.models import Task

        one = db.query(Task).filter(Task.owner_id == uid).first()
        db.delete(one)
        db.commit()
        _guard_enqueue(db, uid)  # 不应抛


def test_user_active_quota_ignores_done_tasks(client, public_mode, monkeypatch):
    """已完成/失败任务不计入活跃配额，不误伤正常用户。"""
    from app.routers.analyze import _guard_enqueue

    from app.db import SessionLocal
    from app.models import User

    uid = uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(User(id=uid, email=f"{uid}@t.local", hashed_password="x", role="user"))
        # 5 个 done + 1 个 queued：active=1，应放行
        for _ in range(5):
            _mk_task(db, uid, "done")
        _mk_task(db, uid, "queued")
        db.commit()
        _guard_enqueue(db, uid)  # 不抛


# ---------------------------------------------------------------------------
# S3 全局排队闸门
# ---------------------------------------------------------------------------
def test_global_queue_gate_blocks_when_full(client, public_mode, monkeypatch):
    """全局 queued 达上限 → 503；新用户也进不来（保护整个服务）。"""
    from app.routers.analyze import _guard_enqueue

    monkeypatch.setattr("app.routers.analyze._MAX_GLOBAL_QUEUE", 4)
    monkeypatch.setattr("app.routers.analyze._MAX_USER_ACTIVE", 99)

    from app.db import SessionLocal
    from app.models import User

    owner_a = uuid.uuid4().hex
    owner_b = uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(User(id=owner_a, email=f"{owner_a}@t.local", hashed_password="x", role="user"))
        db.add(User(id=owner_b, email=f"{owner_b}@t.local", hashed_password="x", role="user"))
        for _ in range(4):
            _mk_task(db, owner_a, "queued")
        db.commit()

        # owner_b 自身 active=0，但全局已满 → 503
        with pytest.raises(Exception) as ei:
            _guard_enqueue(db, owner_b)
        assert getattr(ei.value, "status_code", None) == 503


# ---------------------------------------------------------------------------
# S1 提交频率限流
# ---------------------------------------------------------------------------
def test_analyze_rate_limit_blocks_after_threshold(client, public_mode, monkeypatch):
    """公网下同一用户同一 IP 短时内超频提交 → 429。"""
    from app.routers.analyze import _check_rate_limit

    monkeypatch.setattr("app.routers.analyze._RATE_LIMIT", 3)
    monkeypatch.setattr("app.routers.analyze._RATE_WINDOW", 60)

    uid = uuid.uuid4().hex
    ip = "203.0.113.7"
    for _ in range(3):
        _check_rate_limit(uid, ip)  # 前 3 次通过
    with pytest.raises(Exception) as ei:
        _check_rate_limit(uid, ip)  # 第 4 次拒绝
    assert getattr(ei.value, "status_code", None) == 429


# ---------------------------------------------------------------------------
# 本地零回归：PUBLIC_MODE=0 一律放行
# ---------------------------------------------------------------------------
def test_local_mode_passthrough(client, monkeypatch):
    """本地模式(PUBLIC_MODE=0)下配额/限流/闸门全部放行，不影响本机使用。"""
    from app.routers.analyze import _check_rate_limit, _guard_enqueue

    monkeypatch.setattr("app.routers.analyze._MAX_USER_ACTIVE", 0)
    monkeypatch.setattr("app.routers.analyze._MAX_GLOBAL_QUEUE", 0)
    monkeypatch.setattr("app.routers.analyze._RATE_LIMIT", 0)

    # public_mode 默认 False（conftest 锁回归基线）→ 全放行
    from app.db import SessionLocal
    from app.models import User

    uid = uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(User(id=uid, email=f"{uid}@t.local", hashed_password="x", role="user"))
        db.commit()
        _guard_enqueue(db, uid)  # 即使阈值 0 也放行（本地）
    _check_rate_limit(uid, "127.0.0.1")  # 不抛


# ---------------------------------------------------------------------------
# 匿名检索限流（search/preview）——只测 429 分支，mock 掉真实检索避免外网
# ---------------------------------------------------------------------------
def test_search_preview_rate_limit_anonymous(client, public_mode, monkeypatch):
    """匿名 /api/search/preview：公网下超频 → 429；未超频走 mock 检索正常。"""
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.routers.search.search_web",
        lambda q, n: SimpleNamespace(query=q, provider="mock", hits=[], degraded=""),
    )
    monkeypatch.setattr("app.routers.search._SEARCH_RATE", 3)
    monkeypatch.setattr("app.routers.search._SEARCH_WINDOW", 60)

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app, base_url="https://testserver") as c:
        # 未超频：正常返回（mock 检索为空 hits）
        r = c.post("/api/search/preview", json={"query": "hi"})
        assert r.status_code == 200, r.text
        for _ in range(3):
            c.post("/api/search/preview", json={"query": "hi"})
        r429 = c.post("/api/search/preview", json={"query": "hi"})
        assert r429.status_code == 429, r429.text


# ---------------------------------------------------------------------------
# 账户恢复流（forgot-password）限速 —— 邮箱维度 limit=3 / window=600s
# ---------------------------------------------------------------------------
def test_forgot_password_email_rate_limit(client, public_mode, monkeypatch):
    """同一邮箱短时间内连续申请重置 → 第 4 次 429。

    IP 维度 limit=5 容易在测试间共享计数（多 client 同一 IP），改用邮箱维度作为稳定断言。
    """
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setattr(
        "app.routers.auth.send_password_reset_email",
        lambda to, url, ttl: True,
    )

    with TestClient(app, base_url="https://testserver") as c:
        # 先注册（注册本身也走限速；reset 后清零再注册）
        c.post(
            "/api/auth/register",
            json={"email": "abuse_forgot@test.local", "password": "Passw0rd!123"},
        )
        # 重置限速计数，避免注册阶段的命中影响 forgot 阶段断言
        from app.auth import rate_limiter

        rate_limiter._hits.clear()

        statuses = []
        for _ in range(4):
            r = c.post(
                "/api/auth/forgot-password",
                json={"email": "abuse_forgot@test.local"},
            )
            statuses.append(r.status_code)
        assert statuses[:3] == [200, 200, 200]
        assert statuses[3] == 429
