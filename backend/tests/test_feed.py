"""S2 feed 最小闭环测试（方案 (1) S2 验收口径）。

- 开关关（默认）：端点统一 feed_disabled、feed_tick 直接跳过（零回归主断言）；
- 开关开：连续两轮采集第二轮零新增（S2 验收口径）、同稿多站转载只计 1 独立源、
  unknown region 不进地域统计；
- 采集源打桩：所有用例不发真实网络请求。
"""
import uuid

import pytest

from app.connectors.base import CollectedItem


def _item(title: str, url: str, platform: str = "rss:测试源", kind: str = "rss",
          engagement: int | None = None, region_code: str | None = None,
          region_source: str = "unknown", snippet: str = "") -> CollectedItem:
    return CollectedItem(
        kind=kind,
        platform=platform,
        title=title,
        url=url,
        snippet=snippet,
        engagement=engagement,
        region_code=region_code,
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
