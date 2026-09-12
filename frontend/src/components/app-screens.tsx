"use client";

import Link from "next/link";
import { ArrowRight, ChevronRight, FileText, Network, Radar, Search, Trash2, Upload } from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import { analysisTypes, phaseLabels, type AnalysisType, type AppState, type ProjectStatus, type TaskStatus } from "@/lib/domain";
import { useAppStore } from "@/lib/store";
import { apiRequest } from "@/lib/api";
import { filterProjects, filterReports } from "@/lib/view-models";
import { AnalysisNetwork } from "@/components/analysis-network";
import { ReportGeoMap } from "@/components/report-geo-map";
import { ReportReader } from "@/components/report-reader";
import { ProjectMonitorPanel } from "@/components/project-monitor-panel";
import { LlmConnectionSettings } from "@/components/llm-connection-settings";
import { CollectDialog } from "@/components/collect-dialog";

const projectStatus: Record<ProjectStatus, { label: string; tone: "running" | "warning" | "verified" }> = {
  active: { label: "分析中", tone: "running" },
  review: { label: "待复核", tone: "warning" },
  archived: { label: "已归档", tone: "verified" },
};

const taskStatus: Record<TaskStatus, { label: string; tone: "running" | "warning" | "verified" }> = {
  queued: { label: "等待执行", tone: "warning" },
  generating: { label: "分析中", tone: "running" },
  done: { label: "已完成", tone: "verified" },
  error: { label: "执行失败", tone: "warning" },
};

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}

function typeLabel(type: string) {
  return analysisTypes.find((item) => item.id === type)?.label ?? "结构分析";
}

function Status({ children, tone = "running" }: { children: React.ReactNode; tone?: "running" | "warning" | "verified" }) {
  return <span className={`status-pill status-pill--${tone}`}><span />{children}</span>;
}

