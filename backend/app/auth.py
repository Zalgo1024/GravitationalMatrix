"""认证核心（用户系统 Phase 0）。

职责：
- 密码哈希（bcrypt）
- JWT 签发 / 校验（HS256，密钥自动生成并持久化到 backend/.env）
- get_current_user 依赖：PUBLIC_MODE=1 时校验登录 + 封禁；=0（本地单机）返回虚拟归属身份
- 登录 / 注册限速（进程内存计数，重启即清——足够 Phase 0）

设计红线：与 BYOK 零耦合 —— 本模块不读取、不存储任何 LLM 密钥。
"""
import hashlib
import logging
import os
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security.utils import get_authorization_scheme_param

from app.db import SessionLocal
from app.models import User
from app.settings import settings

logger = logging.getLogger("app")

COOKIE_NAME = "sy_token"
TOKEN_TTL_HOURS = 24 * 7  # 7 天
JWT_ALGO = "HS256"


# ---------------------------------------------------------------------------
# AUTH_SECRET：自动生成并持久化到 backend/.env（不入 git）
# ---------------------------------------------------------------------------
def _load_or_create_secret() -> str:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    secret = os.environ.get("AUTH_SECRET", "").strip()
    if secret:
        return secret

    # .env 里可能有旧值但未加载进环境（dotenv 在 settings 之前已 load），
    # 直接扫一遍 .env 文本兜底
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("AUTH_SECRET=") and len(line) > len("AUTH_SECRET="):
                return line.split("=", 1)[1].strip()

    secret = secrets.token_urlsafe(48)
    try:
        with open(env_path, "a", encoding="utf-8") as f:
            f.write(f"\nAUTH_SECRET={secret}\n")
        logger.info("[auth] AUTH_SECRET 已生成并写入 backend/.env")
    except OSError:
        logger.warning("[auth] AUTH_SECRET 写入 .env 失败，将使用进程内临时密钥（重启后所有登录失效）")
    return secret


AUTH_SECRET = _load_or_create_secret()


# ---------------------------------------------------------------------------
# 密码哈希
# ---------------------------------------------------------------------------
def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
def _create_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(hours=TOKEN_TTL_HOURS),
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, AUTH_SECRET, algorithm=JWT_ALGO)


def _decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, AUTH_SECRET, algorithms=[JWT_ALGO])


def set_auth_cookie(response: Response, user_id: str) -> None:
    token = _create_token(user_id)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=TOKEN_TTL_HOURS * 3600,
        httponly=True,
        # 注意不能用 bool(os.environ.get("PUBLIC_MODE"))：字符串 "0" 是 truthy，
        # 会给本地 http 的 cookie 打上 Secure 导致浏览器不回传（测试也因此 401）。
        secure=settings.public_mode,
        samesite="lax",
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


# ---------------------------------------------------------------------------
# 限速（进程内存；重启清零 —— Phase 0 够用）
# ---------------------------------------------------------------------------
class _RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_sec: int) -> bool:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > window_sec:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


rate_limiter = _RateLimiter()


# ---------------------------------------------------------------------------
# 当前用户解析（核心依赖）
# ---------------------------------------------------------------------------
_ANON = {"id": None, "email": None, "display_name": None, "role": None, "is_banned": 0}


def _user_dict(u: User) -> dict[str, Any]:
    # 邮箱验证是开关式功能：SMTP 未配置时验证流程根本不存在，
    # 此时一律视为已验证，避免 seed 出的 admin / 历史账号被验证卡片死锁。
    email_verified = bool(u.email_verified)
    if not settings.smtp_enabled:
        email_verified = True
    return {
        "id": u.id,
        "email": u.email,
        "display_name": u.display_name,
        "role": u.role or "user",
        "is_banned": u.is_banned or 0,
        "email_verified": email_verified,
    }


def _load_user(user_id: str) -> User | None:
    with SessionLocal() as db:
        return db.get(User, user_id)


