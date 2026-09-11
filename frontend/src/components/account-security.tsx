"use client";

import React, { useState } from "react";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth";

/**
 * 账号安全卡（修改密码）。仅公网/启用用户系统时显示；
 * 本地单机模式（无登录）不渲染，行为与旧版一致。
 */
export function AccountSecurity() {
  const { user, authRequired } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");

  if (!authRequired || !user) return null;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setOk("");
    if (next !== confirm) {
      setError("两次输入的新密码不一致");
      return;
    }
    setBusy(true);
    try {
      await apiRequest("/api/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      setOk("密码已修改。其他设备上的登录已全部失效，本机保持登录状态。");
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "修改失败，请重试");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="account-security">
      <h2>账号安全</h2>
      <p className="account-security__meta">
        当前登录：<strong>{user.display_name || user.email}</strong>（{user.email}）
      </p>
      <form className="auth-card account-security__form" onSubmit={submit}>
        <label className="auth-card__field">
          <span>当前密码</span>
          <input
            type="password"
            required
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            placeholder="••••••••"
          />
        </label>
        <label className="auth-card__field">
          <span>新密码（至少 8 位）</span>
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
        {ok ? <p className="auth-card__ok">{ok}</p> : null}
        <button className="auth-card__submit" type="submit" disabled={busy}>
          {busy ? "提交中…" : "修改密码"}
        </button>
      </form>
    </section>
  );
}
