import type { DiagramNode } from "./report-graph";
import { provinceCenter } from "./province-centers";

export type GraphLayout = "force" | "ring" | "geo";

export interface LayoutPoint {
  x: number;
  y: number;
}

/**
 * 环形分组布局：按主体类型分区，每类一个小圆，小圆沿大圆均匀排布。
 * 目的是「按利益类型看结构」，不是精确图论布局。
 */
export function ringPositions(nodes: DiagramNode[], radius = 520): Map<string, LayoutPoint> {
  const positions = new Map<string, LayoutPoint>();
  if (!nodes.length) return positions;

  const groups: DiagramNode[] = [];
  const groupOf = new Map<string, DiagramNode[]>();
  for (const node of nodes) {
    if (!groupOf.has(node.type)) {
      groupOf.set(node.type, []);
      groups.push(node);
    }
    groupOf.get(node.type)!.push(node);
  }

  const groupCount = groups.length;
  const bigStep = (Math.PI * 2) / groupCount;
  groups.forEach((seed, index) => {
    const members = groupOf.get(seed.type)!;
    const angle = -Math.PI / 2 + index * bigStep;
    const centerX = Math.cos(angle) * radius;
    const centerY = Math.sin(angle) * radius;
    // 单节点直接落在组心；多节点绕组心小圆排布，半径随数量微增避免叠字
    const inner = members.length > 1 ? 70 + members.length * 9 : 0;
    members.forEach((node, memberIndex) => {
      if (inner === 0) {
        positions.set(node.id, { x: centerX, y: centerY });
        return;
      }
      const memberAngle = (Math.PI * 2 * memberIndex) / members.length;
      positions.set(node.id, {
        x: centerX + Math.cos(memberAngle) * inner,
        y: centerY + Math.sin(memberAngle) * inner,
      });
    });
  });
  return positions;
}

const LNG_MIN = 73;
const LNG_MAX = 136;
const LAT_MIN = 17;
const LAT_MAX = 54;
const GEO_WIDTH = 1900;
const GEO_HEIGHT = 1100;
const UNKNOWN_X = 1250;

/**
 * 地理布局：把节点放到所属省份的大致经纬位置（省级中心点，非测绘坐标）。
 * 同省多个主体绕省心散开，没有属地的主体排到右侧「未知地域」一列。
 */
export function geoPositions(nodes: DiagramNode[]): Map<string, LayoutPoint> {
  const positions = new Map<string, LayoutPoint>();
  const perProvince = new Map<string, number>();
  let unknownIndex = 0;

  for (const node of nodes) {
    const center = provinceCenter(node.regionCode);
    if (!center) {
      positions.set(node.id, { x: UNKNOWN_X, y: -420 + unknownIndex * 92 });
      unknownIndex += 1;
      continue;
    }
    const seen = perProvince.get(center.code) ?? 0;
    perProvince.set(center.code, seen + 1);
    const baseX = ((center.lng - LNG_MIN) / (LNG_MAX - LNG_MIN)) * GEO_WIDTH - GEO_WIDTH / 2;
    const baseY = ((LAT_MAX - center.lat) / (LAT_MAX - LAT_MIN)) * GEO_HEIGHT - GEO_HEIGHT / 2;
    if (seen === 0) {
      positions.set(node.id, { x: baseX, y: baseY });
      continue;
    }
    // 同省第 2 个起绕省心螺旋散开，避免完全重叠
    const angle = seen * (Math.PI / 3);
    const spread = 46 + Math.floor(seen / 6) * 26;
    positions.set(node.id, { x: baseX + Math.cos(angle) * spread, y: baseY + Math.sin(angle) * spread });
  }
  return positions;
}

export function layoutPositions(nodes: DiagramNode[], layout: GraphLayout): Map<string, LayoutPoint> | null {
  if (layout === "ring") return ringPositions(nodes);
  if (layout === "geo") return geoPositions(nodes);
  return null;
}
