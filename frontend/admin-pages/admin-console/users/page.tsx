"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Eye, RefreshCw, ShieldCheck, X } from "lucide-react";
import { apiRequest } from "@/lib/api";

interface AdminUserRow {
  id: string;
  email: string;
  display_name: string | null;
  role: string;
  is_banned: number;
  email_verified: boolean;
  report_count: number;
  created_at: string | null;
  last_seen_at: string | null;
}

interface AdminStats {
  total: number; admins: number; verified: number; banned: number; new_7d: number; active_7d: number;
}

interface UserDetail {
  user: AdminUserRow;
  counts: { projects: number; tasks: number; tasks_done: number; tasks_error: number; materials: number };
  recent_tasks: Array<{ id: string; title: string; status: string; analysis_type: string; mode: string; created_at: string | null }>;
}

function fmt(v: string | null | undefined) {
  if (!v) return "—";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleString("zh-CN", { hour12: false });
}

const STAT_CARDS: Array<{ key: keyof AdminStats; label: string; hint: string }> = [
  { key: "total", label: "注册用户", hint: "全部账号数" },
  { key: "new_7d", label: "近 7 日新增", hint: "一周内注册" },
  { key: "active_7d", label: "近 7 日活跃", hint: "一周内使用过" },
  { key: "verified", label: "已验证邮箱", hint: "完成邮箱验证" },
  { key: "admins", label: "管理员", hint: "拥有管理权限" },
  { key: "banned", label: "已封禁", hint: "禁止登录的账号" },
];

const STATUS_TEXT: Record<string, string> = {
  queued: "排队中", generating: "生成中", done: "已完成", error: "失败",
};

