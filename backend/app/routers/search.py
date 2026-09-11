"""来源预览接口：POST /api/search/preview（T8）。

请求 {"query": "关键词"} → 响应 {"query", "provider", "hits":[{title,url,snippet}], "degraded"}
即时返回不落库；检索源自动选择（BING→BRAVE→DDG），失败带明确 degraded 标记，不静默。
"""
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.auth import rate_limiter
from app.search import dedupe_hits, search_web
from app.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter()


class SearchPreviewRequest(BaseModel):
    query: str


# 匿名检索限流：公网下每 IP 60s ≤ 20 次，防刷外部检索（本地放行）
_SEARCH_RATE, _SEARCH_WINDOW = 20, 60


@router.post("/api/search/preview")
def search_preview(req: SearchPreviewRequest, request: Request):
    """来源预览：即时检索，不落库。degraded 非空时前端应提示「检索源不可用」。"""
    if settings.public_mode:
        ip = request.client.host if request.client else "unknown"
        if not rate_limiter.allow(f"search:{ip}", limit=_SEARCH_RATE, window_sec=_SEARCH_WINDOW):
            raise HTTPException(
                status_code=429,
                detail={"status": "rate_limited", "message": "检索过于频繁，请稍后再试"},
            )
    query = (req.query or "").strip()
    if not query:
        return {"query": "", "provider": "duckduckgo", "hits": [], "degraded": "查询为空"}

    result = search_web(query, settings.search_max_results)
    if result is None:
        return {
            "query": query,
            "provider": "duckduckgo",
            "hits": [],
            "degraded": "检索源不可用（可配置 BING/BRAVE Key 或改用手动 URL 输入）",
        }
    hits = dedupe_hits(result.hits)
    return {
        "query": result.query,
        "provider": result.provider,
        "hits": [{"title": h.title, "url": h.url, "snippet": h.snippet} for h in hits],
        "degraded": result.degraded,
    }
