"use client";

import React, { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import { DataSet, Network, type Edge, type Node, type Options } from "vis-network/standalone";
import type { DiagramDocument } from "@/lib/report-graph";
import { layoutPositions, type GraphLayout } from "@/lib/graph-layout";
import { provinceBadge } from "@/lib/province-centers";

export type GraphSelection =
  | { kind: "node"; id: string }
  | { kind: "edge"; id: string }
  | null;

export interface GraphCanvasHandle {
  fit: () => void;
  zoomIn: () => void;
  zoomOut: () => void;
  focusNode: (id: string) => void;
}

interface GraphCanvasProps {
  diagram: DiagramDocument;
  layout?: GraphLayout;
  /** 被筛选器排除的节点（连同其边一起隐藏） */
  hiddenNodeIds?: ReadonlySet<string>;
  /** 未命中搜索/筛选的节点：保留但淡出，避免「图突然变空」的错愕 */
  dimmedNodeIds?: ReadonlySet<string>;
  focusEdgeId?: string | null;
  onSelectionChange: (selection: GraphSelection) => void;
  onError?: (error: Error) => void;
}

const nodeColors: Record<string, { background: string; border: string }> = {
  material: { background: "#e8f0ff", border: "#3769ad" },
  security: { background: "#e7f7f0", border: "#258764" },
  political: { background: "#eeeafe", border: "#6852aa" },
  identity_culture: { background: "#fff2dd", border: "#a66a1f" },
  institutional_future: { background: "#e8f4f7", border: "#2f7c8c" },
  public: { background: "#f5edf7", border: "#8a598f" },
  legal: { background: "#f1f3f6", border: "#596879" },
  event: { background: "#fff0ee", border: "#b34f43" },
  actor: { background: "#f1f4f8", border: "#65758a" },
};

const nodeShapes: Record<string, Node["shape"]> = {
  material: "box",
  security: "ellipse",
  political: "diamond",
  identity_culture: "ellipse",
  institutional_future: "database",
  public: "box",
  legal: "database",
  event: "diamond",
  actor: "box",
};

const edgeColors: Record<string, string> = {
  economic: "#3470b8",
  power: "#7358a6",
  cultural: "#a06d24",
  legal: "#637181",
  unknown: "#7b8490",
};

const edgeDashes: Record<string, false | number[]> = {
  economic: false,
  power: [11, 4],
  cultural: [3, 4],
  legal: [7, 5],
  unknown: [2, 6],
};

export function buildGraphOptions(diagram: DiagramDocument, layout: GraphLayout = "force"): Options {
  const hierarchical = diagram.viz === "org"
    ? { enabled: true, direction: "UD" as const, sortMethod: "directed" as const, levelSeparation: 120, nodeSpacing: 145, treeSpacing: 190 }
    : diagram.viz === "flow"
      ? { enabled: true, direction: "LR" as const, sortMethod: "directed" as const, levelSeparation: 165, nodeSpacing: 120, treeSpacing: 170 }
      : false;

  return {
    autoResize: true,
    interaction: { hover: true, navigationButtons: false, keyboard: { enabled: true }, multiselect: false },
    layout: hierarchical ? { hierarchical } : { improvedLayout: layout === "force" },
    // 环形/地理布局用预计算坐标，物理引擎必须关掉，否则节点会漂走
    physics: diagram.viz === "network" && layout === "force"
      ? { enabled: true, stabilization: { enabled: true, iterations: 280, updateInterval: 30 }, barnesHut: { gravitationalConstant: -5200, springLength: 155, springConstant: 0.035 } }
      : { enabled: false },
    nodes: {
      shape: "box",
      margin: { top: 11, right: 14, bottom: 11, left: 14 },
      widthConstraint: { minimum: 90, maximum: 205 },
      borderWidth: 1,
      borderWidthSelected: 2,
      font: { face: "Inter, PingFang SC, Microsoft YaHei, sans-serif", size: 13, color: "#1d2b3c", multi: false },
      shadow: { enabled: true, color: "rgba(30, 50, 74, 0.10)", size: 12, x: 0, y: 4 },
      shapeProperties: { borderRadius: 5 },
    },
    edges: {
      arrows: { to: { enabled: true, scaleFactor: 0.58 } },
      width: 1.3,
      smooth: diagram.viz === "network" ? { enabled: true, type: "dynamic", roundness: 0.25 } : { enabled: true, type: "cubicBezier", roundness: 0.35 },
      font: { face: "Inter, PingFang SC, Microsoft YaHei, sans-serif", size: 10, color: "#526276", align: "middle", background: "rgba(251,252,254,0.88)", strokeWidth: 0 },
      color: { color: "#6a7889", highlight: "#245f9e", hover: "#245f9e", opacity: 0.86 },
      selectionWidth: 2.2,
    },
  };
}

function escapeTooltipText(value: unknown): string {
  // vis-network 的 tooltip (title) 以 innerHTML 渲染，必须转义，防注入
  return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export interface GraphEncodingOptions {
  layout?: GraphLayout;
  hiddenNodeIds?: ReadonlySet<string>;
  dimmedNodeIds?: ReadonlySet<string>;
  focusEdgeId?: string | null;
}

const DIM_OPACITY = 0.18;

export function buildGraphData(diagram: DiagramDocument, options: GraphEncodingOptions = {}): { nodes: Node[]; edges: Edge[] } {
  const { layout = "force", hiddenNodeIds, dimmedNodeIds, focusEdgeId } = options;
  const positions = layoutPositions(diagram.nodes, layout);
  const maxEvidence = Math.max(1, ...diagram.nodes.map((node) => node.evidenceCount ?? 0));

  const nodes: Node[] = diagram.nodes
    .filter((node) => !hiddenNodeIds?.has(node.id))
    .map((node) => {
      const color = nodeColors[node.type] ?? nodeColors.actor;
      const weight = Math.max(0, Math.min(1, node.weight ?? 0.5));
      const evidence = node.evidenceCount ?? 0;
      // 节点大小 = 证据数（无证据数字段时退回权重，老报告不塌缩成一个点）
      const size = evidence > 0 ? 12 + (evidence / maxEvidence) * 26 : Math.round(10 + weight * 20);
      const badge = provinceBadge(node.regionName);
      const label = badge ? `${node.label} · ${badge}` : node.label;
      const regionLine = node.regionName ? `\n属地：${escapeTooltipText(node.regionName)}` : "";
      const dimmed = Boolean(dimmedNodeIds?.has(node.id));
      const point = positions?.get(node.id);
      return {
        id: node.id,
        label,
        value: size,
        mass: 1 + weight * 2,
        title: `${escapeTooltipText(node.label)}\n类型：${escapeTooltipText(node.type)}\n权重：${Math.round(weight * 100)}%\n证据：${evidence} 条${regionLine}`,
        shape: nodeShapes[node.type] ?? "box",
        ...(point ? { x: point.x, y: point.y, fixed: false } : {}),
        color: {
          ...color,
          ...(dimmed ? { opacity: DIM_OPACITY } : {}),
          highlight: { background: "#ffffff", border: color.border },
          hover: { background: "#ffffff", border: color.border },
        },
        font: dimmed ? { color: "rgba(29, 43, 60, 0.35)" } : undefined,
      } as Node;
    });

  const visibleIds = new Set(nodes.map((node) => String(node.id)));
  const edges: Edge[] = diagram.edges
    .filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target))
    .map((edge) => {
      const strength = Math.max(1, Math.min(5, edge.strength ?? 1));
      const baseColor = edge.polarity === "negative" ? "#b34f43" : edge.polarity === "positive" ? "#258764" : edgeColors[edge.type] ?? edgeColors.unknown;
      const arrows = edge.direction === "undirected"
        ? { from: { enabled: false }, to: { enabled: false } }
        : edge.direction === "mutual"
          ? { from: { enabled: true }, to: { enabled: true } }
          : { from: { enabled: false }, to: { enabled: true } };
      const focused = focusEdgeId === edge.id;
      const crossLine = edge.crossRegion ? "\n跨省关系" : "";
      return {
        id: edge.id,
        from: edge.source,
        to: edge.target,
        label: edge.label,
        // 边宽 = 强度；跨省边额外加粗一点以便与省内边区分
        width: 1 + strength * 0.65 + (edge.crossRegion ? 0.8 : 0),
        arrows,
        title: `${escapeTooltipText(edge.label)}\n类型：${escapeTooltipText(edge.type)}\n强度：${strength}/5\n状态：${escapeTooltipText(edge.relationStatus ?? "未知")}${crossLine}`,
        color: {
          color: baseColor,
          highlight: baseColor,
          hover: baseColor,
          opacity: focused ? 1 : dimmedNodeIds?.size ? 0.28 : 0.86,
        },
        // 跨省统一用长虚线；推测关系沿用短虚线（两者叠加时以跨省为准）
        dashes: edge.crossRegion ? [14, 6] : edge.relationStatus === "inferred" ? [7, 5] : edgeDashes[edge.type] ?? edgeDashes.unknown,
      };
    });
  return { nodes, edges };
}

