"""认证与用户管理接口（用户系统 Phase 0 + 邮箱验证 Phase 1 + 账户恢复流 Phase 2）。

- POST /api/auth/register  注册（邮箱+密码；PUBLIC_MODE=1 时启用，本地模式 404）
- POST /api/auth/login     登录（签发 httpOnly cookie）
- POST /api/auth/logout    登出（清 cookie）
- GET  /api/auth/me        当前用户
- POST /api/auth/verify    邮箱验证码校验（登录态）
- POST /api/auth/resend-verification  重发验证码（登录态，60 秒冷却）
- POST /api/auth/change-password      修改密码（登录态；成功后其他设备立即下线）
- POST /api/auth/forgot-password      申请重置密码（匿名；无论邮箱是否存在都回同一句话，不泄露）
- GET  /api/auth/reset-password/validate  校验重置令牌是否可用（匿名）
- POST /api/auth/reset-password       用令牌设置新密码（匿名；单次使用，改后全端下线）
- GET  /api/admin/users    用户列表（仅 admin）
- POST /api/admin/users/{uid}/ban  封禁/解封（仅 admin）

邮箱验证规则：backend/.env 配置了 SMTP_HOST/SMTP_USER/SMTP_PASS 才启用；
未配置时注册直接视为已验证（email_verified=1），注册/登录流程零变化。

账户恢复规则：重置令牌在库中只存 sha256 哈希、单次使用、30 分钟过期；
重置成功后写 token_valid_after，使此前签发的所有 JWT 立即失效。
"""
import logging
import re
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from app.audit import client_ip, record_audit
from app.auth import (
    RESET_TTL_MINUTES as _RESET_TTL_MINUTES,
    build_reset_url as _build_reset_url,
    clear_auth_cookie,
    get_current_user,
    hash_password,
    hash_reset_token as _hash_reset_token,
    issue_reset_token as _issue_reset_token,
    rate_limiter,
    set_auth_cookie,
    verify_password,
)
from app.db import SessionLocal
from app.email_sender import send_password_reset_email, send_verification_email
from app.models import PasswordResetToken, Task, User, _now
from app.settings import settings

logger = logging.getLogger("app")

router = APIRouter(prefix="/api/auth")
admin_router = APIRouter(prefix="/api/admin")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_CODE_TTL_MINUTES = 15
_RESEND_COOLDOWN_SECONDS = 60


class RegisterIn(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=120)


class LoginIn(BaseModel):
    email: str
    password: str


class VerifyIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


def _public_user(u: User) -> dict:
    return {
        "id": u.id,
        "email": u.email,
        "display_name": u.display_name,
        "role": u.role or "user",
        "email_verified": bool(u.email_verified) if u.email_verified is not None else False,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def _issue_verification_code(user: User, db) -> bool:
    """生成并（线程内）发送验证码。返回是否已安排发送。失败时用户可重发。"""
    code = f"{secrets.randbelow(1000000):06d}"
    user.verification_code = code
    user.verification_code_expires = _now() + timedelta(minutes=_CODE_TTL_MINUTES)
    db.commit()
    to = user.email
    issued_code = code

    def _deliver() -> None:
        ok = send_verification_email(to, issued_code)
        if not ok:
            logger.warning("[auth] 验证码邮件未送达（用户可点重新发送）：%s", to)

    threading.Thread(target=_deliver, daemon=True).start()
    return True


@router.post("/register")
def register(body: RegisterIn, request: Request, response: Response):
    if not settings.public_mode:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status": "not_found", "message": "本地模式无需注册"},
        )

    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail={"status": "invalid", "message": "邮箱格式不正确"})

    ip = request.client.host if request.client else "unknown"
    if not rate_limiter.allow(f"reg:{ip}", limit=3, window_sec=60) or not rate_limiter.allow(
        f"reg:{ip}", limit=10, window_sec=3600
    ):
        raise HTTPException(status_code=429, detail={"status": "rate_limited", "message": "注册过于频繁，请稍后再试"})

    with SessionLocal() as db:
        exists = db.query(User).filter(User.email == email).first()
        if exists:
            raise HTTPException(status_code=409, detail={"status": "conflict", "message": "该邮箱已注册，请直接登录"})

        # SMTP 未配置 → 验证功能关闭，注册即视为已验证（本地/公测零变化）
        email_verified = 0 if settings.smtp_enabled else 1
        user = User(
            id=uuid.uuid4().hex,
            email=email,
            display_name=(body.display_name or email.split("@", 1)[0]).strip()[:120],
            hashed_password=hash_password(body.password),
            role="user",
            is_banned=0,
            email_verified=email_verified,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        if not user.email_verified:
            _issue_verification_code(user, db)
        set_auth_cookie(response, user.id)
        logger.info("[auth] 新用户注册：%s（%s，邮箱验证=%s）", email, user.id, "开" if not user.email_verified else "关")
        record_audit(
            {"id": user.id, "email": user.email},
            "auth.register",
            target_type="user",
            target_id=user.id,
            ip=client_ip(request),
        )
        return {
            "status": "ok",
            "user": _public_user(user),
            "verification_required": not user.email_verified,
        }


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    if not settings.public_mode:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status": "not_found", "message": "本地模式无需登录"},
        )

    email = body.email.strip().lower()
    ip = request.client.host if request.client else "unknown"
    if not rate_limiter.allow(f"login:{ip}", limit=5, window_sec=60) or not rate_limiter.allow(
        f"login:{email}", limit=10, window_sec=300
    ):
        raise HTTPException(status_code=429, detail={"status": "rate_limited", "message": "尝试过于频繁，请稍后再试"})

    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).first()
        if user is None or not verify_password(body.password, user.hashed_password or ""):
            record_audit(
                None, "auth.login_failed", target_type="auth", target_id=email, ip=client_ip(request)
            )
            raise HTTPException(status_code=401, detail={"status": "unauthorized", "message": "邮箱或密码不正确"})
        if user.is_banned:
            record_audit(
                {"id": user.id, "email": user.email},
                "auth.login_blocked",
                target_type="user",
                target_id=user.id,
                ip=client_ip(request),
            )
            raise HTTPException(status_code=403, detail={"status": "forbidden", "message": "账号已被封禁"})

        user.last_seen_at = _now()
        db.commit()
        set_auth_cookie(response, user.id)
        return {"status": "ok", "user": _public_user(user)}


