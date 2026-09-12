"""F15 数据表端点测试：来源证据/主体清单/关系清单 的 JSON 与 CSV 输出。"""
import csv
import io
import uuid


def _ledger() -> dict:
    return {
        "schema_version": "1.2",
        "status": "verified",
        "sources": [
            {
                "id": "s1", "title": "官方通报", "url": "https://www.gov.cn/a",
                "source_type": "official", "quality_tier": "A",
                "published_at": "2026-09-01", "independence_group": "www.gov.cn",
                "content_fingerprint": "fp1", "duplicate_of": None, "excerpt": "通报全文摘录",
            },
            {
                "id": "s2", "title": "媒体转载", "url": "https://media.com/b",
                "source_type": "media", "quality_tier": "B",
                "published_at": "2026-09-02", "independence_group": "media.com",
                "content_fingerprint": "fp2", "duplicate_of": "s1", "excerpt": "转载内容",
            },
        ],
        "nodes": [
            {"id": "n1", "label": "监管部门", "role": "regulator", "stance": "强硬",
             "weight": 0.9, "confidence": 0.8, "evidence_ids": ["s1"], "interests": ["监管合规"]},
            {"id": "n2", "label": "涉事企业", "role": "subject", "stance": "防御",
             "weight": 0.7, "confidence": 0.7, "evidence_ids": ["s1", "s2"], "interests": ["经营收益", "声誉"]},
        ],
        "relations": [
            {"source_node": "n1", "target_node": "n2", "label": "调查施压", "polarity": "negative",
             "strength": 0.8, "status": "active", "evidence_ids": ["s1"], "evidence_count": 1,
             "interest_types": ["监管合规"]},
        ],
    }


def _task_with_ledger(client) -> str:
    from app.db import SessionLocal
    from app.models import Task

    task_id = uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(
            Task(
                id=task_id, title="数据表测试", input_text="x", status="done",
                analysis_type="policy", result={"markdown": "# 报告", "research": _ledger()},
            )
        )
        db.commit()
    client.get(f"/api/reports/{task_id}")  # 触发 original 版本播种
    return task_id


def test_sources_table_returns_rows(client):
    task_id = _task_with_ledger(client)
    body = client.get(f"/api/reports/{task_id}/tables/sources").json()
    assert body["table_name"] == "来源证据表"
    assert body["row_count"] == 2
    assert body["columns"][0] == "编号"
    assert "地域" in body["columns"]  # F15 表内即时派生列
    first = body["rows"][0]
    assert first[0] == "s1" and first[3] == "official" and first[4] == "A"
    assert first[7] == "www.gov.cn"  # 独立源组
    assert first[8] == "首发"
    assert body["rows"][1][8] == "重复"


def test_subjects_and_relations_tables(client):
    task_id = _task_with_ledger(client)
    subjects = client.get(f"/api/reports/{task_id}/tables/subjects").json()
    assert subjects["row_count"] == 2
    assert subjects["rows"][0][1] == "监管部门"
    assert subjects["rows"][1][6] == 2  # 证据数

    relations = client.get(f"/api/reports/{task_id}/tables/relations").json()
    row = relations["rows"][0]
    assert row[0] == "监管部门" and row[1] == "涉事企业"  # 节点 id 已解析为标签
    assert row[2] == "调查施压" and row[3] == "negative" and row[6] == 1


