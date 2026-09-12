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
    first = body["rows"][0]
    assert first[0] == "s1" and first[3] == "official" and first[4] == "A"
    assert first[7] == "首发"
    assert body["rows"][1][7] == "重复"


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
