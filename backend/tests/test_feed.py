"""S2 feed 最小闭环测试（方案 (1) S2 验收口径）+ S3/S4 落库验证。

- 开关关（默认）：端点统一 feed_disabled、feed_tick 直接跳过（零回归主断言）；
- 开关开：连续两轮采集第二轮零新增（S2 验收口径）、同稿多站转载只计 1 独立源、
  unknown region 不进地域统计；
- S3：市级识别（rss 端到端解析 + 落库 + /geo cities 聚合，unknown 不进）；
- S4：词典法情感落库 + /items sentiment 筛选；
- 采集源打桩：所有用例不发真实网络请求。
"""
import uuid

import pytest

from app.connectors.base import CollectedItem


def _item(title: str, url: str, platform: str = "rss:测试源", kind: str = "rss",
          engagement: int | None = None, region_code: str | None = None,
          region_source: str = "unknown", snippet: str = "",
          city_code: str | None = None, city_name: str | None = None) -> CollectedItem:
    return CollectedItem(
        kind=kind,
        platform=platform,
        title=title,
        url=url,
        snippet=snippet,
        engagement=engagement,
        region_code=region_code,
        city_code=city_code,
        city_name=city_name,
        region_source=region_source,
    )


# ---------------------------------------------------------------------------
# 开关关（默认 PUBLIC_MODE=0 + FEED_ENABLED 未设）
# ---------------------------------------------------------------------------
def test_feed_disabled_by_default(client):
    for path in ("/api/feed/items", "/api/feed/hotlist", "/api/feed/stats", "/api/feed/geo"):
        r = client.get(path)
        assert r.status_code == 200, r.text
        assert r.json()["error"] == "feed_disabled", path

    r = client.post("/api/feed/collect")
    assert r.json()["error"] == "feed_disabled"


def test_feed_tick_skipped_when_disabled(monkeypatch):
    from app import feed_collector
    from app.settings import settings

    assert settings.feed_enabled is False
    assert feed_collector.feed_tick() is None


# ---------------------------------------------------------------------------
# 开关开：入库去重 / 统计 / API
# ---------------------------------------------------------------------------
@pytest.fixture()
def feed_on(monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "feed_enabled", True)
    yield


@pytest.fixture()
def clean_feed():
    """session 级隔离库在用例间共享，统计类用例先清空 feed_items。"""
    from app.db import SessionLocal
    from app.models import FeedItem, FeedCollectRun

    with SessionLocal() as db:
        db.query(FeedItem).delete(synchronize_session=False)
        db.query(FeedCollectRun).delete(synchronize_session=False)
        db.commit()
    yield


def _run_round(monkeypatch, rss_items, hotlist_items):
    """打桩两个采集源并跑一轮 collect_feed_round。"""
    from app import feed_collector

    monkeypatch.setattr(
        "app.connectors.rss.collect_rss", lambda *a, **k: (rss_items, None)
    )
    monkeypatch.setattr(
        "app.connectors.hotlist.collect_hotlist", lambda *a, **k: (hotlist_items, None)
    )
    return feed_collector.collect_feed_round()


def test_two_rounds_second_zero_insert(client, feed_on, clean_feed, monkeypatch):
    """S2 验收口径：连续采集两轮，第二轮零新增。"""
    items = [_item("某市发布新政策", f"https://example.com/news/{uuid.uuid4().hex}", snippet="政策内容摘要")]
    first = _run_round(monkeypatch, items, [])
    assert first["inserted"] == 1
    second = _run_round(monkeypatch, items, [])
    assert second["inserted"] == 0
    assert second["deduped"] == 1


def test_same_story_counts_one_independent_source(client, feed_on, clean_feed, monkeypatch):
    """同稿 5 站转载（同 fingerprint）只计 1 条独立源；unknown region 不进 geo。"""
    # 同标题同摘要 → content_fingerprint 相同 → 库内去重只落 1 条
    items = [
        _item("同一事件报道", f"https://site{i}.example.com/a", snippet="相同内容")
        for i in range(5)
    ]
    items += [_item("本地民生新闻", "https://local.example.com/b", snippet="地域内容")]
    summary = _run_round(monkeypatch, items, [])
    # 5 条同稿去重后只插 1 条 + 1 条本地新闻 = 2
    assert summary["inserted"] == 2

    r = client.get("/api/feed/stats")
    body = r.json()
    assert body["total"] == 2
    assert body["independent_sources"] == 2  # 每条来自不同 host


def test_unknown_region_excluded_from_geo(client, feed_on, clean_feed, monkeypatch):
    """region_source=unknown 的条目不进 /api/feed/geo（红线：地域不编造）。"""
    rss = [
        _item("广东出台新政", "https://gd.example.com/x", region_code="440000", region_source="issuer"),
        _item("无地域新闻", "https://nowhere.example.com/y"),
    ]
    _run_round(monkeypatch, rss, [])
    r = client.get("/api/feed/geo")
    regions = {row["region_code"]: row["items"] for row in r.json()["regions"]}
    assert regions.get("440000") == 1
    # unknown（region_code=None）天然不在结果里
    assert all(code for code in regions)


