"""GitHub OAuth 登录（用户系统 Phase 3）。

流程（授权码模式，标准三步）：
1. GET /api/auth/github/login   → 302 跳 GitHub 授权页（带签名 state 防 CSRF）；
2. 用户在 GitHub 授权后回跳 GET /api/auth/github/callback?code&state；
3. 后端用 code 换 access_token → 拉 /user 与 /user/emails → 建号/关联 → 签发本系统
   httpOnly cookie（与密码登录同一套 JWT）→ 302 回前端。

设计约定：
- 配置开关：GITHUB_CLIENT_ID/SECRET 配齐才启用；未配置时三个接口一律 404，前端按钮隐藏；
- 身份识别：以 GitHub「已验证的主邮箱」为唯一身份键。同邮箱已有本地账号 → 直接登录并
  关联 github_id（GitHub 侧邮箱已验证 → email_verified 置 1）；没有 → 建新号；
- 密码：GitHub 建号时随机写入一个未知密码哈希（模型列非空），用户此后可用「忘记密码」
  自主设置密码，形成双通道登录；
- 失败不裸奔：任何一步失败都 302 回前端并带 auth_error 参数（不泄露 GitHub 侧细节）；
- 零新依赖：token 交换与用户信息拉取用标准库 urllib（测试中整体 monkeypatch）。
"""
import json
import logging
import secrets
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.audit import client_ip, record_audit
from app.auth import (
    rate_limiter,
    set_auth_cookie,
)
from app.db import SessionLocal
from app.models import User, _now
from app.settings import settings

logger = logging.getLogger("app")

router = APIRouter(prefix="/api/auth/github")

_STATE_TTL_MINUTES = 10
_GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
_GITHUB_USER_API = "https://api.github.com/user"
_GITHUB_EMAILS_API = "https://api.github.com/user/emails"
_REDIRECT_SCOPE = "read:user user:email"


def _frontend_redirect(target: str) -> RedirectResponse:
    """回前端（PUBLIC_BASE_URL，默认本地 3000），cookie 由调用方按需附加。"""
    return RedirectResponse(url=target, status_code=302)


def _error_redirect(reason: str) -> RedirectResponse:
    sep = "&" if "?" in settings.public_base_url else "?"
    return _frontend_redirect(f"{settings.public_base_url}/{sep}auth_error={urllib.parse.quote(reason)}")


def _ok_redirect() -> RedirectResponse:
    return _frontend_redirect(f"{settings.public_base_url}/?login=github")


def _make_state() -> str:
    payload = {
        "s": "gh_oauth",
        "n": secrets.token_hex(8),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=_STATE_TTL_MINUTES),
    }
    # 复用认证核心的 AUTH_SECRET：state 本身就是签名随机数，无服务端存储需求
    from app.auth import AUTH_SECRET, JWT_ALGO

    return jwt.encode(payload, AUTH_SECRET, algorithm=JWT_ALGO)


def _validate_state(state: str) -> bool:
    from app.auth import AUTH_SECRET, JWT_ALGO

    try:
        payload = jwt.decode(state or "", AUTH_SECRET, algorithms=[JWT_ALGO])
    except jwt.InvalidTokenError:
        return False
    return payload.get("s") == "gh_oauth"


def _callback_uri(request: Request) -> str:
    if settings.github_redirect_uri:
        return settings.github_redirect_uri
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/auth/github/callback"


