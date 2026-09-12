"""
文本解析器 — 将 Markdown 格式的案例/政策分析正文解析为结构化数据。

解析规则：
1. 按 ## 标题拆分为章节
2. 识别特殊块类型：引用块（>）、表格、DIAGRAM JSON 代码块、列表
3. 每个章节包含：标题 + 有序的块列表（段落/引用/表格/图表/列表）

用法:
    from parser import parse_report
    report = parse_report("# 标题\\n\\n## 案例事实摘要\\n...")
    report.sections["fact_summary"].blocks  # [Block, ...]
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Optional


# ── 数据类型定义 ──────────────────────────────────────────────

BlockType = Literal["paragraph", "quote", "table", "diagram", "list", "heading", "blank", "subheading"]


_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


_RE_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")        # [text](url)


@dataclass
class Block:
    """分析正文中的一个内容块。"""
    type: BlockType
    text: str = ""
    rows: Optional[list[list[str]]] = None       # 表格行
    diagram_data: Optional[dict] = None           # DIAGRAM JSON
    items: Optional[list[str]] = None             # 列表项
    level: int = 2                                # heading 级别
    sub_section_id: Optional[str] = None          # 政策对象图谱子维度标识
    segments: Optional[list[tuple[str, Optional[str]]]] = None  # 超链接分段 [(text, url_or_None)]


@dataclass
class Section:
    """一个二级标题及其下所有内容块。"""
    title: str
    blocks: list[Block] = field(default_factory=list)
    cid: Optional[str] = None            # canonical id（新增：源序组合用）
    mode: Optional[str] = None           # 归属模式：policy/event/org/opinion/None(共享)（新增）


@dataclass
class ParsedReport:
    """解析后的完整报告数据。"""
    title: str                              # 报告标题（# 一级标题）
    sections: dict[str, Section] = field(default_factory=dict)
    """章节字典（兼容视图，last-wins）。组合稿同名段只保留最后写入者；精确遍历请用 section_seq。"""
    section_seq: list[Section] = field(default_factory=list)
    """按出现顺序的有序段落列表（源序组合核心；同名段并存，不再互相覆盖）。"""
    _cid_index: set[str] = field(default_factory=set)
    """所有出现过的 canonical id 集合（渲染器哨兵检测用）。"""
    raw_text: str = ""
    tone: str = "neutral"
    """分析基调：neutral=客观中立 / provocative=煽动性。仅作元数据记录与封面标注，不改变报告结构。"""


# ── 章节标识映射 ─────────────────────────────────────────────

_SECTION_IDS: dict[str, str] = {
    "情况概述": "overview",
    "案例事实摘要": "fact_summary",
    "事实摘要": "fact_summary",
    "独立事实摘要": "fact_summary",
    "证据与依据": "evidence",
    "分析框架": "framework",
    "分析框架说明": "framework",
    "三元结构分析正文": "analysis_body",
    "核心冲突点": "core_conflicts",
    "行动建议": "recommendations",
    "政策对象图谱": "policy_portrait",
    "政策条款拆解": "policy_clause_breakdown",
    "政策权重与空间分析": "policy_weight",
    # ── 深度事件分析新增章节（对标政策分析的对象图谱/权重空间） ──
    "利益主体识别": "case_portrait",
    "利益主体图谱": "case_portrait",
    "利益关系图谱": "case_portrait",
    "利益动线与转化": "case_flows",
    "利益动线": "case_flows",
    "利益流动分析": "case_flows",
    "制度与叙事作用": "case_dynamics",
    "动力机制分析": "case_dynamics",
    "动力机制": "case_dynamics",
    # ── 组织诊断新增章节（九段式） ──
    "组织画像": "org_portrait",
    "组织架构拆解": "org_structure",
    "架构拆解与资金来源": "org_structure",
    "资金来源分析": "org_structure",
    "生存诊断": "org_survival",
    "繁衍诊断": "org_reproduction",
    "利益关系网络": "org_interest_network",
    "利益关系网络与利益集团拆解": "org_interest_network",
    "利益集团拆解": "org_interest_network",
    "逆反诊断": "org_reverse",
    "利益转化与组织社会关系": "org_transformation",
    "利益转化与组织—社会关系": "org_transformation",
    # ── 舆情分析新增章节（七段式） ──
    "事件与时间线": "opinion_event",
    "舆情事实摘要": "opinion_event",
    "事实与时间线": "opinion_event",
    "利益主体与沉默方": "opinion_actors",
    "舆论主体与沉默方": "opinion_actors",
    "发声者与沉默方": "opinion_actors",
    "叙事竞争矩阵": "opinion_narrative",
    "舆论叙事矩阵": "opinion_narrative",
    "叙事战场": "opinion_narrative",
    "叙事份额分析": "opinion_narrative_share",
    "三元生命维度": "opinion_trilife",
    "舆论的三元生命维度": "opinion_trilife",
    "三元生命维度（舆论作为活体）": "opinion_trilife",
    "逆反性质与层级": "opinion_reverse",
    "舆论逆反性质": "opinion_reverse",
    "演化曲线与系统回应": "opinion_evolution",
    "舆情演化曲线": "opinion_evolution",
    "结论": "conclusion",
    "诊断结论": "conclusion",
    "结论与推导": "conclusion",
    "核心判断": "conclusion",
    "核心判断与走向": "conclusion",
    "附录": "appendix",
    "附录/数据溯源": "appendix",
    "数据来源": "appendix",
}

# 反向：识别章节标题
_SECTION_TITLES = set(_SECTION_IDS.keys())

# ── 政策对象图谱子维度标识映射 ──────────────────────────────

_POLICY_SUBSECTION_IDS: dict[str, str] = {
    "基本信息": "basic_info",
    "发布主体": "publisher_profile",
    "受影响群体": "affected_groups",
    "行业影响矩阵": "industry_matrix",
    "时间维度预判": "timeline",
    "核心张力": "core_tension",
    "核心命题": "core_proposition",
    "概念选择表": "concept_table",
    "汇流段": "confluence",
    "博弈终局预判": "game_forecast",
    "可传播金句": "golden_sentence",
    "权重层级判定": "weight_level",
    "操作空间评估": "operation_space",
    "竞合政策关系图": "competition_map",
}

# ── 四分法子项标识映射 ────────────────────────────────────────

_AFFECTED_GROUP_IDS: dict[str, str] = {
    "政策发布方": "policy_issuer",
    "既得利益群体": "beneficiary",
    "利益受损群体": "loser",
    "不相关群体": "unaffected",
}


def _mode_of(cid: str) -> Optional[str]:
    """根据 canonical id 前缀判定归属模式；共享键（fact_summary/framework/analysis_body/conclusion/appendix）返回 None。"""
    if cid.startswith("opinion_"):
        return "opinion"
    if cid.startswith("org_"):
        return "org"
    if cid.startswith("case_"):
        return "event"
    if cid.startswith("policy_"):
        return "policy"
    return None


def _detect_section_id(title: str) -> str:
    """根据标题文本识别章节标识符。"""
    title_stripped = title.strip().rstrip(":").strip()
    if title_stripped in _SECTION_IDS:
        return _SECTION_IDS[title_stripped]
    # 模糊匹配：标题包含已知关键词
    for keyword, sid in _SECTION_IDS.items():
        if keyword in title_stripped:
            return sid
    # 无法识别 → 使用标题的 slug
    slug = re.sub(r"[^\w\u4e00-\u9fff]", "_", title_stripped).strip("_").lower()
    return slug if slug else "unknown"


def _detect_subsection_id(title: str) -> Optional[str]:
    """检测政策对象图谱的子维度标识。"""
    title_stripped = title.strip().rstrip(":").strip()
    # 精确匹配
    if title_stripped in _POLICY_SUBSECTION_IDS:
        return _POLICY_SUBSECTION_IDS[title_stripped]
    # 模糊匹配
    for keyword, sid in _POLICY_SUBSECTION_IDS.items():
        if keyword in title_stripped:
            return sid
    # 四分法子项匹配
    if title_stripped in _AFFECTED_GROUP_IDS:
        return _AFFECTED_GROUP_IDS[title_stripped]
    for keyword, sid in _AFFECTED_GROUP_IDS.items():
        if keyword in title_stripped:
            return sid
    return None


# ── 行解析 ───────────────────────────────────────────────────

def _is_table_line(line: str) -> bool:
    """判断是否为表格行（含 | 分隔符）。"""
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 3


def _is_separator_line(line: str) -> bool:
    """判断是否为表格分隔行（|---|）。"""
    return bool(re.match(r"^\|[\s\-:]+\|", line.strip()))


def _parse_table_row(line: str) -> list[str]:
    """解析 | a | b | c | 为 ['a', 'b', 'c']。"""
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return cells


def _is_diagram_start(line: str) -> bool:
    """判断是否为 DIAGRAM JSON 代码块起始行。"""
    return line.strip().startswith("```DIAGRAM") or line.strip().startswith("```diagram")


def _is_list_item(line: str) -> bool:
    """判断是否为列表项。"""
    stripped = line.strip()
    return bool(re.match(r"^[\-\*]\s", stripped)) or bool(re.match(r"^\d+[\.\、]\s", stripped))


def _is_quote_line(line: str) -> bool:
    """判断是否为引用行。"""
    return line.strip().startswith(">")


# ── 主解析函数 ───────────────────────────────────────────────

def _parse_link_segments(text: str) -> list[tuple[str, Optional[str]]]:
    """将文本按 [text](url) 链接拆分为分段列表。

    返回: [(片段文字, None 或 URL), ...]
    """
    segments: list[tuple[str, Optional[str]]] = []
    last_end = 0
    for m in _LINK_PATTERN.finditer(text):
        start, end = m.start(), m.end()
        if start > last_end:
            segments.append((text[last_end:start], None))
        segments.append((m.group(1), m.group(2)))
        last_end = end
    if last_end < len(text):
        segments.append((text[last_end:], None))
    return segments if segments else [(text, None)]

def parse_report(text: str) -> ParsedReport:
    """将 Markdown 正文解析为结构化报告数据。

    Args:
        text: 完整的 Markdown 文本，包含 # 一级标题和 ## 二级章节。

    Returns:
        ParsedReport 实例。
    """
    lines = text.split("\n")
    title = ""
    current_section: Optional[Section] = None
    sections: dict[str, Section] = {}
    section_seq: list[Section] = []        # 源序组合：有序段落列表
    cid_index: set[str] = set()           # 源序组合：cid 出现集合

    # 解析状态机
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # ── 一级标题（报告标题） ──
        if stripped.startswith("# ") and not stripped.startswith("## "):
            title = stripped[2:].strip()
            i += 1
            continue

        # ── 二级标题（章节开始） ──
        if stripped.startswith("## ") and not stripped.startswith("### "):
            sec_title = re.sub(r"^##\s*", "", stripped).strip()
            sec_id = _detect_section_id(sec_title)
            current_section = Section(title=sec_title, cid=sec_id, mode=_mode_of(sec_id))
            sections[sec_id] = current_section          # 兼容视图（last-wins）
            section_seq.append(current_section)          # 有序列表：同名段不再互相覆盖
            cid_index.add(sec_id)
            i += 1
            continue

        # ── 三级标题（子维度 / 子章节） ──
        if stripped.startswith("### "):
            sub_title = re.sub(r"^###\s*", "", stripped).strip()
            sub_id = _detect_subsection_id(sub_title)
            if current_section is not None:
                current_section.blocks.append(
                    Block(type="subheading", text=sub_title, sub_section_id=sub_id)
                )
            i += 1
            continue

        # ── 空行 ──
        if not stripped:
            if current_section is not None:
                current_section.blocks.append(Block(type="blank"))
            i += 1
            continue

        # ── DIAGRAM JSON 块 ──
        if _is_diagram_start(line):
            json_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                json_lines.append(lines[i])
                i += 1
            i += 1  # 跳过结尾 ```
            json_text = "\n".join(json_lines).strip()
            diagram_data: Optional[dict] = None
            try:
                diagram_data = json.loads(json_text)
            except json.JSONDecodeError:
                # 回退：作为普通段落
                if current_section is not None:
                    current_section.blocks.append(
                        Block(type="paragraph", text=f"```DIAGRAM\n{json_text}\n```")
                    )
                continue
            if current_section is not None:
                current_section.blocks.append(
                    Block(type="diagram", diagram_data=diagram_data)
                )
            continue

        # ── 普通代码块（非 DIAGRAM，如 ```python ... ```） ──
        # 保留围栏与内容作为 code 块，避免开/闭围栏被丢弃、内容错乱进正文
        if stripped.startswith("```"):
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # 跳过结尾 ```
            if current_section is not None:
                content = "\n".join(code_lines).strip("\n")
                current_section.blocks.append(
                    Block(type="code", text=f"```{stripped[3:].strip()}\n{content}\n```")
                )
            continue

        # ── 表格 ──
        if _is_table_line(line):
            rows: list[list[str]] = []
            rows.append(_parse_table_row(line))
            i += 1
            # 跳过分隔行
            if i < len(lines) and _is_separator_line(lines[i]):
                i += 1
            # 继续读取表格行
            while i < len(lines) and _is_table_line(lines[i]):
                rows.append(_parse_table_row(lines[i]))
                i += 1
            if current_section is not None:
                current_section.blocks.append(
                    Block(type="table", rows=rows)
                )
            continue

        # ── 引用块 ──
        if _is_quote_line(line):
            quote_lines: list[str] = []
            while i < len(lines) and _is_quote_line(lines[i]):
                ql = lines[i].strip()
                if ql.startswith("> "):
                    quote_lines.append(ql[2:])
                elif ql.startswith(">"):
                    quote_lines.append(ql[1:])
                i += 1
            if current_section is not None:
                current_section.blocks.append(
                    Block(type="quote", text="\n".join(quote_lines))
                )
            continue

        # ── 列表 ──
        if _is_list_item(line):
            items: list[str] = []
            while i < len(lines) and _is_list_item(lines[i]):
                item_text = re.sub(r"^[\-\*]\s+", "", lines[i].strip())
                item_text = re.sub(r"^\d+[\.\、]\s+", "", item_text)
                items.append(item_text)
                i += 1
            if current_section is not None:
                # 为列表项提取链接分段
                item_segments = [_parse_link_segments(it) for it in items]
                current_section.blocks.append(
                    Block(type="list", items=items,
                          segments=item_segments if any(
                              any(u is not None for _, u in s) for s in item_segments
                          ) else None)
                )
            continue

        # ── 普通段落 ──
        para_lines: list[str] = []
        while (
            i < len(lines)
            and lines[i].strip()
            and not lines[i].strip().startswith("## ")
            and not lines[i].strip().startswith("### ")
            and not _is_table_line(lines[i])
            and not _is_quote_line(lines[i])
            and not _is_list_item(lines[i])
            and not _is_diagram_start(lines[i])
            and not lines[i].strip().startswith("```DIAGRAM")
            and not lines[i].strip().startswith("```")
        ):
            # 遇到下一个 ## 或 ### 标题或块类型标记就停
            if lines[i].strip().startswith("## ") or lines[i].strip().startswith("### "):
                break
            para_lines.append(lines[i].rstrip())
            i += 1
        para_text = "\n".join(para_lines).strip()
        if para_text and current_section is not None:
            # 检查是否包含粗体、箭头标记、超链接等富文本（交给渲染器处理）
            segments = _parse_link_segments(para_text)
            has_link = any(url is not None for _, url in segments)
            current_section.blocks.append(
                Block(
                    type="paragraph", text=para_text,
                    segments=segments if has_link else None,
                )
            )
        continue

    return ParsedReport(
        title=title,
        sections=sections,
        section_seq=section_seq,
        _cid_index=cid_index,
        raw_text=text,
    )


def get_section(report: ParsedReport, section_id: str) -> Optional[Section]:
    """按标识符获取章节。"""
    return report.sections.get(section_id)


def get_section_text(report: ParsedReport, section_id: str) -> str:
    """获取章节的纯文本内容（忽略格式）。"""
    sec = get_section(report, section_id)
    if sec is None:
        return ""
    parts: list[str] = []
    for block in sec.blocks:
        if block.type == "paragraph":
            parts.append(block.text)
        elif block.type == "quote":
            parts.append(block.text)
        elif block.type == "code":
            parts.append(block.text)
        elif block.type == "table" and block.rows:
            for row in block.rows:
                parts.append(" | ".join(row))
        elif block.type == "list" and block.items:
            parts.extend(block.items)
    return "\n".join(parts)
