"use client";

import { AlertTriangle, Circle, ExternalLink, FileText, Filter, Globe2, LocateFixed, Network as NetworkIcon, Search, Share2, ZoomIn, ZoomOut } from "lucide-react";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiRequest } from "@/lib/api";
import type { MaterialRecord, ResearchBundle, ResearchSnapshotStatus } from "@/lib/domain";
import { collectReportEvidence, enrichDiagramWithResearch, findResearchNode, findResearchRelation, parseReportGraphs, type DiagramDocument } from "@/lib/report-graph";
import type { GraphLayout } from "@/lib/graph-layout";
import { GraphCanvas, type GraphCanvasHandle, type GraphSelection } from "@/components/graph-canvas";
import { EMPTY_FILTERS, applyGraphFilters, collectInterestOptions, collectRegionOptions, computeDimmedIds, isFilterActive, type GraphFilterState } from "@/lib/graph-filters";

type LoadState = "loading" | "ready" | "missing" | "error";

const graphStatusLabels: Record<string, string> = { confirmed: "已确认", inferred: "推测", conflicted: "存疑" };

const layoutOptions: { id: GraphLayout; label: string; hint: string; Icon: typeof Share2 }[] = [
  { id: "force", label: "力导向", hint: "按关系疏密自动排布，看整体结构", Icon: Share2 },
  { id: "ring", label: "环形分组", hint: "按主体类型分区，看利益构成", Icon: Circle },
  { id: "geo", label: "地理布局", hint: "按主体所属省份摆位，看空间分布", Icon: Globe2 },
];

const vizLabels: Record<DiagramDocument["viz"], string> = {
  network: "关系网络",
  org: "组织架构",
  flow: "流程",
};

const nodeTypeLabels: Record<string, string> = {
  material: "物质利益",
  security: "安全利益",
  political: "权力与政治",
  identity_culture: "身份与文化",
  institutional_future: "制度与未来",
  public: "公共空间",
  legal: "规则与监管",
  event: "事件节点",
  actor: "一般主体",
};

const edgeTypeLabels: Record<string, string> = {
  economic: "经济关系",
  power: "权力关系",
  cultural: "文化关系",
  legal: "法律关系",
  unknown: "未分类关系",
};

const interestTypeLabels: Record<string, string> = { economic: "经济利益", power: "权力利益", cultural: "文化利益", legal: "法律利益", security: "安全利益", identity: "身份利益" };
const directionLabels: Record<string, string> = { directed: "单向", undirected: "无方向", mutual: "双向", unknown: "方向未知" };
const polarityLabels: Record<string, string> = { positive: "正向", negative: "负向", mixed: "正负混合", neutral: "中性", unknown: "作用未知" };

