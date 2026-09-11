"""用户系统 Phase 0：注册 / 登录 / 登出 / 数据隔离（PUBLIC_MODE=1）测试。

核心断言：
- 公共模式下未登录访问业务接口 → 401；
- 注册即登录（下发 httpOnly cookie），/me 能读回身份；
- 用户 A 创建的项目，用户 B 与匿名访客均不可见（列表过滤 + 单查 not_found，不泄露存在性）；
- 材料同样按 owner 隔离；
- PUBLIC_MODE=0（本地单机）行为零变化：无 cookie 也能读写（回归保护）。

注意：monkeypatch settings.public_mode 是函数级夹具，测试结束自动还原，
不影响其余 186 个本地模式测试。
"""
import pytest

from fastapi.testclient import TestClient


@pytest.fixture()
def public_mode(client, monkeypatch):
    """依赖 client：确保 _test_env（隔离 DB）已生效 + startup 已跑过。

    所有用例自建全新 TestClient（无 cookie），session 级 client 只用于触发初始化。
    """
    from app.settings import settings

    monkeypatch.setattr(settings, "public_mode", True)
    yield


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """测试共用同一 TestClient IP，注册/登录限速会把用例拦住 —— 每个用例前后清零。"""
    from app.auth import rate_limiter

    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


def _fresh_client() -> TestClient:
    """新开一个无 cookie 的客户端（模拟一个全新访客）。

    base_url 用 https：公网模式登录 cookie 带 Secure 标志，http 不回传。"""
    from app.main import app

    return TestClient(app, base_url="https://testserver")


def _register(c: TestClient, email: str, password: str = "Passw0rd!123"):
    r = c.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# 注册 / 登录 / 登出 / 身份
# ---------------------------------------------------------------------------
def test_register_then_me_returns_identity(client, public_mode):
    c = _fresh_client()
    body = _register(c, "iso_a@test.local")
    assert body["status"] == "ok"
    assert body["user"]["email"] == "iso_a@test.local"
    assert body["user"]["role"] == "user"

    r = c.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "iso_a@test.local"


def test_register_duplicate_email_rejected(client, public_mode):
    c = _fresh_client()
    _register(c, "iso_dup@test.local")
    c2 = _fresh_client()
    r = c2.post(
        "/api/auth/register", json={"email": "iso_dup@test.local", "password": "Passw0rd!123"}
    )
    assert r.status_code == 409


def test_register_weak_password_rejected(client, public_mode):
    c = _fresh_client()
    r = c.post("/api/auth/register", json={"email": "iso_weak@test.local", "password": "123"})
    assert r.status_code == 422


def test_login_logout_flow(client, public_mode):
    c = _fresh_client()
    _register(c, "iso_login@test.local")
    c.post("/api/auth/logout")

    # 登出后再访问 /me → 401
    r = c.get("/api/auth/me")
    assert r.status_code == 401

    # 重新登录 → 恢复
    r = c.post(
        "/api/auth/login", json={"email": "iso_login@test.local", "password": "Passw0rd!123"}
    )
    assert r.status_code == 200, r.text
    assert c.get("/api/auth/me").status_code == 200

    # 错误密码 → 401
    bad = _fresh_client().post(
        "/api/auth/login", json={"email": "iso_login@test.local", "password": "WrongPass!1"}
    )
    assert bad.status_code == 401


# ---------------------------------------------------------------------------
# 数据隔离：项目 / 任务 / 材料
# ---------------------------------------------------------------------------
def test_project_isolated_between_users(public_mode):
    ca = _fresh_client()
    _register(ca, "iso_owner@test.local")
    created = ca.post("/api/projects", json={"name": "隔离测试项目"})
    assert created.status_code == 200, created.text
    pid = created.json()["id"]

    # 用户 B：列表看不到、单查 not_found（不泄露存在性）
    cb = _fresh_client()
    _register(cb, "iso_other@test.local")
    ids_b = [p["id"] for p in cb.get("/api/projects").json()]
    assert pid not in ids_b
    assert cb.get(f"/api/projects/{pid}").json().get("status") == "not_found"
    # B 也不能删 / 改 A 的项目
    assert cb.delete(f"/api/projects/{pid}?confirm=true").json().get("status") == "not_found"
    assert cb.put(f"/api/projects/{pid}", json={"name": "篡改"}).json().get("status") == "not_found"

    # 匿名访客：401
    anon = _fresh_client()
    assert anon.get("/api/projects").status_code == 401
    assert anon.get(f"/api/projects/{pid}").status_code == 401

    # 属主本人：可见
    ids_a = [p["id"] for p in ca.get("/api/projects").json()]
    assert pid in ids_a


