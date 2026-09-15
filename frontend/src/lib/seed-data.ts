import { defaultSettings, type AnalysisTask, type AnalysisType, type AppState, type InterestNode, type Report } from "./domain";

const reportNodes: Record<AnalysisType, InterestNode[]> = {
  case: [
    { id: "local", label: "沿岸社区", role: "直接承受者", interest: "生活稳定与补偿公平", confidence: 91, x: 19, y: 37 },
    { id: "port", label: "港务集团", role: "项目推动者", interest: "扩容效率与投资回报", confidence: 95, x: 51, y: 19 },
    { id: "gov", label: "地方政府", role: "协调与审批方", interest: "增长、就业与社会稳定", confidence: 88, x: 78, y: 42 },
    { id: "eco", label: "环保组织", role: "监督者", interest: "生态影响与程序透明", confidence: 84, x: 48, y: 72 },
  ],
  policy: [
    { id: "maker", label: "政策制定部门", role: "规则制定者", interest: "目标达成与制度一致性", confidence: 93, x: 50, y: 18 },
    { id: "executor", label: "基层执行部门", role: "执行者", interest: "资源匹配与执行可行性", confidence: 89, x: 22, y: 52 },
    { id: "target", label: "政策对象", role: "受影响者", interest: "成本、公平与可预期性", confidence: 86, x: 76, y: 53 },
  ],
  opinion: [
    { id: "source", label: "首发信源", role: "议题触发者", interest: "事实呈现与关注度", confidence: 82, x: 49, y: 17 },
    { id: "media", label: "传播节点", role: "叙事放大者", interest: "传播效率与可信度", confidence: 91, x: 22, y: 54 },
    { id: "public", label: "核心公众", role: "解释与反馈者", interest: "信息透明与结果公平", confidence: 87, x: 76, y: 55 },
  ],
  org: [
    { id: "decision", label: "决策层", role: "资源配置者", interest: "战略一致与风险控制", confidence: 94, x: 49, y: 18 },
    { id: "delivery", label: "执行团队", role: "任务承担者", interest: "边界清晰与资源充分", confidence: 90, x: 21, y: 55 },
    { id: "partner", label: "协作部门", role: "关键依赖方", interest: "协作成本与责任对等", confidence: 85, x: 76, y: 56 },
  ],
  combo: [
    { id: "c-event", label: "事件现场", role: "矛盾聚焦点", interest: "事实澄清与损失兜底", confidence: 88, x: 20, y: 24 },
    { id: "c-reg", label: "政策主管", role: "规则与资源调度", interest: "目标达成与制度一致性", confidence: 92, x: 52, y: 18 },
    { id: "c-org", label: "执行组织", role: "落地承担者", interest: "权责清晰与资源充分", confidence: 87, x: 80, y: 30 },
    { id: "c-public", label: "舆论公众", role: "解释与反馈者", interest: "信息透明与结果公平", confidence: 85, x: 49, y: 70 },
  ],
};

const reportCopy: Record<AnalysisType, { label: string; diagnosis: string }> = {
  case: { label: "事件", diagnosis: "当前矛盾并非单纯的支持与反对，而是收益兑现节奏、风险承担方式和协商可信度之间的错位。" },
  policy: { label: "政策", diagnosis: "主要风险来自政策目标、基层执行资源与政策对象实际成本之间的传导损耗。" },
  opinion: { label: "舆情", diagnosis: "议题升温由事实不确定、叙事竞争和信任缺口共同驱动，需要分别处理信息、情绪与回应机制。" },
  org: { label: "组织", diagnosis: "组织问题集中在权责、资源和协作依赖没有同时对齐，局部效率掩盖了系统性摩擦。" },
  combo: { label: "组合", diagnosis: "交叉议题需要同时处理事件、政策、组织与舆情之间的结构性耦合。" },
};

export function createReportDraft(task: AnalysisTask, id: string, updatedAt: string): Report {
  const copy = reportCopy[task.type];
  return {
    id,
    taskId: task.id,
    type: task.type,
    title: `${task.title}分析报告`,
    markdown: `# ${task.title}\n\n## 核心诊断\n\n${copy.diagnosis}\n\n## 结构观察\n\n- **主体**：识别拥有行动能力、承担后果或影响解释框架的关键参与者。\n- **利益**：区分公开诉求、实际约束和不可让渡的底线。\n- **关系**：检查依赖、冲突、信任与信息传递如何塑造行动空间。\n\n## 建议\n\n围绕${copy.label}的关键矛盾建立可验证的行动清单，并在每次状态变化后更新证据与判断。`,
    version: 1,
    currentVersionId: `${id}-v1`,
    updatedAt,
    nodes: reportNodes[task.type],
    versions: [{
      id: `${id}-v1`,
      version: 1,
      kind: "original",
      editedBy: "ai",
      summary: "演示报告初始版本",
      note: "",
      editor: "",
      createdAt: updatedAt,
      isCurrent: true,
    }],
  };
}

const harborTask: AnalysisTask = {
  id: "demo-harbor",
  projectId: "harbor",
  type: "case",
  title: "临港港口扩建争议",
  context: "围绕港口扩建、社区搬迁、生态影响与地方经济目标之间的结构性矛盾展开分析。",
  engine: "llm",
  materialIds: ["harbor-brief", "hearing-notes"],
  status: "generating",
  phase: "network",
  progress: 68,
  createdAt: "2026-07-18T09:20:00.000Z",
  updatedAt: "2026-07-21T08:30:00.000Z",
};

export const seedState: AppState = {
  version: 2,
  projects: [
    {
      id: "harbor",
      name: "临港港口扩建争议",
      description: "持续跟踪扩建项目中的公共利益、产业目标与社区关系。",
      type: "case",
      status: "active",
      progress: 68,
      updatedAt: "2026-07-21T08:30:00.000Z",
    },
  ],
  tasks: [harborTask],
  reports: [createReportDraft(harborTask, "harbor-report", "2026-07-21T08:30:00.000Z")],
  materials: [
    { id: "harbor-brief", name: "港口扩建项目背景简报.pdf", kind: "file", note: "项目目标、规划边界与主要时间线", updatedAt: "2026-07-20T14:10:00.000Z", status: "ready" },
    { id: "hearing-notes", name: "社区听证会纪要.docx", kind: "file", note: "社区代表、建设方与审批部门的主要陈述", updatedAt: "2026-07-21T08:12:00.000Z", status: "ready" },
  ],
  settings: defaultSettings,
};