def test_items_api_filters(client, feed_on, clean_feed, monkeypatch):
    hot = [
        _item("热搜话题甲", "https://wb.example.com/1", platform="hotlist:微博",
              kind="hotlist", engagement=9876, snippet="摘要甲"),
        _item("热搜话题乙", "https://wb.example.com/2", platform="hotlist:微博",
              kind="hotlist", engagement=123, snippet="摘要乙"),
    ]
    _run_round(monkeypatch, [], hot)

    # hotlist 端点：按热度倒序
    r = client.get("/api/feed/hotlist")
    rows = r.json()["items"]
    assert [row["hot_score"] for row in rows] == [9876, 123]

    # 关键词筛选
    r = client.get("/api/feed/items", params={"q": "话题甲"})
    assert [row["title"] for row in r.json()["items"]] == ["热搜话题甲"]

    # 平台前缀筛选
    r = client.get("/api/feed/items", params={"platform": "hotlist"})
    assert r.json()["count"] == 2


def test_feed_tick_throttled(client, feed_on, monkeypatch):
    """feed_tick：第一轮执行，立即第二轮被节流跳过。"""
    from app import feed_collector

    monkeypatch.setattr(
        "app.connectors.rss.collect_rss", lambda *a, **k: ([_item("节流测试", "https://t.example.com/1")], None)
    )
    monkeypatch.setattr("app.connectors.hotlist.collect_hotlist", lambda *a, **k: ([], None))
    assert feed_collector.feed_tick() is not None
    assert feed_collector.feed_tick() is None  # 未到 FEED_INTERVAL_MIN，跳过


# ---------------------------------------------------------------------------
# S3：市级地域识别落库 + /geo cities 聚合
# ---------------------------------------------------------------------------
def test_rss_parse_city_level_region():
    """rss 解析端到端：标题含「深圳市」→ city_code=440300（真实走 recognize_region_detailed）。"""
    from app.connectors.rss import parse_feed

    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><title>测试源</title>
    <item><title>深圳市出台新规规范校外培训</title>
    <link>https://sz.example.com/news/1</link>
    <description>深圳市教育局发布最新管理办法。</description></item>
    </channel></rss>"""
    items = parse_feed(xml, "测试源")
    assert len(items) == 1
    assert items[0].city_code == "440300"
    assert items[0].city_name == "深圳市"
    assert items[0].region_code == "440000"  # 市级命中时 region_code 为所属省码
    assert items[0].region_source in ("title", "body")


def test_city_and_sentiment_stored(client, feed_on, clean_feed, monkeypatch):
    """S3+S4 落库：市级字段与词典法情感均真实写入并可经 API 读出。"""
    items = [
        _item("深圳市发生工厂爆炸事故", "https://sz.example.com/x",
              region_code="440000", city_code="440300", city_name="深圳市",
              region_source="title", snippet="现场多人受伤"),
        _item("某部门发布例行公告", "https://plain.example.com/y", snippet="公告全文如下"),
    ]
    _run_round(monkeypatch, items, [])

    r = client.get("/api/feed/items")
    rows = {row["title"]: row for row in r.json()["items"]}
    blast = rows["深圳市发生工厂爆炸事故"]
    assert blast["city_code"] == "440300"
    assert blast["city_name"] == "深圳市"
    assert blast["region_code"] == "440000"
    assert blast["sentiment"] == "negative"
    assert blast["sentiment_score"] < 0
    assert rows["某部门发布例行公告"]["sentiment"] == "neutral"


def test_geo_cities_aggregation(client, feed_on, clean_feed, monkeypatch):
    """/geo cities：市级聚合只计非 unknown 条目（红线：地域不编造）。"""
    items = [
        _item("惠州新闻甲", "https://hz.example.com/1", region_code="440000",
              city_code="441300", city_name="惠州市", region_source="title"),
        _item("惠州新闻乙", "https://hz.example.com/2", region_code="440000",
              city_code="441300", city_name="惠州市", region_source="title"),
        _item("无地域新闻", "https://nowhere.example.com/3"),
    ]
    _run_round(monkeypatch, items, [])
    r = client.get("/api/feed/geo")
    body = r.json()
    cities = {row["city_code"]: row for row in body["cities"]}
    assert cities["441300"]["items"] == 2
    assert cities["441300"]["city_name"] == "惠州市"
    assert cities["441300"]["region_code"] == "440000"
    # unknown 条目（city_code=None）不进市级聚合
    assert len(body["cities"]) == 1
    # 省级聚合不受影响，仍只计 unknown 之外的 2 条
    assert {row["region_code"] for row in body["regions"]} == {"440000"}


def test_items_sentiment_filter(client, feed_on, clean_feed, monkeypatch):
    """/items sentiment 筛选（S4）。"""
    items = [
        _item("某地发生重大交通事故", "https://a.example.com/1", snippet="多人伤亡"),
        _item("某地举办招聘会", "https://b.example.com/2", snippet="提供上千岗位"),
    ]
    _run_round(monkeypatch, items, [])
    r = client.get("/api/feed/items", params={"sentiment": "negative"})
    rows = r.json()["items"]
    assert len(rows) == 1
    assert rows[0]["title"] == "某地发生重大交通事故"
