"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";

/**
 * 重置密码页（/reset-password?token=...）。
 *
 * 独立于 (app) 工作台分组——未登录也能打开（进 (app) 会被 AuthGate 拦住）。
 * 打开先校验令牌；无效/过期则直接给出「重新申请」入口，不显示表单。
 */
export default function ResetPasswordPage() {
  const { resetPassword, validateResetToken } = useAuth();
  const [token, setToken] = useState("");
  const [checking, setChecking] = useState(true);
  const [valid, setValid] = useState(false);
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("token") ?? "";
    setToken(t);
    if (!t) {
      setValid(false);
      setChecking(false);
      return;
    }
    void (async () => {
      const ok = await validateResetToken(t);
      setValid(ok);
      setChecking(false);
    })();
  }, [validateResetToken]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (next !== confirm) {
      setError("两次输入的新密码不一致");
      return;
    }
    setBusy(true);
    try {
      await resetPassword(token, next);
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "重置失败，请重试");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-gate">
      {checking ? (
        <div className="auth-card">
          <h1 className="auth-card__title">正在校验链接…</h1>
        </div>
      ) : done ? (
        <div className="auth-card">
          <h1 className="auth-card__title">密码已重置</h1>
          <p className="auth-card__ok">新密码已生效，其他设备上的登录已全部失效。</p>
          <Link className="auth-card__submit" href="/" style={{ textAlign: "center", textDecoration: "none" }}>
            前往登录
          </Link>
        </div>
      ) : !valid ? (
        <div className="auth-card">
          <h1 className="auth-card__title">链接无效或已过期</h1>
          <p className="auth-card__hint" style={{ marginTop: 0 }}>
            重置链接只能使用一次，且 30 分钟后失效。请在登录页点「忘记密码？」重新申请一条。
          </p>
          <Link className="auth-card__submit" href="/" style={{ textAlign: "center", textDecoration: "none" }}>
            返回登录
          </Link>
        </div>
      ) : (
        <form className="auth-card" onSubmit={submit}>
          <h1 className="auth-card__title">设置新密码</h1>
          <p className="auth-card__hint" style={{ marginTop: 0 }}>
            为你的账号设置一个新密码（至少 8 位）。保存后所有设备都需要重新登录。
          </p>
          <label className="auth-card__field">
            <span>新密码</span>
            <input
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              placeholder="••••••••"
            />
          </label>
          <label className="auth-card__field">
            <span>确认新密码</span>
            <input
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder="••••••••"
            />
          </label>
          {error ? <p className="auth-card__error">{error}</p> : null}
          <button className="auth-card__submit" type="submit" disabled={busy}>
            {busy ? "提交中…" : "确认修改"}
          </button>
          <div className="auth-card__row">
            <Link className="auth-card__link" href="/">返回登录</Link>
          </div>
        </form>
      )}
    </div>
  );
}
