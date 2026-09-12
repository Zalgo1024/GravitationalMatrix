"use client";

// F1：多平台采集弹窗 —— 在材料库输入关键词，跑 L1 渠道（检索/政策/订阅/热榜），
// 预览去重后的候选来源，勾选后一键入库为材料（source_type="collect"）。
// 合规边界：仅采集公开可检索内容；入库后与手工材料同库管理、来源可溯源。

import { Download, LoaderCircle, Radar, X } from "lucide-react";
import { useState } from "react";
import { apiRequest } from "@/lib/api";

interface CollectItemRow {
  kind: string;
  platform: string;
  title: string;
  url: string;
  snippet: string;
  published_at: string | null;
  region_name: string | null;
  engagement: number | null;
  duplicate: boolean;
}

interface CollectPreviewResponse {
  query: string;
  kinds: string[];
  items: CollectItemRow[];
  independent_sources: number;
  degraded: string[] | null;
  error?: string;
  message?: string;
}

interface CollectSaveResponse {
  saved_count: number;
  skipped_count: number;
  error?: string;
  message?: string;
}

const KIND_OPTIONS: { id: string; label: string; hint: string }[] = [
  { id: "websearch", label: "全网检索", hint: "通用搜索引擎公开结果" },
  { id: "govdoc", label: "政策文件", hint: "限定 gov.cn 域内的通知公告" },
  { id: "rss", label: "订阅源", hint: "需在环境变量配置 COLLECT_RSS_FEEDS" },
  { id: "hotlist", label: "热榜聚合", hint: "需在环境变量配置 COLLECT_HOTLIST_URL" },
];

export function CollectDialog({ open, onOpenChange, onSaved }: {
  open: boolean;
  onOpenChange: (next: boolean) => void;
  onSaved: () => void | Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [kinds, setKinds] = useState<string[]>(["websearch", "govdoc"]);
  const [items, setItems] = useState<CollectItemRow[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [independent, setIndependent] = useState(0);
  const [degraded, setDegraded] = useState<string[]>([]);
  const [previewing, setPreviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  if (!open) return null;

  function toggleKind(id: string) {
    setKinds((current) => current.includes(id) ? current.filter((k) => k !== id) : [...current, id]);
  }
  function toggleItem(url: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(url)) next.delete(url); else next.add(url);
      return next;
    });
  }

  async function preview() {
    const q = query.trim();
    if (!q) { setError("请先输入采集关键词。"); return; }
    setPreviewing(true); setError(""); setNotice(""); setItems([]); setSelected(new Set()); setDegraded([]);
    try {
      const body = await apiRequest<CollectPreviewResponse>("/api/collect/preview", {
        method: "POST",
        body: JSON.stringify({ query: q, kinds, rss: kinds.includes("rss"), hotlist: kinds.includes("hotlist") }),
      });
      if (body.error) { setError(body.message || "采集预览失败。"); return; }
      setItems(body.items ?? []);
      setIndependent(body.independent_sources ?? 0);
      setDegraded(body.degraded ?? []);
      if (!body.items?.length) setNotice("本轮没有采集到候选来源，可调整关键词或换渠道再试。");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "采集预览失败，请稍后重试。");
    } finally { setPreviewing(false); }
  }

  async function save() {
    if (!selected.size) { setError("请先勾选要入库的来源。"); return; }
    setSaving(true); setError("");
    try {
      const picked = items.filter((item) => selected.has(item.url));
      const body = await apiRequest<CollectSaveResponse>("/api/collect/save", {
        method: "POST",
        body: JSON.stringify({ items: picked }),
      });
      if (body.error) { setError(body.message || "入库失败。"); return; }
      setNotice(`已入库 ${body.saved_count} 条来源${body.skipped_count ? `，跳过重复 ${body.skipped_count} 条` : ""}。`);
      setItems([]); setSelected(new Set());
      await onSaved();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "入库失败，请稍后重试。");
    } finally { setSaving(false); }
  }

  return <div className="report-conversation-backdrop" role="presentation" onMouseDown={() => onOpenChange(false)}>
    <section className="report-conversation-dialog collect-dialog" role="dialog" aria-modal="true" aria-labelledby="collect-dialog-title" onMouseDown={(event) => event.stopPropagation()}>
      <header><div><span className="eyebrow">材料库 · 多平台采集</span><h2 id="collect-dialog-title">采集公开来源</h2></div><button className="table-icon" type="button" onClick={() => onOpenChange(false)} aria-label="关闭多平台采集"><X size={18} /></button></header>
      <div className="collect-dialog__body">
        <label className="collect-dialog__query"><span>采集关键词</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="例如：某市港口扩建 环评" onKeyDown={(event) => { if (event.key === "Enter" && !previewing) void preview(); }} /></label>
        <div className="collect-dialog__kinds" aria-label="采集渠道">
          {KIND_OPTIONS.map((option) => <label key={option.id} className={kinds.includes(option.id) ? "collect-kind collect-kind--active" : "collect-kind"} title={option.hint}><input type="checkbox" checked={kinds.includes(option.id)} onChange={() => toggleKind(option.id)} /><span><strong>{option.label}</strong><small>{option.hint}</small></span></label>)}
        </div>
        <div className="collect-dialog__actions">
          <button className="primary-button" type="button" onClick={() => void preview()} disabled={previewing}>{previewing ? "采集中" : "开始采集预览"}{previewing ? <LoaderCircle size={15} className="spin" /> : <Radar size={15} />}</button>
          {items.length > 0 && <span className="muted-count">{items.length} 条候选 · 独立来源 {independent} 个 · 已选 {selected.size} 条</span>}
        </div>
        {degraded.length > 0 && <p className="delivery-notice" role="status">部分渠道降级：{degraded.join("；")}</p>}
        {notice && <p className="delivery-notice" role="status">{notice}</p>}
        {error && <p className="delivery-error" role="alert">{error}</p>}
        {items.length > 0 && <div className="collect-dialog__results" role="list">
          {items.map((item) => <label className={selected.has(item.url) ? "collect-result collect-result--selected" : "collect-result"} key={`${item.kind}-${item.url}`} role="listitem">
            <input type="checkbox" checked={selected.has(item.url)} onChange={() => toggleItem(item.url)} aria-label={`选择 ${item.title}`} />
            <div>
              <strong>{item.title}</strong>
              <small>{item.platform}{item.region_name ? ` · ${item.region_name}` : ""}{item.engagement != null ? ` · 热度 ${item.engagement}` : ""}{item.duplicate ? " · 疑似重复" : ""}</small>
              {item.snippet && <p>{item.snippet}</p>}
              <a className="text-action" href={item.url} target="_blank" rel="noreferrer">{item.url}</a>
            </div>
          </label>)}
        </div>}
      </div>
      <footer>
        <button className="secondary-button" type="button" onClick={() => onOpenChange(false)}>关闭</button>
        <button className="primary-button" type="button" onClick={() => void save()} disabled={saving || !selected.size}>{saving ? "入库中" : `入库所选（${selected.size}）`}{!saving && <Download size={15} />}</button>
      </footer>
    </section>
  </div>;
}