export function AnalysisNetwork({ taskId, markdown: currentMarkdown, materials = [], research, researchStatus = "unavailable" }: { taskId: string; markdown?: string; materials?: MaterialRecord[]; research?: ResearchBundle; researchStatus?: ResearchSnapshotStatus }) {
  const [markdown, setMarkdown] = useState<string | null>(currentMarkdown ?? null);
  const [state, setState] = useState<LoadState>(currentMarkdown ? "ready" : "loading");
  const [activeDiagramId, setActiveDiagramId] = useState("");
  const [selection, setSelection] = useState<GraphSelection>(null);
  const [query, setQuery] = useState("");
  const [layout, setLayout] = useState<GraphLayout>("force");
  const [filters, setFilters] = useState<GraphFilterState>(EMPTY_FILTERS);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [canvasError, setCanvasError] = useState<Error | null>(null);
  const [canvasAttempt, setCanvasAttempt] = useState(0);
  const canvasRef = useRef<GraphCanvasHandle>(null);

  useEffect(() => {
    if (currentMarkdown) {
      setMarkdown(currentMarkdown);
      setState("ready");
      return;
    }
    let active = true;
    setState("loading");
    apiRequest<{ status: string; data?: { markdown?: string } }>(`/api/analyze/${taskId}`)
      .then((result) => {
        if (!active) return;
        if (result.status === "done" && result.data?.markdown) {
          setMarkdown(result.data.markdown);
          setState("ready");
        } else if (result.status === "error") {
          setState("error");
        } else {
          setState("missing");
        }
      })
      .catch(() => { if (active) setState("error"); });
    return () => { active = false; };
  }, [currentMarkdown, taskId]);

  const parsed = useMemo(() => parseReportGraphs(markdown ?? ""), [markdown]);
  const evidence = useMemo(() => collectReportEvidence(markdown ?? "", materials), [markdown, materials]);

  useEffect(() => {
    if (!parsed.diagrams.some((diagram) => diagram.id === activeDiagramId)) {
      setActiveDiagramId(parsed.diagrams[0]?.id ?? "");
      setSelection(null);
      setQuery("");
    }
  }, [activeDiagramId, parsed.diagrams]);

  useEffect(() => {
    setSelection(null);
    setQuery("");
    setCanvasError(null);
  }, [markdown]);

  const rawActiveDiagram = parsed.diagrams.find((diagram) => diagram.id === activeDiagramId) ?? parsed.diagrams[0];
  const activeDiagram = useMemo(() => rawActiveDiagram ? enrichDiagramWithResearch(rawActiveDiagram, research) : undefined, [rawActiveDiagram, research]);
  const selectedNode = selection?.kind === "node" ? activeDiagram?.nodes.find((node) => node.id === selection.id) : null;
  const selectedEdge = selection?.kind === "edge" ? activeDiagram?.edges.find((edge) => edge.id === selection.id) : null;
  const citations = evidence.filter((item) => item.kind === "citation");
  const linkedMaterials = evidence.filter((item) => item.kind === "material");
  const searchMatches = query.trim() && activeDiagram
    ? activeDiagram.nodes.filter((node) => node.label.toLocaleLowerCase("zh-CN").includes(query.trim().toLocaleLowerCase("zh-CN"))).slice(0, 8)
    : [];

  const filteredDiagram = useMemo(
    () => (activeDiagram ? applyGraphFilters(activeDiagram, filters) : undefined),
    [activeDiagram, filters],
  );
  const dimmedNodeIds = useMemo(
    () => (filteredDiagram ? computeDimmedIds(filteredDiagram, query) : new Set<string>()),
    [filteredDiagram, query],
  );
  const regionOptions = useMemo(() => (activeDiagram ? collectRegionOptions(activeDiagram.nodes) : []), [activeDiagram]);
  const interestOptions = useMemo(() => (activeDiagram ? collectInterestOptions(activeDiagram.edges) : []), [activeDiagram]);
  const filterCount = (filters.interestTypes.length ? 1 : 0) + (filters.regionCodes.length ? 1 : 0) + (filters.statuses.length ? 1 : 0) + (filters.minStrength > 1 ? 1 : 0);
  const hasEvidenceCounts = Boolean(activeDiagram?.nodes.some((node) => (node.evidenceCount ?? 0) > 0));

  function toggleInList(key: "interestTypes" | "regionCodes" | "statuses", value: string) {
    setFilters((current) => {
      const list = current[key];
      return { ...current, [key]: list.includes(value) ? list.filter((item) => item !== value) : [...list, value] };
    });
  }

  const handleSelection = useCallback((next: GraphSelection) => setSelection(next), []);
  const handleCanvasError = useCallback((error: Error) => setCanvasError(error), []);

  function chooseDiagram(id: string) {
    setActiveDiagramId(id);
    setSelection(null);
    setQuery("");
    setCanvasError(null);
  }

  function focusNode(id: string) {
    setSelection({ kind: "node", id });
    canvasRef.current?.focusNode(id);
  }

  if (state === "loading") return <section className="network-loading" aria-busy="true">正在读取关系图数据…</section>;
  if (state === "error") return <div className="workbench-network"><AlertTriangle size={24} /><div><span className="eyebrow">关系图读取失败</span><h2>无法读取后端报告</h2><p>请确认本地后端仍在运行，再重新进入当前任务。</p></div></div>;
  if (state !== "ready" || !markdown) return <div className="workbench-network"><NetworkIcon size={24} /><div><span className="eyebrow">关系图</span><h2>报告尚未生成</h2><p>分析任务完成后，这里会读取报告中的真实 DIAGRAM 数据。</p></div></div>;
  if (!activeDiagram) return <div className="workbench-network"><NetworkIcon size={24} /><div><span className="eyebrow">关系图</span><h2>未发现可用关系图</h2><p>当前报告没有合法的 DIAGRAM 数据。页面不会根据正文自行补造主体或关系。</p>{parsed.warnings.length > 0 && <span className="graph-warning-count"><AlertTriangle size={14} />{parsed.warnings.length} 项图谱数据未能解析</span>}</div></div>;

  const geoLocated = activeDiagram.nodes.filter((node) => node.regionCode).length;
  const inbound = selectedNode ? activeDiagram.edges.filter((edge) => edge.target === selectedNode.id) : [];
  const outbound = selectedNode ? activeDiagram.edges.filter((edge) => edge.source === selectedNode.id) : [];
  const edgeSource = selectedEdge ? activeDiagram.nodes.find((node) => node.id === selectedEdge.source) : null;
  const edgeTarget = selectedEdge ? activeDiagram.nodes.find((node) => node.id === selectedEdge.target) : null;
  const selectedRelation = selectedEdge ? findResearchRelation(selectedEdge, research) : undefined;
  const selectedProfile = selectedNode ? findResearchNode(selectedNode, research) : undefined;
  const selectedNodeSources = (selectedProfile?.evidenceIds ?? []).map((id) => research?.sources.find((source) => source.id === id)).filter((source): source is NonNullable<typeof source> => Boolean(source));
  const relationClaim = selectedRelation?.claimId ? research?.claims.find((claim) => claim.id === selectedRelation.claimId) : undefined;
  const relationSources = (selectedRelation?.evidenceIds ?? selectedEdge?.evidenceIds ?? [])
    .map((id) => research?.sources.find((source) => source.id === id))
    .filter((source): source is NonNullable<typeof source> => Boolean(source));
  const relationStatusLabel = selectedRelation?.status === "confirmed" ? "已确认" : selectedRelation?.status === "conflicted" ? "存在冲突" : "推测关系";
  const relationConfidenceLabel = selectedRelation?.confidence === "high" ? "高置信度" : selectedRelation?.confidence === "medium" ? "中置信度" : selectedRelation?.confidence === "low" ? "低置信度" : "置信度未知";

  return (
    <section className="analysis-network">
      <header className="graph-header">
        <div>
          <span className="eyebrow">结构图谱</span>
          <h2>{activeDiagram.title}</h2>
          <p>{filteredDiagram && isFilterActive(filters) ? `筛出 ${filteredDiagram.nodes.length}/${activeDiagram.nodes.length} 个主体 · ${filteredDiagram.edges.length}/${activeDiagram.edges.length} 条关系` : `${activeDiagram.nodes.length} 个节点 · ${activeDiagram.edges.length} 条关系`} · {vizLabels[activeDiagram.viz]}</p>
        </div>
        {parsed.warnings.length > 0 && <span className="graph-warning-count"><AlertTriangle size={14} />{parsed.warnings.length} 项图谱数据已跳过</span>}
      </header>

      {parsed.diagrams.length > 1 && (
        <div className="graph-tabs" role="tablist" aria-label="报告关系图">
          {parsed.diagrams.map((diagram) => <button type="button" role="tab" aria-label={diagram.title} aria-selected={diagram.id === activeDiagram.id} className={diagram.id === activeDiagram.id ? "graph-tab graph-tab--active" : "graph-tab"} onClick={() => chooseDiagram(diagram.id)} key={diagram.id}><span>{vizLabels[diagram.viz]}</span>{diagram.title}</button>)}
        </div>
      )}

      <div className="graph-filter-bar">
        <button type="button" className={filtersOpen || filterCount ? "graph-filter-toggle graph-filter-toggle--active" : "graph-filter-toggle"} aria-expanded={filtersOpen} onClick={() => setFiltersOpen((open) => !open)}>
          <Filter size={14} />筛选{filterCount ? ` · ${filterCount}` : ""}
        </button>
        <span className="graph-filter-summary">
          {isFilterActive(filters) ? `强度 ≥ ${filters.minStrength}${filters.interestTypes.length ? ` · ${filters.interestTypes.map((item) => interestTypeLabels[item] ?? item).join("、")}` : ""}${filters.statuses.length ? ` · ${filters.statuses.map((item) => graphStatusLabels[item] ?? item).join("、")}` : ""}${filters.regionCodes.length ? ` · ${filters.regionCodes.length} 个属地` : ""}` : "默认显示全部主体与关系"}
        </span>
        {isFilterActive(filters) && <button type="button" className="graph-filter-clear" onClick={() => setFilters(EMPTY_FILTERS)}>清空</button>}
      </div>

      {filtersOpen && <div className="graph-filter-panel">
        <div className="graph-filter-group">
          <strong>关系强度</strong>
          <label className="graph-strength">
            <input type="range" min={1} max={5} step={1} value={filters.minStrength} aria-label="关系强度阈值" onChange={(event) => setFilters((current) => ({ ...current, minStrength: Number(event.target.value) }))} />
            <span>≥ {filters.minStrength} / 5</span>
          </label>
        </div>
        <div className="graph-filter-group">
          <strong>关系状态</strong>
          <div className="graph-filter-chips">
            {Object.entries(graphStatusLabels).map(([id, label]) => (
              <button type="button" key={id} aria-pressed={filters.statuses.includes(id)} className={filters.statuses.includes(id) ? "graph-chip graph-chip--active" : "graph-chip"} onClick={() => toggleInList("statuses", id)}>{label}</button>
            ))}
          </div>
        </div>
        {interestOptions.length > 0 && <div className="graph-filter-group">
          <strong>利益类型</strong>
          <div className="graph-filter-chips">
            {interestOptions.map((option) => (
              <button type="button" key={option.id} aria-pressed={filters.interestTypes.includes(option.id)} className={filters.interestTypes.includes(option.id) ? "graph-chip graph-chip--active" : "graph-chip"} onClick={() => toggleInList("interestTypes", option.id)}>{interestTypeLabels[option.id] ?? option.id}<em>{option.count}</em></button>
            ))}
          </div>
        </div>}
        {regionOptions.length > 0 && <div className="graph-filter-group">
          <strong>属地</strong>
          <div className="graph-filter-chips">
            {regionOptions.map((option) => (
              <button type="button" key={option.code} aria-pressed={filters.regionCodes.includes(option.code)} className={filters.regionCodes.includes(option.code) ? "graph-chip graph-chip--active" : "graph-chip"} onClick={() => toggleInList("regionCodes", option.code)}>{option.name}<em>{option.count}</em></button>
            ))}
          </div>
        </div>}
      </div>}

      <div className="graph-workspace">
        <section className="graph-stage" aria-label="关系图画布工具">
          <div className="graph-toolbar">
            <label className="graph-search"><Search size={15} /><input type="search" aria-label="搜索图谱节点" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索节点" /></label>
            <div className="graph-layout-switch" role="group" aria-label="布局切换">
              {layoutOptions.map(({ id, label, hint, Icon }) => (
                <button
                  key={id}
                  type="button"
                  aria-pressed={layout === id}
                  title={hint}
                  className={layout === id ? "graph-layout-button graph-layout-button--active" : "graph-layout-button"}
                  onClick={() => setLayout(id)}
                >
                  <Icon size={14} />{label}
                </button>
              ))}
            </div>
            <div className="graph-toolbar__actions">
              <button type="button" aria-label="适应视口" title="适应视口" onClick={() => canvasRef.current?.fit()}><LocateFixed size={16} /></button>
              <button type="button" aria-label="放大图谱" title="放大" onClick={() => canvasRef.current?.zoomIn()}><ZoomIn size={16} /></button>
              <button type="button" aria-label="缩小图谱" title="缩小" onClick={() => canvasRef.current?.zoomOut()}><ZoomOut size={16} /></button>
            </div>
            {searchMatches.length > 0 && <div className="graph-search-results">{searchMatches.map((node) => <button type="button" aria-label={`定位节点 ${node.label}`} onClick={() => focusNode(node.id)} key={node.id}><span className={`graph-node-dot graph-node-dot--${node.type}`} />{node.label}</button>)}</div>}
          </div>
          {layout === "geo" && <p className="graph-geo-hint" role="status"><Globe2 size={13} />{geoLocated > 0 ? `已定位 ${geoLocated}/${activeDiagram.nodes.length} 个主体的属地，其余排到右侧「未知地域」列。` : "本版研究账本没有可用的属地信息，全部节点已排到右侧「未知地域」列。可先重建研究账本再回来看空间分布。"}</p>}
          {canvasError ? <div className="graph-runtime-error" role="alert"><AlertTriangle size={23} /><div><span className="eyebrow">图谱运行时错误</span><h3>关系图暂时无法绘制</h3><p>报告数据仍然保留，可以重新初始化当前画布。</p><button type="button" className="secondary-button" onClick={() => { setCanvasAttempt((value) => value + 1); setCanvasError(null); }}>重试绘制</button></div></div> : <>
            <GraphCanvas key={`${activeDiagram.id}-${layout}-${canvasAttempt}`} ref={canvasRef} diagram={filteredDiagram ?? activeDiagram} layout={layout} dimmedNodeIds={dimmedNodeIds} onSelectionChange={handleSelection} onError={handleCanvasError} />
            <div className="graph-legend" aria-label="图谱编码图例">
              <span className="graph-legend__group"><em>颜色</em>{Object.entries(edgeTypeLabels).map(([type, label]) => <span key={type}><i className={`graph-edge-key graph-edge-key--${type}`} />{label}</span>)}</span>
              <span className="graph-legend__group"><em>方向与正负</em><span><i className="graph-edge-key graph-edge-key--positive" />正向</span><span><i className="graph-edge-key graph-edge-key--negative" />负向</span></span>
              <span className="graph-legend__group"><em>线型</em><span><i className="graph-edge-key graph-edge-key--solid" />已确认</span><span><i className="graph-edge-key graph-edge-key--inferred" />推测</span><span><i className="graph-edge-key graph-edge-key--cross" />跨省</span></span>
              <span className="graph-legend__group"><em>大小</em><span className="graph-legend__note">{hasEvidenceCounts ? "节点越大 = 证据越多" : "本版账本没有证据计数，节点按权重显示"}</span></span>
            </div>
          </>}
        </section>

        <aside className="graph-inspector">
          {selectedNode ? <>
            <span className="eyebrow">选中主体</span><h3>{selectedNode.label}</h3><p>{nodeTypeLabels[selectedNode.type] ?? selectedNode.type}{selectedNode.regionName ? ` · ${selectedNode.regionName}` : ""}{selectedNode.regionName && selectedNode.regionSource === "evidence_majority" ? "（由证据来源推断）" : ""}</p>
            <div className="graph-inspector__stats"><span>流入 <strong>{inbound.length}</strong></span><span>流出 <strong>{outbound.length}</strong></span>{selectedNode.evidenceCount !== undefined && <span>证据 <strong>{selectedNode.evidenceCount}</strong></span>}</div>
            {selectedProfile && <div className="graph-node-dossier"><div><strong>{selectedProfile.role || "角色待确认"}</strong><span>权重 {Math.round(selectedProfile.weight * 100)}%</span></div><dl><div><dt>核心利益</dt><dd>{selectedProfile.interests.length ? selectedProfile.interests.join("、") : "未知"}</dd></div><div><dt>当前立场</dt><dd>{selectedProfile.stance || "未知"}</dd></div><div><dt>置信度</dt><dd>{selectedProfile.confidence === "high" ? "高" : selectedProfile.confidence === "medium" ? "中" : selectedProfile.confidence === "low" ? "低" : "未知"}</dd></div><div><dt>观察区间</dt><dd>{selectedProfile.firstSeen || "未知"} 至 {selectedProfile.lastSeen || "现在"}</dd></div></dl>{selectedNodeSources.length > 0 && <div className="graph-node-sources"><strong>主体证据</strong>{selectedNodeSources.map((source) => source.url ? <a href={source.url} target="_blank" rel="noreferrer" key={source.id}>{source.title}<ExternalLink size={12} /></a> : <span key={source.id}>{source.title}</span>)}</div>}</div>}
            <div className="graph-relation-list">{[...inbound, ...outbound].map((edge) => <button type="button" onClick={() => setSelection({ kind: "edge", id: edge.id })} key={edge.id}><strong>{edge.label}</strong><span>{activeDiagram.nodes.find((node) => node.id === edge.source)?.label} → {activeDiagram.nodes.find((node) => node.id === edge.target)?.label}</span></button>)}</div>
          </> : selectedEdge ? <>
            <span className="eyebrow">选中关系</span><h3>{selectedEdge.label}</h3><p>{edgeTypeLabels[selectedEdge.type] ?? selectedEdge.type}</p>
            <div className="graph-edge-path"><button type="button" onClick={() => focusNode(selectedEdge.source)}>{edgeSource?.label ?? selectedEdge.source}</button><span>→</span><button type="button" onClick={() => focusNode(selectedEdge.target)}>{edgeTarget?.label ?? selectedEdge.target}</button></div>
            {selectedRelation ? <div className="graph-edge-evidence"><h4>为什么系统认为双方存在这条关系？</h4><strong>{relationStatusLabel} · {relationConfidenceLabel}</strong><div className="graph-edge-analysis"><span>关系强度 {selectedRelation.strength ?? 1}/5</span><span>{(selectedRelation.interestTypes ?? []).map((item) => interestTypeLabels[item] ?? item).join(" · ") || "利益类型未知"}</span><span>{directionLabels[selectedRelation.direction] ?? selectedRelation.direction} · {polarityLabels[selectedRelation.polarity] ?? selectedRelation.polarity}</span><span>{selectedRelation.validFrom || "时间未知"}{selectedRelation.validTo ? ` 至 ${selectedRelation.validTo}` : " 起"}</span></div>{researchStatus === "stale" && <p>这条绑定继承自上一版正文，尚未重新核验。</p>}{relationClaim && <><h4>对应判断</h4><p>{relationClaim.text}</p>{relationClaim.confidenceReasons.map((reason) => <p key={reason}>{reason}</p>)}</>}<h4>关系证据 · {selectedRelation.evidenceCount ?? relationSources.length} 条</h4>{relationSources.length ? relationSources.map((source) => source.url ? <a href={source.url} target="_blank" rel="noreferrer" aria-label={`${source.title}，打开关系证据`} key={source.id}><ExternalLink size={13} /><span><strong>{source.title}</strong><small>{source.qualityTier ? `${source.qualityTier} 级来源` : "来源等级未知"}</small>{source.excerpt && <small>{source.excerpt}</small>}</span></a> : <div key={source.id}><span><strong>{source.title}</strong>{source.excerpt && <small>{source.excerpt}</small>}</span></div>) : <p>当前关系没有可核验来源，只能作为推测使用。</p>}</div> : <div className="graph-edge-evidence graph-edge-evidence--empty"><strong>未建立边级证据绑定</strong><p>可查看下方整份报告的来源基础，但不能据此认定这些来源直接证明当前关系。</p></div>}
          </> : <>
            <span className="eyebrow">图谱检查器</span><h3>选择一个主体或关系</h3><p>点击画布节点查看流入与流出关系；点击连线查看关系类型和方向。</p>
            <div className="graph-node-index">{activeDiagram.nodes.slice(0, 12).map((node) => <button type="button" onClick={() => focusNode(node.id)} key={node.id}><span className={`graph-node-dot graph-node-dot--${node.type}`} />{node.label}</button>)}</div>
          </>}
        </aside>
      </div>

      <section className="graph-evidence">
        <header><div><span className="eyebrow">证据基础</span><h3>报告引用与任务材料</h3></div><strong>{citations.length} 条公开引用 · {linkedMaterials.length} 份关联材料</strong></header>
        <p className="graph-evidence__scope">{research?.relations.length ? `当前研究账本已建立 ${research.relations.length} 条关系绑定；选中具体连线可检查对应证据。下列内容仍是整份报告的来源基础。` : "以下内容是整份报告的来源基础，不表示后端已经建立到单个节点或关系的逐句证明映射。"}</p>
        <div className="graph-evidence__columns">
          <div><h4>报告中的公开引用</h4>{citations.length ? citations.map((item) => <a href={item.url} aria-label={item.label} target="_blank" rel="noreferrer" key={item.id}><ExternalLink size={14} /><span><strong>{item.label}</strong><small>{item.detail}</small></span></a>) : <p>当前报告没有 Markdown 公开链接。</p>}</div>
          <div><h4>任务关联材料</h4>{linkedMaterials.length ? linkedMaterials.map((item) => <div className="graph-material" key={item.id}><FileText size={15} /><span><strong>{item.label}</strong><small>{item.detail}</small></span><em className={item.status === "error" ? "graph-material__status graph-material__status--error" : "graph-material__status"}>{item.status === "error" ? "解析告警" : "已关联"}</em></div>) : <p>当前任务没有关联材料。</p>}</div>
        </div>
      </section>
    </section>
  );
}
