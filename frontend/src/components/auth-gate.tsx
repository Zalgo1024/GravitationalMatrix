"use client";

import React, { useEffect, useState } from "react";
import { apiBaseUrl } from "@/lib/api";
import { useAuth } from "@/lib/auth";

/**
 * 登录门：公有模式（PUBLIC_MODE=1）下——
 * - 未登录 → 登录/注册卡片；
 * - 已登录但邮箱未验证 → 验证码卡片（重发 60 秒冷却）；
 * - 本地单机模式直接放行（零变化）。loading 期间显示占位避免闪烁。
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const { loading, user, authRequired } = useAuth();

  if (loading) {
    return (
      <div className="auth-gate auth-gate--loading">
        <p>正在检查登录状态…</p>
      </div>
    );
  }
  if (!authRequired) return <>{children}</>;
  if (!user) return <AuthCard />;
  if (!user.email_verified) return <VerifyCard />;
  return <>{children}</>;
}

const DEFAULT_AUTH_HINT =
  "注册即表示你将在此工作台保存的分析数据归属于本账号；分析模型密钥仅保存在你自己的浏览器中。";

const AUTH_ERROR_TEXT: Record<string, string> = {
  github_failed: "GitHub 登录失败，请稍后再试",
  expired: "GitHub 登录会话已过期，请重新点击登录",
  rate_limited: "尝试过于频繁，请稍后再试",
  no_verified_email: "GitHub 账号没有已验证的邮箱，无法用于登录",
  email_conflict: "该邮箱已绑定其他 GitHub 账号",
  banned: "账号已被封禁",
};

/** GitHub OAuth 登录卡按钮：后端 /api/auth/github/status enabled=true 才展示。 */
function GitHubButton({ mode }: { mode: "login" | "register" }) {
  const { githubEnabled } = useAuth();
  if (!githubEnabled) return null;
  return (
    <>
      <div className="auth-card__divider"><span>或</span></div>
      <button
        className="auth-card__github"
        type="button"
        onClick={() => { window.location.href = `${apiBaseUrl()}/api/auth/github/login`; }}
      >
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" fill="currentColor">
          <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
        </svg>
        {mode === "register" ? "使用 GitHub 注册" : "使用 GitHub 登录"}
      </button>
    </>
  );
}

/**
 * 登录/注册卡片。默认给工作台用；独立运营后台可传 title/hint 复用，
 * 从而不必先去工作台登录再跳转（见 app/admin-console/layout.tsx）。
 */
