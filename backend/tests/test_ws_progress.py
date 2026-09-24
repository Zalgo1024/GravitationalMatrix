"""WS 进度端点（/ws/progress/{task_id}）回归测试。

背景：analyze.py 的 ws_progress 曾把 HTTP 依赖注入的 `current` 变量误用进
WS 处理函数（该函数内只有 ws_user），执行即 NameError → 任何进度订阅直接断线。
本文件从零补齐该端点的覆盖：

- 本地模式（PUBLIC_MODE=0，conftest 默认）：无 cookie 直连可用（本地 owner 放行），
  快照正常返回；不存在的任务 → not_found。
- 公共模式（复用 test_auth_isolation 的 public_mode 夹具模式）：
  无 cookie → unauthorized；用户 A 的任务，用户 B 订阅 → not_found（不泄露存在性）。
"""
import uuid

import pytest
from fastapi.testclient import TestClient


def _make_task(owner_id: str | None = None, status: str = "generating") -> str:
    """直接向隔离库插入一条 Task，返回 task_id。"""
    from app.db import SessionLocal
    from app.models import Task

    tid = uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(
            Task(
                id=tid,
                title="WS 测试任务",
                input_text="测试输入",
                status=status,
                phase="decompose",
                progress_pct=40,
                owner_id=owner_id,
            )
        )
        db.commit()
    return tid


def _fresh_client() -> TestClient:
    from app.main import app

    return TestClient(app, base_url="https://testserver")


# ---------------------------------------------------------------------------
# 本地模式（conftest 默认 PUBLIC_MODE=0）
# ---------------------------------------------------------------------------
def test_ws_local_snapshot_and_disconnect(client):
    tid = _make_task(status="generating")
    with client.websocket_connect(f"/ws/progress/{tid}") as ws:
        msg = ws.receive_json()
        assert msg["status"] == "generating"
        assert msg["phase"] == "decompose"
        assert msg["progress_pct"] == 40


def test_ws_local_done_task_returns_snapshot(client):
    tid = _make_task(status="done")
    with client.websocket_connect(f"/ws/progress/{tid}") as ws:
        msg = ws.receive_json()
        assert msg["status"] == "done"


def test_ws_local_not_found(client):
    with client.websocket_connect(f"/ws/progress/{uuid.uuid4().hex}") as ws:
        assert ws.receive_json() == {"status": "not_found"}


# ---------------------------------------------------------------------------
# 公共模式（PUBLIC_MODE=1，函数级 monkeypatch）
# ---------------------------------------------------------------------------
@pytest.fixture()
def public_mode(client, monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "public_mode", True)
    yield


def _register(c: TestClient, email: str, password: str = "Passw0rd!123") -> str:
    r = c.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["user"]["id"]


def _ws_connect(c: TestClient, path: str):
    """带认证 cookie 建立 WS 连接。

    登录 cookie 带 Secure 标志，TestClient 的 websocket_connect 走 ws:// 不会
    自动回传，因此从 cookie jar 取出 token 手动塞进 Cookie 头。
    """
    token = c.cookies.get("sy_token")
    headers = {"cookie": f"sy_token={token}"} if token else {}
    return c.websocket_connect(path, headers=headers)


def test_ws_public_unauthorized_without_cookie(client, public_mode):
    tid = _make_task()
    c = _fresh_client()  # 无 cookie
    with c.websocket_connect(f"/ws/progress/{tid}") as ws:
        assert ws.receive_json() == {"status": "unauthorized"}


def test_ws_public_owner_isolation(client, public_mode):
    ca = _fresh_client()
    owner_id = _register(ca, "ws_owner@test.local")
    tid = _make_task(owner_id=owner_id)

    # 属主本人：正常收到快照
    with _ws_connect(ca, f"/ws/progress/{tid}") as ws:
        assert ws.receive_json()["status"] == "generating"

    # 其他用户：not_found，不泄露存在性
    cb = _fresh_client()
    _register(cb, "ws_other@test.local")
    with _ws_connect(cb, f"/ws/progress/{tid}") as ws:
        assert ws.receive_json() == {"status": "not_found"}