function PageHeading({ eyebrow, title, children, action }: { eyebrow: string; title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return <section className="page-heading"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{children}</p></div>{action}</section>;
}

function EmptyState({ eyebrow, title, detail, href = "/analysis", action = "新建分析" }: { eyebrow: string; title: string; detail: string; href?: string; action?: string }) {
  return <section className="empty-state"><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{detail}</p><Link className="primary-button" href={href}>{action} <ArrowRight size={16} /></Link></section>;
}

function ProjectDirectory({ state, allowDelete = false, refreshWorkspace }: { state: AppState; allowDelete?: boolean; refreshWorkspace?: () => Promise<void> }) {
  const [query, setQuery] = useState("");
  const [type, setType] = useState<"all" | AnalysisType>("all");
  const [status, setStatus] = useState<"all" | ProjectStatus>("all");
  const [sort, setSort] = useState<"updated-desc" | "updated-asc">("updated-desc");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const projects = filterProjects(state.projects, { query, type, status, sort });
  const visibleIds = projects.map((project) => project.id);
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.includes(id));

  useEffect(() => {
    const currentIds = new Set(state.projects.map((project) => project.id));
    setSelectedIds((current) => current.filter((id) => currentIds.has(id)));
  }, [state.projects]);

  function toggleProject(projectId: string) {
    setSelectedIds((current) => current.includes(projectId) ? current.filter((id) => id !== projectId) : [...current, projectId]);
  }

  function toggleVisibleProjects() {
    setSelectedIds((current) => allVisibleSelected
      ? current.filter((id) => !visibleIds.includes(id))
      : [...new Set([...current, ...visibleIds])]);
  }

  async function removeSelectedProjects() {
    if (!selectedIds.length || !refreshWorkspace) return;
    const confirmed = window.confirm(`永久删除选中的 ${selectedIds.length} 个项目？关联任务、报告和生成文件也会被删除，材料只解除项目绑定。`);
    if (!confirmed) return;
    setDeleting(true);
    setDeleteError("");
    try {
      const result = await apiRequest<{ failed?: { id: string; reason: string }[] }>("/api/projects", {
        method: "DELETE",
        body: JSON.stringify({ ids: selectedIds, confirm: true }),
      });
      await refreshWorkspace();
      const failedIds = (result.failed ?? []).map((item) => item.id);
      setSelectedIds(failedIds);
      if (failedIds.length) setDeleteError(`${failedIds.length} 个项目删除失败，请稍后重试。`);
    } catch (reason) {
      setDeleteError(reason instanceof Error ? reason.message : "项目删除失败，请稍后重试。");
    } finally {
      setDeleting(false);
    }
  }

  return <section className="workspace-projects">
    <div className="section-title"><div><span className="eyebrow">项目组合</span><h2>项目</h2></div><span className="muted-count">{state.projects.length} 个</span></div>
    {state.projects.length === 0 ? <div className="workspace-projects__empty"><p>还没有项目。提交一次新分析后，项目、任务和报告会自动归到一起。</p><Link className="text-action" href="/analysis">新建分析 <ArrowRight size={15} /></Link></div> : <>
      <div className="list-toolbar list-toolbar--inset"><label className="toolbar-search"><Search size={15} /><input aria-label="搜索项目" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索项目" /></label><select aria-label="项目类型" value={type} onChange={(event) => setType(event.target.value as "all" | AnalysisType)}><option value="all">全部类型</option>{analysisTypes.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select><select aria-label="项目状态" value={status} onChange={(event) => setStatus(event.target.value as "all" | ProjectStatus)}><option value="all">全部状态</option><option value="active">分析中</option><option value="review">待复核</option><option value="archived">已归档</option></select><select aria-label="项目排序" value={sort} onChange={(event) => setSort(event.target.value as "updated-desc" | "updated-asc")}><option value="updated-desc">最近更新</option><option value="updated-asc">最早更新</option></select>{allowDelete && <><button type="button" className="selection-action" aria-label="全选当前筛选结果" onClick={toggleVisibleProjects} disabled={!projects.length}>{allVisibleSelected ? "取消全选" : "全选结果"}</button><button type="button" className="selection-action selection-action--danger" aria-label="删除选中的项目" onClick={() => void removeSelectedProjects()} disabled={!selectedIds.length || deleting}><Trash2 size={14} />{deleting ? "删除中" : `删除${selectedIds.length ? ` ${selectedIds.length}` : ""}`}</button></>}<span>显示 {projects.length} / {state.projects.length}</span></div>
      {deleteError && <p className="form-error project-delete-error" role="alert">{deleteError}</p>}
      {projects.length ? <div className="data-table">{allowDelete ? <><div className="data-table__head data-table__head--selectable"><label className="project-select"><input type="checkbox" aria-label="全选当前项目" checked={allVisibleSelected} onChange={toggleVisibleProjects} /></label><span>项目</span><span>进度</span><span>状态</span><span>更新</span><span /></div>{projects.map((project) => { const tasks = state.tasks.filter((task) => task.projectId === project.id); const reports = state.reports.filter((report) => tasks.some((task) => task.id === report.taskId)); const projectState = projectStatus[project.status]; const selected = selectedIds.includes(project.id); return <div className={`data-table__row data-table__row--selectable${selected ? " data-table__row--selected" : ""}`} key={project.id}><label className="project-select"><input type="checkbox" checked={selected} onChange={() => toggleProject(project.id)} aria-label={`选择项目 ${project.name}`} /></label><Link href={`/projects/${project.id}`} className="project-row-link"><div><strong>{project.name}</strong><small>{typeLabel(project.type)} · {tasks.length} 个任务 · {reports.length} 份报告</small></div><span className="table-progress"><i><b style={{ width: `${project.progress}%` }} /></i></span><Status tone={projectState.tone}>{projectState.label}</Status><time>{formatDate(project.updatedAt)}</time><ChevronRight size={17} /></Link></div>; })}</> : <><div className="data-table__head"><span>项目</span><span>进度</span><span>状态</span><span>更新</span><span /></div>{projects.map((project) => { const tasks = state.tasks.filter((task) => task.projectId === project.id); const reports = state.reports.filter((report) => tasks.some((task) => task.id === report.taskId)); const projectState = projectStatus[project.status]; return <Link href={`/projects/${project.id}`} className="data-table__row" key={project.id}><div><strong>{project.name}</strong><small>{typeLabel(project.type)} · {tasks.length} 个任务 · {reports.length} 份报告</small></div><span className="table-progress"><i><b style={{ width: `${project.progress}%` }} /></i></span><Status tone={projectState.tone}>{projectState.label}</Status><time>{formatDate(project.updatedAt)}</time><ChevronRight size={17} /></Link>; })}</>}</div> : <p className="filtered-empty">没有符合当前条件的项目。</p>}
    </>}
  </section>;
}

