"use client";

import Link from "next/link";
import React, { useEffect, useState } from "react";
import {
  fetchFeedHotlist,
  fetchFeedItems,
  fetchFeedStats,
  isDisabled,
  type FeedItemRow,
  type FeedStats,
} from "@/lib/feed-api";

const DEFAULT_CATEGORIES = ["通用"];

function timeLabel(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return `${date.getMonth() + 1}-${String(date.getDate()).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function platformLabel(platform: string | null): string {
  if (!platform) return "未知来源";
  const index = platform.indexOf(":");
  return index >= 0 ? platform.slice(index + 1) : platform;
}

export function TodayScreen() {
  const [category, setCategory] = useState<string | null>(null);
  const [items, setItems] = useState<FeedItemRow[] | null>(null);
  const [hotlist, setHotlist] = useState<FeedItemRow[] | null>(null);
  const [stats, setStats] = useState<FeedStats | null>(null);
  const [disabled, setDisabled] = useState(false);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const [statsResult, itemsResult, hotlistResult] = await Promise.all([
          fetchFeedStats(24),
          fetchFeedItems({ window: 72, limit: 60 }),
          fetchFeedHotlist({ window: 24, limit: 20 }),
        ]);
        if (!live) return;
        if (isDisabled(statsResult)) {
          setDisabled(true);
          return;
        }
        setStats(statsResult);
        if (!isDisabled(itemsResult)) setItems(itemsResult);
        if (!isDisabled(hotlistResult)) setHotlist(hotlistResult);
      } catch (reason) {
        if (live) setLoadError(reason instanceof Error ? reason.message : "加载失败");
      }
    })();
    return () => { live = false; };
  }, []);

  const categories = stats
    ? ["全部", ...Object.keys(stats.by_category)]
    : ["全部", ...DEFAULT_CATEGORIES];
  const activeCategory = category ?? "全部";
  const visibleItems = (items ?? []).filter(
    (item) => activeCategory === "全部" || item.category === activeCategory,
  );

  const analysisHref = (item: FeedItemRow) =>
    `/analysis?prompt=${encodeURIComponent(`请就以下舆情线索做结构化分析：${item.title}`)}`;

  return (
    <div className="wb2-page">
      <header className="wb2-header">
        <h1>今日资讯</h1>
        <p className="wb2-sub">
          全局舆情流 · 按采集时间去重归并 · 全部条目可回溯原文
        </p>
      </header>
      <div className="wb2-rule--accent" aria-hidden="true" />
      <div className="wb2-rule--hair" aria-hidden="true" />

      {disabled ? (
        <div className="today-empty" role="status">
          <strong>舆情流未启用</strong>
          <span>
            后端 FEED_ENABLED=0。启用后本页展示全局采集条目（RSS / 热榜），
            数据由采集服务自动入库，本页不做任何手工编造。
          </span>
        </div>
      ) : loadError ? (
        <div className="today-empty" role="alert">
          <strong>资讯加载失败</strong>
          <span>{loadError}。请确认后端已启动后重试。</span>
        </div>
      ) : (
        <>
          <div className="today-stats" aria-label="24 小时概览">
            <span>24h 条目 <strong>{stats?.total ?? 0}</strong></span>
            <span>独立来源 <strong>{stats?.independent_sources ?? 0}</strong></span>
            <span>热榜条目 <strong>{hotlist?.length ?? 0}</strong></span>
          </div>

          <div className="today-tabs" role="group" aria-label="分类筛选">
            {categories.map((name) => (
              <button
                aria-pressed={activeCategory === name}
                className="today-tab"
                key={name}
                type="button"
                onClick={() => setCategory(name)}
              >
                {name}
              </button>
            ))}
          </div>

          {visibleItems.length === 0 ? (
            <div className="today-empty" role="status">
              <strong>暂无资讯数据</strong>
              <span>
                采集服务尚未入库条目：请确认 .env 已配置
                COLLECT_RSS_FEEDS / COLLECT_HOTLIST_URL 并开启 FEED_ENABLED，
                等待一个采集周期后刷新。
              </span>
            </div>
          ) : (
            <div className="today-list">
              {visibleItems.map((item, index) => (
                <article className="today-card" key={item.id}>
                  <span className="today-card__rank" aria-hidden="true">{index + 1}</span>
                  <div>
                    <p className="today-card__title">
                      {item.url
                        ? <a href={item.url} rel="noreferrer" target="_blank">{item.title}</a>
                        : item.title}
                    </p>
                    <div className="today-card__meta">
                      <span>{platformLabel(item.platform)}</span>
                      {item.hot_score != null && <span>热度 {item.hot_score}</span>}
                      {timeLabel(item.published_at ?? item.collected_at) && (
                        <span>{timeLabel(item.published_at ?? item.collected_at)}</span>
                      )}
                      {item.category && <span>{item.category}</span>}
                    </div>
                  </div>
                  <div className="today-card__actions">
                    <Link className="analyze-btn" href={analysisHref(item)}>起分析</Link>
                  </div>
                </article>
              ))}
            </div>
          )}
          <p className="wb2-footer-note">
            条目由采集服务自动去重入库；情感与地域标注为后续模块，当前未标注的字段一律留空，不编数据。
            {" "}
            <Link href="/map">舆情地图 ›</Link>
          </p>
        </>
      )}
    </div>
  );
}
