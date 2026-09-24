// RelationGraph v3 视角切换纯逻辑（可测试，不依赖 vis-network）。
// 视角 = 选定某个主体后，与其无连线的节点淡出（连同边一起变淡），有连线的保持高亮。
import type { DiagramDocument, DiagramNode } from "./report-graph";

export interface PerspectiveOption {
  id: string; // "all" = 全景，其余为节点 id
  label: string;
}

export interface PerspectiveState {
  options: PerspectiveOption[];
  focusId: string | null;
  dimmedNodeIds: Set<string>;
}

export function perspectiveOptions(diagram: DiagramDocument): PerspectiveOption[] {
  return [
    { id: "all", label: "全景视角" },
    ...diagram.nodes.map((node: DiagramNode) => ({ id: node.id, label: node.label })),
  ];
}

export function applyPerspective(diagram: DiagramDocument, focusId: string | null): PerspectiveState {
  if (!focusId || focusId === "all" || !diagram.nodes.some((node) => node.id === focusId)) {
    return { options: perspectiveOptions(diagram), focusId: null, dimmedNodeIds: new Set() };
  }
  const connected = new Set<string>([focusId]);
  for (const edge of diagram.edges) {
    if (edge.source === focusId) connected.add(edge.target);
    if (edge.target === focusId) connected.add(edge.source);
  }
  const dimmedNodeIds = new Set(
    diagram.nodes.map((node) => node.id).filter((id) => !connected.has(id)),
  );
  return { options: perspectiveOptions(diagram), focusId, dimmedNodeIds };
}
