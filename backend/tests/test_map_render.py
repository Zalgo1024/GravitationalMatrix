"""城市地图渲染服务测试：缓存命中零网络、参数化渲染、缓存键稳定、开关门控。"""
import json
import os

import pytest


@pytest.fixture()
def fake_geojson(tmp_path, monkeypatch):
    """一个小型假城市 GeoJSON（两个区），并 monkeypatch 缓存目录。"""
    payload = {
        "features": [
            {
                "properties": {"name": "甲区"},
                "geometry": {"type": "Polygon", "coordinates": [
                    [[114.0, 34.0], [114.2, 34.0], [114.2, 34.2], [114.0, 34.2], [114.0, 34.0]]
                ]},
            },
            {
                "properties": {"name": "乙县"},
                "geometry": {"type": "Polygon", "coordinates": [
                    [[113.6, 33.6], [113.9, 33.6], [113.9, 33.9], [113.6, 33.9], [113.6, 33.6]]
                ]},
            },
        ]
    }
    cache_dir = tmp_path / "geo_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "419999_full.json").write_text(json.dumps(payload), encoding="utf-8")

    from app import map_render
    from app.settings import settings

    monkeypatch.setattr(map_render, "_geo_cache_dir", lambda: str(cache_dir))
    monkeypatch.setattr(settings, "generated_dir", str(tmp_path / "generated"))
    return payload


def test_render_from_cache_no_network(fake_geojson, monkeypatch):
    """盘缓存命中时绝不发网络请求（mock urlopen 断言零调用）。"""
    from app import map_render

    def _boom(*args, **kwargs):  # pragma: no cover
        raise AssertionError("缓存命中时不应发起网络请求")

    monkeypatch.setattr(map_render.urllib.request, "urlopen", _boom)
    out = map_render.render_city_map("419999", highlights={"甲区": "#D14B3C"}, data_version="2026-09-24")
    assert os.path.isfile(out)
    # 同键二次渲染直接复用
    assert map_render.render_city_map("419999", data_version="2026-09-24") == out


def test_render_png_dimensions(fake_geojson):
    from PIL import Image  # matplotlib 依赖链自带 pillow

    from app import map_render

    out = map_render.render_city_map("419999", data_version="2026-09-25")
    with Image.open(out) as img:
        assert img.size == (2000, 1280)


def test_cache_key_differs_by_version(fake_geojson):
    from app import map_render

    a = map_render.map_cache_path("419999", "2026-09-24")
    b = map_render.map_cache_path("419999", "2026-09-25")
    assert a != b


def test_invalid_city_code_rejected():
    from app import map_render

    with pytest.raises(ValueError):
        map_render.get_city_geojson("abc")


def test_geo_map_api_disabled(client):
    r = client.get("/api/geo/map?city=410100")
    assert r.status_code == 200
    assert r.json()["error"] == "feed_disabled"
