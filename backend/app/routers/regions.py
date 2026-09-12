"""地区码表接口（F10）：给前端 composer 地域多选与地图聚合提供同一份码表。"""
from __future__ import annotations

from fastapi import APIRouter

from app.connectors.regions import load_regions

router = APIRouter()


@router.get("/api/regions")
def get_regions():
    """返回行政区划码表（v2：省级挂地级列表）。静态数据，可直接做前端缓存。"""
    data = load_regions()
    return {
        "version": data.get("version", 2),
        "provinces": [
            {
                "code": p.get("code"),
                "name": p.get("name"),
                "aliases": p.get("aliases") or [],
                "cities": [
                    {
                        "code": c.get("code"),
                        "name": c.get("name"),
                        "aliases": c.get("aliases") or [],
                    }
                    for c in (p.get("cities") or [])
                ],
            }
            for p in data.get("provinces") or []
        ],
    }
