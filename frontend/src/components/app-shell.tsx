"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ChevronDown,
  LayoutGrid,
  LogOut,
  Plus,
  RefreshCw,
  Settings,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  Workflow,
} from "lucide-react";
import React, { useState } from "react";
import { useOptionalAuth } from "@/lib/auth";
import { useAppStore } from "@/lib/store";
import { NavigationBackButton } from "./navigation-back-button";

const navigation = [
  { href: "/dashboard", label: "工作台", icon: LayoutGrid },
  { href: "/analysis", label: "新建分析", icon: Plus },
  { href: "/settings", label: "设置", icon: Settings },
];

function isActive(pathname: string, href: string) {
  return href === "/dashboard" ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { state, connection, connectionError, refreshWorkspace } = useAppStore();
  // useOptionalAuth：测试环境可能没有 AuthProvider，此时按本地模式处理
  const auth = useOptionalAuth();
  const authUser = auth?.user ?? null;
  const authRequired = auth?.authRequired ?? false;
  const [profileOpen, setProfileOpen] = useState(false);
  // A6：工作台/公开构建里根本不含后台页面（见 next.config.ts 的 pageExtensions 门控），
  // 所以入口也必须按构建期开关隐藏，否则会留下一个 404 的死链。
  // NEXT_PUBLIC_* 在构建时被内联，只有运营后台构建才会设成 "1"。
  const adminUiBuilt = process.env.NEXT_PUBLIC_ADMIN_UI === "1";
  const isAdmin = adminUiBuilt && authRequired && authUser?.role === "admin";
  const engineLabel = state.settings.defaultEngine === "auto"
    ? "自动路由已就绪"
    : state.settings.defaultEngine === "llm"
      ? "语言增强已就绪"
      : "规则引擎已就绪";

  return (
    <main className="app-shell">
      <aside className="app-sidebar">
        <Link className="app-brand" href="/" aria-label="返回产品首页" title="返回产品首页">
          <span>三</span>
          <div><strong>Triad</strong><small>Structure Analysis</small></div>
        </Link>
        <nav className="app-navigation" aria-label="主导航">
          {navigation.map(({ href, label, icon: Icon }) => (
            <Link
              className={isActive(pathname, href) ? "app-navigation__item app-navigation__item--active" : "app-navigation__item"}
              href={href}
              key={href}
            >
              <Icon size={18} /><span>{label}</span>
            </Link>
          ))}
        </nav>
        <div className="app-sidebar__footer">
          <div className="app-engine-status"><Sparkles size={15} /><span>{engineLabel}</span></div>
          <div className="app-profile-wrap">
            <button
              className="app-profile"
              type="button"
              aria-label="打开账户菜单"
              aria-expanded={profileOpen}
              onClick={() => setProfileOpen((current) => !current)}
            >
              <span>{authRequired && authUser ? (authUser.display_name || authUser.email || "用")[0] : "林"}</span>
              <div>
                <strong>{authRequired && authUser ? (authUser.display_name || authUser.email) : "林知远"}</strong>
                <small>{authRequired ? (authUser?.role === "admin" ? "管理员" : "分析研究员") : "本地研究者"}</small>
              </div>
              <ChevronDown size={15} />
            </button>
            {profileOpen && (
              <div className="app-profile-menu">
                {authRequired && authUser ? (
                  <span>{authUser.email ?? authUser.id}</span>
                ) : (
                  <span>本地研究工作空间</span>
                )}
                {isAdmin && (
                  <Link href="/admin-console" onClick={() => setProfileOpen(false)}>
                    <ShieldCheck size={14} /> 运营后台
                  </Link>
                )}
                <Link href="/settings" onClick={() => setProfileOpen(false)}>工作空间设置</Link>
                <Link href="/" onClick={() => setProfileOpen(false)}>返回产品首页</Link>
                {authRequired && (
                  <button
                    type="button"
                    className="app-profile-menu__logout"
                    onClick={() => { setProfileOpen(false); void auth?.logout(); }}
                  >
                    <LogOut size={14} /> 退出登录
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </aside>
      <section className="app-stage">
        <header className="app-topbar">
          <div className="app-topbar__context">
            <NavigationBackButton />
            <span className="app-topbar__divider" aria-hidden="true" />
            <Workflow size={17} />
            <span className="app-topbar__label">引力力矩 · 分析空间</span>
          </div>
          <div className="app-topbar__right">
            <span className="app-topbar__mode">{connection === "demo" ? "演示数据" : connection === "checking" ? "正在连接后端" : "本地工作空间"}</span>
            <Link className="topbar-create" href="/analysis"><Plus size={16} />新建分析</Link>
          </div>
        </header>
        {connection === "offline" && (
          <div className="backend-status backend-status--offline" role="alert">
            <TriangleAlert size={17} />
            <div><strong>本地后端未连接</strong><span>{connectionError || "无法读取真实项目和报告，请确认后端已经启动。"}</span></div>
            <button type="button" onClick={() => void refreshWorkspace()}><RefreshCw size={14} />重新连接</button>
          </div>
        )}
        {connection === "demo" && (
          <div className="backend-status backend-status--demo" role="status">
            <TriangleAlert size={17} />
            <div><strong>当前为演示数据</strong><span>这些项目和报告不来自本地后端。</span></div>
          </div>
        )}
        <div className="app-page">{children}</div>
      </section>
    </main>
  );
}
