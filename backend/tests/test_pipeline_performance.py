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

    def counted_generate(input_text="", title=None):
        calls["generate"] += 1
        return original_generate(input_text, title)

    def flaky_export(markdown, title=None, output_dir=None, slug=None, data_tables=None):
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