export default function AdminUsersPage() {
  const [rows, setRows] = useState<AdminUserRow[] | null>(null);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [detail, setDetail] = useState<UserDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [resetLink, setResetLink] = useState<{ email: string; url: string; minutes: number } | null>(null);

  const load = useCallback(async () => {
    setError("");
    try {
      const data = await apiRequest<{ users?: AdminUserRow[]; stats?: AdminStats }>("/api/admin/users");
      setRows(data.users ?? []);
      setStats(data.stats ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载用户列表失败");
      setRows([]);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function toggleBan(row: AdminUserRow) {
    setBusyId(row.id);
    try {
      await apiRequest(`/api/admin/users/${row.id}/ban`, {
        method: "POST",
        body: JSON.stringify({ banned: !row.is_banned }),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusyId(null);
    }
  }

  async function toggleRole(row: AdminUserRow) {
    const nextRole = row.role === "admin" ? "user" : "admin";
    const verb = nextRole === "admin" ? "提升为管理员" : "取消管理员权限";
    if (!window.confirm(`确定要将 ${row.email} ${verb} 吗？`)) return;
    setBusyId(row.id);
    setError("");
    try {
      await apiRequest(`/api/admin/users/${row.id}/role`, {
        method: "POST",
        body: JSON.stringify({ role: nextRole }),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "角色变更失败");
    } finally {
      setBusyId(null);
    }
  }

  async function issueResetLink(row: AdminUserRow) {
    if (!window.confirm(
      `确定为 ${row.email} 生成一条重置密码链接吗？\n链接 30 分钟内有效、仅可使用一次，需要你人工转达给本人。`,
    )) return;
    setBusyId(row.id);
    setError("");
    try {
      const data = await apiRequest<{ reset_url: string; expires_minutes: number }>(
        `/api/admin/users/${row.id}/reset-password`,
        { method: "POST" },
      );
      setResetLink({ email: row.email, url: data.reset_url, minutes: data.expires_minutes });
    } catch (e) {
      setError(e instanceof Error ? e.message : "生成重置链接失败");
    } finally {
      setBusyId(null);
    }
  }

  async function openDetail(id: string) {
    setDetailLoading(true);
    setError("");
    try {
      const data = await apiRequest<UserDetail>(`/api/admin/users/${id}`);
      setDetail(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载用户明细失败");
    } finally {
      setDetailLoading(false);
    }
  }

  return (
    <div className="admin-console__page">
      <header className="admin-console__page-head">
        <div>
          <h1>用户管理</h1>
          <p>注册规模、活跃度与账号治理 · 点击行首「明细」可查看单个用户的内容足迹</p>
        </div>
        <button type="button" className="admin-ban-btn" onClick={() => void load()}>
          <RefreshCw size={13} /> 刷新
        </button>
      </header>

      {error ? <p className="auth-card__error">{error}</p> : null}

      {stats ? (
        <div className="admin-stats">
          {STAT_CARDS.map((card) => (
            <div key={card.key} className="admin-stats__card">
              <strong>{stats[card.key]}</strong><span>{card.label}</span><small>{card.hint}</small>
            </div>
          ))}
        </div>
      ) : null}

      {rows && rows.length > 0 ? (
        <table className="admin-table">
          <thead>
            <tr>
              <th></th>
              <th>邮箱</th><th>角色</th><th>邮箱验证</th><th>报告数</th><th>注册时间</th><th>最近活跃</th><th>状态</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>
                  <button type="button" className="admin-ban-btn" title="查看该用户的内容足迹"
                    onClick={() => void openDetail(row.id)}>
                    <Eye size={13} />
                  </button>
                </td>
                <td>
                  {row.email}
                  <small>{row.display_name || row.id}</small>
                </td>
                <td>
                  <span className={row.role === "admin" ? "admin-badge admin-badge--admin" : "admin-badge admin-badge--user"}>
                    {row.role === "admin" ? "管理员" : "用户"}
                  </span>
                </td>
                <td>
                  <span className={row.email_verified ? "admin-badge admin-badge--user" : "admin-badge admin-badge--banned"}>
                    {row.email_verified ? "已验证" : "未验证"}
                  </span>
                </td>
                <td>{row.report_count}</td>
                <td>{fmt(row.created_at)}</td>
                <td>{fmt(row.last_seen_at)}</td>
                <td>
                  {row.is_banned
                    ? <span className="admin-badge admin-badge--banned">已封禁</span>
                    : <span className="admin-badge admin-badge--user">正常</span>}
                </td>
                <td>
                  <div className="admin-console__toolbar" style={{ gap: 6 }}>
                    <button
                      type="button"
                      className="admin-ban-btn"
                      disabled={busyId === row.id}
                      title={row.role === "admin" ? "取消该账号的管理员权限" : "提升该账号为管理员"}
                      onClick={() => void toggleRole(row)}
                    >
                      {row.role === "admin" ? "取消管理员" : "设为管理员"}
                    </button>
                    <button
                      type="button"
                      className="admin-ban-btn"
                      disabled={busyId === row.id}
                      title="生成一次性重置密码链接（需人工转达给本人）"
                      onClick={() => void issueResetLink(row)}
                    >
                      重置密码
                    </button>
                    <button
                      type="button"
                      className={row.is_banned ? "admin-ban-btn" : "admin-ban-btn admin-ban-btn--danger"}
                      disabled={busyId === row.id || row.role === "admin"}
                      title={row.role === "admin" ? "不能封禁管理员" : undefined}
                      onClick={() => void toggleBan(row)}
                    >
                      {row.is_banned ? "解封" : "封禁"}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p style={{ color: "var(--ink-muted)", fontSize: 13 }}>{rows ? "还没有注册用户。" : "加载中…"}</p>
      )}

      {/* 管理员代发重置链接弹窗 */}
      {resetLink && (
        <div className="admin-console__overlay" onClick={() => setResetLink(null)}>
          <div
            className="admin-console__drawer"
            style={{ height: "auto", maxHeight: "80vh" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="admin-console__drawer-head">
              <h2><ShieldCheck size={16} /> 重置链接已生成</h2>
              <button type="button" className="admin-ban-btn" onClick={() => setResetLink(null)}><X size={14} /></button>
            </div>
            <p className="admin-console__drawer-sub">
              发给 <strong>{resetLink.email}</strong>：{resetLink.minutes} 分钟内有效、仅可使用一次。
              链接内含一次性令牌，请通过可信渠道转达，不要公开张贴。
            </p>
            <textarea
              readOnly
              value={resetLink.url}
              rows={4}
              style={{ width: "100%", fontSize: 12, borderRadius: 8, border: "1px solid var(--line)", padding: 8, boxSizing: "border-box" }}
            />
            <div className="admin-console__toolbar" style={{ marginTop: 10 }}>
              <button
                type="button"
                className="admin-ban-btn"
                onClick={() => { void navigator.clipboard?.writeText(resetLink.url); }}
              >
                复制链接
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 用户明细抽屉 */}
      {detail && (
        <div className="admin-console__overlay" onClick={() => setDetail(null)}>
          <div className="admin-console__drawer" onClick={(e) => e.stopPropagation()}>
            <div className="admin-console__drawer-head">
              <h2><ShieldCheck size={16} /> {detail.user.display_name || detail.user.email}</h2>
              <button type="button" className="admin-ban-btn" onClick={() => setDetail(null)}><X size={14} /></button>
            </div>
            <p className="admin-console__drawer-sub">{detail.user.email} · {detail.user.role === "admin" ? "管理员" : "用户"} · {detail.user.is_banned ? "已封禁" : "正常"}</p>

            <div className="admin-stats" style={{ gridTemplateColumns: "repeat(3, 1fr)", marginBottom: 12 }}>
              {[
                { k: detail.counts.projects, l: "项目" },
                { k: detail.counts.tasks, l: "任务" },
                { k: detail.counts.tasks_done, l: "完成" },
                { k: detail.counts.tasks_error, l: "失败" },
                { k: detail.counts.materials, l: "素材" },
              ].map((c) => (
                <div key={c.l} className="admin-stats__card"><strong>{c.k}</strong><span>{c.l}</span></div>
              ))}
            </div>

            <h3 className="admin-console__drawer-sub" style={{ margin: "8px 0 4px", fontWeight: 800 }}>最近任务</h3>
            {detailLoading ? (
              <p style={{ color: "var(--ink-muted)", fontSize: 13 }}>加载明细…</p>
            ) : detail.recent_tasks.length ? (
              <ul className="admin-console__recent">
                {detail.recent_tasks.map((t) => (
                  <li key={t.id}>
                    <span className="admin-console__recent-title">{t.title}</span>
                    <span className="admin-badge admin-badge--user">{STATUS_TEXT[t.status] ?? t.status}</span>
                    <small>{fmt(t.created_at)}</small>
                  </li>
                ))}
              </ul>
            ) : (
              <p style={{ color: "var(--ink-muted)", fontSize: 13 }}>该用户还没有任务。</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}