export function DashboardScreen() {
  const { state, refreshWorkspace } = useAppStore();
  const currentTask = state.tasks.find((task) => task.status === "queued" || task.status === "generating") ?? state.tasks[0];
  const recentReport = state.reports.reduce((latest, report) => {
    if (!latest) return report;
    const reportTime = Date.parse(report.updatedAt) || 0;
    const latestTime = Date.parse(latest.updatedAt) || 0;
    return reportTime > latestTime ? report : latest;
  }, state.reports[0]);
  const currentProject = currentTask ? state.projects.find((project) => project.id === currentTask.projectId) : undefined;
  const phase = currentTask ? phaseLabels.find((item) => item.id === currentTask.phase)?.label ?? "准备分析" : "等待开始";
  const currentStatus = currentTask ? taskStatus[currentTask.status] : null;

  return <>
    <PageHeading eyebrow="接着分析" title="工作台" action={<Link className="primary-button" href="/analysis">新建分析 <ArrowRight size={16} /></Link>}>集中处理正在进行的判断、需要复核的证据与最近产生的报告。</PageHeading>
    <section className="dashboard-focus"><div className="focus-visual">{currentTask ? <><span className="eyebrow">{currentStatus?.label} · {typeLabel(currentTask.type)}</span><h2>{currentTask.title}</h2><p>{currentTask.context || "该任务未填写补充背景。"}</p><div className="focus-progress"><div><span>{phase}</span><strong>{currentTask.progress}%</strong></div><i><b style={{ width: `${currentTask.progress}%` }} /></i></div><Link href={`/analysis/${currentTask.id}`} className="text-action">进入分析操作台 <ArrowRight size={15} /></Link></> : <><span className="eyebrow">开始建立分析资产</span><h2>工作台还没有任务</h2><p>从一个事件、政策、舆情或组织问题开始，系统会自动建立项目与分析任务。</p><Link href="/analysis" className="text-action">新建第一个分析 <ArrowRight size={15} /></Link></>}</div><aside className="focus-queue"><span className="eyebrow">本地数据</span><div><strong>{String(state.materials.length).padStart(2, "0")}</strong><p>来源材料</p></div><div><strong>{String(state.tasks.filter((task) => task.status === "queued" || task.status === "generating").length).padStart(2, "0")}</strong><p>进行中任务</p></div><span className="focus-queue__note">材料在新建分析时统一管理</span></aside></section>
    <ProjectDirectory state={state} allowDelete refreshWorkspace={refreshWorkspace} />
    <section className="dashboard-bottom"><div className="recent-report"><span className="eyebrow">{recentReport ? `最近报告 · v${recentReport.version}` : "最近报告"}</span><h2>{recentReport?.title ?? "当前还没有报告"}</h2><p>{recentReport ? `${typeLabel(recentReport.type)} · 后端当前版本 · 可继续修订` : "任务完成后，后端生成的结构化报告会自动出现在这里。"}</p>{recentReport ? <Link href={`/reports/${recentReport.id}`} className="text-action">阅读报告 <ArrowRight size={15} /></Link> : <Link href="/analysis" className="text-action">新建分析 <ArrowRight size={15} /></Link>}</div><div className="signal-note"><Network size={20} /><div><span className="eyebrow">结构提醒</span><p>{currentProject?.description ?? "项目的主体、利益与关系网络会在分析过程中持续更新。"}</p></div></div></section>
  </>;
}