def get_current_user(request: Request) -> dict[str, Any]:
    """FastAPI 依赖：解析当前用户。

    - PUBLIC_MODE=0（本地单机）：不做任何校验，返回虚拟身份（owner_id 用 default_owner_id），
      现有接口行为零变化 —— 这是「本地零回归」的关键。
    - PUBLIC_MODE=1（公网）：cookie 里必须有合法 JWT 且用户未被封禁，否则 401。
      例外：标记了 public=True 的只读演示接口自行决定不挂本依赖。
    """
    if not settings.public_mode:
        return {
            "id": settings.default_owner_id,
            "email": None,
            "display_name": settings.default_owner_name,
            "role": "admin",
            "is_banned": 0,
        }

    token = request.cookies.get(COOKIE_NAME)
    if not token:
        # 兼容 Authorization: Bearer <token>（脚本/测试用）
        auth = request.headers.get("Authorization", "")
        scheme, param = get_authorization_scheme_param(auth)
        if scheme.lower() == "bearer" and param:
            token = param
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"status": "unauthorized", "message": "请先登录"},
        )
    try:
        payload = _decode_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"status": "unauthorized", "message": "登录已过期，请重新登录"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"status": "unauthorized", "message": "登录状态无效"},
        )

    user_id = payload.get("sub")
    user = _load_user(user_id) if user_id else None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"status": "unauthorized", "message": "账号不存在"},
        )
    if user.is_banned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"status": "forbidden", "message": "账号已被封禁"},
        )

    # 会话失效锚点（账户恢复流）：改密 / 重置密码后置位，此前签发的令牌一律作废。
    # 只在锚点存在时比较；SQLite 读回为 naive(UTC)，统一按 UTC 处理。
    tva = user.token_valid_after
    if tva is not None:
        tva_aware = tva.replace(tzinfo=timezone.utc) if tva.tzinfo is None else tva
        iat = payload.get("iat")
        if isinstance(iat, (int, float)):
            issued = datetime.fromtimestamp(int(iat), tz=timezone.utc)
            # iat 只有秒级精度，锚点带微秒：把锚点也截到秒，
            # 使「改密/重置的同一秒内签发的新令牌」不被误判为旧令牌。
            if issued < tva_aware.replace(microsecond=0):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"status": "unauthorized", "message": "登录状态已失效，请重新登录"},
                )

    # 最后活跃时间（后台看板用）——低频更新：距上次 >5 分钟才写
    now = datetime.now(timezone.utc)
    if user.last_seen_at is None or (now - user.last_seen_at.replace(tzinfo=timezone.utc)).total_seconds() > 300:
        try:
            with SessionLocal() as db:
                row = db.get(User, user.id)
                if row:
                    row.last_seen_at = now
                    db.commit()
        except Exception:  # 看板字段失败不影响主流程
            logger.debug("[auth] last_seen_at 更新失败", exc_info=True)

    return _user_dict(user)


def require_admin(current: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if current.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"status": "forbidden", "message": "需要管理员权限"},
        )
    return current


# ---------------------------------------------------------------------------
# 资源归属校验（数据隔离核心 helper）
# ---------------------------------------------------------------------------
def task_owned(db, task_id: str, current: dict[str, Any]):
    """取任务并校验归属。不存在 / 不属于当前用户 → None（接口按 not_found 处理，不泄露存在性）。

    - 本地单机模式（PUBLIC_MODE=0）：不做过滤（current.id=default_owner_id，迁移已保证行归属一致）；
    - 公共模式：owner_id 必须等于当前用户；owner_id 为 NULL 的行不可见（启动迁移后不应存在）。
    """
    from app.models import Task

    t = db.get(Task, task_id)
    if t is None:
        return None
    if not settings.public_mode:
        return t
    if t.owner_id != current.get("id"):
        return None
    return t


def project_owned(db, pid: str, current: dict[str, Any]):
    """同 task_owned，作用于 Project。"""
    from app.models import Project

    p = db.get(Project, pid)
    if p is None:
        return None
    if not settings.public_mode:
        return p
    if p.owner_id != current.get("id"):
        return None
    return p


def user_from_ws_cookies(cookies: dict) -> dict[str, Any] | None:
    """WebSocket 握手校验：浏览器 ws 连接会自动带 cookie。返回用户 dict，未登录/无效返回 None。"""
    if not settings.public_mode:
        return {
            "id": settings.default_owner_id,
            "email": None,
            "display_name": settings.default_owner_name,
            "role": "admin",
            "is_banned": 0,
        }
    token = cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        payload = _decode_token(token)
    except jwt.InvalidTokenError:
        return None
    u = _load_user(payload.get("sub"))
    if u is None or u.is_banned:
        return None
    return _user_dict(u)


def require_enabled_auth() -> None:
    """占位依赖：标记「PUBLIC_MODE 下需要登录、本地模式跳过」的路由使用 get_current_user 即可，
    此函数保留给未来需要「仅公网启用的中间件级逻辑」时使用。"""
    if settings.public_mode:
        return
    return None


# ---------------------------------------------------------------------------
# 账户恢复流：重置令牌工具（哈希存储 / 单次使用 / 短时效）
# 放在认证核心，供 routers/auth.py（匿名申请）与 routers/admin_ops.py（管理员代发）共用。
# ---------------------------------------------------------------------------
RESET_TTL_MINUTES = 30


def hash_reset_token(raw: str) -> str:
    """重置令牌只以 sha256 十六进制入库；明文仅存在于邮件链接里。"""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_reset_url(raw_token: str) -> str:
    return f"{settings.public_base_url}/reset-password?token={raw_token}"


def issue_reset_token(user: User, db) -> str:
    """作废该用户此前所有未用令牌，签发一枚新令牌，返回明文（明文只在这一句出现）。"""
    from app.models import PasswordResetToken

    now = datetime.now(timezone.utc)
    for old in (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .all()
    ):
        old.used_at = now
    raw = secrets.token_urlsafe(32)
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_reset_token(raw),
            expires_at=now + timedelta(minutes=RESET_TTL_MINUTES),
        )
    )
    db.commit()
    return raw
