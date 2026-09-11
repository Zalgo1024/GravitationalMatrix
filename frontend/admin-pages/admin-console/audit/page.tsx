"use client";

import React, { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { apiRequest } from "@/lib/api";

interface AuditRow {
  id: string;
  actor_id: string | null;
  actor_email: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  detail: Record<string, unknown> | null;
  ip: string | null;
  created_at: string | null;
}

const ACTION_LABELS: Record<string, string> = {
  "auth.register": "注册",
  "auth.login_failed": "登录失败",
  "auth.login_blocked": "封禁账号尝试登录",
  "auth.change_password": "修改密码",
  "auth.forgot_password": "申请重置密码",
  "auth.reset_password": "重置密码成功",
  "user.ban": "封禁用户",
  "user.unban": "解封用户",
  "user.role_change": "角色变更",
  "user.reset_password_link": "代发重置链接",
  "project.archive": "归档项目",
  "project.unarchive": "取消归档",
  "project.delete": "删除项目",
  "task.delete": "删除任务",
};

function fmt(v: string | null | undefined) {
  if (!v) return "—";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleString("zh-CN", { hour12: false });
}

function detailText(detail: Record<string, unknown> | null): string {
  if (!detail) return "—";
  const parts: string[] = [];
  if (typeof detail.email === "string") parts.push(detail.email);
  if (typeof detail.name === "string") parts.push(detail.name);
  if (typeof detail.title === "string") parts.push(detail.title);
  if (typeof detail.from === "string" && typeof detail.to === "string") {
    parts.push(`${detail.from} → ${detail.to}`);
  }
  if (typeof detail.banned === "number") parts.push(detail.banned ? "封禁" : "解封");
  if (typeof detail.tasks_deleted === "number") parts.push(`连带任务 ${detail.tasks_deleted}`);
  if (parts.length === 0) {
    return JSON.stringify(detail);
  }
  return parts.join(" · ");
}

export default function AdminAuditPage() {
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  const [total, setTotal] = useState(0);
  const [action, setAction] = useState("");
  const [limit, setLimit] = useState(100);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const qs = new URLSearchParams();
      if (action) qs.set("action", action);
      qs.set("limit", String(limit));
      const data = await apiRequest<{ logs: AuditRow[]; total: number }>(
        `/api/admin/audit?${qs.toString()}`,
      );
      setRows(data.logs ?? []);
      setTotal(data.total ?? 0);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载审计日志失败");
      setRows([]);
    }
  }, [action, limit]);

  useEffect(() => { void load(); }, [load]);

  return (
    <div className="admin-console__page">
      <header className="admin-console__page-head">
        <div>
          <h1>审计日志</h1>
          <p>敏感操作留痕：谁 / 何时 / 对谁 / 做了什么 · 只追加，不可修改</p>
        </div>
        <div className="admin-console__toolbar">
          <select
            value={action}
            onChange={(e) => setAction(e.target.value)}
            style={{ padding: "6px 8px", borderRadius: 8, border: "1px solid var(--line)", background: "var(--surface)" }}
          >
            <option value="">全部动作</option>
            {Object.entries(ACTION_LABELS).map(([k, label]) => (
              <option key={k} value={k}>{label}</option>
            ))}
          </select>
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            style={{ padding: "6px 8px", borderRadius: 8, border: "1px solid var(--line)", background: "var(--surface)" }}
          >
            <option value={50}>近 50 条</option>
            <option value={100}>近 100 条</option>
            <option value={300}>近 300 条</option>
          </select>
          <button type="button" className="admin-ban-btn" onClick={() => void load()}>
            <RefreshCw size={13} /> 刷新
          </button>
        </div>
      </header>

      {error ? <p className="auth-card__error">{error}</p> : null}

      <p style={{ color: "var(--ink-muted)", fontSize: 12, marginTop: 0 }}>
        共 {total} 条记录
      </p>

      {rows && rows.length > 0 ? (
        <table className="admin-table">
          <thead>
            <tr>
              <th>时间</th><th>操作者</th><th>动作</th><th>对象</th><th>详情</th><th>IP</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>{fmt(row.created_at)}</td>
                <td>{row.actor_email || (row.actor_id ? row.actor_id : "—")}</td>
                <td>
                  <span className="admin-badge admin-badge--user">
                    {ACTION_LABELS[row.action] ?? row.action}
                  </span>
                </td>
                <td>
                  {row.target_type ? `${row.target_type}:${row.target_id ?? ""}` : "—"}
                </td>
                <td style={{ maxWidth: 320, wordBreak: "break-all" }}>{detailText(row.detail)}</td>
                <td>{row.ip || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p style={{ color: "var(--ink-muted)", fontSize: 13 }}>
          {rows ? "还没有审计记录。" : "加载中…"}
        </p>
      )}
    </div>
  );
}