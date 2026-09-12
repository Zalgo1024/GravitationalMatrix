"""第六阶段：生成器拆分的独立单元验证。

验证 generate / extract_network / validate / export 四个阶段可独立调用、
边界清晰，且 generate_and_export 编排后返回结构向后兼容。
"""
import json
import os
from pathlib import Path

import pytest

from app import rule_engine
from app.generator import ReportGenerator
from app.llm_client import MockClient
from app.report_quality import ReportQualityError

FIX = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def _gen(sample: dict) -> ReportGenerator:
    si = rule_engine.StructuredInput.model_validate(sample)
    return ReportGenerator(
        None, analysis_type=sample.get("analysis_type", "case"), mode="rule", structured=si
    )


def test_generate_returns_markdown():
    sample = _load("sample_event")
    gen = _gen(sample)
    md = gen.generate(title=sample["title"])
    assert isinstance(md, str) and md.strip()
    assert md.lstrip().startswith("# ")  # _normalize 保证以一级标题开头


def test_extract_network_parses_diagram():
    sample = _load("sample_event")
    gen = _gen(sample)
    md = gen.generate(title=sample["title"])
    net = gen.extract_network(md)
    assert "diagram" in net and "valid" in net
    # 规则引擎产物必含 DIAGRAM 区块
    assert net["valid"] is True
    assert "```" not in net["diagram"]  # 已剥离代码围栏


def test_extract_network_handles_missing_diagram():
    sample = _load("sample_event")
    gen = _gen(sample)
    net = gen.extract_network("# 标题\n\n无网络区块的正文")
    assert net["valid"] is False
    assert net["diagram"] is None


def test_validate_returns_contract():
    sample = _load("sample_event")
    gen = _gen(sample)
    gen.generate(title=sample["title"])
    contract = gen.validate()
    assert isinstance(contract, dict)
    assert "valid" in contract
    assert contract["engine_used"] == "rule"


def test_validate_before_generate_returns_fallback():
    gen = _gen(_load("sample_event"))
    contract = gen.validate()
    assert contract["valid"] is False
    assert contract["engine_used"] is None


def test_generate_and_export_orchestrates_and_is_compatible(tmp_path):
    sample = _load("sample_event")
    gen = _gen(sample)
    out = gen.generate_and_export(title=sample["title"], output_dir=str(tmp_path), slug="split_event")
    # 向后兼容字段齐全
    assert out["markdown"]
    assert out["contract"]["valid"] is True
    assert out["engine_used"] == "rule"
    assert out["degraded_from_llm"] is False
    # 新增 network 阶段产物
    assert out["network"]["valid"] is True
    assert out["research"]["schema_version"] == "1.4"
    assert out["research"]["status"] == "fallback"
    # 引擎导出契约字段
    assert isinstance(out.get("pdf_available"), bool)
    assert out.get("word") and os.path.exists(out["word"])


def test_llm_research_extraction_binds_claims_to_material_sources():
    class LedgerLlm:
        def generate(self, system, user, temperature=0.2):
            assert "只返回 JSON" in system
            assert "nodes" in system
            assert "timeline" in system
            assert "strength" in system
            assert "s1" in user
            return json.dumps(
                {
                    "sources": [
                        {
                            "id": "s1",
                            "title": "官方公告",
                            "url": "https://example.com/a",
                            "source_type": "official",
                            "source_level": "primary",
                            "excerpt": "公告确认事件发生。",
                        }
                    ],
                    "claims": [
                        {
                            "id": "c1",
                            "text": "事件已经发生",
                            "claim_type": "fact",
                            "confidence": "high",
                            "evidence_ids": ["s1"],
                        }
                    ],
                    "nodes": [
                        {
                            "id": "platform",
                            "label": "平台公司",
                            "role": "规则制定者",
                            "interests": ["治理效率"],
                            "stance": "执行公告",
                            "weight": 0.8,
                            "confidence": "high",
                            "evidence_ids": ["s1"],
                        }
                    ],
                    "relations": [
                        {
                            "id": "r1",
                            "source_node": "platform",
                            "target_node": "users",
                            "label": "规则约束",
                            "strength": 4,
                            "interest_types": ["power", "legal"],
                            "direction": "directed",
                            "polarity": "mixed",
                            "confidence": "high",
                            "evidence_ids": ["s1"],
                            "claim_id": "c1",
                            "status": "confirmed",
                        }
                    ],
                    "timeline": [
                        {
                            "id": "t1",
                            "date": "2026-08-10",
                            "title": "公告发布",
                            "actor_ids": ["platform"],
                            "claim_ids": ["c1"],
                            "evidence_ids": ["s1"],
                            "confidence": "high",
                            "turning_point": True,
                        }
                    ],
                    "gaps": [],
                },
                ensure_ascii=False,
            )

    gen = ReportGenerator(
        None,
        analysis_type="case",
        mode="llm",
        materials={
            "items": [
                {
                    "title": "官方公告",
                    "url": "https://example.com/a",
                    "text": "公告确认事件发生。",
                    "kept": True,
                }
            ],
            "sources": [{"title": "官方公告", "url": "https://example.com/a"}],
        },
    )
    gen._generation_llm = LedgerLlm()
    gen._engine_meta = {"engine_used": "llm"}

    ledger = gen.build_research_ledger("# 报告\n\n## 结论\n\n事件已经发生。", "分析事件")

    assert ledger.status == "verified"
    assert ledger.claims[0].evidence_ids == ["s1"]
    assert ledger.nodes[0].weight == 0.8
    assert ledger.relations[0].strength == 4
    assert ledger.timeline[0].turning_point is True
    assert ledger.metrics.key_claim_evidence_coverage == 1.0


