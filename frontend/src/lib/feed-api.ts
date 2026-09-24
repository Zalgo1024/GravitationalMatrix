// S2 舆情流前端 API 封装：全部走既有 apiRequest（同源 cookie 自动携带，sy_token JWT 语义）。
// 红线：feed 全链无密钥，与 BYOK 无耦合。
import { apiRequest } from "./api";

export interface FeedItemRow {
  id: string;
  title: string;
  url: string | null;
  canonical_url: string | null;
  platform: string | null;
  kind: string | null;
  category: string | null;
  published_at: string | null;
  collected_at: string | null;
  summary: string | null;
  hot_score: number | null;
  region_code: string | null;
  region_source: string | null;
}

export interface FeedStats {
  window_hours: number;
  total: number;
  independent_sources: number;
  by_platform: Record<string, number>;
  by_category: Record<string, number>;
}

export type FeedDisabled = { error: "feed_disabled"; message: string };

function isDisabled(value: unknown): value is FeedDisabled {
  return typeof value === "object" && value !== null
    && (value as FeedDisabled).error === "feed_disabled";
}

export { isDisabled };

export async function fetchFeedItems(params: {
  category?: string;
  platform?: string;
  q?: string;
  window?: number;
  limit?: number;
  offset?: number;
} = {}): Promise<FeedItemRow[] | FeedDisabled> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  const body = await apiRequest<{ items: FeedItemRow[]; count: number }>(`/api/feed/items${suffix}`);
  return body.items;
}

export async function fetchFeedHotlist(params: { window?: number; limit?: number } = {}): Promise<FeedItemRow[] | FeedDisabled> {
  const query = new URLSearchParams();
  if (params.window) query.set("window", String(params.window));
  if (params.limit) query.set("limit", String(params.limit));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  const body = await apiRequest<{ items: FeedItemRow[] }>(`/api/feed/hotlist${suffix}`);
  return body.items;
}

export async function fetchFeedStats(window = 24): Promise<FeedStats | FeedDisabled> {
  return apiRequest<FeedStats>(`/api/feed/stats?window=${window}`);
}
