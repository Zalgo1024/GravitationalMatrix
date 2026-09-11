"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Archive, ArchiveRestore, RefreshCw, Trash2 } from "lucide-react";
import { apiRequest } from "@/lib/api";

interface ProjectRow {
  id: string; name: string; description: string | null; status: string;
  owner_id: string | null; owner_email: string | null; owner_display: string | null;
  is_archived: number; archived_at: string | null; task_count: number; updated_at: string | null;
}

interface TaskRow {
  id: string; title: string; status: string; phase: string | null; progress_pct: number;
  analysis_type: string; mode: string; owner_id: string | null; owner_email: string | null;
  project_id: string | null; version_count: number; has_error: boolean; created_at: string | null; updated_at: string | null;
}

const TASK_STATUS: Record<string, string> = {
  queued: "排队", generating: "生成中", done: "完成", error: "失败",
};

function fmt(v: string | null | undefined) {
  if (!v) return "—";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleString("zh-CN", { hour12: false });
}

function ownerLabel(email: string | null, display: string | null) {
  if (email) return email;
  if (display) return display;
  return "系统";
}

/** confirm 二次确认：window.confirm 列出连带影响。 */
function confirmDanger(msg: string): boolean {
  // eslint-disable-next-line no-alert
  return window.confirm(`${msg}\n\n此操作不可撤销（物理删除，非归档）。确定继续？`);
}

export default function AdminContentPage() {
  const [tab, setTab] = useState<"projects" | "tasks">("projects");
  const [projects, setProjects] = useState<ProjectRow[] | null>(null);
  const [tasks, setTasks] = useState<TaskRow[] | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError("");
    try {
      const [pr, ta] = await Promise.all([
        apiRequest<{ projects?: ProjectRow[] }>(`/api/admin/projects?include_archived=${includeArchived}`),
        apiRequest<{ tasks?: TaskRow[] }>("/api/admin/tasks"),
      ]);
      setProjects(pr.projects ?? []);
      setTasks(ta.tasks ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载内容失败");
    }
  }, [includeArchived]);

  useEffect(() => { void load(); }, [load]);

  async function archiveProject(p: ProjectRow) {
    setBusy(p.id);
    try {
      await apiRequest(`/api/admin/projects/${p.id}/archive`, {
        method: "POST",
        body: JSON.stringify({ archived: !p.is_archived }),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusy(null);
    }
  }

  async function deleteProject(p: ProjectRow) {
    if (!confirmDanger(`删除项目「${p.name}」？\n将连带删除 ${p.task_count} 个任务及其全部报告版本与产物文件。`)) return;
    setBusy(p.id);
    try {
      const r = await apiRequest<{ tasks_deleted: number }>(`/api/admin/projects/${p.id}/delete`, {
        method: "POST",
        body: JSON.stringify({ confirm: true }),
      });
      setError(`已删除项目：连带 ${r.tasks_deleted} 个任务。`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    } finally {
      setBusy(null);
    }
  }

  async function deleteTask(t: TaskRow) {
    if (!confirmDanger(`删除报告「${t.title}」？\n将删除 ${t.version_count} 个报告版本及其产物文件。`)) return;
    setBusy(t.id);
    try {
      const r = await apiRequest<{ report_versions_deleted: number }>(`/api/admin/tasks/${t.id}/delete`, {
        method: "POST",
        body: JSON.stringify({ confirm: true }),
      });
      setError(`已删除报告：连带 ${r.report_versions_deleted} 个版本。`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="admin-console__page">
      <header className="admin-console__page-head">
        <div>
          <h1>内容治理</h1>
          <p>跨用户查看项目与报告，归档或删除违规 / 冗余内容</p>
        </div>
        <div className="admin-console__toolbar">
          {tab === "projects" && (
            <label className="admin-console__check">
              <input type="checkbox" checked={includeArchived} onChange={(e) => setIncludeArchived(e.target.checked)} />
              含已归档
            </label>
          )}
          <button type="button" className="admin-ban-btn" onClick={() => void load()}><RefreshCw size={13} /> 刷新</button>
        </div>
      </header>

      {error ? <p className="auth-card__error">{error}</p> : null}

      <div className="admin-console__tabs">
        <button type="button" className={tab === "projects" ? "tabs-btn tabs-btn--active" : "tabs-btn"} onClick={() => setTab("projects")}>
          项目（{projects?.length ?? "…"}）
        </button>
        <button type="button" className={tab === "tasks" ? "tabs-btn tabs-btn--active" : "tabs-btn"} onClick={() => setTab("tasks")}>
          报告任务（{tasks?.length ?? "…"}）
        </button>
      </div>

      {tab === "projects" ? (
        projects && projects.length ? (
          <table className="admin-table">
            <thead>
              <tr>
                <th>项目</th><th>归属</th><th>状态</th><th>任务</th><th>更新</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id}>
                  <td>{p.name}<small>{p.id}</small></td>
                  <td>{ownerLabel(p.owner_email, p.owner_display)}</td>
                  <td>
                    {p.is_archived
                      ? <span className="admin-badge admin-badge--banned">已归档</span>
                      : <span className="admin-badge admin-badge--user">{p.status || "active"}</span>}
                  </td>
                  <td>{p.task_count}</td>
                  <td>{fmt(p.updated_at)}</td>
                  <td>
                    <button type="button" className="admin-ban-btn" disabled={busy === p.id}
                      onClick={() => void archiveProject(p)} title={p.is_archived ? "恢复项目" : "归档项目（软删，可恢复）"}>
                      {p.is_archived ? <ArchiveRestore size={13} /> : <Archive size={13} />}
                    </button>
                    <button type="button" className="admin-ban-btn admin-ban-btn--danger" disabled={busy === p.id}
                      onClick={() => void deleteProject(p)} title="硬删除（连带任务与版本）">
                      <Trash2 size={13} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p style={{ color: "var(--ink-muted)", fontSize: 13 }}>{projects ? "暂无项目。" : "加载中…"}</p>
        )
      ) : tasks && tasks.length ? (
        <table className="admin-table">
          <thead>
            <tr>
              <th>报告</th><th>归属</th><th>状态</th><th>版本</th><th>类型</th><th>创建</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((t) => (
              <tr key={t.id}>
                <td>{t.title}<small>{t.id}</small></td>
                <td>{ownerLabel(t.owner_email, null)}</td>
                <td>
                  {t.has_error
                    ? <span className="admin-badge admin-badge--banned">{TASK_STATUS[t.status] ?? t.status}</span>
                    : <span className="admin-badge admin-badge--user">{TASK_STATUS[t.status] ?? t.status}</span>}
                </td>
                <td>{t.version_count}</td>
                <td>{t.analysis_type}</td>
                <td>{fmt(t.created_at)}</td>
                <td>
                  <button type="button" className="admin-ban-btn admin-ban-btn--danger" disabled={busy === t.id}
                    onClick={() => void deleteTask(t)} title="删除报告（连带版本）">
                    <Trash2 size={13} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p style={{ color: "var(--ink-muted)", fontSize: 13 }}>{tasks ? "暂无任务。" : "加载中…"}</p>
      )}
    </div>
  );
}