export function AuthCard({ title, hint }: { title?: string; hint?: string } = {}) {
  const { login, register, forgotPassword } = useAuth();
  const [tab, setTab] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [forgot, setForgot] = useState(false);
  const [sentHint, setSentHint] = useState("");

  // OAuth 回跳错误提示：/??auth_error=...（一次性，读后从地址栏清除）
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const err = params.get("auth_error");
    if (err) {
      setError(AUTH_ERROR_TEXT[err] ?? "登录失败，请重试");
      params.delete("auth_error");
      params.delete("login");
      const rest = params.toString();
      window.history.replaceState(null, "", window.location.pathname + (rest ? `?${rest}` : ""));
    }
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (forgot) {
        setSentHint(await forgotPassword(email.trim()));
      } else if (tab === "login") {
        await login(email.trim(), password);
      } else {
        await register({ email: email.trim(), password });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败，请重试");
    } finally {
      setBusy(false);
    }
  }

  // 忘记密码：只收邮箱；无论邮箱是否注册，都回同一句话（不泄露账号是否存在）。
  if (forgot) {
    return (
      <div className="auth-gate">
        <form className="auth-card" onSubmit={submit}>
          <h1 className="auth-card__title">重置密码</h1>
          <p className="auth-card__hint" style={{ marginTop: 0 }}>
            输入注册邮箱，我们会发送一条重置链接（30 分钟内有效，仅可使用一次）。
          </p>
          <label className="auth-card__field">
            <span>邮箱</span>
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
            />
          </label>
          {error ? <p className="auth-card__error">{error}</p> : null}
          {sentHint ? <p className="auth-card__ok">{sentHint}</p> : null}
          <button className="auth-card__submit" type="submit" disabled={busy || Boolean(sentHint)}>
            {busy ? "提交中…" : sentHint ? "已发送" : "发送重置链接"}
          </button>
          <div className="auth-card__row">
            <button
              className="auth-card__link"
              type="button"
              onClick={() => { setForgot(false); setError(""); setSentHint(""); }}
            >
              返回登录
            </button>
          </div>
        </form>
      </div>
    );
  }

  return (
    <div className="auth-gate">
      <form className="auth-card" onSubmit={submit}>
        <h1 className="auth-card__title">{title ?? "引力矩阵引擎"}</h1>
        <p className="auth-card__subtitle">把混沌事件，拆成可检验的结构</p>
        <div className="auth-card__tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "login"}
            className={tab === "login" ? "auth-card__tab auth-card__tab--active" : "auth-card__tab"}
            onClick={() => { setTab("login"); setError(""); }}
          >
            登录
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "register"}
            className={tab === "register" ? "auth-card__tab auth-card__tab--active" : "auth-card__tab"}
            onClick={() => { setTab("register"); setError(""); }}
          >
            注册
          </button>
        </div>
        <label className="auth-card__field">
          <span>邮箱</span>
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
          />
        </label>
        <label className="auth-card__field">
          <span>密码{tab === "register" ? "（至少 8 位）" : ""}</span>
          <input
            type="password"
            required
            minLength={tab === "register" ? 8 : undefined}
            autoComplete={tab === "register" ? "new-password" : "current-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
          />
        </label>
        {error ? <p className="auth-card__error">{error}</p> : null}
        <button className="auth-card__submit" type="submit" disabled={busy}>
          {busy ? "请稍候…" : tab === "login" ? "登录" : "注册并进入"}
        </button>
        <GitHubButton mode={tab} />
        {tab === "login" ? (
          <div className="auth-card__row">
            <button
              className="auth-card__link"
              type="button"
              onClick={() => { setForgot(true); setError(""); }}
            >
              忘记密码？
            </button>
          </div>
        ) : null}
        <p className="auth-card__hint">
          {hint ?? DEFAULT_AUTH_HINT}
        </p>
      </form>
    </div>
  );
}

function VerifyCard() {
  const { user, verify, resendVerification, logout } = useAuth();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [cooldown, setCooldown] = useState(60);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setInterval(() => setCooldown((s) => (s > 0 ? s - 1 : 0)), 1000);
    return () => clearInterval(t);
  }, [cooldown]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await verify(code.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : "验证失败，请重试");
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setError("");
    try {
      await resendVerification();
      setCooldown(60);
      setError("已重新发送，请查收邮箱（可能在垃圾邮件里）");
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送失败，请稍后再试");
    }
  }

  return (
    <div className="auth-gate">
      <form className="auth-card" onSubmit={submit}>
        <h1 className="auth-card__title">验证你的邮箱</h1>
        <p className="auth-card__hint" style={{ marginTop: 0 }}>
          验证码已发送至 <strong>{user?.email}</strong>，15 分钟内有效。收不到的话看看垃圾邮件，或在下方重新发送。
        </p>
        <label className="auth-card__field">
          <span>6 位验证码</span>
          <input
            type="text"
            required
            inputMode="numeric"
            pattern="\d{6}"
            maxLength={6}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            placeholder="000000"
            style={{ letterSpacing: "0.5em", textAlign: "center", fontSize: 20 }}
          />
        </label>
        {error ? <p className={error.startsWith("已重新发送") ? "auth-card__ok" : "auth-card__error"}>{error}</p> : null}
        <button className="auth-card__submit" type="submit" disabled={busy}>
          {busy ? "验证中…" : "完成验证，进入工作台"}
        </button>
        <div className="auth-card__row">
          <button className="auth-card__link" type="button" disabled={cooldown > 0} onClick={() => void resend()}>
            {cooldown > 0 ? `重新发送（${cooldown}s）` : "重新发送验证码"}
          </button>
          <button className="auth-card__link" type="button" onClick={() => void logout()}>
            换个账号
          </button>
        </div>
      </form>
    </div>
  );
}