# ---------------------------------------------------------------------------
# 外部 HTTP（拆成模块级函数：测试整体 monkeypatch，不触网）
# ---------------------------------------------------------------------------
def _exchange_code(code: str, redirect_uri: str) -> str:
    """授权码换 access_token。失败/被 GitHub 拒绝时抛 RuntimeError。"""
    body = urllib.parse.urlencode(
        {
            "client_id": settings.github_client_id,
            "client_secret": settings.github_client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        _GITHUB_TOKEN_URL,
        data=body,
        headers={"Accept": "application/json", "User-Agent": "sanyuan-workbench"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    token = str(data.get("access_token") or "")
    if not token:
        raise RuntimeError(f"github token exchange failed: {data.get('error') or 'no token'}")
    return token


def _fetch_github_identity(access_token: str) -> tuple[dict, list]:
    """拉取 GitHub 用户资料与邮箱列表。返回 (profile, emails)。失败抛异常。"""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "sanyuan-workbench",
    }
    with urllib.request.urlopen(urllib.request.Request(_GITHUB_USER_API, headers=headers), timeout=15) as resp:
        profile = json.loads(resp.read().decode("utf-8"))
    try:
        with urllib.request.urlopen(urllib.request.Request(_GITHUB_EMAILS_API, headers=headers), timeout=15) as resp:
            emails = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 —— emails 接口失败不挡登录，退化用 profile.email
        emails = []
    return profile, emails


def _pick_verified_email(profile: dict, emails: list) -> str | None:
    """优先「主邮箱且已验证」，其次任一已验证邮箱；profile.email 兜底（可能未验证）。"""
    if isinstance(emails, list):
        verified = [e for e in emails if isinstance(e, dict) and e.get("verified") and e.get("email")]
        primary = next((e["email"] for e in verified if e.get("primary")), None)
        chosen = primary or (verified[0]["email"] if verified else None)
        if chosen:
            return str(chosen).strip().lower()
    raw = profile.get("email")
    return str(raw).strip().lower() if raw else None


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------
@router.get("/status")
def github_status():
    """前端按钮可见性探测：未配置 Client ID/Secret 时 enabled=false。"""
    return {"enabled": settings.github_oauth_enabled}


@router.get("/login")
def github_login(request: Request):
    if not settings.github_oauth_enabled:
        from fastapi import HTTPException, status as http_status

        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={"status": "not_found", "message": "GitHub 登录未启用"},
        )
    ip = request.client.host if request.client else "unknown"
    if not rate_limiter.allow(f"gh_login:{ip}", limit=10, window_sec=60):
        return _error_redirect("rate_limited")
    params = urllib.parse.urlencode(
        {
            "client_id": settings.github_client_id,
            "redirect_uri": _callback_uri(request),
            "scope": _REDIRECT_SCOPE,
            "state": _make_state(),
        }
    )
    return RedirectResponse(url=f"{_GITHUB_AUTHORIZE_URL}?{params}", status_code=302)


@router.get("/callback")
def github_callback(request: Request, code: str = "", state: str = ""):
    if not settings.github_oauth_enabled:
        from fastapi import HTTPException, status as http_status

        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={"status": "not_found", "message": "GitHub 登录未启用"},
        )
    ip = request.client.host if request.client else "unknown"
    if not rate_limiter.allow(f"gh_cb:{ip}", limit=10, window_sec=60):
        return _error_redirect("rate_limited")
    if not code or not _validate_state(state):
        return _error_redirect("expired")

    try:
        access_token = _exchange_code(code, _callback_uri(request))
        profile, emails = _fetch_github_identity(access_token)
    except Exception:  # noqa: BLE001
        logger.warning("[auth] GitHub OAuth 换取身份失败", exc_info=True)
        return _error_redirect("github_failed")

    email = _pick_verified_email(profile, emails)
    github_id = str(profile.get("id") or "").strip()
    if not email or not github_id:
        return _error_redirect("no_verified_email")

    with SessionLocal() as db:
        user = db.query(User).filter(User.github_id == github_id).first()
        if user is None:
            # 同邮箱关联：GitHub 邮箱已验证，可安全视为同一个人
            user = db.query(User).filter(User.email == email).first()
            if user is not None:
                if user.github_id and user.github_id != github_id:
                    return _error_redirect("email_conflict")
                user.github_id = github_id
        if user is None:
            from app.auth import hash_password

            user = User(
                id=secrets.token_hex(16),
                email=email,
                display_name=(profile.get("name") or profile.get("login") or email.split("@", 1)[0])[:120],
                # 随机密码：GitHub 用户不知道它，密码通道实际不可用；可用「忘记密码」自主设置
                hashed_password=hash_password(secrets.token_urlsafe(32)),
                role="user",
                is_banned=0,
                email_verified=1,  # GitHub 侧已验证邮箱 → 免本系统验证
                github_id=github_id,
            )
            db.add(user)
            logger.info("[auth] GitHub OAuth 新用户：%s（%s）", email, github_id)
        if user.is_banned:
            record_audit(None, "auth.github_blocked", target_type="auth", target_id=email, ip=client_ip(request))
            return _error_redirect("banned")
        user.email_verified = 1  # GitHub 验证邮箱即视为已验证（含历史未验证账号的关联升级）
        user.last_seen_at = _now()
        db.commit()
        db.refresh(user)
        record_audit(
            {"id": user.id, "email": user.email},
            "auth.login_github",
            target_type="user",
            target_id=user.id,
            ip=client_ip(request),
        )
        resp = _ok_redirect()
        set_auth_cookie(resp, user.id)
        return resp
