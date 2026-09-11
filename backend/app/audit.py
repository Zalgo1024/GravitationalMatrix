"""审计日志写入（运营留痕）。

设计要点：
- **自持会话**：record_audit 自己开一个 SessionLocal 提交，不与调用方的业务事务
  共用连接——避免审计写入把业务事务带崩，也避免业务回滚连审计一起回滚。
- **绝不抛异常**：审计失败只记 warning，不能拖垮主流程（封禁/删除照常完成）。
- **冗余快照**：actor_id / actor_email 落库时一并写入，用户被删后日志仍可读。

用法：
    from app.audit import record_audit, client_ip
    record_audit(admin, "user.ban", target_type="user", target_id=uid, detail={"banned": 1}, ip=client_ip(request))
"""
import logging

from fastapi import Request

from app.db import SessionLocal
from app.models import AuditLog

logger = logging.getLogger("app")


def client_ip(request: Request | None) -> str | None:
    """取客户端 IP（优先 X-Forwarded-For 首个地址，兼容反代部署）。"""
    if request is None:
        return None
    try:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()[:64]
        return (request.client.host if request.client else None)
    except Exception:  # noqa: BLE001
        return None


def record_audit(
    actor: dict | None,
    action: str,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict | None = None,
    ip: str | None = None,
) -> None:
    """写入一条审计日志。失败静默（仅 warning），不阻塞业务。"""
    try:
        with SessionLocal() as db:
            db.add(
                AuditLog(
                    actor_id=(actor or {}).get("id"),
                    actor_email=(actor or {}).get("email"),
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    detail=detail,
                    ip=ip,
                )
            )
            db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("[audit] 写入失败 action=%s target=%s", action, target_id, exc_info=True)
