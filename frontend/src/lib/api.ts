// API 基址：默认直连本地后端（127.0.0.1:8000，本地工作台）。
// 同源部署（NEXT_PUBLIC_API_URL 设为空字符串）时走相对路径，
// 由前置反代（Caddy/nginx）把 /api /ws 转发到后端，浏览器只访问前端一个源。
const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

export class ApiError extends Error {
  code: string;
  status: number;
  phase?: string;
  details: string[];

  constructor(message: string, code: string, status: number, phase?: string, details: string[] = []) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.phase = phase;
    this.details = details;
  }
}

export async function apiRequest<T = unknown>(path: string, options: RequestInit & { workspaceId?: string } = {}): Promise<T> {
  const { workspaceId: _workspaceId, ...requestOptions } = options;
  const headers = new Headers(requestOptions.headers);
  if (requestOptions.body && !(requestOptions.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(`${API_BASE}${path}`, { ...requestOptions, headers, credentials: "include" });
  if (!response.ok) {
    let payload: unknown = {};
    try { payload = await response.json(); } catch { /* empty response */ }
    const root = payload && typeof payload === "object" ? payload as Record<string, unknown> : {};
    const nested = root.error && typeof root.error === "object"
      ? root.error as Record<string, unknown>
      : root;
    const details = Array.isArray(nested.details)
      ? nested.details.filter((item): item is string => typeof item === "string")
      : [];
    const baseMessage = typeof nested.message === "string"
      ? nested.message
      : typeof root.detail === "string"
        ? root.detail
        : "请求失败";
    const message = details.length ? `${baseMessage} ${details.join("；")}` : baseMessage;
    throw new ApiError(
      message,
      typeof nested.code === "string" ? nested.code : "request_failed",
      response.status,
      typeof nested.phase === "string" ? nested.phase : undefined,
      details,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function apiBaseUrl() {
  return API_BASE;
}

// WebSocket 地址：独立部署时与 API_BASE 同主机、仅协议不同（http→ws）；
// 同源部署（API_BASE 为空）时基于当前页面 host 构造 ws(s):// URL。
export function wsUrl(path: string): string {
  if (API_BASE) return `${API_BASE.replace(/^http/, "ws")}${path}`;
  const proto =
    typeof location !== "undefined" && location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}${path}`;
}