@router.post("/logout")
def logout(response: Response):
    clear_auth_cookie(response)
    return {"status": "ok"}


@router.get("/me")
def me(current: dict = Depends(get_current_user)):
    return {"status": "ok", "user": current}


# ---------------------------------------------------------------------------
# 邮箱验证（Phase 1）
# ---------------------------------------------------------------------------
@router.post("/verify")
def verify_email(body: VerifyIn, current: dict = Depends(get_current_user)):
    if not settings.smtp_enabled:
        raise HTTPException(status_code=400, detail={"status": "disabled", "message": "邮箱验证未启用"})
    if not rate_limiter.allow(f"verify:{current['id']}", limit=5, window_sec=600):
        raise HTTPException(status_code=429, detail={"status": "rate_limited", "message": "尝试过于频繁，请 10 分钟后再试"})

    with SessionLocal() as db:
        user = db.get(User, current["id"])
        if user is None:
            raise HTTPException(status_code=401, detail={"status": "unauthorized", "message": "账号不存在"})
        if user.email_verified:
            return {"status": "ok", "already_verified": True, "user": _public_user(user)}
        if not user.verification_code or not user.verification_code_expires:
            raise HTTPException(status_code=400, detail={"status": "no_code", "message": "验证码不存在，请先重新发送"})
        # SQLite 读回的是 naive UTC（timezone=True 不生效），统一转 naive 再比较
        expires = user.verification_code_expires
        if expires.tzinfo is not None:
            expires = expires.astimezone(timezone.utc).replace(tzinfo=None)
        if datetime.now(timezone.utc).replace(tzinfo=None) > expires:
            raise HTTPException(status_code=400, detail={"status": "expired", "message": "验证码已过期，请重新发送"})
        if body.code.strip() != user.verification_code:
            raise HTTPException(status_code=400, detail={"status": "invalid_code", "message": "验证码不正确"})

        user.email_verified = 1
        user.verification_code = None
        user.verification_code_expires = None
        db.commit()
        logger.info("[auth] 邮箱验证通过：%s", user.email)
        return {"status": "ok", "already_verified": False, "user": _public_user(user)}


@router.post("/resend-verification")
def resend_verification(current: dict = Depends(get_current_user)):
    if not settings.smtp_enabled:
        raise HTTPException(status_code=400, detail={"status": "disabled", "message": "邮箱验证未启用"})
    if not rate_limiter.allow(f"resend:{current['id']}", limit=1, window_sec=_RESEND_COOLDOWN_SECONDS):
        raise HTTPException(
            status_code=429,
            detail={"status": "rate_limited", "message": f"发送过于频繁，请 {_RESEND_COOLDOWN_SECONDS} 秒后再试"},
        )

    with SessionLocal() as db:
        user = db.get(User, current["id"])
        if user is None:
            raise HTTPException(status_code=401, detail={"status": "unauthorized", "message": "账号不存在"})
        if user.email_verified:
            return {"status": "ok", "already_verified": True}
        _issue_verification_code(user, db)
        return {"status": "ok", "already_verified": False}