export function ProjectsScreen() {
  const { state, refreshWorkspace } = useAppStore();
  return <><PageHeading eyebrow="项目组合" title="项目" action={<Link className="primary-button" href="/analysis">新建项目 <ArrowRight size={16} /></Link>}>以项目为容器，让材料、分析任务、报告和判断始终保留在同一个上下文中。</PageHeading><ProjectDirectory state={state} allowDelete refreshWorkspace={refreshWorkspace} /></>;
}

export function ProjectDetailScreen({ projectId }: { projectId: string }) {
  const { state, hydrated } = useAppStore();
  const project = state.projects.find((item) => item.id === projectId);
  if (!project) return hydrated ? <EmptyState eyebrow="未找到项目" title="这个项目不存在" detail="返回工作台，选择一个仍在当前工作区中的项目。" href="/dashboard" action="返回工作台" /> : null;
  const tasks = state.tasks.filter((task) => task.projectId === project.id);
  const taskIds = new Set(tasks.map((task) => task.id));
  const reports = state.reports.filter((report) => taskIds.has(report.taskId));
  const materialIds = new Set(tasks.flatMap((task) => task.materialIds));
  const primaryTask = tasks[0];

  const primaryStatus = primaryTask ? taskStatus[primaryTask.status] : null;
  return <><PageHeading eyebrow={`项目 / ${typeLabel(project.type)}`} title={project.name} action={primaryTask ? <Link className="primary-button" href={`/analysis/${primaryTask.id}`}>进入操作台 <ArrowRight size={16} /></Link> : undefined}>{project.description}</PageHeading><section className="project-detail-grid"><div className="detail-block"><span className="eyebrow">分析任务</span><h2>{tasks.length} 个结构化分析任务</h2><p>{primaryTask ? `当前进度 ${primaryTask.progress}%，后端阶段为“${phaseLabels.find((phase) => phase.id === primaryTask.phase)?.label}”。` : "这个项目尚未创建分析任务。"}</p><div className="detail-actions"><Status tone={primaryStatus?.tone ?? "warning"}>{primaryStatus?.label ?? "待开始"}</Status>{primaryTask && <Link href={`/analysis/${primaryTask.id}`} className="text-action">查看任务 <ArrowRight size={15} /></Link>}</div></div><div className="detail-block"><span className="eyebrow">项目资料</span><h2>{materialIds.size} 份关联材料</h2><p>材料通过分析任务与项目关联，可在新建分析时继续添加和核对来源。</p><Link href="/analysis" className="text-action">添加分析材料 <ArrowRight size={15} /></Link></div></section>{primaryTask && <ProjectMonitorPanel projectId={project.id} seedTaskId={primaryTask.id} />}<section className="split-section"><div className="section-title"><div><span className="eyebrow">交付物</span><h2>报告版本</h2></div></div>{reports.length ? reports.map((report) => <div className="report-row" key={report.id}><FileText size={20} /><div><strong>{report.title}</strong><small>v{report.version} · {typeLabel(report.type)} · {formatDate(report.updatedAt)}</small></div><Status tone="verified">后端当前版本</Status><Link href={`/reports/${report.id}`} className="table-icon" aria-label={`阅读 ${report.title}`}><ChevronRight size={18} /></Link></div>) : <p className="section-empty">当前项目尚未生成报告；任务完成后，后端报告会自动出现在这里。</p>}</section></>;
}

