from app import rule_engine
from app.generator import ReportGenerator


def test_export_retry_does_not_repeat_report_generation(monkeypatch, sample_event):
    structured = rule_engine.StructuredInput.model_validate(sample_event)
    gen = ReportGenerator(
        None,
        analysis_type=sample_event["analysis_type"],
        mode="rule",
        structured=structured,
    )
    original_generate = gen.generate
    calls = {"generate": 0, "export": 0}

    def counted_generate(input_text="", title=None, region_scope=None):
        calls["generate"] += 1
        return original_generate(input_text, title)

    def flaky_export(markdown, title=None, output_dir=None, slug=None, data_tables=None, geo_map=None):
        calls["export"] += 1
        if calls["export"] == 1:
            raise OSError("docx is temporarily locked")
        return {"word": "report.docx", "pdf_available": False}

    monkeypatch.setattr(gen, "generate", counted_generate)
    monkeypatch.setattr(gen, "export", flaky_export)
    monkeypatch.setattr("app.generator.time.sleep", lambda _seconds: None)

    out = gen.generate_and_export(title=sample_event["title"])

    assert out["word"] == "report.docx"
    assert calls == {"generate": 1, "export": 2}


def _generator(sample_event):
    structured = rule_engine.StructuredInput.model_validate(sample_event)
    return ReportGenerator(
        None,
        analysis_type=sample_event["analysis_type"],
        mode="rule",
        structured=structured,
    )


def test_geo_map_is_threaded_to_export(monkeypatch, sample_event):
    """F11：地域聚合必须真的走到导出层，否则 Word 附录永远拿不到地图。"""
    gen = _generator(sample_event)
    captured = {}

    def capture_export(markdown, title=None, output_dir=None, slug=None, data_tables=None, geo_map=None):
        captured["geo_map"] = geo_map
        return {"word": "report.docx", "pdf_available": False}

    monkeypatch.setattr(gen, "export", capture_export)
    gen.generate_and_export(title=sample_event["title"])

    assert isinstance(captured.get("geo_map"), dict), "geo_map 未传到导出层"
    assert {"regions", "coverage"} <= set(captured["geo_map"])


def test_geo_derivation_failure_degrades_to_none(monkeypatch, sample_event):
    """附录是可选件：派生地域失败必须降级为 None，不能拖垮整份交付。"""
    gen = _generator(sample_event)
    captured = {}

    def boom(_ledger):
        raise RuntimeError("geo aggregation blew up")

    def capture_export(markdown, title=None, output_dir=None, slug=None, data_tables=None, geo_map=None):
        captured["geo_map"] = geo_map
        return {"word": "report.docx", "pdf_available": False}

    monkeypatch.setattr("app.generator.geo_aggregation", boom)
    monkeypatch.setattr(gen, "export", capture_export)

    out = gen.generate_and_export(title=sample_event["title"])

    assert out["word"] == "report.docx"
    assert captured["geo_map"] is None
