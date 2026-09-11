"""用户系统 Phase 2：审计日志（AuditLog）测试。

覆盖：
- register / login_failed / login_blocked / change_password 留痕；
- admin ban / unban / role_change / 代发重置链接 留痕；
- admin project.delete / task.delete 留痕；
- GET /api/admin/audit 仅 admin 可访问，且支持 action / actor_id 过滤；
- 普通用户访问 audit 端点 → 403。
"""
import uuid

import pytest

from fastapi.testclient import TestClient


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


def _fresh_client() -> TestClient:
    from app.main import app

    return TestClient(app, base_url="https://testserver")


def _register(c: TestClient, email: str, password: str = "Passw0rd!123"):
    r = c.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _login(c: TestClient, email: str, password: str = "Passw0rd!123"):
    r = c.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text


def _admin_client(email: str) -> TestClient:
    """直接造一个 admin 账号（绕过注册限流 + 提升 role），登录后返回客户端。"""
    from app.auth import hash_password
    from app.db import SessionLocal
    from app.models import User

    pw = "Passw0rd!123"
    with SessionLocal() as db:
        u = User(
            id=uuid.uuid4().hex,
            email=email,
            display_name="审计测试 admin",
            hashed_password=hash_password(pw),
            role="admin",
            email_verified=1,
        )
        db.add(u)
        db.commit()

    c = _fresh_client()
    _login(c, email, pw)
    return c


def _audit_actions(db, action: str):
    from app.models import AuditLog

    return db.query(AuditLog).filter(AuditLog.action == action).all()


# ---------------------------------------------------------------------------
# 鉴权 / 角色门槛
# ---------------------------------------------------------------------------
def test_audit_endpoint_requires_admin(client, public_mode):
    """普通用户访问 /api/admin/audit → 403；未登录 → 401。"""
    cu = _fresh_client()
    _register(cu, "iso_audit_plain@test.local")
    r = cu.get("/api/admin/audit")
    assert r.status_code == 403

    anon = _fresh_client()
    assert anon.get("/api/admin/audit").status_code == 401


def test_audit_endpoint_filter_by_action_and_actor(client, public_mode):
    """action / actor_id 过滤能落到查询结果上。"""
    c = _admin_client("iso_audit_admin@test.local")

    # 触发一个可识别的 audit
    cu = _fresh_client()
    target_email = "iso_audit_target@test.local"
    _register(cu, target_email)
    target_id = cu.get("/api/auth/me").json()["user"]["id"]

    r = c.post(
        f"/api/admin/users/{target_id}/ban",
        json={"banned": 1},
    )
    assert r.status_code == 200

    # 按 action 过滤
    r_ban = c.get("/api/admin/audit?action=user.ban")
    assert r_ban.status_code == 200
    rows = r_ban.json()["logs"]
    assert any(row["target_id"] == target_id for row in rows)

    # 按 actor_id 过滤（admin 自己）
    me_id = c.get("/api/auth/me").json()["user"]["id"]
    r_actor = c.get(f"/api/admin/audit?actor_id={me_id}&action=user.ban")
    assert r_actor.status_code == 200
    assert all(row["actor_id"] == me_id for row in r_actor.json()["logs"])


# ---------------------------------------------------------------------------
# 各动作留痕
# ---------------------------------------------------------------------------
def test_register_writes_audit(client, public_mode):
    from app.db import SessionLocal

    cu = _fresh_client()
    _register(cu, "iso_audit_reg@test.local")
    with SessionLocal() as db:
        rows = _audit_actions(db, "auth.register")
    assert len(rows) >= 1
    assert rows[-1].actor_email == "iso_audit_reg@test.local"
    assert rows[-1].target_type == "user"


def test_login_failed_writes_audit(client, public_mode):
    from app.db import SessionLocal

    c = _fresh_client()
    # 注册后用错密码登录
    _register(c, "iso_audit_loginf@test.local")
    r = c.post(
        "/api/auth/login",
        json={"email": "iso_audit_loginf@test.local", "password": "WrongPass!1"},
    )
    assert r.status_code == 401
    with SessionLocal() as db:
        rows = _audit_actions(db, "auth.login_failed")
    assert any(r.target_id == "iso_audit_loginf@test.local" for r in rows)


def test_login_blocked_writes_audit(client, public_mode):
    """被封禁账号尝试登录 → audit.login_blocked。"""
    from app.auth import hash_password
    from app.db import SessionLocal
    from app.models import User

    # 直接造一个被封禁的用户（绕开注册流，避免触发 login_blocked 之外的 audit）
    with SessionLocal() as db:
        db.add(
            User(
                id=uuid.uuid4().hex,
                email="iso_audit_banned@test.local",
                display_name="封禁用户",
                hashed_password=hash_password("Passw0rd!123"),
                role="user",
                email_verified=1,
                is_banned=1,
            )
        )
        db.commit()

    c = _fresh_client()
    r = c.post(
        "/api/auth/login",
        json={"email": "iso_audit_banned@test.local", "password": "Passw0rd!123"},
    )
    assert r.status_code == 403
    with SessionLocal() as db:
        rows = _audit_actions(db, "auth.login_blocked")
    assert any(r.target_id and len(r.target_id) > 0 for r in rows)


