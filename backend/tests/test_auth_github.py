"""GitHub OAuth 登录（用户系统 Phase 3）测试。

核心断言：
- 未配置 Client ID/Secret：三个接口一律 404，前端按钮探测 enabled=false；
- 配置后 /login 302 跳 GitHub 授权页并带签名 state；
- callback 全链路（monkeypatch 外部 HTTP）：新号创建（email_verified=1、github_id 入库、
  cookie 签发）、同邮箱老号关联（不新建）、封禁/坏 state/邮箱冲突各自落到对应错误回跳；
- 外部 HTTP 用 monkeypatch 替换模块级 _exchange_code / _fetch_github_identity，全程不触网。

注意：monkeypatch settings 是函数级夹具，测试结束自动还原，不影响其余本地模式测试。
"""
import pytest

from fastapi.testclient import TestClient


def _fresh_client() -> TestClient:
    """新开无 cookie 客户端；base_url 用 https：公网模式 cookie 带 Secure，http 不回传。"""
    from app.main import app

    return TestClient(app, base_url="https://testserver")


@pytest.fixture()
def _reset_rate_limiter():
    from app.auth import rate_limiter

    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


@pytest.fixture()
def github_mode(client, monkeypatch, _reset_rate_limiter):
    """隔离 DB + PUBLIC_MODE=1 + GitHub OAuth 已配置。"""
    from app.settings import settings

    monkeypatch.setattr(settings, "public_mode", True)
    monkeypatch.setattr(settings, "github_client_id", "test-client-id")
    monkeypatch.setattr(settings, "github_client_secret", "test-client-secret")
    monkeypatch.setattr(settings, "github_oauth_enabled", True)


def _mock_github(monkeypatch, email: str, github_id: str = "100001", name: str = "Octo Cat"):
    """把「换 token → 拉身份」两步外部 HTTP 换成纯内存桩。"""
    from app.routers import github_oauth as gh

    monkeypatch.setattr(gh, "_exchange_code", lambda code, redirect_uri: "stub-access-token")
    monkeypatch.setattr(
        gh,
        "_fetch_github_identity",
        lambda token: (
            {"id": int(github_id), "login": "octocat", "name": name, "email": email},
            [{"email": email, "primary": True, "verified": True}],
        ),
    )


def _valid_state() -> str:
    from app.routers.github_oauth import _make_state

    return _make_state()


# ---------------------------------------------------------------------------
# 开关与按钮探测
# ---------------------------------------------------------------------------
def test_status_disabled_by_default(client):
    r = client.get("/api/auth/github/status")
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_endpoints_404_when_disabled(client, monkeypatch, _reset_rate_limiter):
    from app.settings import settings

    monkeypatch.setattr(settings, "public_mode", True)
    monkeypatch.setattr(settings, "github_oauth_enabled", False)
    c = _fresh_client()
    assert c.get("/api/auth/github/status").json()["enabled"] is False
    assert c.get("/api/auth/github/login").status_code == 404
    assert c.get("/api/auth/github/callback", params={"code": "x", "state": "y"}).status_code == 404


