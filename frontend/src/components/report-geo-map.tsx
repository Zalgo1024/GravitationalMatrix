"use client";

// F11 地域分布图（增强版）：echarts 中国图按省着色 + 南海诸岛小窗
//   + 市级下钻（点省详情 → 市级视图，底图懒加载 DataV 省 GeoJSON）
//   + 时间轴播放（按月累计播放来源地域扩散）。
// 数据来自 GET /api/reports/{id}/geo 纯派生聚合（独立源组归并）。
// 底图说明：省级底图为本地开源行政区划数据；市级底图按需从 DataV GeoAtlas
// 在线拉取并缓存。均为分析示意用途，不是自然资源部审图号标准地图。

import * as echarts from "echarts/core";
import { MapChart } from "echarts/charts";
import { TooltipComponent, VisualMapComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { ChevronLeft, ExternalLink, LoaderCircle, MapPin, Pause, Play, X } from "lucide-react";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { apiRequest } from "@/lib/api";
import { ensureChinaMap, ensureCityMap, type GeoPayload, type GeoRegion } from "@/lib/geo-map-assets";

echarts.use([MapChart, TooltipComponent, VisualMapComponent, CanvasRenderer]);

export type Metric = "independent_sources" | "sources" | "share";

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

export const GEO_METRICS: { id: Metric; label: string }[] = [
  { id: "independent_sources", label: "独立源数" },
  { id: "sources", label: "来源数" },
  { id: "share", label: "份额" },
];

export function ReportGeoMap({ taskId, versionId, metric: metricProp, onMetricChange }: { taskId: string; versionId?: string | null; metric?: Metric; onMetricChange?: (id: Metric) => void }) {
  const [payload, setPayload] = useState<GeoPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [localMetric, setLocalMetric] = useState<Metric>("independent_sources");
  const metric = metricProp ?? localMetric;
  function switchMetric(id: Metric) {
    if (onMetricChange) onMetricChange(id);
    else setLocalMetric(id);
  }
  const [selected, setSelected] = useState<string>("");
  const [drill, setDrill] = useState<{ code: string; name: string } | null>(null);
  const [drillError, setDrillError] = useState("");
  const [playIndex, setPlayIndex] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const mainRef = useRef<HTMLDivElement>(null);
  const seaRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError("");
    const versionQuery = versionId ? `?version_id=${encodeURIComponent(versionId)}` : "";
    apiRequest<GeoPayload>(`/api/reports/${encodeURIComponent(taskId)}/geo${versionQuery}`)
      .then((body) => { if (!cancelled) { setPayload(body); setSelected(""); setDrill(null); setPlayIndex(null); setPlaying(false); } })
      .catch((reason) => { if (!cancelled) setError(reason instanceof Error ? reason.message : "地域聚合读取失败。"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [taskId, versionId]);

  const metricLabel = GEO_METRICS.find((item) => item.id === metric)?.label ?? "";

  // 时间轴帧数据：截至当前月的**累计**独立源数（扩散是「点亮」过程，累计更直观）
  const timelineFrames = useMemo(() => {
    const frames = payload?.timeline ?? [];
    if (frames.length < 2) return [];
    const acc = new Map<string, { name: string; value: number }>();
    return frames.map((frame) => {
      for (const region of frame.regions) {
        const current = acc.get(region.region_code);
        acc.set(region.region_code, { name: region.region_name, value: (current?.value ?? 0) + region.independent_sources });
      }
      return [...acc.values()];
    });
  }, [payload]);

  // 播放器：每 900ms 推进一帧，到尾帧停住
  useEffect(() => {
    if (!playing || timelineFrames.length < 2) return;
    const timer = window.setInterval(() => {
      setPlayIndex((current) => {
        const next = (current ?? -1) + 1;
        if (next >= timelineFrames.length - 1) setPlaying(false);
        return Math.min(next, timelineFrames.length - 1);
      });
    }, 900);
    return () => window.clearInterval(timer);
  }, [playing, timelineFrames]);

  const drillRegion = drill ? (payload?.regions ?? []).find((region) => region.region_code === drill.code) : undefined;

  useEffect(() => {
    let disposed = false;
    let mainChart: echarts.ECharts | null = null;
    let seaChart: echarts.ECharts | null = null;

    async function render() {
      if (!payload || !mainRef.current) return;
      await ensureChinaMap();
      if (disposed) return;

      // 时间轴激活时用帧数据（累计），否则用全量数据；下钻时用市级数据
      const provinceData = playIndex !== null && timelineFrames.length
        ? timelineFrames[Math.min(playIndex, timelineFrames.length - 1)].map((entry) => ({ name: entry.name, value: entry.value }))
        : payload.regions.map((region) => ({ name: region.region_name, value: region[metric], cities: region.cities }));

      const cityData = drillRegion
        ? (drillRegion.city_groups ?? []).map((entry) => ({ name: entry.name, value: entry.groups }))
        : [];

      const maxValue = Math.max(1, ...(drill ? cityData : provinceData).map((item) => Number(item.value) || 0));
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
          const unit = drill ? "独立源组" : metricLabel;
          return `${params.name ?? "未识别"}：${params.value ?? 0}${unit}${cities}`;
        },
      };

      mainChart = echarts.init(mainRef.current);
      mainChart.on("click", (params: { name?: string }) => {
        if (drill) return; // 市级视图暂不二级下钻
        const name = params?.name;
        if (name) setSelected((current) => (current === name ? "" : name));
      });
      mainChart.setOption({
        tooltip,
        visualMap: { ...visual, orient: "vertical" },
        series: [{
          type: "map",
          map: drill ? `geo-city-${drill.code}` : "china",
          roam: false,
          zoom: drill ? 0.9 : 1.16,
          layoutCenter: ["50%", "52%"],
          layoutSize: "100%",
          label: { show: drill, fontSize: 9, color: "#40506a" },
          itemStyle: { borderColor: "#FFFFFF", borderWidth: 0.6 },
          emphasis: { label: { show: true, fontSize: 10 }, itemStyle: { areaColor: "#F5C065" } },
          data: drill ? cityData : provinceData,
        }],
      });

      // 南海诸岛小窗只在省级视图有意义；市级下钻时隐藏（容器由 CSS 控制显隐）
      if (!drill && seaRef.current) {
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
            data: provinceData,
          }],
        });
      }
    }

    void render();
    return () => {
      disposed = true;
      mainChart?.dispose();
      seaChart?.dispose();
    };
  }, [payload, metric, metricLabel, drill, drillRegion, playIndex, timelineFrames]);

  async function enterCityView(region: GeoRegion) {
    if (!region.city_groups?.length) return;
    setDrillError("");
    setPlaying(false);
    setPlayIndex(null);
    try {
      await ensureCityMap(region.region_code);
      setDrill({ code: region.region_code, name: region.region_name });
    } catch (reason) {
      setDrillError(reason instanceof Error ? `${reason.message}，已保留省级视图。` : "市级底图加载失败，已保留省级视图。");
    }
  }

  const lowCoverage = Boolean(payload && payload.coverage > 0 && payload.coverage < 0.5);
  const empty = Boolean(payload && (!payload.regions || payload.regions.length === 0));
  const topRegions = (payload?.regions ?? []).slice(0, 5);
  const selectedRegion = (payload?.regions ?? []).find((region) => region.region_name === selected);
  const hiddenItems = selectedRegion ? Math.max(0, (selectedRegion.item_total ?? 0) - (selectedRegion.items ?? []).length) : 0;
  const currentMonth = playIndex !== null && payload?.timeline?.length ? payload.timeline[Math.min(playIndex, payload.timeline.length - 1)].month : "";

  return <section className="report-geo" id="geo-map" aria-label="地域分布图">
    <header className="report-geo__bar">
      <div className="report-geo__tabs" role="tablist" aria-label="地域指标切换">
        {GEO_METRICS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={metric === item.id}
            className={metric === item.id ? "data-tab data-tab--active" : "data-tab"}
            onClick={() => switchMetric(item.id)}
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
            {drill && <div className="report-geo__crumb">
              <button type="button" onClick={() => { setDrill(null); setDrillError(""); }}><ChevronLeft size={13} />返回全国</button>
              <span>全国 › {drill.name}（市级视图 · 独立源组计数）</span>
            </div>}
            {drillError && <p className="report-geo__warning" role="alert"><MapPin size={13} /> {drillError}</p>}
            <div className="report-geo__canvas">
              <div ref={mainRef} className="report-geo__main" />
              <div className={drill ? "report-geo__sea report-geo__sea--hidden" : "report-geo__sea"}>
                <div ref={seaRef} className="report-geo__sea-canvas" aria-label="南海诸岛" />
                <span className="report-geo__sea-title">南海诸岛</span>
              </div>
            </div>
            {drill
              ? <p className="report-geo__note">市级视图按「独立源组」计数着色（同组转载只算 1）；市级底图按需加载自开源数据服务，返回全国可切回省级。</p>
              : <p className="report-geo__note">点击省份查看该省来源条目（同组转载已去重）。示意图：按省级聚合的来源地域分布；底图为开源行政区划数据，非审图号标准地图，正式出版请使用自然资源部标准地图。</p>}
            {timelineFrames.length >= 2 && !drill && <div className="report-geo__timeline" role="group" aria-label="时间轴播放">
              <button type="button" aria-label={playing ? "暂停播放" : "播放地域扩散"}
                className="report-geo__timeline-play"
                onClick={() => {
                  if (playIndex === null || playIndex >= timelineFrames.length - 1) setPlayIndex(0);
                  setPlaying((current) => !current);
                }}>
                {playing ? <Pause size={13} /> : <Play size={13} />}{playing ? "暂停" : "播放扩散"}
              </button>
              <input
                type="range"
                min={0}
                max={timelineFrames.length - 1}
                step={1}
                value={playIndex ?? timelineFrames.length - 1}
                aria-label="时间轴月份"
                onChange={(event) => { setPlaying(false); setPlayIndex(Number(event.target.value)); }}
              />
              <span className="report-geo__timeline-month">{currentMonth || "全部"}</span>
              {(playIndex !== null) && <button type="button" className="report-geo__timeline-reset" onClick={() => { setPlaying(false); setPlayIndex(null); }}>看全量</button>}
            </div>}
            {!drill && topRegions.length > 0 && <ul className="report-geo__top" aria-label="省份排行">
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
                <div className="report-geo__detail-actions">
                  {selectedRegion.city_groups?.length ? (
                    <button type="button" className="report-geo__drill-btn" onClick={() => void enterCityView(selectedRegion)}><MapPin size={12} />市级视图</button>
                  ) : null}
                  <button type="button" aria-label="关闭省份详情" onClick={() => setSelected("")}><X size={15} /></button>
                </div>
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
