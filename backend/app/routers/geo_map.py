"""城市级舆情地图 API：GET /api/geo/map → 渲染 PNG（FEED_ENABLED 门控）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse

from app.auth import get_current_user
from app.settings import settings

router = APIRouter()


@router.get("/api/geo/map")
def geo_map(
    request: Request,
    city: str = "410100",
    current: dict = Depends(get_current_user),
):
    if not settings.feed_enabled:
        return {"error": "feed_disabled", "message": "舆情流未启用（FEED_ENABLED=0）。"}
    from app.map_render import map_cache_path, render_city_map

    try:
        out_path = render_city_map(city)
    except ValueError as exc:
        return {"error": "invalid_city", "message": str(exc)}
    except Exception:  # noqa: BLE001 —— DataV 不可达/渲染失败：明示原因，不白屏
        return {"error": "map_unavailable", "message": "地图渲染暂不可用（数据源不可达），请稍后重试。"}

    etag = f'"{out_path.rsplit("_", 1)[-1].split(".")[0]}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return FileResponse(
        out_path,
        media_type="image/png",
        headers={"ETag": etag, "Cache-Control": "private, max-age=3600"},
    )


@router.get("/api/geo/map/status")
def geo_map_status(city: str = "410100", current: dict = Depends(get_current_user)):
    """产物存在性查询（前端判断缓存是否就绪，避免空图）。"""
    if not settings.feed_enabled:
        return {"error": "feed_disabled", "message": "舆情流未启用。"}
    import os
    from datetime import date

    from app.map_render import map_cache_path

    return {"ready": os.path.isfile(map_cache_path(city, date.today().isoformat()))}
