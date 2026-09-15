"use client";

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { apiBaseUrl } from "@/lib/api";

export interface AuthUser {
  id: string;
  email: string | null;
  display_name: string | null;
  role: string;
  email_verified?: boolean;
}

interface AuthValue {
  loading: boolean;
  /** 当前用户；null = 未登录（仅公有模式会出现） */
  user: AuthUser | null;
  /** true = 后端处于公有模式（需要登录才能用工作台） */
  authRequired: boolean;
  /** true = 后端已配置 GitHub OAuth（登录卡显示「使用 GitHub 登录」按钮） */
  githubEnabled: boolean;
  error: string;
  login: (email: string, password: string) => Promise<void>;
  register: (input: { email: string; password: string; display_name?: string }) => Promise<void>;
  logout: () => Promise<void>;
  verify: (code: string) => Promise<void>;
  resendVerification: () => Promise<void>;
  /** 申请重置密码；返回后端给用户的提示语（不区分邮箱是否存在） */
  forgotPassword: (email: string) => Promise<string>;
  /** 用重置令牌设置新密码 */
  resetPassword: (token: string, newPassword: string) => Promise<void>;
  /** 校验重置令牌是否仍然可用 */
  validateResetToken: (token: string) => Promise<boolean>;
}

const AuthContext = createContext<AuthValue | null>(null);

/**
 * 模式探测逻辑（一次 /api/auth/me 请求同时回答两个问题）：
 * - 200 + email 为空  → 本地单机模式（PUBLIC_MODE=0，虚拟身份 workbench）→ 无需登录；
 * - 200 + email 非空  → 公有模式且已登录；
 * - 401              → 公有模式且未登录 → 显示登录门。
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authRequired, setAuthRequired] = useState(false);
  const [githubEnabled, setGithubEnabled] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(`${apiBaseUrl()}/api/auth/me`, { credentials: "include" });
      if (res.ok) {
        const data = await res.json();
        const u = (data?.user ?? null) as AuthUser | null;
        setUser(u);
        // 本地模式虚拟身份没有 email → 不需要登录门
        setAuthRequired(Boolean(u?.email));
      } else if (res.status === 401) {
        setUser(null);
        setAuthRequired(true);
      } else {
        setUser(null);
        setAuthRequired(false);
      }
    } catch {
      // 后端没起：按本地模式放行，页面自身会展示连接错误
      setUser(null);
      setAuthRequired(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  // GitHub 按钮可见性：后端配了 Client ID/Secret 才展示（接口未启用时 enabled=false）
  useEffect(() => {
    let cancelled = false;
    fetch(`${apiBaseUrl()}/api/auth/github/status`)
      .then((r) => (r.ok ? r.json() : { enabled: false }))
      .then((d) => { if (!cancelled) setGithubEnabled(Boolean(d?.enabled)); })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    setError("");
    const res = await fetch(`${apiBaseUrl()}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}));
      throw new Error(payload?.message ?? "登录失败，请检查邮箱与密码");
    }
    await refresh();
  }, [refresh]);

  const register = useCallback(async (input: { email: string; password: string; display_name?: string }) => {
    setError("");
    const res = await fetch(`${apiBaseUrl()}/api/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(input),
    });
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}));
      throw new Error(payload?.message ?? "注册失败");
    }
    await refresh();
  }, [refresh]);

  const logout = useCallback(async () => {
    await fetch(`${apiBaseUrl()}/api/auth/logout`, { method: "POST", credentials: "include" }).catch(() => undefined);
    setUser(null);
    await refresh();
  }, [refresh]);

  const verify = useCallback(async (code: string) => {
    setError("");
    const res = await fetch(`${apiBaseUrl()}/api/auth/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ code }),
    });
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}));
      throw new Error(payload?.message ?? "验证失败，请检查验证码");
    }
    await refresh();
  }, [refresh]);

  const resendVerification = useCallback(async () => {
    setError("");
    const res = await fetch(`${apiBaseUrl()}/api/auth/resend-verification`, {
      method: "POST",
      credentials: "include",
    });
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}));
      throw new Error(payload?.message ?? "发送失败，请稍后再试");
    }
  }, []);

  const forgotPassword = useCallback(async (email: string) => {
    const res = await fetch(`${apiBaseUrl()}/api/auth/forgot-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ email }),
    });
    const payload = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(payload?.message ?? "提交失败，请稍后再试");
    return typeof payload?.message === "string"
      ? (payload.message as string)
      : "如果该邮箱已注册，我们已发送重置链接，请查收。";
  }, []);

  const resetPassword = useCallback(async (token: string, newPassword: string) => {
    const res = await fetch(`${apiBaseUrl()}/api/auth/reset-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ token, new_password: newPassword }),
    });
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}));
      throw new Error(payload?.message ?? "重置失败，链接可能已失效");
    }
  }, []);

  const validateResetToken = useCallback(async (token: string) => {
    try {
      const res = await fetch(
        `${apiBaseUrl()}/api/auth/reset-password/validate?token=${encodeURIComponent(token)}`,
        { credentials: "include" },
      );
      if (!res.ok) return false;
      const payload = await res.json().catch(() => ({}));
      return Boolean(payload?.valid);
    } catch {
      return false;
    }
  }, []);

  const value = useMemo<AuthValue>(
    () => ({
      loading, user, authRequired, githubEnabled, error,
      login, register, logout, verify, resendVerification,
      forgotPassword, resetPassword, validateResetToken,
    }),
    [loading, user, authRequired, githubEnabled, error, login, register, logout, verify, resendVerification, forgotPassword, resetPassword, validateResetToken],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used within AuthProvider");
  return value;
}

export function useOptionalAuth() { return useContext(AuthContext); }
