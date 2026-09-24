"use client";

import React, { useEffect, useState } from "react";
import { apiBaseUrl, apiRequest } from "@/lib/api";

const CITIES = [
  { code: "410100", name: "郑州" },
  { code: "440100", name: "广州" },
  { code: "440300", name: "深圳" },
  { code: "441300", name: "惠州" },
] as const;

type MapStatus = { ready: boolean } | { error: string; message?: string };

export function OpinionMapScreen() {
  const [city, setCity] = useState<string>(CITIES[0].code);
  const [ready, setReady] = useState(false);
  const [status, setStatus] = useState("");
  const [imgFailed, setImgFailed] = useState(false);
  const base = apiBaseUrl();

  useEffect(() => {
    let live = true;
    setReady(false);
    setImgFailed(false);
    setStatus("");
    apiRequest<MapStatus>(`/api/geo/map/status?city=${city}`)
      .then((body) => {
        if (!live) return;
        if ("error" in body) {
          setStatus(body.error === "feed_disabled" ? "舆情流未启用（FEED_ENABLED=0）。" : "地图服务暂不可用。");
          return;
        }
        setReady(body.ready);
      })
      .catch(() => {
        if (live) setStatus("无法连接后端，请确认服务已启动。");
      });
    return () => { live = false; };
  }, [city]);

  const cityChanged = () => {
    setReady(false);
    setImgFailed(false);
    setStatus("");
  };

  return (
    <div className="wb2-page">
      <header className="wb2-header">
        <h1>舆情地图</h1>
        <p className="wb2-sub">
          溯源导向 · 真实行政边界（DataV GeoJSON 服务化渲染）· 从事件发生地与政策发布地定位舆情
        </p>
      </header>
      <div className="wb2-rule--accent" aria-hidden="true" />
      <div className="wb2-rule--hair" aria-hidden="true" />

      <div className="benchmark-picker" role="group" aria-label="城市选择">
        {CITIES.map(({ code, name }) => (
          <button
            aria-pressed={city === code}
            className="today-tab"
            key={code}
            type="button"
            onClick={() => { if (city !== code) { setCity(code); cityChanged(); } }}
          >
            {name}
          </button>
        ))}
      </div>

      {status ? (
        <div className="today-empty" role="status">
          <strong>地图暂不可用</strong>
          <span>{status}</span>
        </div>
      ) : imgFailed ? (
        <div className="today-empty" role="status">
          <strong>地图渲染失败</strong>
          <span>数据源不可达或区划码无边界数据，可稍后重试或换一个城市。</span>
        </div>
      ) : (
        <figure className="map-figure">
          <img
            alt={`${CITIES.find((c) => c.code === city)?.name ?? city} 行政边界地图`}
            className="map-image"
            src={`${base}/api/geo/map?city=${city}`}
            onError={() => setImgFailed(true)}
            onLoad={() => setReady(true)}
          />
          <figcaption>示意底图，非标准地图 · 行政边界取自官方底图服务（DataV），禁止手绘边界</figcaption>
        </figure>
      )}
      <p className="wb2-footer-note">
        当前展示行政边界与区划底色；事件落点与政策机关标注将随 feed 地域聚合数据接入后点亮，
        识别不出地域的条目不进地图统计（不编造）。
      </p>
    </div>
  );
}
