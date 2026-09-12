"use client";

// F11 地域分布图（初版）：echarts 内置中国图按省着色 + 南海诸岛小窗。
// 数据来自 GET /api/reports/{id}/geo 纯派生聚合（独立源组归并）。
// 底图说明：本图使用开源行政区划数据（与 echarts 生态一致的省级边界），
// 为分析示意用途，不是自然资源部审图号标准地图；对外正式出版请用标准地图。

import * as echarts from "echarts/core";
import { MapChart } from "echarts/charts";
import { TooltipComponent, VisualMapComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { ExternalLink, LoaderCircle, MapPin, X } from "lucide-react";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { apiRequest } from "@/lib/api";

echarts.use([MapChart, TooltipComponent, VisualMapComponent, CanvasRenderer]);

interface GeoItem {
  id: string;
  title: string;
  url: string;
  published_at: string;
  source_type: string;
  city: string;
}
interface GeoRegion {
  region_code: string;
  region_name: string;
  independent_sources: number;
  sources: number;
  share: number;
  cities: string[];
  items?: GeoItem[];
  item_total?: number;
}
interface GeoPayload {
  regions: GeoRegion[];
  coverage: number;
  polarity: { length: number }[] | unknown[];
  research_status: string;
  version_no?: number;
}

type Metric = "independent_sources" | "sources" | "share";

const sourceTypeLabels: Record<string, string> = {
  official: "官方发布",
  company: "企业披露",
  mainstream_media: "主流媒体",
  self_media: "自媒体",
  forum: "论坛",
  social_media: "社交媒体",
  user_material: "用户提供",
  unknown: "来源未分类",
};

const METRICS: { id: Metric; label: string }[] = [
  { id: "independent_sources", label: "独立源数" },
  { id: "sources", label: "来源数" },
  { id: "share", label: "份额" },
];

let mapRegistered: Promise<void> | null = null;
function ensureChinaMap(): Promise<void> {
  if (!mapRegistered) {
    mapRegistered = fetch("/geo/china.json")
      .then((resp) => resp.json())
      .then((json) => {
        echarts.registerMap("china", json as Parameters<typeof echarts.registerMap>[1]);
      });
  }
  return mapRegistered;
}

export function ReportGeoMap({ taskId, versionId }: { taskId: string; versionId?: string | null }) {
  const [payload, setPayload] = useState<GeoPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [metric, setMetric] = useState<Metric>("independent_sources");
  const [selected, setSelected] = useState<string>("");
  const mainRef = useRef<HTMLDivElement>(null);
  const seaRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError("");
    const versionQuery = versionId ? `?version_id=${encodeURIComponent(versionId)}` : "";
    apiRequest<GeoPayload>(`/api/reports/${encodeURIComponent(taskId)}/geo${versionQuery}`)
      .then((body) => { if (!cancelled) { setPayload(body); setSelected(""); } })
      .catch((reason) => { if (!cancelled) setError(reason instanceof Error ? reason.message : "地域聚合读取失败。"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [taskId, versionId]);

  const metricLabel = METRICS.find((item) => item.id === metric)?.label ?? "";

  useEffect(() => {
    let disposed = false;
    let mainChart: echarts.ECharts | null = null;
    let seaChart: echarts.ECharts | null = null;

    async function render() {
      if (!payload || !mainRef.current || !seaRef.current) return;
      await ensureChinaMap();
      if (disposed) return;

      const data = payload.regions.map((region) => ({
        name: region.region_name,
        value: region[metric],
        cities: region.cities,
      }));
      const maxValue = Math.max(1, ...data.map((item) => Number(item.value) || 0));
      const visual = {
        min: 0,
        max: maxValue,
        left: 8,
        bottom: 8,
        calculable: false,
        text: ["高", "低"],
        inRange: { color: ["#E8F0FB", "#8FB6E8", "#2E5FA3"] },
        textStyle: { fontSize: 10, color: "#5A6B80" },
      };
      const tooltip = {
        trigger: "item" as const,
        formatter: (params: { name?: string; value?: number | string; data?: { cities?: string[] } }) => {
          const cities = params.data?.cities?.length ? `（${params.data.cities.slice(0, 6).join("、")}）` : "";
          return `${params.name ?? "未识别"}：${params.value ?? 0}${metricLabel}${cities}`;
        },
      };

      mainChart = echarts.init(mainRef.current);
      mainChart.on("click", (params: { name?: string }) => {
        const name = params?.name;
        if (name) setSelected((current) => (current === name ? "" : name));
      });
      mainChart.setOption({
        tooltip,
        visualMap: { ...visual, orient: "vertical" },
        series: [{
          type: "map",
          map: "china",
          roam: false,
          zoom: 1.16,
          // 主体裁剪：把南海诸岛留给小窗（主图不含九段线以南区域）
          layoutCenter: ["50%", "52%"],
          layoutSize: "100%",
          label: { show: false },
          itemStyle: { borderColor: "#FFFFFF", borderWidth: 0.6 },
          emphasis: { label: { show: true, fontSize: 10 }, itemStyle: { areaColor: "#F5C065" } },
          data,
        }],
      });

      // 南海诸岛小窗：同一份地图数据，视口定位到南海区域
      seaChart = echarts.init(seaRef.current);
      seaChart.setOption({
        series: [{
          type: "map",
          map: "china",
          roam: false,
          center: [112.5, 12.5],
          zoom: 2.4,
          label: { show: false },
          itemStyle: { borderColor: "#FFFFFF", borderWidth: 0.6 },
          emphasis: { label: { show: false } },
          data,
        }],
      });
    }

    void render();
    return () => {
      disposed = true;
      mainChart?.dispose();
      seaChart?.dispose();
    };
  }, [payload, metric, metricLabel]);

  const lowCoverage = Boolean(payload && payload.coverage > 0 && payload.coverage < 0.5);
  const empty = Boolean(payload && (!payload.regions || payload.regions.length === 0));
  const topRegions = (payload?.regions ?? []).slice(0, 5);
  const selectedRegion = (payload?.regions ?? []).find((region) => region.region_name === selected);
  const hiddenItems = selectedRegion ? Math.max(0, (selectedRegion.item_total ?? 0) - (selectedRegion.items ?? []).length) : 0;

  return <section className="report-geo" aria-label="地域分布图">
    <header className="report-geo__bar">
      <div className="report-geo__tabs" role="tablist" aria-label="地域指标切换">
        {METRICS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={metric === item.id}
            className={metric === item.id ? "data-tab data-tab--active" : "data-tab"}
            onClick={() => setMetric(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {payload && <span className="report-geo__coverage">地域覆盖 {Math.round(payload.coverage * 100)}%</span>}
    </header>
    {loading && <div className="report-version-loading" aria-busy="true"><LoaderCircle size={16} className="spin" /> 正在聚合地域数据...</div>}
    {error && <p className="delivery-error" role="alert">{error}</p>}
    {!loading && !error && payload && (
      empty
        ? <p className="section-empty">该版本还没有可定位的地域数据（研究账本不可用或来源均未识别到地区）。可先「补充信息与证据」重建研究账本。</p>
        : <div className="report-geo__stage">
            {lowCoverage && <p className="report-geo__warning" role="status"><MapPin size={13} /> 识别到地区的独立来源不足 {Math.round(payload!.coverage * 100)}%，下图仅反映可定位部分。</p>}
            <div className="report-geo__canvas">
              <div ref={mainRef} className="report-geo__main" />
              <div className="report-geo__sea">
                <div ref={seaRef} className="report-geo__sea-canvas" aria-label="南海诸岛" />
                <span className="report-geo__sea-title">南海诸岛</span>
              </div>
            </div>
            <p className="report-geo__note">点击省份查看该省来源条目（同组转载已去重）。示意图：按省级聚合的来源地域分布（市级明细见数据表「地域」列）；底图为开源行政区划数据，非审图号标准地图，正式出版请使用自然资源部标准地图。</p>
            {topRegions.length > 0 && <ul className="report-geo__top" aria-label="省份排行">
              {topRegions.map((region) => (
                <li key={region.region_code}>
                  <button type="button" aria-pressed={selected === region.region_name} onClick={() => setSelected((current) => (current === region.region_name ? "" : region.region_name))}>
                    <span className="report-geo__top-name">{region.region_name}</span>
                    <span className="report-geo__top-bar"><i style={{ width: `${Math.max(4, Math.round(region.share * 100))}%` }} /></span>
                    <span className="report-geo__top-value">{region.independent_sources} 源 · {Math.round(region.share * 100)}%</span>
                  </button>
                </li>
              ))}
            </ul>}
            {selectedRegion && <div className="report-geo__detail" role="region" aria-label={`${selectedRegion.region_name}来源条目`}>
              <header>
                <div>
                  <strong>{selectedRegion.region_name}</strong>
                  <span>{selectedRegion.independent_sources} 个独立源 · {selectedRegion.sources} 条来源 · 份额 {Math.round(selectedRegion.share * 100)}%{selectedRegion.cities.length ? ` · 涉及 ${selectedRegion.cities.slice(0, 6).join("、")}${selectedRegion.cities.length > 6 ? " 等" : ""}` : ""}</span>
                </div>
                <button type="button" aria-label="关闭省份详情" onClick={() => setSelected("")}><X size={15} /></button>
              </header>
              {(selectedRegion.items ?? []).length ? <ul className="report-geo__items">
                {(selectedRegion.items ?? []).map((item) => (
                  <li key={item.id || item.title}>
                    {item.url ? <a href={item.url} target="_blank" rel="noreferrer"><ExternalLink size={12} /><span><strong>{item.title}</strong><small>{[item.published_at || "时间未知", sourceTypeLabels[item.source_type] ?? item.source_type, item.city].filter(Boolean).join(" · ")}</small></span></a>
                      : <div><span><strong>{item.title}</strong><small>{[item.published_at || "时间未知", sourceTypeLabels[item.source_type] ?? item.source_type, item.city].filter(Boolean).join(" · ")}</small></span></div>}
                  </li>
                ))}
              </ul> : <p className="report-geo__detail-empty">该省没有可展示的代表条目。</p>}
              {hiddenItems > 0 && <p className="report-geo__detail-more">另有 {hiddenItems} 条来源未列出（已按同组转载去重，完整清单见数据表）。</p>}
            </div>}
          </div>
    )}
  </section>;
}