def test_llm_research_extraction_skips_llm_without_verifiable_sources():
    class BrokenLedgerLlm:
        def __init__(self):
            self.calls = 0

        def generate(self, system, user, temperature=0.2):
            self.calls += 1
            return "这不是 JSON"

    llm = BrokenLedgerLlm()
    gen = ReportGenerator(None, analysis_type="case", mode="llm")
    gen._generation_llm = llm
    gen._engine_meta = {"engine_used": "llm"}

    ledger = gen.build_research_ledger("# 报告", "用户提供的待核验信息")

    assert llm.calls == 0
    assert ledger.status == "no_evidence"
    assert ledger.claims[0].claim_type == "user_input"
    assert any("没有可核验来源" in warning for warning in ledger.warnings)


def test_research_catalog_never_trusts_urls_hallucinated_in_report_markdown():
    gen = ReportGenerator(
        None,
        analysis_type="case",
        mode="llm",
        materials={
            "items": [
                {
                    "title": "已抓取来源",
                    "url": "https://source.example/verified",
                    "text": "这是一段已经抓取并保留的来源正文。",
                    "kept": True,
                }
            ],
            "sources": [
                {"title": "已抓取来源", "url": "https://source.example/verified"}
            ],
        },
    )

    catalog = gen._research_source_catalog(
        "# 报告\n\n## 附录\n\n- [模型编造来源](https://fake.example/not-fetched)"
    )

    assert [item["url"] for item in catalog] == ["https://source.example/verified"]


def test_unverified_markdown_links_are_removed_from_report_text():
    gen = ReportGenerator(
        None,
        analysis_type="case",
        mode="llm",
        materials={
            "items": [
                {
                    "title": "已抓取来源",
                    "url": "https://source.example/verified",
                    "text": "这是一段已经抓取并保留的来源正文。",
                    "kept": True,
                }
            ],
            "sources": [
                {"title": "已抓取来源", "url": "https://source.example/verified"}
            ],
        },
    )

    cleaned = gen._sanitize_unverified_links(
        "[已核验](https://source.example/verified)\n[模型编造](https://fake.example/not-fetched)"
    )

    assert "[已核验](https://source.example/verified)" in cleaned
    assert "https://fake.example/not-fetched" not in cleaned
    assert "模型编造" in cleaned


def test_freeform_llm_failure_never_degrades_to_rule(monkeypatch):
    monkeypatch.setattr(
        "app.llm_client.create_llm_from_config", lambda _config=None: MockClient()
    )
    gen = ReportGenerator(None, analysis_type="case", mode="llm", structured=None)

    with pytest.raises(ValueError, match="自由输入"):
        gen.generate("分析这个事件", "自由输入报告")