export function MaterialsScreen() {
  const { state, refreshWorkspace } = useAppStore();
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploadError, setUploadError] = useState("");
  const [collectOpen, setCollectOpen] = useState(false);
  async function importFiles(files: FileList | null) {
    if (!files?.length) return;
    setUploadError("");
    const selected = Array.from(files);
    const oversized = selected.find((file) => file.size > 50 * 1024 * 1024);
    if (oversized) { setUploadError(`"${oversized.name}"超过 50MB 限制。`); return; }
    try {
      await Promise.all(selected.map(async (file) => {
        const body = new FormData();
        body.append("file", file);
        await apiRequest("/api/materials/upload", { method: "POST", body });
      }));
      await refreshWorkspace();
    } catch (reason) {
      setUploadError(reason instanceof Error ? reason.message : "材料上传失败，请稍后重试。");
    }
  }
  return <><PageHeading eyebrow="证据基础" title="材料库" action={<div className="heading-actions"><button className="secondary-button" type="button" onClick={() => setCollectOpen(true)}><Radar size={16} />多平台采集</button><button className="primary-button" type="button" onClick={() => inputRef.current?.click()}><Upload size={16} />导入材料</button></div>}>保留原始材料与来源关系，让每一个结论都可以回到它的证据基础。</PageHeading><CollectDialog open={collectOpen} onOpenChange={setCollectOpen} onSaved={refreshWorkspace} /><input ref={inputRef} className="visually-hidden" type="file" multiple accept=".pdf,.docx,.txt,.md" onChange={(event) => { void importFiles(event.target.files); }} /><section className="material-importer"><div><Upload size={22} /><strong>导入文件作为分析来源</strong><span>支持 PDF、Word（docx）、TXT 与 Markdown，单文件不超过 50MB；文件会进入解析队列。</span>{uploadError && <p className="form-error" role="alert">{uploadError}</p>}</div><button type="button" onClick={() => inputRef.current?.click()}>选择文件</button></section><section className="split-section"><div className="section-title"><div><span className="eyebrow">全部材料</span><h2>已导入来源</h2></div><span className="muted-count">{state.materials.length} 份</span></div>{state.materials.length ? <div className="material-records">{state.materials.map((material) => <div className="material-record" key={material.id}><span><FileText size={19} /></span><div><strong>{material.name}</strong><small>{material.kind === "file" ? "文件" : material.kind} · {formatDate(material.updatedAt)}</small></div><p>{material.note}</p><span className="table-icon" aria-hidden="true"><ChevronRight size={18} /></span></div>)}</div> : <p className="section-empty">尚未导入材料。材料也可以在新建分析时一并加入。</p>}</section></>;
}