def test_material_isolated_between_users(public_mode):
    ca = _fresh_client()
    _register(ca, "iso_mat_a@test.local")
    m = ca.post(
        "/api/materials",
        json={"title": "A 的材料", "content_text": "只有属主可见的正文"},
    )
    assert m.status_code == 200, m.text
    mid = m.json()["id"]

    # 用户 B：列表看不到、详情/删除都按 not_found 处理
    cb = _fresh_client()
    _register(cb, "iso_mat_b@test.local")
    ids_b = [x["id"] for x in cb.get("/api/materials").json()]
    assert mid not in ids_b
    assert cb.get(f"/api/materials/{mid}").json().get("error") == "not_found"
    assert cb.delete(f"/api/materials/{mid}").json().get("error") == "not_found"

    # 属主：可见且能删
    ids_a = [x["id"] for x in ca.get("/api/materials").json()]
    assert mid in ids_a
    assert ca.delete(f"/api/materials/{mid}").json() == {"ok": True}


def test_tasks_isolated_between_users(public_mode):
    """任务列表按属主过滤：直接往库里塞两个用户的任务，各自只能看到自己的。"""
    from app.db import SessionLocal
    from app.models import Task

    ca = _fresh_client()
    ua = _register(ca, "iso_task_a@test.local")["user"]
    cb = _fresh_client()
    ub = _register(cb, "iso_task_b@test.local")["user"]

    with SessionLocal() as db:
        db.add(
            Task(
                id="iso_task_a_row",
                title="A 的任务",
                input_text="A 的输入正文",
                analysis_type="event",
                status="done",
                owner_id=ua["id"],
            )
        )
        db.add(
            Task(
                id="iso_task_b_row",
                title="B 的任务",
                input_text="B 的输入正文",
                analysis_type="event",
                status="done",
                owner_id=ub["id"],
            )
        )
        db.commit()

    ids_a = [t["task_id"] for t in ca.get("/api/tasks").json()]
    ids_b = [t["task_id"] for t in cb.get("/api/tasks").json()]
    assert "iso_task_a_row" in ids_a and "iso_task_b_row" not in ids_a
    assert "iso_task_b_row" in ids_b and "iso_task_a_row" not in ids_b

    # 匿名：任务列表 401
    assert _fresh_client().get("/api/tasks").status_code == 401


def test_admin_endpoints_require_admin(client, public_mode):
    """普通用户访问管理接口 → 403；admin 可列出用户并封禁。"""
    cu = _fresh_client()
    _register(cu, "iso_plain@test.local")
    assert cu.get("/api/admin/users").status_code == 403

    # 把该用户升为 admin 后可访问（直接改库，模拟运维操作）
    from app.db import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        row = db.query(User).filter(User.email == "iso_plain@test.local").first()
        row.role = "admin"
        db.commit()
    assert cu.get("/api/admin/users").status_code == 200

    # admin 不能封禁自己（接口对 admin 目标返回 400 拒绝）
    me_id = cu.get("/api/auth/me").json()["user"]["id"]
    r_self = cu.post(f"/api/admin/users/{me_id}/ban", json={"banned": 1})
    assert r_self.status_code in (400, 403)


# ---------------------------------------------------------------------------
# 本地模式（PUBLIC_MODE=0）零回归
# ---------------------------------------------------------------------------
def test_local_mode_no_auth_required(client):
    """本地单机模式：不登录也能读写（这是全部既有测试依赖的默认行为）。"""
    r = client.get("/api/projects")
    assert r.status_code == 200
    r2 = client.get("/api/tasks")
    assert r2.status_code == 200
    r3 = client.get("/api/materials")
    assert r3.status_code == 200


# ---------------------------------------------------------------------------
# 邮箱验证（Phase 1）：SMTP 未配置 = 关闭；配置态走完整验证流
# ---------------------------------------------------------------------------
def test_register_without_smtp_auto_verified(client, public_mode):
    """SMTP 未配置（默认）：注册直接视为已验证，验证接口返回 disabled。"""
    c = _fresh_client()
    body = _register(c, "iso_nosmtp@test.local")
    assert body["verification_required"] is False
    assert body["user"]["email_verified"] is True

    r = c.post("/api/auth/verify", json={"code": "123456"})
    assert r.status_code == 400
    assert r.json()["error"] == "disabled"


