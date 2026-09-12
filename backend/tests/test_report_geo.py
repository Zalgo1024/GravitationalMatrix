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

    assert geo_aggregation({}) == {"regions": [], "coverage": 0.0, "polarity": []}
    assert geo_aggregation(None)["regions"] == []


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
