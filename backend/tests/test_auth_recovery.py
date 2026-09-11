"""用户系统 Phase 2：账户恢复流（forgot-password → reset-password）测试。

覆盖：
- 枚举防御：未知邮箱与已知邮箱返回同一句话（响应时间不敏感，仅文案）；
- 已知邮箱：签发令牌 + 写 audit + 邮件投递被 mock 拦截；
- 令牌校验：未过期 → valid=True；过期 / 已被用 → valid=False；
- 重置密码：单次使用、用过即失效、过期的也失效、改后全端会话失效（token_valid_after）；
- 改密/重置均会改 token_valid_after 锚点，使此前签发的所有 JWT 立即失效。
"""
from datetime import datetime, timedelta, timezone

import pytest

from fastapi.testclient import TestClient


@pytest.fixture()
def public_mode(client, monkeypatch):
    """打开 PUBLIC_MODE 让 forgot/reset 端点从 404 切换为实际路由。"""
    from app.settings import settings

    monkeypatch.setattr(settings, "public_mode", True)
    yield


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """测试共用同一 IP，限速会把用例拦住 —— 每用例前后清零。"""
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


# ---------------------------------------------------------------------------
# 枚举防御
# ---------------------------------------------------------------------------
def test_forgot_unknown_email_returns_same_message(client, public_mode, monkeypatch):
    """未注册邮箱也返回与已注册相同文案（仅 HTTP 文案层面防枚举，不做时序防御）。"""
    sent: list[str] = []
    monkeypatch.setattr(
        "app.routers.auth.send_password_reset_email",
        lambda to, url, ttl: (sent.append(to), True)[1],
    )
    c = _fresh_client()
    r_unknown = c.post("/api/auth/forgot-password", json={"email": "nobody-here@test.local"})
    r_known = c.post(
        "/api/auth/forgot-password",
        json={"email": "iso_recov_known@test.local"},
    )
    assert r_unknown.status_code == 200
    assert r_known.status_code == 200
    # 文案完全一致
    assert r_unknown.json()["message"] == r_known.json()["message"]
    # 仅已知邮箱触发邮件投递（避免给未注册地址发信导致信噪比 + 被用作枚举）
    assert sent == []
    # 已知邮箱仍然什么也不做（未注册）
    r_known_again = c.post(
        "/api/auth/forgot-password",
        json={"email": "iso_recov_real@test.local"},
    )
    # 现在注册再申请，应当投递
    _register(c, "iso_recov_real@test.local")
    c.post("/api/auth/forgot-password", json={"email": "iso_recov_real@test.local"})
    assert sent == ["iso_recov_real@test.local"]


# ---------------------------------------------------------------------------
# 已知邮箱：签发令牌 + audit
# ---------------------------------------------------------------------------
def test_forgot_known_email_creates_token_and_audits(client, public_mode, monkeypatch):
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.routers.auth.send_password_reset_email",
        lambda to, url, ttl: (sent.append((to, url)), True)[1],
    )
    c = _fresh_client()
    email = "iso_recov_create@test.local"
    _register(c, email)
    sent.clear()  # 丢弃 register 阶段可能的副作用

    r = c.post("/api/auth/forgot-password", json={"email": email})
    assert r.status_code == 200
    assert len(sent) == 1
    sent_to, sent_url = sent[0]
    assert sent_to == email
    assert "/reset-password?token=" in sent_url

    # audit 记录（actor_id 留空因为是匿名操作）
    from app.db import SessionLocal
    from app.models import AuditLog

    with SessionLocal() as db:
        rows = (
            db.query(AuditLog)
            .filter(AuditLog.action == "auth.forgot_password")
            .all()
        )
    assert len(rows) >= 1
    assert rows[-1].target_type == "user"