function graphData(diagram: DiagramDocument, options: GraphEncodingOptions) {
  const data = buildGraphData(diagram, options);
  return { nodes: new DataSet<Node>(data.nodes), edges: new DataSet<Edge>(data.edges) };
}

export const GraphCanvas = forwardRef<GraphCanvasHandle, GraphCanvasProps>(function GraphCanvas({ diagram, layout = "force", hiddenNodeIds, dimmedNodeIds, focusEdgeId, onSelectionChange, onError }, ref) {
  const containerRef = useRef<HTMLDivElement>(null);
  const networkRef = useRef<Network | null>(null);

  useImperativeHandle(ref, () => ({
    fit() {
      networkRef.current?.fit({ animation: { duration: 220, easingFunction: "easeOutCubic" } });
    },
    zoomIn() {
      const network = networkRef.current;
      if (!network) return;
      network.moveTo({ scale: Math.min(2.4, network.getScale() * 1.2), animation: { duration: 180, easingFunction: "easeOutCubic" } });
    },
    zoomOut() {
      const network = networkRef.current;
      if (!network) return;
      network.moveTo({ scale: Math.max(0.28, network.getScale() / 1.2), animation: { duration: 180, easingFunction: "easeOutCubic" } });
    },
    focusNode(id: string) {
      networkRef.current?.selectNodes([id]);
      networkRef.current?.focus(id, { scale: 1.2, animation: { duration: 240, easingFunction: "easeOutCubic" } });
    },
  }), []);

  useEffect(() => {
    if (!containerRef.current) return;
    let network: Network;
    try {
      network = new Network(containerRef.current, graphData(diagram, { layout, hiddenNodeIds, dimmedNodeIds, focusEdgeId }), buildGraphOptions(diagram, layout));
    } catch (error) {
      onError?.(error instanceof Error ? error : new Error("关系图运行时初始化失败"));
      return;
    }
    networkRef.current = network;
    if (focusEdgeId) {
      try {
        network.selectEdges([focusEdgeId]);
      } catch {
        // 边因筛选被隐藏时忽略，不打断渲染
      }
    }
    network.on("selectNode", (event) => onSelectionChange(event.nodes?.[0] ? { kind: "node", id: String(event.nodes[0]) } : null));
    network.on("selectEdge", (event) => {
      if (!event.nodes?.length && event.edges?.[0]) onSelectionChange({ kind: "edge", id: String(event.edges[0]) });
    });
    network.on("deselectNode", () => onSelectionChange(null));
    network.on("deselectEdge", () => onSelectionChange(null));
    return () => {
      network.destroy();
      networkRef.current = null;
    };
  }, [diagram, layout, hiddenNodeIds, dimmedNodeIds, focusEdgeId, onError, onSelectionChange]);

  return <div ref={containerRef} className="graph-canvas" role="img" aria-label={diagram.title} tabIndex={0} />;
});