def test_change_password_writes_audit(client, public_mode):
    from app.db import SessionLocal

    c = _fresh_client()
    _register(c, "iso_audit_chgpw@test.local")
    r = c.post(
        "/api/auth/change-password",
        json={"current_password": "Passw0rd!123", "new_password": "NewPassw0rd!456"},
    )
    assert r.status_code == 200
    with SessionLocal() as db:
        rows = _audit_actions(db, "auth.change_password")
    assert any(rows)


def test_admin_ban_writes_audit(client, public_mode):
    c = _admin_client("iso_audit_ban_admin@test.local")
    cu = _fresh_client()
    _register(cu, "iso_audit_ban_target@test.local")
    tid = cu.get("/api/auth/me").json()["user"]["id"]

    c.post(f"/api/admin/users/{tid}/ban", json={"banned": 1})
    c.post(f"/api/admin/users/{tid}/ban", json={"banned": 0})

    from app.db import SessionLocal

    with SessionLocal() as db:
        bans = _audit_actions(db, "user.ban")
        unbans = _audit_actions(db, "user.unban")
    assert any(r.target_id == tid for r in bans)
    assert any(r.target_id == tid for r in unbans)


def test_admin_role_change_writes_audit(client, public_mode):
    c = _admin_client("iso_audit_role_admin@test.local")
    cu = _fresh_client()
    _register(cu, "iso_audit_role_target@test.local")
    tid = cu.get("/api/auth/me").json()["user"]["id"]

    r = c.post(f"/api/admin/users/{tid}/role", json={"role": "admin"})
    assert r.status_code == 200

    from app.db import SessionLocal

    with SessionLocal() as db:
        rows = _audit_actions(db, "user.role_change")
    assert any(r.target_id == tid and r.detail and r.detail.get("to") == "admin" for r in rows)


def test_admin_reset_password_link_writes_audit(client, public_mode):
    c = _admin_client("iso_audit_reset_admin@test.local")
    cu = _fresh_client()
    _register(cu, "iso_audit_reset_target@test.local")
    tid = cu.get("/api/auth/me").json()["user"]["id"]

    r = c.post(f"/api/admin/users/{tid}/reset-password")
    assert r.status_code == 200
    assert "reset_url" in r.json()

    from app.db import SessionLocal

    with SessionLocal() as db:
        rows = _audit_actions(db, "user.reset_password_link")
    assert any(r.target_id == tid for r in rows)


def test_admin_project_delete_writes_audit(client, public_mode):
    """管理面删除项目：必须 confirm=true，写 audit。"""
    c = _admin_client("iso_audit_proj_admin@test.local")

    # 直接塞一个 Project（避免走 owner_id 复杂的本地创建流）
    from app.models import Project
    from app.db import SessionLocal

    pid = uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(Project(id=pid, name="审计测试项目", status="active", is_archived=0))
        db.commit()

    r = c.post(f"/api/admin/projects/{pid}/delete", json={"confirm": True})
    assert r.status_code == 200

    with SessionLocal() as db:
        rows = _audit_actions(db, "project.delete")
    assert any(r.target_id == pid for r in rows)


def test_admin_task_delete_writes_audit(client, public_mode):
    """管理面删除任务：必须 confirm=true，写 audit。"""
    c = _admin_client("iso_audit_task_admin@test.local")

    from app.models import Task
    from app.db import SessionLocal

    tid = uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(
            Task(
                id=tid,
                title="审计测试任务",
                input_text="x",
                analysis_type="case",
                status="done",
                mode="rule",
            )
        )
        db.commit()

    r = c.post(f"/api/admin/tasks/{tid}/delete", json={"confirm": True})
    assert r.status_code == 200

    with SessionLocal() as db:
        rows = _audit_actions(db, "task.delete")
    assert any(r.target_id == tid for r in rows)


def test_admin_role_change_cannot_demote_self(client, public_mode):
    """admin 不能降自己 → 400；可降其他 admin → 200。

    注：「保证至少一名 admin」的守卫在当前 endpoint 设计下不可达：
    caller 必须本身是 admin（require_admin 守住），caller != target 时 caller
    就是「另一个 admin」，`others >= 1` 永远成立。caller == target 时又被 self-demote
    守卫拦住。所以该守卫是防御性兜底，不在测试覆盖范围。
    """
    c = _admin_client("iso_audit_solo_admin@test.local")
    me_id = c.get("/api/auth/me").json()["user"]["id"]

    # 降自己 → 400
    r_self = c.post(f"/api/admin/users/{me_id}/role", json={"role": "user"})
    assert r_self.status_code == 400
    assert "自己" in r_self.json()["message"]

    # 升 / 降另一个 admin → 200
    cu = _fresh_client()
    _register(cu, "iso_audit_other_admin@test.local")
    other_id = cu.get("/api/auth/me").json()["user"]["id"]
    from app.db import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        db.get(User, other_id).role = "admin"
        db.commit()
    r_up = c.post(f"/api/admin/users/{other_id}/role", json={"role": "admin"})
    assert r_up.status_code == 200
    assert r_up.json()["changed"] is False  # 已是 admin，幂等

    r_down = c.post(f"/api/admin/users/{other_id}/role", json={"role": "user"})
    assert r_down.status_code == 200
    assert r_down.json()["changed"] is True

    # 非法角色 → 400
    r_bad = c.post(f"/api/admin/users/{other_id}/role", json={"role": "superuser"})
    assert r_bad.status_code == 400
    assert r_bad.json()["error"] == "invalid"