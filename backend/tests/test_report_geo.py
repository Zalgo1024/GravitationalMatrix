"""F11 地图聚合测试：/api/reports/{id}/geo 纯派生聚合（独立源组归并 + 省级着色口径）。"""
import uuid


def test_geo_aggregation_merges_independence_groups_and_city_to_province():
    from app.report_tables import geo_aggregation

    ledger = {
        "sources": [
            # 惠州首发 + 深圳转载同组 → 只算 1 个广东独立源、2 条来源
            {"id": "s1", "title": "惠州市奖补措施印发", "independence_group": "gov.cn"},
            {"id": "s2", "title": "转载：深圳市媒体转发", "independence_group": "gov.cn"},
            # 浙江独立源
            {"id": "s3", "title": "杭州市企业跟进申请", "independence_group": "zj.com"},
            # 无法识别地域的独立源 → 计入 coverage 分母
            {"id": "s4", "title": "某行业分析报告", "independence_group": "industry.org"},
        ],
    }
    out = geo_aggregation(ledger)

    by_name = {r["region_name"]: r for r in out["regions"]}
    gd = by_name["广东省"]
    assert gd["independent_sources"] == 1
    assert gd["sources"] == 2
    assert gd["region_code"] == "440000"
    assert "惠州市" in gd["cities"] and "深圳市" in gd["cities"]
    zj = by_name["浙江省"]
    assert zj["independent_sources"] == 1
    # 份额：有地域独立源 2 个，各省各占 0.5；coverage = 2/3
    assert gd["share"] == 0.5 and zj["share"] == 0.5
    assert out["coverage"] == 0.667
    assert out["polarity"] == []
    # 排序：独立源数降序
    assert out["regions"][0]["independent_sources"] >= out["regions"][-1]["independent_sources"]
    # 点省浮层：同组转载只留一条代表条目，条目带城市与链接
    assert len(gd["items"]) == 1
    assert gd["items"][0]["title"] == "惠州市奖补措施印发"
    assert gd["items"][0]["city"] == "惠州市"
    assert gd["item_total"] == 1


def test_geo_items_cap_and_total():
    from app.report_tables import _GEO_ITEMS_PER_REGION, geo_aggregation

    sources = [
        {"id": f"s{i}", "title": f"广东省报道 {i}", "independence_group": f"g{i}", "url": f"https://x/{i}"}
        for i in range(_GEO_ITEMS_PER_REGION + 4)
    ]
    out = geo_aggregation({"sources": sources})
    gd = out["regions"][0]
    assert gd["item_total"] == _GEO_ITEMS_PER_REGION + 4
    assert len(gd["items"]) == _GEO_ITEMS_PER_REGION
    assert all(item["url"] for item in gd["items"])


def test_geo_aggregation_empty_ledger():
    from app.report_tables import geo_aggregation

    empty = geo_aggregation({})
    assert empty["regions"] == [] and empty["online_items"] == []
    assert empty["classification"]["overall"] == "online"
    assert geo_aggregation(None)["regions"] == []


def test_classify_spread_three_ways():
    from app.report_tables import classify_spread

    def regions(n):
        return [{"region_code": str(440000 + i), "region_name": f"省{i}"} for i in range(n)]

    # 全部来源无地域 → 纯网络传播
    assert classify_spread([], 0, 7)["overall"] == "online"
    # 有地域的独立源占比过低（<0.6）→ 主体在网络平台传播
    assert classify_spread(regions(1), 2, 9)["overall"] == "online"
    # 集中在 2 省 → 地区性
    regional = classify_spread(regions(2), 6, 8)
    assert regional["overall"] == "regional"
    assert regional["online_total"] == 2 and regional["province_count"] == 2
    # 覆盖 5 省 → 全国性
    assert classify_spread(regions(5), 10, 10)["overall"] == "national"