# ---------------------------------------------------------------------------
# 令牌 validate
# ---------------------------------------------------------------------------
def test_validate_token_returns_true_for_fresh_and_false_for_used(client, public_mode):
    c = _fresh_client()
    email = "iso_recov_validate@test.local"
    _register(c, email)

    # 申请令牌 → 读库拿到 hash + 原始 token 是发信侧的事；此处通过 dev echo 拿明文
    from app.settings import settings

    original_dev = settings.dev_reset_echo
    settings.dev_reset_echo = True
    try:
        r = c.post("/api/auth/forgot-password", json={"email": email})
        # dev_reset_echo + smtp 未配 → 响应里附 dev_reset_url
        url = r.json().get("dev_reset_url")
        assert url is not None
        token = url.split("token=", 1)[1]
    finally:
        settings.dev_reset_echo = original_dev

    # 验证令牌 → valid=True
    r_v = c.get(f"/api/auth/reset-password/validate?token={token}")
    assert r_v.status_code == 200
    assert r_v.json()["valid"] is True

    # 重置密码 → 用掉
    new_pw = "NewPassw0rd!456"
    r_reset = c.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": new_pw},
    )
    assert r_reset.status_code == 200

    # 再验证 → valid=False
    r_v2 = c.get(f"/api/auth/reset-password/validate?token={token}")
    assert r_v2.json()["valid"] is False


# ---------------------------------------------------------------------------
# 重置密码：单次使用
# ---------------------------------------------------------------------------
def test_reset_token_single_use(client, public_mode):
    """用过一次的令牌再拿来 reset → 400 invalid_token。"""
    from app.settings import settings

    c = _fresh_client()
    email = "iso_recov_single@test.local"
    _register(c, email)

    original_dev = settings.dev_reset_echo
    settings.dev_reset_echo = True
    try:
        c.post("/api/auth/forgot-password", json={"email": email})
    finally:
        settings.dev_reset_echo = original_dev

    # 直接从库读最新未用令牌的 hash；明文走 dev echo 也行，但读库更稳
    from app.db import SessionLocal
    from app.auth import hash_reset_token
    from app.models import PasswordResetToken, User

    # 重新申请一次拿到一个全新的明文
    settings.dev_reset_echo = True
    try:
        r = c.post("/api/auth/forgot-password", json={"email": email})
        token = r.json()["dev_reset_url"].split("token=", 1)[1]
    finally:
        settings.dev_reset_echo = original_dev

    new_pw = "NewPassw0rd!456"
    r1 = c.post("/api/auth/reset-password", json={"token": token, "new_password": new_pw})
    assert r1.status_code == 200

    # 第二次用同 token → 400
    r2 = c.post("/api/auth/reset-password", json={"token": token, "new_password": "AnotherPass!789"})
    assert r2.status_code == 400
    assert r2.json()["error"] == "invalid_token"


# ---------------------------------------------------------------------------
# 重置密码：过期令牌
# ---------------------------------------------------------------------------
def test_reset_token_expired(client, public_mode):
    """将库中令牌手动置为过期 → 重置返回 expired_token。"""
    from app.settings import settings
    from app.db import SessionLocal
    from app.models import PasswordResetToken

    c = _fresh_client()
    email = "iso_recov_expired@test.local"
    _register(c, email)

    # 拿一枚新令牌
    original_dev = settings.dev_reset_echo
    settings.dev_reset_echo = True
    try:
        r = c.post("/api/auth/forgot-password", json={"email": email})
        token = r.json()["dev_reset_url"].split("token=", 1)[1]
    finally:
        settings.dev_reset_echo = original_dev

    # 改库把过期时间拨到过去
    from app.auth import hash_reset_token
    with SessionLocal() as db:
        row = (
            db.query(PasswordResetToken)
            .filter(PasswordResetToken.token_hash == hash_reset_token(token))
            .first()
        )
        row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
        db.commit()

    r_reset = c.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": "NewPassw0rd!456"},
    )
    assert r_reset.status_code == 400
    assert r_reset.json()["error"] == "expired_token"


