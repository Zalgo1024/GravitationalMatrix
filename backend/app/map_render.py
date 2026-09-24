"""城市级真实行政边界地图渲染（服务化，matplotlib Agg）。

数据源：阿里 DataV GeoJSON（areas_v3/bound/{adcode}_full.json），落盘缓存于
backend/data/geo_cache/，命中缓存不发网络请求；拉取使用正常 SSL 校验
（废弃脚本里的 CERT_NONE 绝不带入生产代码）。

渲染：区划填色由调用方 highlights 参数驱动（region 名 → 色值），不硬编码任何
具体区县；可选事件落点 dots（圆点/方点，基于区划质心 + 像素偏移）。

缓存键：(city_code, data_version) 的 sha1 → generated/map_cache/{hash}.png，
同键直接复用，不重渲染。data_version 当前取当日日期，未来接入 feed 地域
聚合版本号即可自动失效。

合规口径（方案 (1) S8）：南海诸岛小窗 + 审图号红线适用于全国省级底图；
本模块只做城市级视图，页面角标固定标注「示意底图，非标准地图」。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import urllib.request
from datetime import date

from app.settings import settings

DATAV_URL = "https://geo.datav.aliyun.com/areas_v3/bound/{code}_full.json"

# 与画布 / tokens.css 一致的地图语义色
DEFAULT_FILL = "#EDF0F4"
BG_FILL = "#F2F4F8"
EDGE_COLOR = "#FFFFFF"
CANVAS_W, CANVAS_H, MARGIN = 1000, 640, 10


def _geo_cache_dir() -> str:
    path = os.path.join(os.path.dirname(settings.generated_dir), "data", "geo_cache")
    os.makedirs(path, exist_ok=True)
    return path


def get_city_geojson(city_code: str) -> dict:
    """读取城市 GeoJSON：盘缓存优先，未命中才拉 DataV 并落盘。"""
    code = city_code.strip()
    if not code.isdigit() or len(code) != 6:
        raise ValueError(f"非法城市区划码：{city_code}")
    cache_path = os.path.join(_geo_cache_dir(), f"{code}_full.json")
    if os.path.isfile(cache_path):
        with open(cache_path, encoding="utf-8") as fh:
            return json.load(fh)
    url = DATAV_URL.format(code=code)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # 正常 SSL 校验
        payload = json.loads(resp.read().decode("utf-8"))
    tmp_path = cache_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    os.replace(tmp_path, cache_path)
    return payload


def _rings(geom: dict) -> list[list]:
    if geom.get("type") == "Polygon":
        return [geom["coordinates"][0]]
    if geom.get("type") == "MultiPolygon":
        return [poly[0] for poly in geom["coordinates"]]
    return []


def map_cache_path(city_code: str, data_version: str) -> str:
    key = hashlib.sha1(f"{city_code}|{data_version}".encode("utf-8")).hexdigest()
    out_dir = os.path.join(settings.generated_dir, "map_cache")
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, f"map_{key}.png")


def render_city_map(
    city_code: str,
    *,
    highlights: dict[str, str] | None = None,
    dots: list[dict] | None = None,
    data_version: str | None = None,
) -> str:
    """渲染城市地图 PNG，返回产物路径（同缓存键直接复用）。

    highlights：区划名 → 填色（未命中的区划用 DEFAULT_FILL）；
    dots：可选落点 [{district, dx, dy, color, radius, shape: circle|square|burst}]。
    """
    version = data_version or date.today().isoformat()
    out_path = map_cache_path(city_code, version)
    if os.path.isfile(out_path):
        return out_path

    payload = get_city_geojson(city_code)
    feats = payload.get("features", [])

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle as MPCircle
    from matplotlib.patches import Polygon as MPoly
    from matplotlib.patches import Rectangle as MPRect

    all_pts = [p for f in feats for ring in _rings(f.get("geometry") or {}) for p in ring]
    if not all_pts:
        raise ValueError(f"城市 {city_code} 无可用边界数据")
    lngs = [p[0] for p in all_pts]
    lats = [p[1] for p in all_pts]
    minx, maxx, miny, maxy = min(lngs), max(lngs), min(lats), max(lats)
    coslat = math.cos(math.radians((miny + maxy) / 2))
    gw = (maxx - minx) * coslat
    gh = maxy - miny
    scale = min((CANVAS_W - 2 * MARGIN) / gw, (CANVAS_H - 2 * MARGIN) / gh)
    ox = (CANVAS_W - gw * scale) / 2
    oy = (CANVAS_H - gh * scale) / 2

    def project(p: tuple[float, float]) -> tuple[float, float]:
        return ox + (p[0] - minx) * coslat * scale, oy + (maxy - p[1]) * scale

    def centroid(ring: list) -> tuple[float, float]:
        a = cx = cy = 0.0
        n = len(ring)
        for i in range(n - 1):
            x1, y1 = ring[i]
            x2, y2 = ring[i + 1]
            cr = x1 * y2 - x2 * y1
            a += cr
            cx += (x1 + x2) * cr
            cy += (y1 + y2) * cr
        if abs(a) < 1e-9:
            return (
                sum(p[0] for p in ring) / len(ring),
                sum(p[1] for p in ring) / len(ring),
            )
        return cx / (3 * a), cy / (3 * a)

    fig = plt.figure(figsize=(10, 6.4), dpi=200)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, CANVAS_W)
    ax.set_ylim(CANVAS_H, 0)
    ax.axis("off")
    ax.add_patch(plt.Rectangle((0, 0), CANVAS_W, CANVAS_H, facecolor=BG_FILL, edgecolor="none", zorder=0))

    entries = []
    cents: dict[str, tuple[float, float]] = {}
    for f in feats:
        name = (f.get("properties") or {}).get("name", "")
        rs = _rings(f.get("geometry") or {})
        if not rs:
            continue
        big = max(
            rs,
            key=lambda r: abs(sum(
                (r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1])
                for i in range(len(r) - 1)
            )),
        )
        entries.append((name, big))
        cents[name] = project(centroid(big))

    # 大区域先画，小区域叠在上层
    def signed_area(ring: list) -> float:
        return abs(sum(
            (ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1])
            for i in range(len(ring) - 1)
        ))

    entries.sort(key=lambda item: -signed_area(item[1]))
    fills = highlights or {}
    for name, big in entries:
        pts = [project(p) for p in big]
        ax.add_patch(MPoly(
            pts,
            closed=True,
            facecolor=fills.get(name, DEFAULT_FILL),
            edgecolor=EDGE_COLOR,
            linewidth=1.4,
            zorder=2,
        ))

    for dot in dots or []:
        base = cents.get(dot.get("district", ""))
        if base is None:
            continue
        cx, cy = base[0] + float(dot.get("dx", 0)), base[1] + float(dot.get("dy", 0))
        color = dot.get("color", "#D14B3C")
        radius = float(dot.get("radius", 6))
        shape = dot.get("shape", "circle")
        if shape == "square":
            ax.add_patch(MPRect(
                (cx - radius, cy - radius), radius * 2, radius * 2,
                facecolor=color, ec=EDGE_COLOR, lw=1.8, zorder=4,
            ))
        elif shape == "burst":
            ax.add_patch(MPCircle(
                (cx, cy), radius * 2.2, fill=False, ec=color, lw=1.8, alpha=0.45, zorder=3,
            ))
            ax.add_patch(MPCircle(
                (cx, cy), radius, facecolor=color, ec=EDGE_COLOR, lw=2.2, zorder=4,
            ))
        else:
            ax.add_patch(MPCircle(
                (cx, cy), radius, facecolor=color, ec=EDGE_COLOR, lw=1.8, zorder=4,
            ))

    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return out_path