def test_structured_llm_failure_can_degrade_to_rule(monkeypatch):
    sample = _load("sample_event")
    structured = rule_engine.StructuredInput.model_validate(sample)
    monkeypatch.setattr(
        "app.llm_client.create_llm_from_config", lambda _config=None: MockClient()
    )
    gen = ReportGenerator(
        None,
        analysis_type="case",
        mode="llm",
        structured=structured,
    )

    markdown = gen.generate("", sample["title"])

    assert markdown.startswith("# ")
    assert gen.validate()["engine_used"] == "rule"
    assert gen.validate()["degraded_from_llm"] is True


def test_rule_generation_attaches_a_passing_quality_result():
    sample = _load("sample_event")
    gen = _gen(sample)

    gen.generate(title=sample["title"])

    assert gen.quality().valid is True
    assert gen.quality().score > 0


def test_rule_generation_rejects_a_broken_template(monkeypatch):
    sample = _load("sample_event")
    gen = _gen(sample)
    monkeypatch.setattr(
        rule_engine,
        "generate",
        lambda _structured: "# 失败报告\n\n## 结论\n\n（未提供分析）",
    )

    with pytest.raises(ReportQualityError):
        gen.generate(title=sample["title"])


def test_llm_quality_failure_gets_at_most_two_targeted_revisions(monkeypatch):
    sample = _load("sample_event")
    valid = rule_engine.generate(rule_engine.StructuredInput.model_validate(sample))
    invalid = valid.replace("图 1", "下图")

    class SequenceLlm:
        def __init__(self):
            self.calls = []
            self.responses = [invalid, invalid, valid]

        def generate(self, system, user, temperature=0.2):
            self.calls.append(user)
            return self.responses.pop(0)

    llm = SequenceLlm()
    monkeypatch.setattr("app.llm_client.create_llm_from_config", lambda _config=None: llm)
    gen = ReportGenerator(None, analysis_type="case", mode="llm", structured=None)

    markdown = gen.generate("分析这个事件", sample["title"])

    assert markdown
    assert len(llm.calls) == 3
    assert "figure_reference" in llm.calls[1]
    assert gen.quality().valid is True


def test_llm_repairs_use_stable_low_temperature(monkeypatch):
    sample = _load("sample_event")
    valid = rule_engine.generate(rule_engine.StructuredInput.model_validate(sample))
    invalid = valid.replace("图 1", "下图")

    class SequenceLlm:
        def __init__(self):
            self.temperatures = []
            self.responses = [invalid, invalid, valid]

        def generate(self, system, user, temperature=0.2):
            self.temperatures.append(temperature)
            return self.responses.pop(0)

    llm = SequenceLlm()
    monkeypatch.setattr("app.llm_client.create_llm_from_config", lambda _config=None: llm)
    gen = ReportGenerator(None, analysis_type="case", mode="llm", structured=None)

    assert gen.generate("分析这个事件", sample["title"])
    assert len(llm.temperatures) == 3
    assert llm.temperatures[1] == llm.temperatures[2]
    assert llm.temperatures[1] <= 0.3


def test_empty_llm_output_never_becomes_an_exportable_report(monkeypatch, tmp_path):
    class EmptyLlm:
        def generate(self, system, user, temperature=0.2):
            return ""

    monkeypatch.setattr("app.llm_client.create_llm_from_config", lambda _config=None: EmptyLlm())
    gen = ReportGenerator(None, analysis_type="case", mode="llm", structured=None)

    with pytest.raises(ValueError, match="自由输入的 LLM 生成失败"):
        gen.generate_and_export("分析这个事件", "空报告测试", str(tmp_path), "empty")


def test_ai_revise_also_runs_the_quality_revision_loop(monkeypatch):
    sample = _load("sample_event")
    valid = rule_engine.generate(rule_engine.StructuredInput.model_validate(sample))
    invalid = valid.replace("图 1", "下图")

    class SequenceLlm:
        def __init__(self):
            self.calls = []
            self.responses = [invalid, valid]

        def generate(self, system, user, temperature=0.2):
            self.calls.append(user)
            return self.responses.pop(0)

    llm = SequenceLlm()
    monkeypatch.setattr("app.llm_client.create_llm_from_config", lambda _config=None: llm)
    gen = ReportGenerator(None, analysis_type="case", mode="llm")

    revised = gen.revise(valid, "压缩重复内容", sample["title"])

    assert revised
    assert len(llm.calls) == 2
    assert "figure_reference" in llm.calls[1]
    assert gen.quality().valid is True