export function ReportsScreen() {
  const { state, deleteReports, refreshWorkspace } = useAppStore();
  const [query, setQuery] = useState("");
  const [type, setType] = useState<"all" | AnalysisType>("all");
  const [sort, setSort] = useState<"updated-desc" | "updated-asc">("updated-desc");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const reports = filterReports(state.reports, { query, type, sort });
  const allSelected = reports.length > 0 && reports.every((report) => selectedIds.includes(report.id));
  function toggle(reportId: string) { setSelectedIds((current) => current.includes(reportId) ? current.filter((id) => id !== reportId) : [...current, reportId]); }
  function toggleAll() { setSelectedIds(allSelected ? [] : reports.map((report) => report.id)); }
  async function removeSelected() {
    if (!selectedIds.length) return;
    setDeleting(true); setDeleteError("");
    try {
      // 分析skill 后端：DELETE /api/reports/{task_id}（report.id 即 task_id）。
      await Promise.all(selectedIds.map((id) => apiRequest(`/api/reports/${id}`, { method: "DELETE" })));
      deleteReports(selectedIds);
      await refreshWorkspace();
      setSelectedIds([]);
    } catch (reason) {
      setDeleteError(reason instanceof Error ? reason.message : "报告删除失败，请稍后重试。");
    } finally { setDeleting(false); }
  }
  return <><PageHeading eyebrow="输出与沉淀" title="报告" action={<Link className="primary-button" href="/analysis">从分析新建 <ArrowRight size={16} /></Link>}>这里展示后端已经生成的报告当前版本，并保留阅读、修订和结构拆解入口。</PageHeading>{state.reports.length ? <><div className="list-toolbar"><label className="toolbar-search"><Search size={15} /><input aria-label="搜索报告" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索报告" /></label><select aria-label="报告类型" value={type} onChange={(event) => setType(event.target.value as "all" | AnalysisType)}><option value="all">全部类型</option>{analysisTypes.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select><select aria-label="报告排序" value={sort} onChange={(event) => setSort(event.target.value as "updated-desc" | "updated-asc")}><option value="updated-desc">最近更新</option><option value="updated-asc">最早更新</option></select><button type="button" className="selection-action" onClick={toggleAll} disabled={!reports.length}>{allSelected ? "取消全选" : "全选结果"}</button><button type="button" className="selection-action selection-action--danger" onClick={() => void removeSelected()} disabled={!selectedIds.length || deleting}><Trash2 size={14} />{deleting ? "删除中" : `删除 ${selectedIds.length || ""}`}</button><span>显示 {reports.length} / {state.reports.length}</span></div>{deleteError && <p className="form-error" role="alert">{deleteError}</p>}{reports.length ? <section className="report-catalog">{reports.map((report, index) => <article className={index === 0 ? "report-catalog__lead" : "report-catalog__item"} key={report.id}><label className="report-select"><input type="checkbox" checked={selectedIds.includes(report.id)} onChange={() => toggle(report.id)} aria-label={`选择报告 ${report.title}`} /><span>选择</span></label><span className="eyebrow">{index === 0 ? "最近更新" : "分析成果"} · v{report.version}</span><h2>{report.title}</h2><p>{typeLabel(report.type)} · 后端当前版本 · {formatDate(report.updatedAt)}</p><div><Link href={`/reports/${report.id}`} className="table-icon" aria-label={`阅读 ${report.title}`}><ChevronRight size={18} /></Link><Link href={`/interest-analysis/${report.id}`} className="table-icon" aria-label={`拆解 ${report.title}`}><Network size={17} /></Link></div></article>)}</section> : <p className="filtered-empty">没有符合当前条件的报告。</p>}</> : <EmptyState eyebrow="暂无报告" title="还没有生成报告" detail="从新建分析开始，任务完成后会自动生成结构化报告。" />}</>;
}

export function ReportReaderScreen({ reportId }: { reportId: string }) {
  const { state, hydrated, loadReport } = useAppStore();
  const report = state.reports.find((item) => item.id === reportId);
  if (!report) return hydrated ? <EmptyState eyebrow="未找到报告" title="这个报告不存在" detail="返回工作台，或从分析任务生成一份新的报告。" href="/dashboard" action="返回工作台" /> : null;
  const task = state.tasks.find((item) => item.id === report.taskId);
  return <ReportReader report={report} task={task} onReload={() => loadReport(report.taskId)} />;
}

export function InterestIndexScreen() {
  const { state } = useAppStore();
  const [query, setQuery] = useState("");
  const [type, setType] = useState<"all" | AnalysisType>("all");
  const reports = filterReports(state.reports, { query, type, sort: "updated-desc" });
  return <><PageHeading eyebrow="结构关系" title="利益拆解">从后端当前报告版本进入主体、利益和关系章节，查看结构化拆解。</PageHeading>{state.reports.length ? <><div className="list-toolbar"><label className="toolbar-search"><Search size={15} /><input aria-label="搜索利益拆解" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索报告" /></label><select aria-label="利益拆解类型" value={type} onChange={(event) => setType(event.target.value as "all" | AnalysisType)}><option value="all">全部类型</option>{analysisTypes.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select><span>显示 {reports.length} / {state.reports.length}</span></div>{reports.length ? <section className="data-table"><div className="data-table__head"><span>分析报告</span><span>版本</span><span>类型</span><span>更新</span><span /></div>{reports.map((report) => <Link className="data-table__row" href={`/interest-analysis/${report.id}`} key={report.id}><div><strong>{report.title}</strong><small>后端当前版本 · 结构拆解视图</small></div><span>v{report.version}</span><Status tone="verified">{typeLabel(report.type)}</Status><time>{formatDate(report.updatedAt)}</time><ChevronRight size={17} /></Link>)}</section> : <p className="filtered-empty">没有符合当前条件的关系网络。</p>}</> : <EmptyState eyebrow="暂无关系网络" title="先从分析生成一份报告" detail="任务完成后，可从后端报告进入独立的结构拆解视图。" />}</>;
}

export function InterestAnalysisScreen({ reportId }: { reportId: string }) {
  const { state, hydrated } = useAppStore();
  const [view, setView] = useState<"network" | "geo">("network");
  const report = state.reports.find((item) => item.id === reportId);
  if (!report) return hydrated ? <EmptyState eyebrow="未找到关系网络" title="无法打开利益拆解" detail="请先从分析任务生成报告，再进入对应的关系网络。" href="/dashboard" action="返回工作台" /> : null;
  const task = state.tasks.find((item) => item.id === report.taskId);
  const materials = state.materials.filter((material) => task?.materialIds.includes(material.id));
  return <>
    <PageHeading eyebrow={`报告视图 / ${typeLabel(report.type)}`} title="利益拆解">把"{report.title}"切换为结构化的主体、利益与关系拆解。</PageHeading>
    <div className="interest-view-tabs" role="tablist" aria-label="拆解视图">
      <button type="button" role="tab" aria-selected={view === "network"} className={view === "network" ? "data-tab data-tab--active" : "data-tab"} onClick={() => setView("network")}>关系网络</button>
      <button type="button" role="tab" aria-selected={view === "geo"} className={view === "geo" ? "data-tab data-tab--active" : "data-tab"} onClick={() => setView("geo")}>地域分布</button>
    </div>
    {view === "geo"
      ? <ReportGeoMap taskId={report.taskId} />
      : <AnalysisNetwork taskId={report.taskId} markdown={report.markdown} materials={materials} research={report.research} researchStatus={report.researchStatus} />}
  </>;
}

export function SettingsScreen() {
  const { state, updateSettings } = useAppStore();
  const engineLabel = state.settings.defaultEngine === "auto" ? "系统自动选择" : state.settings.defaultEngine === "rule" ? "规则引擎优先" : "语言增强优先";
  return <><PageHeading eyebrow="应用偏好" title="设置">配置你自己的 AI 接口、分析引擎、界面主题和默认导出方式。</PageHeading><section className="settings-stack"><LlmConnectionSettings /><div><span className="eyebrow">默认引擎</span><h2>{engineLabel}</h2><p>自动模式会根据输入方式和当前浏览器的 AI 连接状态选择实际引擎。</p><label className="setting-control"><span>默认分析引擎</span><select aria-label="默认分析引擎" value={state.settings.defaultEngine} onChange={(event) => updateSettings({ defaultEngine: event.target.value as "auto" | "rule" | "llm" })}><option value="auto">自动选择</option><option value="rule">规则引擎</option><option value="llm">语言增强</option></select></label></div><div><span className="eyebrow">显示主题</span><h2>{state.settings.theme === "light" ? "明亮研究工作台" : "深色研究工作台"}</h2><p>主题立即作用于整个分析空间，并在下次打开时恢复。</p><label className="setting-control"><span>显示主题</span><select aria-label="显示主题" value={state.settings.theme} onChange={(event) => updateSettings({ theme: event.target.value as "light" | "dark" })}><option value="light">明亮</option><option value="dark">深色</option></select></label></div><div><span className="eyebrow">默认导出</span><h2>{state.settings.defaultExport === "markdown" ? "Markdown 报告" : "HTML 报告"}</h2><p>报告阅读器的导出按钮将直接使用这一格式。</p><label className="setting-control"><span>默认导出格式</span><select aria-label="默认导出格式" value={state.settings.defaultExport} onChange={(event) => updateSettings({ defaultExport: event.target.value as "markdown" | "html" })}><option value="markdown">Markdown</option><option value="html">HTML</option></select></label></div></section></>;
}
