export type AnalysisType = "case" | "policy" | "org" | "opinion" | "combo";
export type EngineMode = "auto" | "rule" | "llm";
export type InputMode = "freeform" | "structured";
export type TaskStatus = "queued" | "generating" | "done" | "error";
export type TaskPhase = "inspect" | "search" | "decompose" | "network" | "organize" | "output";
export type TaskErrorPhase = TaskPhase | "input_validation" | "quality_gate";
export type ProjectStatus = "active" | "review" | "archived";
export type MaterialKind = "file" | "link" | "note";
export type MaterialStatus = "pending" | "ready" | "error";
export type ThemeMode = "light" | "dark";
export type ExportFormat = "markdown" | "html";

export interface NewAnalysisInput {
  type: AnalysisType;
  title: string;
  context: string;
  engine: EngineMode;
  inputMode: InputMode;
  materialIds: string[];
  projectId?: string;
  /** 是否开启联网检索撰写（映射到后端 /api/analyze 的 web 字段） */
  web?: boolean;
  /** F2 自动取证：分析时同步多平台采集并把结果入库材料库（后端 auto_collect） */
  autoCollect?: boolean;
}

export interface ProjectSummary {
  id: string;
  name: string;
  description: string;
  type: AnalysisType;
  status: TaskStatus;
  progress: number;
  updatedAt: string;
  taskCount: number;
  reportCount: number;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  type: AnalysisType;
  status: ProjectStatus;
  progress: number;
  updatedAt: string;
}

export interface AnalysisTask {
  id: string;
  projectId: string;
  type: AnalysisType;
  title: string;
  context: string;
  engine: EngineMode;
  materialIds: string[];
  status: TaskStatus;
  phase: TaskPhase;
  progress: number;
  error?: string;
  errorPhase?: TaskErrorPhase;
  quality?: ReportQualityResult;
  createdAt: string;
  updatedAt: string;
}

export interface QualityIssue {
  code: string;
  severity: "error" | "warning";
  message: string;
  section?: string | null;
}

export interface ReportQualityResult {
  valid: boolean;
  score: number;
  issues: QualityIssue[];
}

export type ResearchConfidence = "high" | "medium" | "low" | "unknown";
export type ResearchSnapshotStatus = "verified" | "fallback" | "no_evidence" | "extraction_failed" | "stale" | "unavailable";

export interface ResearchSource {
  id: string;
  title: string;
  url: string;
  excerpt: string;
  sourceType: string;
  sourceLevel: string;
  publishedAt?: string;
  retrievedAt?: string;
  independenceGroup: string;
  materialId?: string;
  qualityTier?: "A" | "B" | "C" | "D" | "unknown";
  qualityReasons?: string[];
  canonicalUrl?: string;
  originalUrl?: string;
  contentFingerprint?: string;
  duplicateOf?: string;
}

export interface ResearchClaim {
  id: string;
  text: string;
  claimType: "fact" | "source_view" | "inference" | "user_input";
  significance: "key" | "supporting";
  confidence: ResearchConfidence;
  confidenceReasons: string[];
  evidenceIds: string[];
  counterEvidenceIds: string[];
  section: string;
  unsupported: boolean;
}

export interface ResearchRelation {
  id: string;
  sourceNode: string;
  targetNode: string;
  label: string;
  relationType: string;
  direction: string;
  polarity: string;
  confidence: ResearchConfidence;
  evidenceIds: string[];
  claimId?: string;
  status: "confirmed" | "inferred" | "conflicted";
  strength?: number;
  interestTypes?: string[];
  validFrom?: string;
  validTo?: string;
  evidenceCount?: number;
}

export interface ResearchStancePoint {
  at: string;
  stance: string;
  evidenceIds: string[];
}

export interface ResearchNode {
  id: string;
  label: string;
  aliases: string[];
  role: string;
  interests: string[];
  stance: string;
  weight: number;
  confidence: ResearchConfidence;
  evidenceIds: string[];
  firstSeen?: string;
  lastSeen?: string;
  stanceHistory: ResearchStancePoint[];
}

export interface ResearchTimelineEvent {
  id: string;
  date?: string;
  title: string;
  detail: string;
  eventType: string;
  actorIds: string[];
  claimIds: string[];
  evidenceIds: string[];
  confidence: ResearchConfidence;
  turningPoint: boolean;
}

export interface ResearchGap {
  id: string;
  question: string;
  reason: string;
  impact: string[];
  recommendedMaterials: string[];
  priority?: "critical" | "high" | "medium" | "low";
  materialType?: string;
}

export interface ResearchAnalogue {
  id: string;
  title: string;
  summary: string;
  period?: string;
  jurisdiction: string;
  domain: string;
  similarities: string[];
  differences: string[];
  response: string;
  outcome: string;
  relevanceReason: string;
  evidenceIds: string[];
  comparability: ResearchConfidence;
  confidence: ResearchConfidence;
  confidenceReasons: string[];
}

export interface ResearchCounterfactual {
  id: string;
  premise: string;
  changedCondition: string;
  baselineOutcome: string;
  alternativeOutcome: string;
  causalChain: string[];
  supportingClaimIds: string[];
  evidenceIds: string[];
  assumptions: string[];
  invalidationSignals: string[];
  confidence: ResearchConfidence;
  confidenceReasons: string[];
  status: "evidence_based" | "modelled" | "insufficient";
}

