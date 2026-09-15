"use client";

// 地域画报（F-poster）：报告的独立海报页——大字标题 + 三性判定 + 数字卡 +
// 市级/省级地图 + 来源清单两栏。排版走画报风（.poster 前缀），不复用报告
// 阅读页样式。三性判定与全部数字来自 /geo 纯派生聚合，零 LLM。
// 地图策略：地区性 → 默认下钻主导省的市级视图（失败降级省级）；
// 全国性 / 纯网络 → 省级着色全国图。

import * as echarts from "echarts/core";
import { MapChart } from "echarts/charts";
import { TooltipComponent, VisualMapComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { ArrowUpRight, Globe2, LoaderCircle, MapPin } from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import { apiRequest } from "@/lib/api";
import { ensureChinaMap, ensureCityMap, type GeoPayload } from "@/lib/geo-map-assets";

echarts.use([MapChart, TooltipComponent, VisualMapComponent, CanvasRenderer]);

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

const overallLabels: Record<string, string> = {
  regional: "地区性舆情",
  national: "全国性舆情",
  online: "纯网络传播",
};

export function PosterGeo({ taskId }: { taskId: string }) {
  const [payload, setPayload] = useState<GeoPayload | null>(null);
  const [title, setTitle] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [cityMode, setCityMode] = useState<{ code: string; name: string } | null>(null);
  const [cityError, setCityError] = useState("");
  const mainRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    Promise.all([
      apiRequest<GeoPayload>(`/api/reports/${encodeURIComponent(taskId)}/geo`),
      apiRequest<{ title?: string }>(`/api/reports/${encodeURIComponent(taskId)}`).catch(() => ({ title: "" })),
    ])
      .then(([geo, meta]) => {
        if (cancelled) return;
        setPayload(geo);
        setTitle(meta?.title ?? "");
      })
      .catch((reason) => { if (!cancelled) setError(reason instanceof Error ? reason.message : "画报数据读取失败。"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [taskId]);

  const classification = payload?.classification;
  const leadRegion = payload?.regions?.[0];

  // 地区性舆情默认下钻主导省市级视图
  useEffect(() => {
    if (!classification || !leadRegion) return;
    if (classification.overall !== "regional" || !leadRegion.city_groups?.length) {
      setCityMode(null);
      return;
    }
    let cancelled = false;
    setCityError("");
    ensureCityMap(leadRegion.region_code)
      .then(() => { if (!cancelled) setCityMode({ code: leadRegion.region_code, name: leadRegion.region_name }); })
      .catch(() => { if (!cancelled) setCityMode(null); });
    return () => { cancelled = true; };
  }, [classification, leadRegion]);

  useEffect(() => {
    let disposed = false;
    let chart: echarts.ECharts | null = null;
    async function render() {
      if (!payload || !mainRef.current) return;
      await ensureChinaMap();
      if (disposed) return;
      const useCity = Boolean(cityMode);
      const data = useCity
        ? (payload.regions.find((region) => region.region_code === cityMode!.code)?.city_groups ?? []).map((entry) => ({ name: entry.name, value: entry.groups }))
        : payload.regions.map((region) => ({ name: region.region_name, value: region.independent_sources }));
      chart = echarts.init(mainRef.current);
      chart.setOption({
        tooltip: {
          trigger: "item" as const,
          formatter: (params: { name?: string; value?: number | string }) => `${params.name ?? "未识别"}：${params.value ?? 0}${useCity ? " 个独立源组" : " 个独立源"}`,
        },
        visualMap: {
          min: 0,
          max: Math.max(1, ...data.map((item) => Number(item.value) || 0)),
          left: 10,
          bottom: 10,
          calculable: false,
          text: ["高", "低"],
          inRange: { color: ["#EDF2FA", "#9DBCE8", "#2E5FA3"] },
          textStyle: { fontSize: 11, color: "#5A6B80" },
        },
        series: [{
          type: "map",
          map: useCity ? `geo-city-${cityMode!.code}` : "china",
          roam: false,
          zoom: useCity ? 0.9 : 1.16,
          layoutCenter: ["50%", "52%"],
          layoutSize: "100%",
          label: { show: useCity, fontSize: 9, color: "#40506a" },
          itemStyle: { borderColor: "#FFFFFF", borderWidth: 0.6 },
          emphasis: { label: { show: true, fontSize: 10 }, itemStyle: { areaColor: "#F5C065" } },
          data,
        }],
      });
    }
    void render();
    return () => { disposed = true; chart?.dispose(); };
  }, [payload, cityMode]);

  if (loading) return <div className="poster__loading" aria-busy="true"><LoaderCircle size={18} className="spin" /> 正在生成画报...</div>;
  if (error) return <p className="poster__error" role="alert">{error}</p>;
  if (!payload || !payload.regions?.length) return <p className="poster__error">该版本还没有可定位的地域数据，无法生成画报。可先「补充信息与证据」重建研究账本。</p>;

  const overall = classification?.overall ?? "regional";
  const stats: { label: string; value: string }[] = [
    { label: "独立来源", value: String(classification?.independent_total ?? 0) },
    { label: overall === "online" ? "覆盖省份" : "覆盖省份", value: String(classification?.province_count ?? payload.regions.length) },
    { label: "市级命中", value: String(classification?.city_count ?? 0) },
    { label: "网络来源占比", value: `${Math.round((classification?.online_share ?? 0) * 100)}%` },
  ];
  const regionalItems = payload.regions.flatMap((region) => (region.items ?? []).map((item) => ({ ...item, province: item.province || region.region_name })));
  const onlineItems = payload.online_items ?? [];

  return <article className="poster" aria-label="地域分布画报">
    <header className="poster__masthead">
      <span className="poster__kicker">地域分布画报 · 引力力矩</span>
      <h1>{title || "未命名报告"}</h1>
      <p className={`poster__verdict poster__verdict--${overall}`}>
        <MapPin size={15} />{overallLabels[overall]}{classification?.label ? ` — ${classification.label}` : ""}
      </p>
    </header>

    <section className="poster__stats" aria-label="关键数字">
      {stats.map((stat) => (
        <div key={stat.label} className="poster__stat">
          <strong>{stat.value}</strong>
          <span>{stat.label}</span>
        </div>
      ))}
    </section>

    <section className="poster__map" aria-label="舆 情 地图">
      {cityError && <p className="poster__map-note" role="alert">{cityError}</p>}
      <div ref={mainRef} className="poster__map-canvas" />
      <p className="poster__map-note">
        {cityMode ? `${cityMode.name} 市级视图（按独立源组着色）` : "省级视图（按独立源着色）"}。底图为开源行政区划数据，仅分析示意，不是自然资源部审图号标准地图；正式出版请使用标准地图。
      </p>
    </section>

    <section className="poster__sources" aria-label="来源清单">
      <div className="poster__source-col">
        <h2><Globe2 size={13} />地方来源（可定位）</h2>
        {regionalItems.length ? <ul>
          {regionalItems.map((item) => (
            <li key={item.id || item.title}>
              {item.url ? <a href={item.url} target="_blank" rel="noreferrer"><ArrowUpRight size={12} /></a> : null}
              <div><strong>{item.title}</strong><small>{[item.province, item.city, item.published_at || "时间未知", sourceTypeLabels[item.source_type] ?? item.source_type].filter(Boolean).join(" · ")}</small></div>
            </li>
          ))}
        </ul> : <p className="poster__source-empty">没有可定位到省市的来源。</p>}
      </div>
      <div className="poster__source-col">
        <h2><Globe2 size={13} />网络来源（无地域属性）</h2>
        {onlineItems.length ? <ul>
          {onlineItems.map((item) => (
            <li key={item.id || item.title}>
              {item.url ? <a href={item.url} target="_blank" rel="noreferrer"><ArrowUpRight size={12} /></a> : null}
              <div><strong>{item.title}</strong><small>{[item.published_at || "时间未知", sourceTypeLabels[item.source_type] ?? item.source_type].filter(Boolean).join(" · ")}</small></div>
            </li>
          ))}
        </ul> : <p className="poster__source-empty">全部来源都可定位到省市。</p>}
      </div>
    </section>
  </article>;
}
