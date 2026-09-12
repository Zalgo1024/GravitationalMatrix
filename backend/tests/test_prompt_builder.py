"""prompt_builder 单测（T4）：5 类型骨架哨兵逐一断言「所选类型命中哨兵标题」。

哨兵章节逐字取自 KERNEL parser._SECTION_IDS（SENTINEL_SECTIONS），
保证「前端所选类型 = LLM 提示词骨架 = 内核哨兵路由」双轨一致。
"""
import pytest

from app.prompt_builder import EXPECTED_CHAPTERS, SENTINEL_SECTIONS, build_system_prompt

ALL_TYPES = ("case", "policy", "org", "opinion", "combo")


def test_all_five_types_have_sentinel_definitions():
    for t in ALL_TYPES:
        assert t in SENTINEL_SECTIONS
        assert isinstance(SENTINEL_SECTIONS[t], list)


def test_sentinel_counts_match_design():
    assert len(SENTINEL_SECTIONS["case"]) == 4
    assert len(SENTINEL_SECTIONS["policy"]) == 2
    assert len(SENTINEL_SECTIONS["org"]) == 7
    assert len(SENTINEL_SECTIONS["opinion"]) == 6
    assert SENTINEL_SECTIONS["combo"] == []


@pytest.mark.parametrize("atype", ["case", "policy", "org", "opinion"])
def test_prompt_contains_all_sentinels(atype):
    """所选类型的系统提示词必须原样包含其全部哨兵章节标题。"""
    prompt = build_system_prompt(atype)
    for s in SENTINEL_SECTIONS[atype]:
        assert f"## {s}" in prompt, f"{atype} 提示词缺少哨兵章节：{s}"


def test_combo_prompt_requires_multi_type():
    """combo 提示词必须显式要求「至少 2 类哨兵混编」，而非强制单类。"""
    prompt = build_system_prompt("combo")
    assert "2 类" in prompt or "两类" in prompt or "至少" in prompt
    for section in ("核心冲突点", "三元结构分析正文", "行动建议", "附录"):
        assert f"## {section}" in prompt
    assert "短横线列表" in prompt


def test_org_prompt_has_full_nine_section_skeleton():
    prompt = build_system_prompt("org")
    assert "## 诊断结论" in prompt
    assert "## 附录" in prompt


def test_opinion_prompt_has_full_skeleton():
    prompt = build_system_prompt("opinion")
    assert "## 结论" in prompt
    assert "## 附录" in prompt


def test_expected_chapters():
    assert EXPECTED_CHAPTERS["org"] == 9
    assert EXPECTED_CHAPTERS["opinion"] == 7
    assert EXPECTED_CHAPTERS["combo"] == 0


def test_optional_sections_present_as_optional_not_sentinels():
    """账本 1.3：叙事份额/政策条款拆解为可选节——结构里有、哨兵集里没有。"""
    from app.prompt_builder import PROMPT_VERSION

    assert PROMPT_VERSION == "1.3"

    opinion_prompt = build_system_prompt("opinion")
    assert "## 叙事份额分析" in opinion_prompt
    assert "可选" in opinion_prompt
    # 不进哨兵集：不写不触发契约校验
    assert "叙事份额分析" not in SENTINEL_SECTIONS["opinion"]

    policy_prompt = build_system_prompt("policy")
    assert "## 政策条款拆解" in policy_prompt
    assert "可选" in policy_prompt
    assert "政策条款拆解" not in SENTINEL_SECTIONS["policy"]

    # 可选节标注了降级规则：无法量化/无证据时省略，不得编造
    assert "省略" in opinion_prompt or "整节省略" in opinion_prompt
    assert "省略" in policy_prompt or "整节省略" in policy_prompt
