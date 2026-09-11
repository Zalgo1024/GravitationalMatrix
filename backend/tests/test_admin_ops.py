"""独立管理员运营后台（admin_ops.py）端点测试。

覆盖：
- 非 admin 访问 admin 运营端点(projects/tasks/stats/overview/system) → 403；
- admin 能跨用户查看项目 / 任务（含归属 email）；
- 归档项目 → is_archived 翻转；
- 硬删除项目（confirm=false 拒绝，confirm=true 连带删任务+版本）；
- 删除任务（confirm=true 连带删 ReportVersion）；
- stats/overview 各口径正确（无时区异常）；
- system 返回健康与队列。

复用 test_auth_isolation 的隔离策略：依赖 session 级 client(触发 startup+隔离 DB)，
monkeypatch settings.public_mode=True 走真实 JWT 鉴权，自建 https TestClient。
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


def _seed_user(email: str, role: str = "user") -> str:
    """直接向隔离 DB 插一个用户（避开注册接口限速），返回其 id。"""
    from app.auth import hash_password
    from app.db import SessionLocal
    from app.models import User

    uid = "u_" + uuid.uuid4().hex[:16]
    with SessionLocal() as db:
        db.add(User(id=uid, email=email, hashed_password=hash_password("Passw0rd!123"),
                    role=role, email_verified=1))
        db.commit()
    return uid


def _login_client(email: str) -> TestClient:
    """登录已有用户，返回带 cookie 的客户端。"""
    c = _fresh_client()
    r = c.post("/api/auth/login", json={"email": email, "password": "Passw0rd!123"})
    assert r.status_code == 200, r.text
    return c


def _make_admin(email: str) -> TestClient:
    """DB 直插 admin + 登录。"""
    _seed_user(email, role="admin")
    return _login_client(email)


def _register_user(email: str) -> str:
    """DB 直插普通用户，返回 id。"""
    return _seed_user(email, role="user")


def _make_owned_data(owner_id: str, db):
    """为 owner_id 造一个项目 + 2 任务 + 若干报告版本，返回 (project_id, task_id)。"""
    from app.models import Project, ReportVersion, Task

    pid = "u_" + uuid.uuid4().hex[:12]
    proj = Project(id=pid, name="运营测试项目", description="治理测试", owner_id=owner_id)
    db.add(proj)
    t1 = Task(id="t_" + uuid.uuid4().hex[:12], title="报告A", input_text="素材", owner_id=owner_id,
              project_id=pid, status="done", analysis_type="case", mode="rule")
    db.add(t1)
    db.flush()
    db.add_all([
        ReportVersion(id=uuid.uuid4().hex, task_id=t1.id, kind="original", content_markdown="# 报告A",
                      version_no=1, is_current=1),
        ReportVersion(id=uuid.uuid4().hex, task_id=t1.id, kind="revised", content_markdown="# 改",
                      version_no=2, is_current=0),
    ])
    db.commit()
    return pid, t1.id


# ---------------------------------------------------------------------------
# 鉴权：非 admin 一律 403
# ---------------------------------------------------------------------------
def test_admin_ops_require_admin(client, public_mode):
    """普通用户访问项目/任务/看板/系统 端点 → 403；匿名 → 401；admin → 200。"""
    # 匿名未登录 → 401
    anon = _fresh_client()
    assert anon.get("/api/admin/projects").status_code == 401

    # 已登录普通用户 → 403
    cu_email = "iso_ops_plain@test.local"
    _seed_user(cu_email, role="user")
    cu = _login_client(cu_email)

    forbidden = [
        "/api/admin/projects",
        "/api/admin/tasks",
        "/api/admin/stats/overview",
        "/api/admin/system",
    ]
    for path in forbidden:
        r = cu.get(path)
        assert r.status_code == 403, f"{path} 应 403，实际 {r.status_code}"

    # admin 提权后可访问
    au = _make_admin("iso_ops_admin@test.local")
    assert au.get("/api/admin/projects").status_code == 200
    assert au.get("/api/admin/stats/overview").status_code == 200
    assert au.get("/api/admin/system").status_code == 200


# ---------------------------------------------------------------------------
# 跨用户查看与治理
# ---------------------------------------------------------------------------
def test_admin_cross_user_projects_and_archive(client, public_mode):
    """admin 能列出他人项目(含 owner email)；归档翻转；硬删除需 confirm。"""
    uid = _register_user("iso_ops_owner@test.local")
    from app.db import SessionLocal

    with SessionLocal() as db:
        pid, _ = _make_owned_data(uid, db)

    au = _make_admin("iso_ops_arch@test.local")

    # 跨用户项目列表含归属
    r = au.get("/api/admin/projects")
    assert r.status_code == 200
    projs = r.json()["projects"]
    mine = [p for p in projs if p["id"] == pid]
    assert mine, "admin 应能看到其他用户的项目"
    assert mine[0]["owner_email"] == "iso_ops_owner@test.local"

    # 归档
    r_arch = au.post(f"/api/admin/projects/{pid}/archive", json={"archived": True})
    assert r_arch.status_code == 200
    assert r_arch.json()["is_archived"] == 1

    # 归档后默认列表不含（include_archived 才含）
    r_active = au.get("/api/admin/projects")
    assert all(p["id"] != pid for p in r_active.json()["projects"])
    r_all = au.get("/api/admin/projects?include_archived=true")
    assert any(p["id"] == pid for p in r_all.json()["projects"])

    # 取消归档
    r_unarch = au.post(f"/api/admin/projects/{pid}/archive", json={"archived": False})
    assert r_unarch.json()["is_archived"] == 0


def test_admin_delete_project_requires_confirm_and_cascades(client, public_mode):
    """硬删除项目：confirm=false 拒绝；confirm=true 连带删任务+报告版本。"""
    uid = _register_user("iso_ops_delowner@test.local")
    from app.db import SessionLocal

    with SessionLocal() as db:
        pid, _ = _make_owned_data(uid, db)

    au = _make_admin("iso_ops_deladmin@test.local")

    # 无 confirm → 400
    r_no = au.post(f"/api/admin/projects/{pid}/delete", json={})
    assert r_no.status_code == 400
    assert r_no.json()["error"] == "confirm_required"

    # 带 confirm → 200，任务与版本被清
    r_yes = au.post(f"/api/admin/projects/{pid}/delete", json={"confirm": True})
    assert r_yes.status_code == 200
    body = r_yes.json()
    assert body["tasks_deleted"] == 1
    assert body["report_versions_deleted"] == 2

    from app.models import Project, Task
    with SessionLocal() as db:
        assert db.get(Project, pid) is None
        assert db.query(Task).filter(Task.project_id == pid).count() == 0


def test_admin_tasks_and_delete_cascades(client, public_mode):
    """admin 列跨用户任务；删除任务连带删 ReportVersion。"""
    uid = _register_user("iso_ops_towner@test.local")
    from app.db import SessionLocal

    with SessionLocal() as db:
        pid, task_id = _make_owned_data(uid, db)

    au = _make_admin("iso_ops_tadmin@test.local")

    r = au.get("/api/admin/tasks")
    assert r.status_code == 200
    tasks = r.json()["tasks"]
    mine = [t for t in tasks if t["id"] == task_id]
    assert mine, "admin 应能看到他人任务"
    assert mine[0]["owner_email"] == "iso_ops_towner@test.local"
    assert mine[0]["version_count"] == 2

    # 删除需 confirm
    r_no = au.post(f"/api/admin/tasks/{task_id}/delete", json={})
    assert r_no.status_code == 400

    # confirm 后删除
    r_yes = au.post(f"/api/admin/tasks/{task_id}/delete", json={"confirm": True})
    assert r_yes.status_code == 200
    assert r_yes.json()["report_versions_deleted"] == 2

    from app.models import Project, ReportVersion, Task
    with SessionLocal() as db:
        assert db.get(Task, task_id) is None
        assert db.query(ReportVersion).filter(ReportVersion.task_id == task_id).count() == 0
        # 非 auto_ 项目不被连带删除
        assert db.get(Project, pid) is not None


# ---------------------------------------------------------------------------
# 单用户明细
# ---------------------------------------------------------------------------
def test_admin_user_detail(client, public_mode):
    """admin 看单用户内容足迹。"""
    uid = _register_user("iso_ops_detail@test.local")
    from app.db import SessionLocal

    with SessionLocal() as db:
        pid, task_id = _make_owned_data(uid, db)

    au = _make_admin("iso_ops_detadmin@test.local")
    r = au.get(f"/api/admin/users/{uid}")
    assert r.status_code == 200
    counts = r.json()["counts"]
    assert counts["projects"] >= 1
    assert counts["tasks"] >= 1
    assert counts["tasks_done"] >= 1
    assert "tasks_error" in counts
    assert "materials" in counts
    assert "recent_tasks" in r.json()

    # 不存在用户 → 404
    r404 = au.get("/api/admin/users/nonexistent_id")
    assert r404.status_code == 404


# ---------------------------------------------------------------------------
# 看板聚合 + 系统状态
# ---------------------------------------------------------------------------
def test_admin_stats_overview(client, public_mode):
    """stats/overview 各口径返回正确、无时区异常。"""
    _register_user("iso_ops_s1@test.local")
    uid = _register_user("iso_ops_s2@test.local")
    from app.db import SessionLocal

    with SessionLocal() as db:
        _make_owned_data(uid, db)

    au = _make_admin("iso_ops_sadmin@test.local")
    r = au.get("/api/admin/stats/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["users"]["total"] >= 3  # 2 普通 + 1 admin
    assert body["users"]["admins"] >= 1
    assert body["content"]["tasks"] >= 1
    assert body["content"]["report_versions"] >= 2
    assert body["quality"]["task_success_rate"] is not None
    # 趋势 14 天桶
    assert len(body["trend_14d"]) == 14
    assert all("date" in b and "registered" in b for b in body["trend_14d"])


def test_admin_system_status(client, public_mode):
    au = _make_admin("iso_ops_sysadmin@test.local")
    r = au.get("/api/admin/system")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["health"] == "up"
    assert "public_mode" in body
    assert "queue" in body