# ---------------------------------------------------------------------------
# 修改密码（登录态）
# ---------------------------------------------------------------------------
class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/change-password")
def change_password(
    body: ChangePasswordIn,
    request: Request,
    response: Response,
    current: dict = Depends(get_current_user),
):
    if not settings.public_mode:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status": "not_found", "message": "本地模式无需修改密码"},
        )
    if not rate_limiter.allow(f"chgpass:{current['id']}", limit=5, window_sec=600):
        raise HTTPException(
            status_code=429,
            detail={"status": "rate_limited", "message": "尝试过于频繁，请 10 分钟后再试"},
        )

    with SessionLocal() as db:
        user = db.get(User, current["id"])
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"status": "unauthorized", "message": "账号不存在"},
            )
        if not verify_password(body.current_password, user.hashed_password or ""):
            raise HTTPException(
                status_code=400,
                detail={"status": "invalid", "message": "当前密码不正确"},
            )
        if body.current_password == body.new_password:
            raise HTTPException(
                status_code=400,
                detail={"status": "invalid", "message": "新密码不能与当前密码相同"},
            )
        user.hashed_password = hash_password(body.new_password)
        # 会话失效锚点：其他设备上尚未过期的旧令牌立即失效
        user.token_valid_after = _now()
        db.commit()
        # 当前这台设备重新签发令牌，避免把操作者自己也踢下线
        set_auth_cookie(response, user.id)
        logger.info("[auth] 用户修改密码：%s", user.email)
        record_audit(
            current,
            "auth.change_password",
            target_type="user",
            target_id=user.id,
            ip=client_ip(request),
        )
        return {"status": "ok", "sessions_invalidated": True}


# ---------------------------------------------------------------------------
# 账户恢复流（忘记密码 → 邮件重置链接 → 设置新密码）
# ---------------------------------------------------------------------------
class ForgotPasswordIn(BaseModel):
    email: str = Field(min_length=5, max_length=255)


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=16, max_length=256)
    new_password: str = Field(min_length=8, max_length=128)


def _naive_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordIn, request: Request):
    """申请重置密码。**无论邮箱是否注册，都返回同一句话**，避免账号枚举。"""
    if not settings.public_mode:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status": "not_found", "message": "本地模式无需重置密码"},
        )

    email = body.email.strip().lower()
    ip = client_ip(request) or "unknown"
    if not rate_limiter.allow(f"forgot:{ip}", limit=5, window_sec=600) or not rate_limiter.allow(
        f"forgot:{email}", limit=3, window_sec=600
    ):
        raise HTTPException(
            status_code=429, detail={"status": "rate_limited", "message": "操作过于频繁，请稍后再试"}
        )

    result: dict = {
        "status": "ok",
        "message": "如果该邮箱已注册，我们已发送重置链接，请查收（30 分钟内有效）。",
    }

    if _EMAIL_RE.match(email):
        with SessionLocal() as db:
            user = db.query(User).filter(User.email == email).first()
            if user is not None and not user.is_banned:
                raw = _issue_reset_token(user, db)
                url = _build_reset_url(raw)
                if not settings.smtp_enabled:
                    logger.warning("[auth] SMTP 未配置，重置链接仅记录在后端日志：%s", url)
                threading.Thread(
                    target=send_password_reset_email,
                    args=(user.email, url, _RESET_TTL_MINUTES),
                    daemon=True,
                ).start()
                record_audit(None, "auth.forgot_password", target_type="user", target_id=user.id, ip=ip)
                # 本地调试开关（默认关，生产必须关）：SMTP 未配且显式开启时才回显链接
                if settings.dev_reset_echo and not settings.smtp_enabled:
                    result["dev_reset_url"] = url

    return result


@router.get("/reset-password/validate")
def validate_reset_token(token: str):
    """校验重置令牌是否可用（供重置页显示「链接已失效」）。"""
    if not settings.public_mode:
        return {"status": "ok", "valid": False}
    with SessionLocal() as db:
        row = (
            db.query(PasswordResetToken)
            .filter(
                PasswordResetToken.token_hash == _hash_reset_token(token.strip()),
                PasswordResetToken.used_at.is_(None),
            )
            .first()
        )
        exp = _naive_utc(row.expires_at) if row else None
        valid = bool(exp) and datetime.now(timezone.utc).replace(tzinfo=None) <= exp
        return {"status": "ok", "valid": valid}