export interface QuantitativeObservation {
  id: string;
  metricName: string;
  value: number | string | null;
  unit: string;
  observedAt?: string;
  periodStart?: string;
  periodEnd?: string;
  scope: string;
  methodology: string;
  formula: string;
  evidenceIds: string[];
  status: "observed" | "derived" | "unknown" | "conflicted";
  caveats: string[];
  confidence: ResearchConfidence;
}

export interface ResearchMetrics {
  sourceCount: number;
  independentSourceGroupCount: number;
  keyClaimCount: number;
  keyClaimEvidenceCoverage: number;
  directFactCitationRate: number;
  unsupportedInferenceCount: number;
  conflictCount: number;
  gapCount: number;
  duplicateSourceCount?: number;
  highQualitySourceCount?: number;
  relationEvidenceCoverage?: number;
  temporalCompleteness?: number;
  sourceIndependenceRate?: number;
  analogueCount?: number;
  evidenceBackedAnalogueCount?: number;
  counterfactualCount?: number;
  evidenceBackedCounterfactualCount?: number;
  quantitativeObservationCount?: number;
  sourcedQuantitativeRate?: number;
  unknownQuantitativeCount?: number;
}

export interface ResearchBundle {
  schemaVersion: string;
  status: "verified" | "fallback" | "no_evidence" | "extraction_failed";
  sources: ResearchSource[];
  claims: ResearchClaim[];
  nodes?: ResearchNode[];
  relations: ResearchRelation[];
  timeline?: ResearchTimelineEvent[];
  gaps: ResearchGap[];
  analogues?: ResearchAnalogue[];
  counterfactuals?: ResearchCounterfactual[];
  quantitativeObservations?: QuantitativeObservation[];
  metrics: ResearchMetrics;
  warnings: string[];
}

export interface ResearchChangeSet {
  status: "ready" | "unavailable";
  hasChanges: boolean;
  summary: string[];
  addedNodes: Array<Record<string, unknown>>;
  removedNodes: Array<Record<string, unknown>>;
  stanceChanges: Array<{ nodeId: string; label: string; before: string; after: string }>;
  addedRelations: Array<Record<string, unknown>>;
  removedRelations: Array<Record<string, unknown>>;
  changedRelations: Array<Record<string, unknown>>;
  addedClaims: Array<Record<string, unknown>>;
  removedClaims: Array<Record<string, unknown>>;
  changedClaims: Array<Record<string, unknown>>;
  addedSources: Array<Record<string, unknown>>;
  newGaps: Array<Record<string, unknown>>;
  resolvedGaps: Array<Record<string, unknown>>;
  riskChange?: { before: string; after: string };
}

export interface ProjectMonitor {
  id?: string;
  projectId: string;
  configured: boolean;
  enabled: boolean;
  intervalHours: number;
  seedTaskId?: string;
  lastRunAt?: string;
  nextRunAt?: string;
  lastTaskId?: string;
  lastSuccessTaskId?: string;
  latestChange?: ResearchChangeSet;
  lastError?: string;
}

export interface InterestNode {
  id: string;
  label: string;
  role: string;
  interest: string;
  confidence: number;
  x: number;
  y: number;
}

export interface Report {
  id: string;
  taskId: string;
  type: AnalysisType;
  title: string;
  markdown: string;
  version: number;
  currentVersionId: string;
  updatedAt: string;
  nodes: InterestNode[];
  versions: ReportVersionSummary[];
  research?: ResearchBundle;
  researchStatus?: ResearchSnapshotStatus;
}

export interface ReportVersionSummary {
  id: string;
  version: number;
  kind: "original" | "revised" | string;
  editedBy: "ai" | "human" | string;
  summary: string;
  note: string;
  editor: string;
  createdAt: string;
  isCurrent: boolean;
  researchStatus?: ResearchSnapshotStatus;
}

export interface MaterialRecord {
  id: string;
  name: string;
  kind: MaterialKind;
  note: string;
  updatedAt: string;
  status: MaterialStatus;
}

export interface WorkspaceSettings {
  defaultEngine: EngineMode;
  theme: ThemeMode;
  defaultExport: ExportFormat;
}

export interface AppState {
  version: 2;
  projects: Project[];
  tasks: AnalysisTask[];
  reports: Report[];
  materials: MaterialRecord[];
  settings: WorkspaceSettings;
}

export const defaultSettings: WorkspaceSettings = {
  defaultEngine: "auto",
  theme: "light",
  defaultExport: "markdown",
};

export const analysisTypes: Array<{ id: AnalysisType; label: string; description: string }> = [
  { id: "case", label: "事件分析", description: "拆解事件中的主体、利益与关系变化" },
  { id: "policy", label: "政策分析", description: "理解政策目标、约束与执行结构" },
  { id: "opinion", label: "舆情分析", description: "辨识叙事、信任与传播的作用方式" },
  { id: "org", label: "组织分析", description: "审视组织角色、资源与协同边界" },
  { id: "combo", label: "组合分析", description: "事件/政策/组织/舆情交叉的复合结构" }
];

export const phaseLabels: Array<{ id: TaskPhase; label: string; note: string }> = [
  { id: "inspect", label: "检查分析目标", note: "识别输入边界与对象" },
  { id: "search", label: "补充外部线索", note: "可选的来源检索与核对" },
  { id: "decompose", label: "拆解分析结构", note: "建立主体、利益与约束" },
  { id: "network", label: "构建关系网络", note: "识别关系强度和冲突点" },
  { id: "organize", label: "整理诊断结果", note: "归纳可审阅的判断链" },
  { id: "output", label: "生成分析输出", note: "形成报告、图谱和引用" }
];
