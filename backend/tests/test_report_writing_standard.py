from app.prompt_builder import PROMPT_VERSION, build_system_prompt


def test_case_prompt_embeds_the_report_writing_standard():
    prompt = build_system_prompt("case")

    # 版本只增不减：1.2（写作规格）→ 1.3（可选哨兵节）→ 1.4（地域范围约束段）
    assert PROMPT_VERSION >= "1.2"
    assert "报告是分析骨架，不是素材搬运" in prompt
    assert "## 情况概述" in prompt
    assert "## 核心冲突点" in prompt
    assert "## 行动建议" in prompt
    assert "不得用任何“未提供、未标注、建议补充、结构占位、依据不足”占位句" in prompt