def test_table_csv_output_is_utf8_sig(client):
    task_id = _task_with_ledger(client)
    resp = client.get(f"/api/reports/{task_id}/tables/sources?format=csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    text = resp.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0][0] == "编号" and rows[1][1] == "官方通报"


def test_unknown_table_id_and_legacy_report(client):
    task_id = _task_with_ledger(client)
    assert client.get(f"/api/reports/{task_id}/tables/nope").json()["error"] == "table_not_found"

    from app.db import SessionLocal
    from app.models import Task

    legacy = uuid.uuid4().hex
    with SessionLocal() as db:
        db.add(Task(id=legacy, title="旧报告", status="done", input_text="", result={"markdown": "# 旧"}))
        db.commit()
    body = client.get(f"/api/reports/{legacy}/tables/sources").json()
    assert body["row_count"] == 0
    assert body["research_status"] == "unavailable"


def test_narratives_table_share_formatting_and_applicable(client):
    """F15 叙事份额表：0~1 份额格式化为百分比、无份额显示「定性」；仅舆情/组合适用。"""
    from app.report_tables import ledger_rows, table_applicable

    ledger = {
        "narratives": [
            {"id": "nar1", "name": "受害者叙事", "stance": "supportive",
             "share": 0.45, "share_basis": "样本 20 条来源中 9 条", "source_ids": ["s1"]},
            {"id": "nar2", "name": "阴谋论叙事", "stance": "opposing",
             "share": None, "share_basis": "", "source_ids": []},
        ],
    }
    rows = ledger_rows("narratives", ledger)
    assert rows[0][0] == "受害者叙事" and rows[0][2] == "45%" and rows[0][3].startswith("样本")
    assert rows[1][2] == "定性"

    assert table_applicable("narratives", "opinion") is True
    assert table_applicable("narratives", "combo") is True
    assert table_applicable("narratives", "policy") is False
    assert table_applicable("sources", "policy") is True  # 基础三表全类型适用


def test_policy_clauses_table_rows_and_applicable(client):
    """F15 政策条款表：条款号/影响对象/利益变化/地域层级派生；仅政策/组合适用。"""
    from app.report_tables import ledger_rows, table_applicable

    ledger = {
        "policy_clauses": [
            {"id": "pc1", "clause_no": "第二条", "title": "奖补资金申领",
             "content_digest": "符合条件的企业可申领最高 50 万元奖补。",
             "target_groups": ["中小企业", "个体工商户"],
             "interest_change": "benefit", "region_level": "city",
             "effective_at": "2026-09-01", "confidence": "high"},
        ],
    }
    rows = ledger_rows("policy_clauses", ledger)
    row = rows[0]
    assert row[0] == "第二条" and row[1] == "奖补资金申领"
    assert "中小企业" in row[3] and "个体工商户" in row[3]
    assert row[4] == "benefit" and row[5] == "city" and row[6] == "2026-09-01"

    assert table_applicable("policy_clauses", "policy") is True
    assert table_applicable("policy_clauses", "case") is False


def test_timeline_table_and_region_derivation(client):
    """F15 事件时间线表：日期缺省「（未注明）」、转折点标注；地域列即时派生不改账本。"""
    from app.report_tables import ledger_rows, region_of, table_applicable

    ledger = {
        "nodes": [
            {"id": "n1", "label": "广东某制造企业", "role": "subject", "interests": ["奖补资金"]},
        ],
        "timeline": [
            {"id": "t1", "date": "2026-08-01", "title": "政策发布",
             "detail": "市政府印发措施", "actor_ids": ["n1"], "evidence_ids": ["s1"],
             "turning_point": True},
            {"id": "t2", "title": "企业递交申请", "actor_ids": [], "evidence_ids": []},
        ],
    }
    rows = ledger_rows("timeline", ledger)
    assert rows[0][0] == "2026-08-01" and rows[0][5] == "是"
    assert rows[0][3] == "广东某制造企业"  # actor id 已解析为标签
    assert rows[1][0] == "（未注明）" and rows[1][5] == ""

    # 地域派生：主体文本含省级名 → 识别为广东省；不改账本模型（市级属 F10）
    assert region_of(ledger["nodes"][0]) == "广东省"
    assert region_of({"label": "某企业"}) == ""
    assert table_applicable("timeline", "case") is True
    assert table_applicable("timeline", "org") is False


def test_word_data_tables_picks_by_analysis_type():
    """Word 附表：来源+主体恒选，政策报告选条款表、其余选时间线；空账本返回空列表。"""
    from app.report_tables import word_data_tables

    rich = {
        "sources": [{"id": "s1", "title": "公告", "url": "https://example.com/a"}],
        "nodes": [{"id": "n1", "label": "企业", "role": "subject"}],
        "timeline": [{"id": "t1", "date": "2026-08-01", "title": "发布"}],
        "policy_clauses": [{"id": "pc1", "title": "第二条 奖补"}],
    }
    policy_tables = word_data_tables(rich, "policy")
    assert [t["name"] for t in policy_tables] == ["来源证据表", "主体清单表", "政策条款表"]
    case_tables = word_data_tables(rich, "case")
    assert [t["name"] for t in case_tables] == ["来源证据表", "主体清单表", "事件时间线表"]

    assert word_data_tables({}, "case") == []
    assert word_data_tables(None, "case") == []