@router.post("/reset-password")
def reset_password(body: ResetPasswordIn, request: Request):
    """用令牌设置新密码。成功后：令牌作废 + 全端会话失效（token_valid_after）。"""
    if not settings.public_mode:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"status": "not_found", "message": "本地模式无需重置密码"},
        )

    ip = client_ip(request) or "unknown"
    if not rate_limiter.allow(f"reset:{ip}", limit=10, window_sec=600):
        raise HTTPException(
            status_code=429, detail={"status": "rate_limited", "message": "尝试过于频繁，请稍后再试"}
        )

    token_hash = _hash_reset_token(body.token.strip())
    with SessionLocal() as db:
        row = (
            db.query(PasswordResetToken)
            .filter(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
            )
            .first()
        )
        if row is None:
            raise HTTPException(
                status_code=400,
                detail={"status": "invalid_token", "message": "重置链接无效或已被使用，请重新申请"},
            )
        exp = _naive_utc(row.expires_at)
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        if exp is None or now_naive > exp:
            raise HTTPException(
                status_code=400,
                detail={"status": "expired_token", "message": "重置链接已过期，请重新申请"},
            )

        user = db.get(User, row.user_id)
        if user is None:
            raise HTTPException(
                status_code=400,
                detail={"status": "invalid_token", "message": "重置链接无效，请重新申请"},
            )
        if user.is_banned:
            raise HTTPException(status_code=403, detail={"status": "forbidden", "message": "账号已被封禁"})

        user.hashed_password = hash_password(body.new_password)
        user.token_valid_after = _now()  # 全端下线：此前签发的所有 JWT 立即失效
        row.used_at = _now()
        for other in (
            db.query(PasswordResetToken)
            .filter(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.id != row.id,
            )
            .all()
        ):
            other.used_at = _now()
        db.commit()
        logger.info("[auth] 用户重置密码成功：%s", user.email)
        record_audit(None, "auth.reset_password", target_type="user", target_id=user.id, ip=ip)

    return {"status": "ok", "message": "密码已重置，请用新密码登录"}


# ---------------------------------------------------------------------------
# admin（用户管理后台）
# ---------------------------------------------------------------------------
@admin_router.get("/users")
def list_users(current: dict = Depends(get_current_user)):
    _require_admin_dict(current)
    with SessionLocal() as db:
        users = db.query(User).order_by(User.created_at.desc()).all()
        items = []
        for u in users:
            report_count = db.query(Task).filter(Task.owner_id == u.id).count()
            items.append(
                {
                    **_public_user(u),
                    "is_banned": u.is_banned or 0,
                    "report_count": report_count,
                    "last_seen_at": u.last_seen_at.isoformat() if u.last_seen_at else None,
                }
            )
        # 统计总览：注册规模 / 验证 / 封禁 / 近 7 日新增与活跃
        # SQLite 读回 naive UTC；_now() 可能带 tzinfo —— 统一压成 naive 再比较
        now = _now()
        now_naive = now.replace(tzinfo=None) if now.tzinfo else now
        week_ago = now_naive - timedelta(days=7)

        def _naive(dt):
            if dt is None:
                return None
            return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt

        stats = {
            "total": len(users),
            "admins": sum(1 for u in users if u.role == "admin"),
            "verified": sum(1 for u in users if u.email_verified),
            "banned": sum(1 for u in users if u.is_banned),
            "new_7d": sum(1 for u in users if _naive(u.created_at) and _naive(u.created_at) >= week_ago),
            "active_7d": sum(1 for u in users if _naive(u.last_seen_at) and _naive(u.last_seen_at) >= week_ago),
        }
        return {"status": "ok", "users": items, "total": len(items), "stats": stats}


@admin_router.post("/users/{uid}/ban")
def ban_user(uid: str, body: dict, request: Request, current: dict = Depends(get_current_user)):
    _require_admin_dict(current)
    banned = 1 if body.get("banned") else 0
    with SessionLocal() as db:
        user = db.get(User, uid)
        if user is None:
            raise HTTPException(status_code=404, detail={"status": "not_found", "message": "用户不存在"})
        if user.role == "admin":
            raise HTTPException(status_code=400, detail={"status": "invalid", "message": "不能封禁管理员账号"})
        user.is_banned = banned
        db.commit()
        record_audit(
            current,
            "user.ban" if banned else "user.unban",
            target_type="user",
            target_id=uid,
            detail={"email": user.email, "banned": banned},
            ip=client_ip(request),
        )
        return {"status": "ok", "id": uid, "is_banned": banned}


def _require_admin_dict(current: dict) -> None:
    if current.get("role") != "admin":
        raise HTTPException(status_code=403, detail={"status": "forbidden", "message": "需要管理员权限"})