def test_geo_spread_annotation_and_online_items():
    from app.report_tables import geo_aggregation

    ledger = {
        "sources": [
            # 有地域：广东独立源（地方来源）
            {"id": "s1", "title": "惠州市奖补措施印发", "independence_group": "gov.cn"},
            # 无地域：平台型来源（网络来源）
            {"id": "s2", "title": "微博热搜词条讨论", "independence_group": "weibo"},
        ],
    }
    out = geo_aggregation(ledger)
    assert out["classification"]["overall"] == "regional"
    assert out["classification"]["online_total"] == 1
    assert out["classification"]["located_total"] == 1
    gd = out["regions"][0]
    assert gd["items"][0]["spread"] == "regional" and gd["items"][0]["province"] == "广东省"
    assert len(out["online_items"]) == 1
    assert out["online_items"][0]["spread"] == "online"
    assert out["online_items"][0]["title"] == "微博热搜词条讨论"


def test_geo_timeline_buckets_by_month_and_city_groups_counted():
    from app.report_tables import geo_aggregation

    ledger = {
        "sources": [
            # 广东两个独立源：8 月一票、9 月一票；惠州/广州各一票
            {"id": "s1", "title": "惠州市奖补措施印发", "independence_group": "gov.cn", "published_at": "2026-08-12"},
            {"id": "s2", "title": "广州市企业连夜准备材料", "independence_group": "media.com", "published_at": "2026-09-02"},
            # 浙江独立源，无日期 → 不进时间轴
            {"id": "s3", "title": "杭州市企业跟进申请", "independence_group": "zj.com"},
        ],
    }
    out = geo_aggregation(ledger)

    gd = next(r for r in out["regions"] if r["region_name"] == "广东省")
    assert {"name": "惠州市", "groups": 1} in gd["city_groups"]
    assert {"name": "广州市", "groups": 1} in gd["city_groups"]
    assert gd["cities"] == ["广州市", "惠州市"]  # 同票按名称序

    months = {entry["month"]: entry for entry in out["timeline"]}
    assert set(months) == {"2026-08", "2026-09"}
    assert months["2026-08"]["regions"] == [{"region_code": "440000", "region_name": "广东省", "independent_sources": 1}]
    assert months["2026-09"]["regions"][0]["region_code"] == "440000"
    # 无日期的浙江组不进任何月份桶
    assert all(entry["regions"][0]["region_code"] != "330000" for entry in out["timeline"] if entry["regions"])


def test_geo_endpoint_returns_aggregation(client):
    from app.db import SessionLocal
    from app.models import Task

    task_id = uuid.uuid4().hex
    ledger = {
        "status": "verified",
        "sources": [
            {"id": "s1", "title": "惠州市奖补措施印发", "independence_group": "gov.cn"},
            {"id": "s2", "title": "广州市企业连夜准备材料", "independence_group": "media.com"},
        ],
        "claims": [],
        "relations": [],
    }
    with SessionLocal() as db:
        db.add(
            Task(
                id=task_id, title="地图聚合测试", input_text="x", status="done",
                analysis_type="policy", result={"markdown": "# 报告", "research": ledger},
            )
        )
        db.commit()
    client.get(f"/api/reports/{task_id}")  # 播种 original 版本

    body = client.get(f"/api/reports/{task_id}/geo").json()
    assert body["task_id"] == task_id
    assert body["research_status"] == "verified"
    names = {r["region_name"] for r in body["regions"]}
    assert "广东省" in names
    gd = next(r for r in body["regions"] if r["region_name"] == "广东省")
    assert gd["independent_sources"] == 2 and gd["share"] == 1.0
    assert {"惠州市", "广州市"} <= set(gd["cities"])
    assert body["coverage"] == 1.0


def test_geo_endpoint_legacy_report_zero_coverage(client):
    from app.db import SessionLocal
    from app.models import Task

    legacy = uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(Task(id=legacy, title="旧报告", status="done", input_text="", result={"markdown": "# 旧"}))
        db.commit()
    body = client.get(f"/api/reports/{legacy}/geo").json()
    assert body["regions"] == [] and body["coverage"] == 0.0
