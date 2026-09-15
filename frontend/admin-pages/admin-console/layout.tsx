"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ArrowLeft,
  Database,
  LayoutDashboard,
  ScrollText,
  ShieldCheck,
  Users,
} from "lucide-react";
import React from "react";
import { AuthCard } from "@/components/auth-gate";
import { useOptionalAuth } from "@/lib/auth";

/**
 * 独立管理员运营后台布局。
 *
 * 与工作台 (app) 完全解耦：不走 AppShell，独立 AdminShell 侧栏；
 * 不挂 AuthGate（那是给工作台用的"整站登录门"），后台自行做身份守卫。
 *
 * 守卫逻辑（AdminAuthGuard）：
 * - loading            → 占位；
 * - 未登录 + 需登录     → 直接渲染后台自己的登录卡（不必先去工作台登录）；
 * - user?.role !== admin → 整页"需要管理员权限"，且内容完全不下发（后端 403 兜底）。
 *   注意：不要求 authRequired，这样 PUBLIC_MODE=0 的虚拟 admin(role=admin) 也能进纯本地后台。
 */
function AdminAuthGuard({ children }: { children: React.ReactNode }) {
  const auth = useOptionalAuth();
  const user = auth?.user ?? null;
  const loading = auth?.loading ?? false;
  const authRequired = auth?.authRequired ?? false;

  if (loading) {
    return <div className="admin-console" style={{ padding: 40 }}>正在校验管理员身份…</div>;
  }

  // 公有模式且尚未登录：给后台独立的登录入口。
  // 这样「启动后台 → 登录 → 看数据」一条链路自成闭环，无需绕道 3000 工作台。
  if (!user && authRequired) {
    return (
      <AuthCard
        title="运营后台"
        hint="仅限管理员账号登录。普通用户账号即使登录，也无法进入此控制台。"
      />
    );
  }

  if (!user || user.role !== "admin") {
    return (
      <div className="admin-console__denied">
        <ShieldCheck size={34} />
        <h1>需要管理员权限</h1>
        <p>此页面为系统管理员运营后台，不对普通用户开放。</p>
        <p className="admin-console__denied-sub">
          已登录但非管理员时同样无权访问；如需查看工作空间，请{" "}
          <Link href="/dashboard">返回工作台</Link>。
        </p>
      </div>
    );
  }

  return <>{children}</>;
}

const adminNav = [
  { href: "/admin-console/overview", label: "运营总览", icon: LayoutDashboard },
  { href: "/admin-console/users", label: "用户管理", icon: Users },
  { href: "/admin-console/content", label: "内容治理", icon: Database },
  { href: "/admin-console/audit", label: "审计日志", icon: ScrollText },
];

function isActive(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

const WORKBENCH_PORT = 3000;

/**
 * 「返回工作台」的目标地址。
 * 独立后台通常跑在 3001，此时应回到工作台端口（3000），
 * 而不是把整个工作台塞进后台端口里打开；同端口访问时保持相对路径即可。
 */
function useWorkbenchHref(): string {
  const [href, setHref] = React.useState("/dashboard");
  React.useEffect(() => {
    if (typeof window === "undefined") return;
    const { protocol, hostname, port } = window.location;
    if (port && port !== String(WORKBENCH_PORT)) {
      setHref(`${protocol}//${hostname}:${WORKBENCH_PORT}/dashboard`);
    }
  }, []);
  return href;
}

function AdminShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const auth = useOptionalAuth();
  const user = auth?.user ?? null;
  const workbenchHref = useWorkbenchHref();

  return (
    <main className="admin-console">
      <aside className="admin-console__sidebar">
        <div className="admin-console__brand">
          <ShieldCheck size={18} />
          <div>
            <strong>运营后台</strong>
            <small>引力矩阵运营后台</small>
          </div>
        </div>
        <nav className="admin-console__nav" aria-label="运营后台导航">
          {adminNav.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className={isActive(pathname, href) ? "admin-console__nav-item admin-console__nav-item--active" : "admin-console__nav-item"}
            >
              <Icon size={16} /><span>{label}</span>
            </Link>
          ))}
        </nav>
        <div className="admin-console__sidebar-footer">
          <span className="admin-console__who">
            {user?.email ?? user?.display_name ?? "管理员"}
          </span>
          <Link className="admin-console__back" href={workbenchHref}>
            <ArrowLeft size={13} /> 返回工作台
          </Link>
        </div>
      </aside>
      <section className="admin-console__stage">
        <div className="admin-console__page">{children}</div>
      </section>
    </main>
  );
}

export default function AdminConsoleLayout({ children }: { children: React.ReactNode }) {
  return (
    <AdminAuthGuard>
      <AdminShell>{children}</AdminShell>
    </AdminAuthGuard>
  );
}