def test_login_redirects_to_github(client, github_mode):
    c = _fresh_client()
    r = c.get("/api/auth/github/login", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=test-client-id" in loc
    assert "state=" in loc
    assert "user%3Aemail" in loc or "user:email" in loc


# ---------------------------------------------------------------------------
# callback 全链路
# ---------------------------------------------------------------------------
def test_callback_creates_new_user_and_logs_in(client, github_mode, monkeypatch):
    _mock_github(monkeypatch, email="gh_new@test.local", github_id="200001")
    c = _fresh_client()
    r = c.get(
        "/api/auth/github/callback",
        params={"code": "good-code", "state": _valid_state()},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers["location"].startswith("http://127.0.0.1:3000/?login=github")
    # cookie 已签发（Secure 标志 + https base_url → TestClient 会回传）
    assert "sy_token" in c.cookies

    me = c.get("/api/auth/me")
    assert me.status_code == 200, me.text
    user = me.json()["user"]
    assert user["email"] == "gh_new@test.local"
    assert user["email_verified"] is True

    from app.db import SessionLocal
    from app.models import User

    with SessionLocal() as db:
        row = db.query(User).filter(User.email == "gh_new@test.local").first()
        assert row is not None
        assert row.github_id == "200001"
        assert row.email_verified == 1
        # 随机密码已写入（列非空约束），但用户不可知 —— 密码通道不可用
        assert row.hashed_password


def test_callback_links_existing_same_email_user(client, github_mode, monkeypatch):
    from app.db import SessionLocal
    from app.models import User
    from app.auth import hash_password

    with SessionLocal() as db:
        db.add(User(
            id="existing0000000000000000000001",
            email="gh_link@test.local",
            display_name="老用户",
            hashed_password=hash_password("Passw0rd!123"),
            role="user",
            is_banned=0,
            email_verified=0,  # 历史未验证账号，GitHub 关联后应升级为已验证
        ))
        db.commit()

    _mock_github(monkeypatch, email="gh_link@test.local", github_id="200002")
    c = _fresh_client()
    r = c.get(
        "/api/auth/github/callback",
        params={"code": "good-code", "state": _valid_state()},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "sy_token" in c.cookies
    me = c.get("/api/auth/me").json()["user"]
    assert me["id"] == "existing0000000000000000000001"  # 登进的是原账号，不是新号
    assert me["email_verified"] is True

    with SessionLocal() as db:
        count = db.query(User).filter(User.email == "gh_link@test.local").count()
        assert count == 1  # 没有建重复号


def test_callback_rejects_bad_state(client, github_mode, monkeypatch):
    _mock_github(monkeypatch, email="x@test.local")
    c = _fresh_client()
    r = c.get(
        "/api/auth/github/callback",
        params={"code": "good-code", "state": "forged-state"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "auth_error=expired" in r.headers["location"]
    assert "sy_token" not in c.cookies


def test_callback_reports_banned_user(client, github_mode, monkeypatch):
    from app.db import SessionLocal
    from app.models import User
    from app.auth import hash_password

    with SessionLocal() as db:
        db.add(User(
            id="banned000000000000000000000001",
            email="gh_banned@test.local",
            hashed_password=hash_password("Passw0rd!123"),
            role="user",
            is_banned=1,
            email_verified=1,
        ))
        db.commit()

    _mock_github(monkeypatch, email="gh_banned@test.local", github_id="200003")
    c = _fresh_client()
    r = c.get(
        "/api/auth/github/callback",
        params={"code": "good-code", "state": _valid_state()},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "auth_error=banned" in r.headers["location"]
    assert "sy_token" not in c.cookies


def test_callback_rejects_github_id_conflict(client, github_mode, monkeypatch):
    """同邮箱已绑定另一个 GitHub 账号 → 拒绝，防止顶号。"""
    from app.db import SessionLocal
    from app.models import User
    from app.auth import hash_password

    with SessionLocal() as db:
        db.add(User(
            id="conflict00000000000000000000001",
            email="gh_conflict@test.local",
            hashed_password=hash_password("Passw0rd!123"),
            role="user",
            is_banned=0,
            email_verified=1,
            github_id="999999",
        ))
        db.commit()

    _mock_github(monkeypatch, email="gh_conflict@test.local", github_id="888888")
    c = _fresh_client()
    r = c.get(
        "/api/auth/github/callback",
        params={"code": "good-code", "state": _valid_state()},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "auth_error=email_conflict" in r.headers["location"]
    assert "sy_token" not in c.cookies


def test_callback_reports_missing_verified_email(client, github_mode, monkeypatch):
    from app.routers import github_oauth as gh

    monkeypatch.setattr(gh, "_exchange_code", lambda code, redirect_uri: "stub-access-token")
    monkeypatch.setattr(
        gh,
        "_fetch_github_identity",
        lambda token: (
            {"id": 200004, "login": "noemail", "name": None, "email": None},
            [{"email": "noreply@users.noreply.github.com", "primary": True, "verified": False}],
        ),
    )
    c = _fresh_client()
    r = c.get(
        "/api/auth/github/callback",
        params={"code": "good-code", "state": _valid_state()},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "auth_error=no_verified_email" in r.headers["location"]


def test_callback_survives_github_outage(client, github_mode, monkeypatch):
    """GitHub 侧故障（换 token 失败）→ 友好回跳，不 500。"""
    from app.routers import github_oauth as gh

    def boom(code, redirect_uri):
        raise RuntimeError("network down")

    monkeypatch.setattr(gh, "_exchange_code", boom)
    c = _fresh_client()
    r = c.get(
        "/api/auth/github/callback",
        params={"code": "good-code", "state": _valid_state()},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "auth_error=github_failed" in r.headers["location"]
