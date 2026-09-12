"""F12 后端支撑：主体地域派生 + 关系跨省标记（账本 1.4）。"""

from app.research_ledger import normalize_research_ledger


def _source(sid: str, title: str, group: str | None = None) -> dict:
    return {
        "id": sid,
        "title": title,
        "url": f"https://example.com/{sid}",
        "source_type": "mainstream_media",
        "independence_group": group or sid,
        "excerpt": f"{title}相关报道正文。",
    }


def _node(nid: str, label: str, evidence: list[str], region_code: str | None = None) -> dict:
    raw = {"id": nid, "label": label, "role": "当事方", "evidence_ids": evidence, "weight": 0.6}
    if region_code:
        raw["region_code"] = region_code
    return raw


def _relation(rid: str, source: str, target: str) -> dict:
    return {"id": rid, "source_node": source, "target_node": target, "label": "施压", "status": "inferred"}


def test_model_region_code_is_normalized_to_province():
    ledger = normalize_research_ledger(
        {
            "sources": [_source("s1", "广东省能源集团公告")],
            "nodes": [_node("n1", "某市企业", ["s1"], region_code="441300")],
            "relations": [],
        }
    )
    node = ledger.nodes[0]
    assert node.region_code == "440000"
    assert node.region_name == "广东省"
    assert node.region_source == "model"


def test_region_is_derived_from_evidence_majority():
    ledger = normalize_research_ledger(
        {
            "sources": [
                _source("s1", "广东省发改委通报"),
                _source("s2", "广东省财政厅回应"),
                _source("s3", "浙江省媒体评论"),
            ],
            "nodes": [_node("n1", "涉事企业", ["s1", "s2", "s3"])],
            "relations": [],
        }
    )
    node = ledger.nodes[0]
    assert node.region_code == "440000"
    assert node.region_source == "evidence_majority"
    assert ledger.metrics.node_region_coverage == 1.0


def test_bogus_model_region_code_is_rejected_and_derived_instead():
    ledger = normalize_research_ledger(
        {
            "sources": [_source("s1", "四川省本地媒体报道")],
            "nodes": [_node("n1", "涉事企业", ["s1"], region_code="999999")],
            "relations": [],
        }
    )
    node = ledger.nodes[0]
    assert node.region_source == "evidence_majority"
    assert node.region_code == "510000"


def test_cross_region_marks_difference_and_stays_unknown_when_missing():
    ledger = normalize_research_ledger(
        {
            "sources": [
                _source("s1", "广东省发改委通报"),
                _source("s2", "浙江省企业声明"),
            ],
            "nodes": [
                _node("n1", "广东一方", ["s1"]),
                _node("n2", "浙江一方", ["s2"]),
                _node("n3", "属地未知方", []),
            ],
            "relations": [
                _relation("r1", "n1", "n2"),
                _relation("r2", "n1", "n1"),
                _relation("r3", "n1", "n3"),
            ],
        }
    )
    by_id = {relation.id: relation for relation in ledger.relations}
    assert by_id["r1"].cross_region is True
    assert by_id["r2"].cross_region is False
    assert by_id["r3"].cross_region is None
    assert ledger.metrics.cross_region_relation_count == 1


def test_legacy_1_3_snapshot_stays_region_free():
    """旧快照没有地域字段：不报错、不臆造，覆盖率如实为 0。"""
    ledger = normalize_research_ledger(
        {
            "schema_version": "1.3",
            "sources": [_source("s1", "一份没有地域线索的材料")],
            "nodes": [_node("n1", "某主体", ["s1"])],
            "relations": [_relation("r1", "n1", "n1")],
        }
    )
    assert ledger.nodes[0].region_code is None
    assert ledger.nodes[0].region_source == "unknown"
    assert ledger.relations[0].cross_region is None
    assert ledger.metrics.node_region_coverage == 0.0
