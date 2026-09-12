import type { DiagramDocument, DiagramEdge, DiagramNode } from "./report-graph";

export interface GraphFilterState {
  /** 利益类型（空 = 不过滤） */
  interestTypes: string[];
  /** 属地省码（空 = 不过滤） */
  regionCodes: string[];
  /** 关系强度阈值 1–5 */
  minStrength: number;
  /** 关系状态（空 = 不过滤） */
  statuses: string[];
}

export const EMPTY_FILTERS: GraphFilterState = {
  interestTypes: [],
  regionCodes: [],
  minStrength: 1,
  statuses: [],
};

export function isFilterActive(state: GraphFilterState): boolean {
  return Boolean(
    state.interestTypes.length
    || state.regionCodes.length
    || state.minStrength > 1
    || state.statuses.length,
  );
}

function keepEdge(edge: DiagramEdge, state: GraphFilterState): boolean {
  const strength = Math.max(1, Math.min(5, edge.strength ?? 1));
  if (strength < state.minStrength) return false;
  if (state.statuses.length && !state.statuses.includes(edge.relationStatus ?? "inferred")) return false;
  if (state.interestTypes.length) {
    const types = edge.interestTypes ?? [];
    if (!types.some((item) => state.interestTypes.includes(item))) return false;
  }
  return true;
}

/**
 * 按筛选条件裁剪图谱。
 *
 * 规则：属地筛选直接裁节点；边条件（利益类型/强度/状态）只裁边，
 * 连带裁掉因此变得孤立的节点——这正是「从一团乱麻变成几条清晰的利益链」的
 * 效果。没有任何边条件时保留孤立节点，避免一开页就少掉一片主体。
 */
export function applyGraphFilters(diagram: DiagramDocument, state: GraphFilterState): DiagramDocument {
  const regionFilter = new Set(state.regionCodes);
  let nodes: DiagramNode[] = diagram.nodes;
  if (regionFilter.size) {
    nodes = nodes.filter((node) => Boolean(node.regionCode) && regionFilter.has(node.regionCode!));
  }
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edgeConditions = Boolean(state.interestTypes.length || state.statuses.length || state.minStrength > 1);
  const edges = diagram.edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target) && keepEdge(edge, state));

  if (edgeConditions) {
    const linked = new Set<string>();
    for (const edge of edges) {
      linked.add(edge.source);
      linked.add(edge.target);
    }
    nodes = nodes.filter((node) => linked.has(node.id));
  }
  return { ...diagram, nodes, edges };
}

/** 搜索命中的节点保留原样，其余淡出（不隐藏，避免「图突然空了」的错愕）。 */
export function computeDimmedIds(diagram: DiagramDocument, query: string): Set<string> {
  const keyword = query.trim().toLocaleLowerCase("zh-CN");
  if (!keyword) return new Set();
  const matched = new Set(
    diagram.nodes
      .filter((node) => node.label.toLocaleLowerCase("zh-CN").includes(keyword))
      .map((node) => node.id),
  );
  return new Set(diagram.nodes.filter((node) => !matched.has(node.id)).map((node) => node.id));
}

export function collectRegionOptions(nodes: DiagramNode[]): { code: string; name: string; count: number }[] {
  const buckets = new Map<string, { code: string; name: string; count: number }>();
  for (const node of nodes) {
    if (!node.regionCode) continue;
    const name = node.regionName || node.regionCode;
    const bucket = buckets.get(node.regionCode);
    if (bucket) bucket.count += 1;
    else buckets.set(node.regionCode, { code: node.regionCode, name, count: 1 });
  }
  return [...buckets.values()].sort((a, b) => b.count - a.count || a.code.localeCompare(b.code));
}

export function collectInterestOptions(edges: DiagramEdge[]): { id: string; count: number }[] {
  const buckets = new Map<string, number>();
  for (const edge of edges) {
    for (const type of edge.interestTypes ?? []) {
      buckets.set(type, (buckets.get(type) ?? 0) + 1);
    }
  }
  return [...buckets.entries()].map(([id, count]) => ({ id, count })).sort((a, b) => b.count - a.count);
}