def test_email_verification_full_flow(client, public_mode, monkeypatch):
    """SMTP 配置态：注册 → 未验证 → 错码拒绝 → 正码通过 → 复验提示已验证。"""
    from app.settings import settings

    from app.db import SessionLocal
    from app.models import User

    # 启用验证 + 拦截真实发信（线程里会调它），记录调用参数
    monkeypatch.setattr(settings, "smtp_enabled", True)
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.routers.auth.send_verification_email",
        lambda to, code: (sent.append((to, code)), True)[1],
    )
    monkeypatch.setattr(
        "app.email_sender.send_verification_email",
        lambda to, code: (sent.append((to, code)), True)[1],
    )

    c = _fresh_client()
    body = _register(c, "iso_verify@test.local")
    assert body["verification_required"] is True
    assert body["user"]["email_verified"] is False

    # 从库读验证码（发信线程已被拦截，不打真实 SMTP）
    with SessionLocal() as db:
        row = db.query(User).filter(User.email == "iso_verify@test.local").first()
        code = row.verification_code
        assert code and len(code) == 6

    # 错误验证码 → 400
    r_bad = c.post("/api/auth/verify", json={"code": "000000" if code != "000000" else "111111"})
    assert r_bad.status_code == 400
    assert r_bad.json()["error"] == "invalid_code"

    # 正确验证码 → 200 + 已验证
    r_ok = c.post("/api/auth/verify", json={"code": code})
    assert r_ok.status_code == 200
    assert r_ok.json()["user"]["email_verified"] is True

    # 再验一次 → already_verified
    r_again = c.post("/api/auth/verify", json={"code": code})
    assert r_again.status_code == 200
    assert r_again.json()["already_verified"] is True


def test_resend_verification_cooldown(client, public_mode, monkeypatch):
    """重发验证码：第一次成功，冷却期内第二次 → 429。"""
    from app.settings import settings

    monkeypatch.setattr(settings, "smtp_enabled", True)
    monkeypatch.setattr("app.routers.auth.send_verification_email", lambda to, code: True)
    c = _fresh_client()
    _register(c, "iso_resend@test.local")
    r1 = c.post("/api/auth/resend-verification")
    assert r1.status_code == 200
    r2 = c.post("/api/auth/resend-verification")
    assert r2.status_code == 429


def test_admin_users_stats(client, public_mode):
    """用户列表带统计总览：total/admins/verified/banned/new_7d/active_7d。

    直接向测试库插入用户（绕开注册限流，避免用例内多次 _register 触发 429）。"""
    import uuid

    from app.auth import hash_password
    from app.db import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        db.add_all(
            [
                User(id=uuid.uuid4().hex, email="iso_stats_admin@test.local", display_name="甲",
                     hashed_password=hash_password("Passw0rd!123"), role="admin", email_verified=1),
                User(id=uuid.uuid4().hex, email="iso_stats_a@test.local", display_name="乙",
                     hashed_password=hash_password("Passw0rd!123"), role="user", email_verified=1),
                User(id=uuid.uuid4().hex, email="iso_stats_b@test.local", display_name="丙",
                     hashed_password=hash_password("Passw0rd!123"), role="user",
                     email_verified=0, is_banned=1),
            ]
        )
        db.commit()

    admin_client = _fresh_client()
    r_login = admin_client.post(
        "/api/auth/login", json={"email": "iso_stats_admin@test.local", "password": "Passw0rd!123"}
    )
    assert r_login.status_code == 200

    r = admin_client.get("/api/admin/users")
    assert r.status_code == 200
    stats = r.json()["stats"]
    assert stats["total"] >= 3
    assert stats["admins"] >= 1
    assert stats["verified"] >= 2
    assert stats["banned"] >= 1
    assert stats["new_7d"] >= 3  # 刚插入的都在 7 日窗口内
    assert "active_7d" in stats


def test_change_password_flow(client, public_mode):
    """改密码：错旧密码 400 → 正确流程 200 → 新密码可登录、旧密码被拒。"""
    email = "iso_chgpass@test.local"
    old_pw = "Passw0rd!123"
    new_pw = "NewPassw0rd!456"
    c = _fresh_client()
    _register(c, email, old_pw)

    # 旧密码错误 → 400
    r_bad = c.post(
        "/api/auth/change-password",
        json={"current_password": "WrongOld!123", "new_password": new_pw},
    )
    assert r_bad.status_code == 400

    # 正确流程 → 200
    r_ok = c.post(
        "/api/auth/change-password",
        json={"current_password": old_pw, "new_password": new_pw},
    )
    assert r_ok.status_code == 200

    # 旧密码登录被拒、新密码登录成功
    c2 = _fresh_client()
    assert c2.post("/api/auth/login", json={"email": email, "password": old_pw}).status_code == 401
    assert c2.post("/api/auth/login", json={"email": email, "password": new_pw}).status_code == 200

    # 新旧相同 → 400
    c3 = _fresh_client()
    c3.post("/api/auth/login", json={"email": email, "password": new_pw})
    r_same = c3.post(
        "/api/auth/change-password",
        json={"current_password": new_pw, "new_password": new_pw},
    )
    assert r_same.status_code == 400


def test_change_password_requires_login(client, public_mode):
    """未登录调用改密码 → 401。"""
    r = _fresh_client().post(
        "/api/auth/change-password",
        json={"current_password": "whatever1", "new_password": "whatever2"},
    )
    assert r.status_code == 401
