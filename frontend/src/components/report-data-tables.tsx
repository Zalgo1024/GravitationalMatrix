"use client";

// F15：结构化数据表 —— 报告阅读页「数据」视图。
// 三张表（来源证据 / 主体清单 / 关系清单）由后端从版本绑定的研究账本纯派生，
// 支持列排序、关键词过滤与 CSV 导出（Excel 直开，utf-8-sig）。

import { ArrowDownUp, Download, LoaderCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { apiBaseUrl, apiRequest } from "@/lib/api";

interface TablePayload {
  table_id: string;
  table_name: string;
  columns: string[];
  rows: (string | number)[][];
  row_count: number;
  research_status: string;
  applicable?: boolean;
}

// F15 六表：基础三表全类型适用；时间线=事件/舆情/组合、叙事份额=舆情/组合、
// 政策条款=政策/组合（后端 applicable 判定，不适用的表显示占位说明）。
export const DATA_TABLES: { id: string; label: string }[] = [
  { id: "sources", label: "来源证据" },
  { id: "subjects", label: "主体清单" },
  { id: "relations", label: "关系清单" },
  { id: "timeline", label: "事件时间线" },
  { id: "narratives", label: "叙事份额" },
  { id: "policy_clauses", label: "政策条款" },
];

// 研究状态中文化（extraction_failed 等原始英文状态不直接示人）
const STATUS_LABELS: Record<string, string> = {
  verified: "已验证",
  fallback: "降级账本",
  no_evidence: "无公开证据",
  extraction_failed: "抽取失败",
  unavailable: "无研究数据",
};

function cellText(value: string | number) {
  return value === null || value === undefined ? "" : String(value);
}

export function ReportDataTables({ taskId, versionId, tableId, onTableIdChange }: { taskId: string; versionId?: string | null; tableId?: string; onTableIdChange?: (id: string) => void }) {
  const [localTableId, setLocalTableId] = useState("sources");
  const activeTableId = tableId ?? localTableId;
  function switchTable(id: string) {
    if (onTableIdChange) onTableIdChange(id);
    else setLocalTableId(id);
  }
  const [payload, setPayload] = useState<TablePayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState<{ col: number; asc: boolean } | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(""); setFilter(""); setSort(null);
    const versionQuery = versionId ? `?version_id=${encodeURIComponent(versionId)}` : "";
    apiRequest<TablePayload>(`/api/reports/${encodeURIComponent(taskId)}/tables/${activeTableId}${versionQuery}`)
      .then((body) => { if (!cancelled) setPayload(body); })
      .catch((reason) => { if (!cancelled) setError(reason instanceof Error ? reason.message : "数据表读取失败。"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [taskId, activeTableId, versionId]);

  const rows = useMemo(() => {
    const raw = payload?.rows ?? [];
    const filtered = filter.trim()
      ? raw.filter((row) => row.some((cell) => cellText(cell).toLowerCase().includes(filter.trim().toLowerCase())))
      : raw;
    if (!sort) return filtered;
    return [...filtered].sort((left, right) => {
      const a = cellText(left[sort.col]);
      const b = cellText(right[sort.col]);
      const na = Number(a), nb = Number(b);
      const cmp = !Number.isNaN(na) && !Number.isNaN(nb) && a !== "" && b !== "" ? na - nb : a.localeCompare(b, "zh-CN");
      return sort.asc ? cmp : -cmp;
    });
  }, [payload, filter, sort]);

  function toggleSort(col: number) {
    setSort((current) => current?.col === col ? (current.asc ? null : { col, asc: true }) : { col, asc: false });
  }
  function csvUrl() {
    const versionQuery = versionId ? `&version_id=${encodeURIComponent(versionId)}` : "";
    return `${apiBaseUrl()}/api/reports/${encodeURIComponent(taskId)}/tables/${activeTableId}?format=csv${versionQuery}`;
  }

  const statusLabel = payload ? (STATUS_LABELS[payload.research_status] ?? payload.research_status) : "";
  const researchIncomplete = payload?.research_status === "extraction_failed" || payload?.research_status === "fallback";

  return <section className="report-data-tables" id="data-tables" aria-label="结构化数据表">
    <header className="report-data-tables__bar">
      <div className="report-data-tables__tabs" role="tablist" aria-label="数据表切换">
        {DATA_TABLES.map((table) => <button key={table.id} type="button" role="tab" aria-selected={activeTableId === table.id} className={activeTableId === table.id ? "data-tab data-tab--active" : "data-tab"} onClick={() => switchTable(table.id)}>{table.label}</button>)}
      </div>
      <div className="report-data-tables__tools">
        <input aria-label="过滤数据表" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="过滤行…" />
        <a className="secondary-button" href={csvUrl()} download aria-label="导出当前数据表为 CSV"><Download size={15} />CSV</a>
      </div>
    </header>
    {loading && <div className="report-version-loading" aria-busy="true"><LoaderCircle size={16} className="spin" /> 正在读取数据表...</div>}
    {error && <p className="delivery-error" role="alert">{error}</p>}
    {!loading && !error && payload && payload.applicable === false
      ? <p className="section-empty">{payload.table_name}仅适用于对应的报告类型（事件时间线→事件/舆情/组合，叙事份额→舆情/组合，政策条款→政策/组合）；当前报告类型不适用。</p>
      : null}
    {!loading && !error && payload && payload.applicable !== false && (payload.row_count === 0
      ? <p className="section-empty">该版本还没有可展示的{payload.table_name}数据（研究账本不可用或为空）。可先「补充信息与证据」重建研究账本。</p>
      : <div className="data-table data-table--scroll" role="table" aria-label={payload.table_name}>
          <div className="data-table__head data-table__head--sortable">
            {payload.columns.map((column, index) => <button key={column} type="button" onClick={() => toggleSort(index)} aria-label={`按${column}排序`}>{column}{sort?.col === index && <ArrowDownUp size={12} />}</button>)}
          </div>
          {rows.map((row, rowIndex) => <div className="data-table__row" key={rowIndex} role="row">
            {row.map((cell, cellIndex) => {
              const text = cellText(cell);
              const isUrl = /^https?:\/\//.test(text);
              return <span key={cellIndex} title={text} role="cell">{isUrl ? <a href={text} target="_blank" rel="noreferrer" className="text-action">{text.length > 48 ? `${text.slice(0, 48)}…` : text}</a> : text}</span>;
            })}
          </div>)}
        </div>)}
    {!loading && !error && payload && payload.applicable !== false && researchIncomplete && <p className="section-empty">该版本的研究账本抽取失败，以下数据来自采集来源的降级快照，可能不完整；可「补充信息与证据」重新抽取。</p>}
    {!loading && !error && payload && payload.applicable !== false && payload.row_count > 0 && <p className="muted-count">共 {payload.row_count} 行{filter ? `（过滤后 ${rows.length} 行）` : ""} · 研究状态 {statusLabel}</p>}
  </section>;
}