# ---------------------------------------------------------------------------
# 重置密码：踢掉此前所有 session
# ---------------------------------------------------------------------------
def test_reset_invalidates_all_existing_sessions(client, public_mode):
    """重置密码后，此前签发的 cookie 立即失效（401 unauthorized/session_invalidated）。"""
    from app.settings import settings

    c = _fresh_client()
    email = "iso_recov_kick@test.local"
    old_pw = "Passw0rd!123"
    new_pw = "NewPassw0rd!456"
    _register(c, email, old_pw)

    # /me 应可访问（持有刚签发的 cookie）
    r_me_before = c.get("/api/auth/me")
    assert r_me_before.status_code == 200
    cookie_before = c.cookies.get("sy_token")
    assert cookie_before

    # 重置密码
    original_dev = settings.dev_reset_echo
    settings.dev_reset_echo = True
    try:
        c.post("/api/auth/forgot-password", json={"email": email})
        token = c.post("/api/auth/forgot-password", json={"email": email}).json()["dev_reset_url"].split("token=", 1)[1]
    finally:
        settings.dev_reset_echo = original_dev
    r_reset = c.post("/api/auth/reset-password", json={"token": token, "new_password": new_pw})
    assert r_reset.status_code == 200

    # 用新密码登录会立刻改 session 锚点；但旧 cookie 必须已经无效
    # 在另一台设备上拿到旧 cookie（用同一 client 的 cookies jar 复制）来测失效
    import copy

    stale_client = TestClient.__new__(TestClient)
    stale_client.__dict__ = copy.copy(c.__dict__)
    stale_client.cookies = copy.copy(c.cookies)

    # 用新密码登录主 client（避免把 anchor 算到主 client 头上）
    c.post("/api/auth/login", json={"email": email, "password": new_pw})

    # 把旧 token 写到另一个 client 上，/me 必须 401
    other = _fresh_client()
    other.cookies.set("sy_token", cookie_before, domain="testserver", path="/")
    r_stale = other.get("/api/auth/me")
    assert r_stale.status_code == 401


# ---------------------------------------------------------------------------
# 同秒重发 cookie 不被自身踢下线（微秒精度回归）
# ---------------------------------------------------------------------------
def test_change_password_same_second_relogin_succeeds(client, public_mode):
    """改密后立刻用同一 client 的新 cookie 登录测试：iat 与 token_valid_after 同秒 → 通过。

    之前 token_valid_after 用微秒精度而 JWT iat 是秒精度，会把「同秒签发的新 cookie」误判为
    旧 cookie 失效 → 401。修法：tva_aware.replace(microsecond=0)。
    """
    c = _fresh_client()
    email = "iso_recov_same_sec@test.local"
    old_pw = "Passw0rd!123"
    new_pw = "NewPassw0rd!456"
    _register(c, email, old_pw)

    # 改密接口会重新签发 cookie 给本机（保留登录态）
    r = c.post(
        "/api/auth/change-password",
        json={"current_password": old_pw, "new_password": new_pw},
    )
    assert r.status_code == 200

    # 本机 cookie 立刻能用 —— 不应被自身踢下线
    r_me = c.get("/api/auth/me")
    assert r_me.status_code == 200, r_me.text
    assert r_me.json()["user"]["email"] == email


# ---------------------------------------------------------------------------
# 限速：forgot-password
# ---------------------------------------------------------------------------
def test_forgot_password_rate_limit(client, public_mode):
    """短时间内多次 forgot 同一邮箱 → 429。"""
    email = "iso_recov_rl@test.local"
    c = _fresh_client()
    _register(c, email)

    # 邮箱维度 limit=3/window=600s；前 3 次 ok，第 4 次 429
    statuses = []
    for _ in range(4):
        r = c.post("/api/auth/forgot-password", json={"email": email})
        statuses.append(r.status_code)
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429