// F11 画报共用：/geo 载荷类型 + echarts 底图资源加载。
// 省级底图本地（/geo/china.json）；市级底图按需从 DataV GeoAtlas 拉取并按省缓存
// （用户已拍板放行 DataV 第三方边界，仅分析示意用途，不是审图号标准地图）。

import * as echarts from "echarts/core";

export interface GeoItem {
  id: string;
  title: string;
  url: string;
  published_at: string;
  source_type: string;
  city: string;
  spread?: string;
  province?: string;
}
export interface GeoCityGroup {
  name: string;
  groups: number;
}
export interface GeoRegion {
  region_code: string;
  region_name: string;
  independent_sources: number;
  sources: number;
  share: number;
  cities: string[];
  city_groups?: GeoCityGroup[];
  items?: GeoItem[];
  item_total?: number;
}
export interface GeoTimelineRegion {
  region_code: string;
  region_name: string;
  independent_sources: number;
}
export interface GeoTimelineFrame {
  month: string;
  regions: GeoTimelineRegion[];
}
export interface GeoClassification {
  overall: "regional" | "national" | "online";
  label: string;
  province_count: number;
  independent_total: number;
  located_total: number;
  online_total: number;
  online_share: number;
  city_count?: number;
}
export interface GeoPayload {
  task_id?: string;
  regions: GeoRegion[];
  coverage: number;
  polarity: { length: number }[] | unknown[];
  timeline?: GeoTimelineFrame[];
  classification?: GeoClassification;
  online_items?: GeoItem[];
  research_status: string;
  version_no?: number;
}

let mapRegistered: Promise<void> | null = null;
export function ensureChinaMap(): Promise<void> {
  if (!mapRegistered) {
    mapRegistered = fetch("/geo/china.json")
      .then((resp) => resp.json())
      .then((json) => {
        echarts.registerMap("china", json as Parameters<typeof echarts.registerMap>[1]);
      });
  }
  return mapRegistered;
}

// 市级底图按需拉取并按省缓存；失败抛错由调用方降级回省级视图
const cityMapCache = new Set<string>();
export async function ensureCityMap(code: string): Promise<void> {
  if (cityMapCache.has(code)) return;
  const resp = await fetch(`https://geo.datav.aliyun.com/areas_v3/bound/${code}_full.json`);
  if (!resp.ok) throw new Error(`市级底图加载失败（HTTP ${resp.status}）`);
  const json = await resp.json();
  echarts.registerMap(`geo-city-${code}`, json as Parameters<typeof echarts.registerMap>[1]);
  cityMapCache.add(code);
}
