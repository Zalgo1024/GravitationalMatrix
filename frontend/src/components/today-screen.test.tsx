import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { TodayScreen } from "./today-screen";
import * as feedApi from "@/lib/feed-api";

vi.mock("@/lib/feed-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/feed-api")>();
  return { ...actual, fetchFeedItems: vi.fn(), fetchFeedHotlist: vi.fn(), fetchFeedStats: vi.fn() };
});

function mockFeed({
  stats = { window_hours: 24, total: 2, independent_sources: 2, by_platform: { "rss:测试": 2 }, by_category: { 通用: 2 } },
  items = [
    { id: "a", title: "某市发布新政策", url: "https://example.com/a", canonical_url: null, platform: "rss:测试", kind: "rss", category: "通用", published_at: null, collected_at: "2026-09-24T10:00:00+00:00", summary: null, hot_score: null, region_code: null, region_source: "unknown" },
    { id: "b", title: "热搜话题乙", url: "https://example.com/b", canonical_url: null, platform: "hotlist:微博", kind: "hotlist", category: "通用", published_at: null, collected_at: "2026-09-24T09:00:00+00:00", summary: null, hot_score: 321, region_code: null, region_source: "unknown" },
  ] as feedApi.FeedItemRow[],
  hotlist = [] as feedApi.FeedItemRow[],
  disabled = false,
}) {
  vi.mocked(feedApi.fetchFeedStats).mockResolvedValue(
    disabled ? { error: "feed_disabled", message: "x" } : (stats as feedApi.FeedStats),
  );
  vi.mocked(feedApi.fetchFeedItems).mockResolvedValue(disabled ? { error: "feed_disabled", message: "x" } : items);
  vi.mocked(feedApi.fetchFeedHotlist).mockResolvedValue(disabled ? { error: "feed_disabled", message: "x" } : hotlist);
}

describe("TodayScreen", () => {
  beforeEach(() => vi.clearAllMocks());

  it("渲染资讯卡片并提供分类页签与起分析入口", async () => {
    mockFeed({});
    render(<TodayScreen />);
    expect(await screen.findByText("某市发布新政策")).toBeInTheDocument();
    expect(screen.getByText("热搜话题乙")).toBeInTheDocument();
    // 「起分析」预填 prompt 链接
    const links = screen.getAllByRole("link", { name: "起分析" });
    expect(links[0]).toHaveAttribute("href", expect.stringContaining("/analysis?prompt="));
    // 分类页签：默认选中「全部」
    expect(screen.getByRole("button", { name: "全部" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "通用" })).toBeInTheDocument();
  });

  it("24h 概览统计渲染", async () => {
    mockFeed({});
    render(<TodayScreen />);
    await screen.findByText("某市发布新政策");
    expect(screen.getByText("24h 条目")).toBeInTheDocument();
    expect(screen.getByText("独立来源")).toBeInTheDocument();
    expect(screen.getByText("热榜条目")).toBeInTheDocument();
    expect(screen.getAllByText("2").length).toBeGreaterThan(0);
  });

  it("FEED_ENABLED=0 时展示明确的空态原因（不编数据）", async () => {
    mockFeed({ disabled: true });
    render(<TodayScreen />);
    expect(await screen.findByText("舆情流未启用")).toBeInTheDocument();
    expect(screen.getByText(/FEED_ENABLED=0/)).toBeInTheDocument();
  });

  it("空数据时展示采集配置提示", async () => {
    mockFeed({ items: [], hotlist: [] });
    render(<TodayScreen />);
    expect(await screen.findByText("暂无资讯数据")).toBeInTheDocument();
    expect(screen.getByText(/COLLECT_RSS_FEEDS/)).toBeInTheDocument();
  });

  it("分类页签切换过滤条目", async () => {
    mockFeed({
      stats: {
        window_hours: 24, total: 2, independent_sources: 2,
        by_platform: {}, by_category: { 通用: 1, 财经: 1 },
      },
      items: [
        { id: "a", title: "政策条目", url: null, canonical_url: null, platform: "rss:x", kind: "rss", category: "通用", published_at: null, collected_at: null, summary: null, hot_score: null, region_code: null, region_source: "unknown" },
        { id: "b", title: "财经条目", url: null, canonical_url: null, platform: "rss:y", kind: "rss", category: "财经", published_at: null, collected_at: null, summary: null, hot_score: null, region_code: null, region_source: "unknown" },
      ],
    });
    render(<TodayScreen />);
    await screen.findByText("政策条目");
    fireEvent.click(screen.getByRole("button", { name: "财经" }));
    expect(screen.getByText("财经条目")).toBeInTheDocument();
    expect(screen.queryByText("政策条目")).not.toBeInTheDocument();
  });
});
