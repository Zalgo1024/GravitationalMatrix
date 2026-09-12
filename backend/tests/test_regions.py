"""F10 地域范围约束链路测试：市级码表识别、region_scope 校验/注入、/api/regions 码表端点。"""
import uuid


# ---------------------------------------------------------------------------
# connectors.regions：市级识别 + 码值解析
# ---------------------------------------------------------------------------

def test_recognize_region_detailed_city_first():
    from app.connectors.regions import recognize_region_detailed

    out = recognize_region_detailed("惠州某企业的补贴申请被驳回")
    assert out["region_code"] == "440000" and out["region_name"] == "广东省"
    assert out["city_code"] == "441300" and out["city_name"] == "惠州市"

    out2 = recognize_region_detailed("深圳市发布新规，深圳速度再现")
    assert out2["city_code"] == "440300" and out2["region_name"] == "广东省"


def test_recognize_region_detailed_province_fallback_and_unknown():
    from app.connectors.regions import recognize_region_detailed

    out = recognize_region_detailed("浙江省某地发生事件，引发关注。")
    assert out["region_code"] == "330000" and out["city_code"] is None

    unknown = recognize_region_detailed("完全无关的一段文字没有地区信息。")
    assert unknown["region_source"] == "unknown" and unknown["city_code"] is None


def test_province_alias_priority_beats_city_alias():
    """「吉林」既是省也是市：省级优先，吉林市只认全称。"""
    from app.connectors.regions import recognize_region_detailed

    out = recognize_region_detailed("吉林某化工厂发生爆炸")
    assert out["region_code"] == "220000" and out["city_code"] is None

    out2 = recognize_region_detailed("吉林市某化工厂发生爆炸")
    assert out2["city_code"] == "220200" and out2["city_name"] == "吉林市"


def test_valid_region_codes_filters_unknown_and_dedupes():
    from app.connectors.regions import valid_region_codes

    assert valid_region_codes(["441300", "999999", "440000", "", "441300"]) == [
        "441300", "440000",
    ]
    assert valid_region_codes(None) == []
    assert valid_region_codes([]) == []


def test_region_scope_names_groups_cities_by_province():
    from app.connectors.regions import region_scope_names

    assert region_scope_names(["440000", "441300", "330000"]) == [
        "广东省（惠州市）", "浙江省",
    ]
    assert region_scope_names(["441300", "441900"]) == ["广东省（惠州市、东莞市）"]
    assert region_scope_names([]) == []


# ---------------------------------------------------------------------------
# /api/regions 码表端点
# ---------------------------------------------------------------------------

def test_get_regions_returns_provinces_with_cities(client):
    body = client.get("/api/regions").json()
    assert body["version"] >= 2
    provinces = {p["code"]: p for p in body["provinces"]}
    assert len(provinces) == 34
    gd = provinces["440000"]
    assert gd["name"] == "广东省"
    codes = {c["code"] for c in gd["cities"]}
    assert {"440100", "440300", "441300"} <= codes
    huizhou = next(c for c in gd["cities"] if c["code"] == "441300")
    assert huizhou["name"] == "惠州市" and "惠州" in huizhou["aliases"]
    # 直辖市不设地级列表
    assert provinces["110000"]["cities"] == []


# ---------------------------------------------------------------------------
# /api/analyze 落库：region_scope 校验 + retry 继承
# ---------------------------------------------------------------------------

def test_analyze_persists_validated_region_scope(client, sample_event):
    from app.db import SessionLocal
    from app.models import Task

    r = client.post(
        "/api/analyze",
        json={
            "title": sample_event["title"],
            "analysis_type": "case",
            "mode": "rule",
            "structured": sample_event,
            "region_scope": ["441300", "999999", "440000"],
        },
    )
    assert r.status_code == 200, r.text
    tid = r.json()["task_id"]
    with SessionLocal() as db:
        t = db.get(Task, tid)
        assert t.region_scope == ["441300", "440000"]  # 999999 被过滤


def test_analyze_empty_region_scope_stays_none(client, sample_event):
    """不选地域 = 不传/空 → Task.region_scope 为 None（零回归）。"""
    from app.db import SessionLocal
    from app.models import Task

    r = client.post(
        "/api/analyze",
        json={
            "title": sample_event["title"],
            "analysis_type": "case",
            "mode": "rule",
            "structured": sample_event,
        },
    )
    tid = r.json()["task_id"]
    with SessionLocal() as db:
        assert db.get(Task, tid).region_scope is None


def test_retry_inherits_region_scope(client, sample_event):
    from app.db import SessionLocal
    from app.models import Task

    r = client.post(
        "/api/analyze",
        json={
            "title": sample_event["title"],
            "analysis_type": "case",
            "mode": "rule",
            "structured": sample_event,
            "region_scope": ["441300"],
        },
    )
    tid = r.json()["task_id"]
    with SessionLocal() as db:
        t = db.get(Task, tid)
        t.status = "error"
        db.commit()
    r2 = client.post(f"/api/analyze/{tid}/retry")
    assert r2.status_code == 200, r2.text
    new_id = r2.json()["new_task_id"]
    with SessionLocal() as db:
        assert db.get(Task, new_id).region_scope == ["441300"]


# ---------------------------------------------------------------------------
# prompt_builder：地域约束段注入（LLM 路径；rule 路径不注入）
# ---------------------------------------------------------------------------

def test_prompt_injects_region_scope_section_only_when_provided():
    from app.prompt_builder import PROMPT_VERSION, build_system_prompt

    assert PROMPT_VERSION == "1.4"

    with_scope = build_system_prompt("policy", region_scope=["440000", "441300"])
    assert "# 地域范围约束" in with_scope
    assert "广东省（惠州市）" in with_scope
    assert "不得编造范围内不存在的事实" in with_scope

    without = build_system_prompt("policy")
    assert "# 地域范围约束" not in without

    # 非法码值 → 整段不注入
    invalid = build_system_prompt("policy", region_scope=["999999"])
    assert "# 地域范围约束" not in invalid
