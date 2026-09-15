"""注册邮箱验证码发送（Phase 1）。

- 纯标准库 smtplib（SSL 465），零新依赖；QQ / 163 / Gmail 等 SMTP 均可用。
- 配置读 settings（SMTP_HOST/PORT/USER/PASS/SENDER），未配置时 smtp_enabled=False，
  注册流程整体跳过验证（email_verified=1），本地与公测行为零变化。
- 发送失败不抛异常（返回 False），注册主流程不受影响——用户可稍后点"重新发送"。
"""
import logging
import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

from app.settings import settings

logger = logging.getLogger("app")

_CODE_MAIL_HTML = """\
<div style="max-width:480px;margin:0 auto;font-family:'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;">
  <h2 style="margin:0 0 6px;font-size:18px;">引力力矩</h2>
  <p style="margin:0 0 18px;color:#666;font-size:13px;">你正在注册/验证邮箱，验证码如下（15 分钟内有效）：</p>
  <div style="display:inline-block;background:#f5f5f2;border:1px solid #e2e2dd;border-radius:10px;
              padding:14px 28px;font-size:28px;font-weight:800;letter-spacing:8px;color:#111;">{code}</div>
  <p style="margin:18px 0 0;color:#999;font-size:12px;">如果这不是你的操作，请忽略本邮件，账号不会被激活使用。</p>
</div>
"""


def send_verification_email(to: str, code: str) -> bool:
    """发送验证码邮件。成功 True；未配置/失败 False（不抛出）。"""
    if not settings.smtp_enabled:
        logger.warning("[email] SMTP 未配置，跳过发送验证码到 %s", to)
        return False
    try:
        msg = MIMEText(_CODE_MAIL_HTML.format(code=code), "html", "utf-8")
        msg["Subject"] = Header(f"【引力力矩】邮箱验证码 {code}", "utf-8")
        msg["From"] = formataddr((str(Header("引力力矩", "utf-8")), settings.smtp_sender))
        msg["To"] = formataddr((to, to))

        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            server.login(settings.smtp_user, settings.smtp_pass)
            server.sendmail(settings.smtp_sender, [to], msg.as_string())
        logger.info("[email] 验证码已发送至 %s", to)
        return True
    except Exception:  # noqa: BLE001 —— 邮件失败不能挡注册主流程
        logger.exception("[email] 验证码发送失败：%s", to)
        return False


_RESET_MAIL_HTML = """\
<div style="max-width:480px;margin:0 auto;font-family:'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;">
  <h2 style="margin:0 0 6px;font-size:18px;">引力力矩</h2>
  <p style="margin:0 0 18px;color:#666;font-size:13px;">你申请了重置密码。点击下面的按钮设置新密码（{ttl} 分钟内有效，仅可使用一次）：</p>
  <p style="margin:0 0 18px;">
    <a href="{url}" style="display:inline-block;background:#111;color:#fff;text-decoration:none;
       border-radius:8px;padding:11px 22px;font-size:14px;">重置密码</a>
  </p>
  <p style="margin:0 0 6px;color:#999;font-size:12px;">按钮打不开时，把下面的链接复制到浏览器：</p>
  <p style="margin:0 0 18px;font-size:12px;word-break:break-all;color:#555;">{url}</p>
  <p style="margin:18px 0 0;color:#999;font-size:12px;">如果这不是你的操作，请忽略本邮件，你的密码不会改变。</p>
</div>
"""


def send_password_reset_email(to: str, reset_url: str, ttl_minutes: int = 30) -> bool:
    """发送「重置密码」邮件。成功 True；未配置/失败 False（不抛出）。"""
    if not settings.smtp_enabled:
        logger.warning("[email] SMTP 未配置，跳过发送重置邮件到 %s（重置链接见后端日志）", to)
        return False
    try:
        msg = MIMEText(_RESET_MAIL_HTML.format(url=reset_url, ttl=ttl_minutes), "html", "utf-8")
        msg["Subject"] = Header("【引力力矩】重置你的登录密码", "utf-8")
        msg["From"] = formataddr((str(Header("引力力矩", "utf-8")), settings.smtp_sender))
        msg["To"] = formataddr((to, to))

        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            server.login(settings.smtp_user, settings.smtp_pass)
            server.sendmail(settings.smtp_sender, [to], msg.as_string())
        logger.info("[email] 重置密码邮件已发送至 %s", to)
        return True
    except Exception:  # noqa: BLE001 —— 邮件失败不抛出，调用方按「已受理」处理
        logger.exception("[email] 重置密码邮件发送失败：%s", to)
        return False
