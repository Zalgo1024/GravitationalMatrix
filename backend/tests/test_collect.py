"""F1/F2 采集链路测试：去重三元组、地区识别、预览/保存接口、自动取证字段。"""
import uuid


# ---------------------------------------------------------------------------
# connectors.base：去重三元组
# ---------------------------------------------------------------------------

def test_canonicalize_url_strips_tracking_params():
    from app.connectors.base import canonicalize_url

    raw = "http://News.Example.com/a/b.html?utm_source=x&id=7&spm=1#top"
    assert canonicalize_url(raw) == "https://news.example.com/a/b.html?id=7"


def test_dedupe_items_marks_url_and_fingerprint_duplicates():
    from app.connectors.base import CollectedItem, dedupe_items

    items = [
        CollectedItem(kind="websearch", platform="websearch:ddg", title="某市发布新政策", url="https://a.com/1?utm_source=x"),
        CollectedItem(kind="govdoc", platform="govdoc", title="某市发布新政策", url="https://b.com/mirror"),
        CollectedItem(kind="rss", platform="rss:某源", title="另一条独立消息", url="https://c.com/2"),
    ]
    dedupe_items(items)
    assert items[0].duplicate_of == ""
    assert items[1].duplicate_of  # 同指纹异链 → 判重
    assert items[2].duplicate_of == ""


def test_independence_group_clusters_by_host():
    from app.connectors.base import CollectedItem, fill_dedupe_fields

    items = [
        CollectedItem(kind="websearch", platform="w", title="t1", url="https://news.gov.cn/a"),
        CollectedItem(kind="websearch", platform="w", title="t2", url="https://news.gov.cn/b"),
        CollectedItem(kind="websearch", platform="w", title="t3", url="https://other.com/c"),
    ]
    fill_dedupe_fields(items)
    assert items[0].independence_group == items[1].independence_group
    assert items[0].independence_group != items[2].independence_group


# ---------------------------------------------------------------------------
# connectors.regions：省级识别
# ---------------------------------------------------------------------------

def test_recognize_region_issuer_priority():
    from app.connectors.regions import recognize_region

    out = recognize_region("广东省人民政府办公厅关于印发的通知，全文如下。")
    assert out["region_code"] == "440000"
    assert out["region_name"] == "广东省"
    assert out["region_source"] == "issuer"


def test_recognize_region_body_match_and_unknown():
    from app.connectors.regions import recognize_region

    out = recognize_region("浙江某地发生一起事件，引发关注。")
    assert out["region_code"] == "330000"
    assert recognize_region("完全无关的一段文字没有地区信息。")["region_source"] == "unknown"


# ---------------------------------------------------------------------------
# rss 解析（纯函数，无网络）
# ---------------------------------------------------------------------------

def test_parse_feed_rss_and_atom():
    from app.connectors.rss import parse_feed

    rss = "<?xml version='1.0'?><rss><channel><item><title>标题一</title><link>https://x.com/1</link><description>摘要一</description><pubDate>2026-09-11</pubDate></item></channel></rss>"
    atom = "<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'><entry><title>标题二</title><link href='https://x.com/2'/><summary>摘要二</summary></entry></feed>"
    items_rss = parse_feed(rss, "测试源")
    items_atom = parse_feed(atom, "测试源")
    assert items_rss[0].title == "标题一" and items_rss[0].url == "https://x.com/1"
    assert items_rss[0].published_at == "2026-09-11"
    assert items_atom[0].url == "https://x.com/2"
    assert items_rss[0].platform == "rss:测试源"


# ---------------------------------------------------------------------------
# /api/collect 接口
# ---------------------------------------------------------------------------

def test_collect_preview_requires_query(client):
    resp = client.post("/api/collect/preview", json={"query": ""})
    assert resp.status_code == 200
    assert resp.json()["error"] == "query_required"


def test_collect_preview_returns_deduped_items(client, monkeypatch):
    from app.connectors.base import CollectedItem

    def fake_websearch(query, max_results=10):
        return [
            CollectedItem(kind="websearch", platform="websearch:mock", title="事件A通报", url="https://a.com/1"),
            CollectedItem(kind="websearch", platform="websearch:mock", title="事件A通报转载", url="https://a.com/1?utm_source=x"),
        ], None

    def fake_govdoc(query, max_results=8):
        return [
            CollectedItem(kind="govdoc", platform="govdoc", title="事件A 通报 gov", url="https://www.gov.cn/x"),
        ], None

    import app.connectors.govdoc  # noqa: F401 - 确保 patch 目标模块已加载
    import app.connectors.websearch  # noqa: F401

    monkeypatch.setattr("app.connectors.websearch.collect_websearch", fake_websearch)
    monkeypatch.setattr("app.connectors.govdoc.collect_govdoc", fake_govdoc)

    resp = client.post("/api/collect/preview", json={"query": "事件A"})
    body = resp.json()
    assert body["query"] == "事件A"
    assert body["degraded"] is None
    urls = [item["url"] for item in body["items"]]
    assert len(urls) == 2  # utm 重复被去掉
    assert "https://a.com/1" in urls and "https://www.gov.cn/x" in urls
    assert body["independent_sources"] == 2


def test_collect_save_creates_materials_and_skips_duplicates(client):
    from app.db import SessionLocal
    from app.models import Material

    payload = {
        "items": [
            {"title": "来源一", "url": "https://x.com/1", "snippet": "摘要", "kind": "websearch", "platform": "websearch:mock"},
            {"title": "来源一重复", "url": "https://x.com/1/", "kind": "websearch", "platform": "websearch:mock"},
            {"title": "无链接", "kind": "websearch", "platform": "websearch:mock"},
        ],
        "tags": "测试采集",
    }
    first = client.post("/api/collect/save", json=payload).json()
    assert first["saved_count"] == 1
    assert first["skipped_count"] == 2

    second = client.post("/api/collect/save", json=payload).json()
    assert second["saved_count"] == 0  # 与库内既有素材同链 → 跳过

    with SessionLocal() as db:
        m = db.get(Material, first["saved"][0]["id"])
        assert m is not None
        assert m.source_type == "collect"
        assert m.source == "https://x.com/1"
        assert m.warnings and m.warnings[0].startswith("collect_channel:")


def test_analyze_request_accepts_auto_collect_and_persists(client):
    """F2：AnalyzeRequest.auto_collect 落库 Task.auto_collect（不跑 worker，仅验证入库）。"""
    from app.db import SessionLocal
    from app.models import Task

    task_id = uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(
            Task(
                id=task_id, title="自动取证落库", input_text="x", status="done",
                analysis_type="case", auto_collect=True,
            )
        )
        db.commit()
    with SessionLocal() as db:
        assert db.get(Task, task_id).auto_collect is True
