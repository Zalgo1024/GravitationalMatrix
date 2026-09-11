"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Activity, AlertTriangle, Database, RefreshCw, Users } from "lucide-react";
import { apiRequest } from "@/lib/api";

interface TrendBucket {
  date: string;
  registered: number;
  active: number;
  reports: number;
}

interface OverviewData {
  users: { total: number; admins: number; banned: number; verified: number; new_7d: number; active_7d: number };
  content: {
    projects: number; active_projects: number; tasks: number;
    reports_done: number; reports_error: number; report_versions: number; materials: number;
  };
  quality: { task_success_rate: number; task_error_count: number; queued_or_generating: number };
  trend_14d: TrendBucket[];
}

interface SystemData {
  status: string; health: string; public_mode: boolean; smtp_enabled: boolean;
  queue: { queued_or_generating: number; error: number; total: number };
  storage: { sqlite_mb: number; sqlite_path: string };
}

function fmtNum(n: number | undefined | null) {
  return (n ?? 0).toLocaleString("zh-CN");
}

/** 轻量内联 SVG 折线（不引入重型图表库，自用内测够用）。 */
function MiniLineChart({ buckets, dataKey, color }: { buckets: TrendBucket[]; dataKey: "registered" | "active" | "reports"; color: string }) {
  const W = 640, H = 150, PAD = 18;
  const values = buckets.map((b) => b[dataKey]);
  const max = Math.max(1, ...values);
  const pts = buckets.map((b, i) => {
    const x = PAD + (i * (W - PAD * 2)) / Math.max(1, buckets.length - 1);
    const y = H - PAD - ((b[dataKey] / max) * (H - PAD * 2));
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const last = buckets[buckets.length - 1];
  const lastVal = last?.[dataKey] ?? 0;
  const lastX = PAD + ((buckets.length - 1) * (W - PAD * 2)) / Math.max(1, buckets.length - 1);
  const lastY = H - PAD - (lastVal / max) * (H - PAD * 2);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="admin-console__chart" role="img" aria-label="14 日趋势">
      {[0.25, 0.5, 0.75].map((f) => (
        <line key={f} x1={PAD} x2={W - PAD} y1={H - PAD - f * (H - PAD * 2)} y2={H - PAD - f * (H - PAD * 2)} stroke="var(--line)" strokeWidth={1} strokeDasharray="3 4" />
      ))}
      <polyline points={pts.join(" ")} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      {buckets.map((b, i) => (
        <circle key={b.date} cx={PAD + (i * (W - PAD * 2)) / Math.max(1, buckets.length - 1)} cy={H - PAD - ((b[dataKey] / max) * (H - PAD * 2))} r={2.2} fill={color} />
      ))}
      <circle cx={lastX} cy={lastY} r={4} fill={color} stroke="var(--surface)" strokeWidth={2} />
    </svg>
  );
}

function TrendCard({ title, buckets, dataKey, color, latestLabel }: {
  title: string; buckets: TrendBucket[]; dataKey: "registered" | "active" | "reports"; color: string; latestLabel: string;
}) {
  const latest = buckets[buckets.length - 1];
  const total = buckets.reduce((s, b) => s + b[dataKey], 0);
  return (
    <div className="admin-console__panel">
      <div className="admin-console__panel-head">
        <strong>{title}</strong>
        <span>近 14 日合计 {fmtNum(total)} · 今日 {fmtNum(latest?.[dataKey])} {latestLabel}</span>
      </div>
      <MiniLineChart buckets={buckets} dataKey={dataKey} color={color} />
    </div>
  );
}

export default function AdminOverviewPage() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [sys, setSys] = useState<SystemData | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [ov, sy] = await Promise.all([
        apiRequest<OverviewData>("/api/admin/stats/overview"),
        apiRequest<SystemData>("/api/admin/system"),
      ]);
      setData(ov);
      setSys(sy);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载运营数据失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const u = data?.users;
  const c = data?.content;
  const q = data?.quality;
  const trend = data?.trend_14d ?? [];

  return (
    <div className="admin-console__page">
      <header className="admin-console__page-head">
        <div>
          <h1>运营总览</h1>
          <p>注册规模、内容产出、质量与系统状态 · 面向自用/内测与对外公测</p>
        </div>
        <button type="button" className="admin-ban-btn" onClick={() => void load()}>
          <RefreshCw size={13} /> 刷新
        </button>
      </header>

      {error ? <p className="auth-card__error">{error}</p> : null}

      {/* 用户规模卡 */}
      <div className="admin-console__section-title"><Users size={15} /> 用户</div>
      <div className="admin-stats" style={{ marginTop: 6 }}>
        {[
          { k: fmtNum(u?.total), l: "注册用户", h: "全部账号" },
          { k: fmtNum(u?.new_7d), l: "近 7 日新增", h: "一周内注册" },
          { k: fmtNum(u?.active_7d), l: "近 7 日活跃", h: "一周内使用" },
          { k: fmtNum(u?.verified), l: "已验证邮箱", h: "完成验证" },
          { k: fmtNum(u?.admins), l: "管理员", h: "运营角色" },
          { k: fmtNum(u?.banned), l: "已封禁", h: "禁止登录" },
        ].map((card) => (
          <div key={card.l} className="admin-stats__card">
            <strong>{card.k}</strong><span>{card.l}</span><small>{card.h}</small>
          </div>
        ))}
      </div>

      {/* 内容产出卡 */}
      <div className="admin-console__section-title"><Database size={15} /> 内容产出</div>
      <div className="admin-stats" style={{ marginTop: 6 }}>
        {[
          { k: fmtNum(c?.projects), l: "项目", h: `${fmtNum(c?.active_projects)} 活跃` },
          { k: fmtNum(c?.reports_done), l: "完成报告", h: `${fmtNum(c?.tasks)} 任务` },
          { k: fmtNum(c?.report_versions), l: "报告版本", h: "含修订" },
          { k: fmtNum(c?.materials), l: "素材", h: "输入材料" },
          { k: `${q?.task_success_rate ?? 0}%`, l: "任务成功率", h: `${fmtNum(c?.reports_error)} 失败` },
          { k: fmtNum(q?.queued_or_generating), l: "队列中", h: "排队/生成中" },
        ].map((card) => (
          <div key={card.l} className="admin-stats__card">
            <strong>{card.k}</strong><span>{card.l}</span><small>{card.h}</small>
          </div>
        ))}
      </div>

      {/* 趋势图 */}
      <div className="admin-console__section-title"><Activity size={15} /> 14 日趋势</div>
      {trend.length ? (
        <div className="admin-console__trend-grid">
          <TrendCard title="注册" buckets={trend} dataKey="registered" color="oklch(0.48 0.13 245)" latestLabel="人" />
          <TrendCard title="活跃" buckets={trend} dataKey="active" color="oklch(0.64 0.14 160)" latestLabel="人" />
          <TrendCard title="完成报告" buckets={trend} dataKey="reports" color="oklch(0.62 0.18 25)" latestLabel="篇" />
        </div>
      ) : (
        <p style={{ color: "var(--ink-muted)", fontSize: 13 }}>{loading ? "加载趋势…" : "暂无趋势数据。"}</p>
      )}

      {/* 系统状态 */}
      <div className="admin-console__section-title"><Activity size={15} /> 系统状态</div>
      <div className="admin-console__sys">
        <div className="admin-console__sys-row">
          <span><i className={sys?.health === "up" ? "dot dot--ok" : "dot dot--bad"} /> 后端健康</span>
          <b>{sys?.health === "up" ? "正常" : "异常"}</b>
        </div>
        <div className="admin-console__sys-row"><span>运行模式</span><b>{sys?.public_mode ? "公网（多用户）" : "本地单机"}</b></div>
        <div className="admin-console__sys-row"><span>邮箱验证(SMTP)</span><b>{sys?.smtp_enabled ? "已启用" : "未启用（注册即验证）"}</b></div>
        <div className="admin-console__sys-row"><span>队列积压</span><b>{fmtNum(sys?.queue.queued_or_generating)} 条</b></div>
        <div className="admin-console__sys-row"><span>失败任务</span><b>{fmtNum(sys?.queue.error)} 条</b></div>
        <div className="admin-console__sys-row"><span>数据库</span><b>{sys?.storage.sqlite_mb ?? 0} MB</b></div>
      </div>
      {!data && !error && loading ? (
        <p style={{ color: "var(--ink-muted)", fontSize: 13 }}>加载中…</p>
      ) : !data && error ? (
        <p className="admin-console__err"><AlertTriangle size={15} /> {error}（请确认后端已启动，且以管理员身份登录）</p>
      ) : null}
    </div>
  );
}