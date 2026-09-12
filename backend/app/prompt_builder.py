"""提示词装配 — 把 analysis_prompt.md 的「写作铁律 + DIAGRAM 格式」与
theory_config.json 的「概念池 / 利益类型 / 节点边类型」组装成系统提示词。

设计要点：
- analysis_prompt.md 是单一真相源（案例型规则），运行时读取，不复制。
- 5 类型骨架（T4）：case/policy/org/opinion/combo，各自换一套报告结构；
- **双轨护栏**：SENTINEL_SECTIONS 逐字取自 KERNEL parser._SECTION_IDS，
  系统提示词强制产出与所选类型匹配的哨兵章节标题（org 7 项 / opinion 6 项 /
  case 4 项 / policy 2 项 / combo 不强制单类），生成后由 contract 后校验。
- 把理论语境（可选概念、节点/边 type 取值）注入提示词，约束 LLM 输出可被
  engine.parser + viz_network 正确消费的 Markdown。
"""
import json
import os
from app.settings import settings

# 提示词版本（阶段四：与每次生成结果一起持久化，保证报告可复现、可审计）。
# 当系统提示词（analysis_prompt.md / 结构要求 / 理论语境）发生重大变更时，递增此版本号。
PROMPT_VERSION = "1.4"

# 5 类型哨兵章节（逐字取自 KERNEL parser._SECTION_IDS，保证内核路由命中）。
# combo 不强制单类（走「≥2 类哨兵」后校验，见 contract._count_sentinel_modes）。
SENTINEL_SECTIONS: dict[str, list[str]] = {
    "case": ["案例事实摘要", "利益主体识别", "利益动线与转化", "制度与叙事作用"],
    "policy": ["政策对象图谱", "政策权重与空间分析"],
    "org": [
        "组织画像",
        "架构拆解与资金来源",
        "生存诊断",
        "繁衍诊断",
        "利益关系网络与利益集团拆解",
        "逆反诊断",
        "利益转化与组织—社会关系",
    ],
    "opinion": [
        "事件与时间线",
        "利益主体与沉默方",
        "叙事竞争矩阵",
        "三元生命维度",
        "逆反性质与层级",
        "演化曲线与系统回应",
    ],
    "combo": [],
}

# 章节数（供前端展示「所选类型 → 预计章节数」，双轨护栏显性化）
EXPECTED_CHAPTERS: dict[str, int] = {
    "case": 8,
    "policy": 8,
    "org": 9,
    "opinion": 7,
    "combo": 0,  # 组合按作者源序，不固定
}


def _read_prompt_template() -> str:
    p = os.path.join(settings.engine_dir, "analysis_prompt.md")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return f.read()
    return ""


def _theory_context() -> str:
    cfg_path = os.path.join(settings.engine_dir, "theory_config.json")
    if not os.path.exists(cfg_path):
        return ""
    try:
        with open(cfg_path, encoding="utf-8") as f:
            data = json.load(f)
        concepts = [c.get("name", "") for c in data.get("concept_pool", [])][:24]
        interests = [
            f'{t.get("id")}({t.get("name", "")})'
            for t in data.get("interest_types", [])
        ]
        nodes = [
            f'{n.get("id")}({n.get("name", "")})'
            for n in data.get("visualization", {}).get("node_types", [])
        ]
        edges = [
            f'{e.get("id")}({e.get("name", "")})'
            for e in data.get("visualization", {}).get("edge_types", [])
        ]
        lines = []
        if concepts:
            lines.append("可选概念池（单篇选用 ≤3 个）：" + "、".join(concepts))
        if interests:
            lines.append("六类利益：" + "，".join(interests))
        if nodes:
            lines.append("网络图节点 type 取值：" + "，".join(nodes))
        if edges:
            lines.append("网络图边 type 取值：" + "，".join(edges))
        return "\n".join(lines)
    except Exception:
        return ""


# 案例型 8 段结构（含事件深度分析哨兵章节，与 parser._SECTION_IDS 对齐）
CASE_STRUCTURE = """报告结构（严格按顺序，用 ## 二级标题）：
## 情况概述
## 案例事实摘要
## 分析框架说明
## 利益主体识别
## 利益动线与转化
## 核心冲突点
## 制度与叙事作用
## 三元结构分析正文（下设 ### 第N节：冲突式标题）
## 结论
## 行动建议
## 附录
"""

# 政策型 8 段结构（与 parser 已知 section id 对齐；政策条款拆解为可选节，无证据可整节省略）
POLICY_STRUCTURE = """报告结构（严格按顺序，用 ## 二级标题）：
## 情况概述
## 独立事实摘要
## 分析框架说明
## 政策对象图谱（下设 ### 基本信息 / ### 发布主体与主题画像 / ### 受影响群体（四分法） / ### 行业影响矩阵 / ### 时间维度预判）
## 政策条款拆解（可选：仅当政策文本含 2 条以上可拆解的具体条款时产出，下设 ### 条款定位 / ### 影响对象与利益变化 / ### 生效与地域层级；材料不足时整节省略，不得编造条款）
## 政策权重与空间分析（下设 ### 权重层级判定 / ### 操作空间评估）
## 核心冲突点
## 三元结构分析正文（下设 ### 第N节：冲突式标题）
## 结论与推导（下设 ### 汇流段 / ### 博弈终局预判 / ### 可传播金句）
## 行动建议
## 附录/数据溯源
"""

# 组织诊断 9 段结构（哨兵 7 项 + 诊断结论 + 附录）
ORG_STRUCTURE = """报告结构（严格按顺序，用 ## 二级标题）：
## 组织画像
## 架构拆解与资金来源
## 生存诊断
## 繁衍诊断
## 利益关系网络与利益集团拆解
## 逆反诊断
## 利益转化与组织—社会关系
## 核心冲突点
## 诊断结论
## 行动建议
## 附录
"""

# 舆情分析 7 段结构（哨兵 6 项 + 结论 + 附录；叙事份额分析为可选节，无法量化时省略）
OPINION_STRUCTURE = """报告结构（严格按顺序，用 ## 二级标题）：
## 情况概述
## 事件与时间线
## 利益主体与沉默方
## 叙事竞争矩阵
## 叙事份额分析（可选：仅当能从来源材料合理估计各叙事的声量份额时产出；每条叙事必须写明份额口径（如按样本来源数、按互动量）并附证据支撑，无法量化时整节省略，不得编造百分比）
## 三元生命维度
## 逆反性质与层级
## 演化曲线与系统回应
## 核心冲突点
## 结论
## 行动建议
## 附录
"""

REPORT_WRITING_STANDARD = """
# 报告写作规格 v1.0（强制，优先于任何素材格式）
- 报告是分析骨架，不是素材搬运。正文不得出现【联网抓取素材】、【内部研究材料】、[素材]或整段原文复读。
- 首章为「情况概述」（组织型为「组织画像」）：自然散文 2–4 段，交代对象、范围和结论前置，禁止“开卷先看”等清单腔。
- 事实摘要只保留 3–6 条关键事实，纯事实、零分析；每条只写来源名称，不在正文堆 URL。所有可点击链接仅放在附录，每行格式为 [来源名](url)。
- 分析框架必须有一句核心命题，使用「A不是B，而是C」句式。正文按主体→利益→关系递进；每节须有事实锚点、成本收益、行为解释与结构归因，不能按时间线复述。
- 分析正文优先使用「核心判断 → 证据 → 推理 → 不确定性 → 含义」的短块结构。没有证据的字段明确写“未知”或“待验证”，不得用连贯文风掩盖资料缺口。
- 同一个判断只在最相关章节完整论证一次；摘要、框架、正文和结论不得换措辞重复。后续章节如需引用，只用一句话指回原判断并补充新的证据或含义。
- 追求信息增量而非篇幅：删除套话、过渡句和材料复述，优先呈现非显然关系、公开说法与行为矛盾、被分散材料共同支持的机制。
- 「核心冲突点」必须压缩为 3–5 条，格式为「1. 【主体A】对【主体B】在【利益】上的张力：解释」。
- 「结论」必须用 ### 汇流段、### 核心判断、### 博弈终局预判 三个小节；汇流段写出 2–3 个具体主体名，终局预判写 3–5 条“走向 + 触发条件 + 影响”。
- 「行动建议」按主体分块，每方 2–3 条，以动词开头，写清约束条件。材料不足时不要编造、不要输出“未提供/建议补充/占位”等失败提示；仅做有证据边界的判断。
- 每份正式报告至少有一张全景利益关系图；图前后须有「图 N」文字说明，节点写主体及角色，边标明合作/对抗/中立/交换等关系。
"""

# 组合模式：至少 2 类哨兵混编（作者源序），共同骨架不能省略
COMBO_STRUCTURE = """报告结构（组合模式）：
组合报告可以按事件/政策/组织/舆情的实际分析顺序组织，但必须保留以下共同骨架，不能省略：
## 情况概述（或组织画像）
## 分析框架说明
## 核心冲突点
## 三元结构分析正文
## 结论（或结论与推导、诊断结论）
## 行动建议
## 附录
其中「核心冲突点」必须列出 2 至 6 条真实冲突，数字编号或 Markdown 短横线列表均可；
「结论」必须包含 ### 汇流段、### 核心判断、### 博弈终局预判，终局预判列出 2 至 6 条并写明触发条件。
除此之外，必须至少包含 2 类以上的哨兵章节（如「政策对象图谱」+「组织画像」+「事件与时间线」混编）。
用 ## 二级标题，顺序自定，结尾以 ## 附录 收束。
"""


def _region_scope_block(region_scope: list[str] | None) -> str:
    """F10：把 region_scope 码值列表渲染为「# 地域范围约束」提示词段。

    码值经 regions.region_scope_names 解析为「XX省（XX市、XX市）」；空/None 返回
    空串（不注入任何约束段，行为与既有逐字一致）。rule 引擎路径不走本函数。
    """
    if not region_scope:
        return ""
    from app.connectors.regions import region_scope_names

    names = region_scope_names(region_scope)
    if not names:
        return ""
    listing = "、".join(names)
    return f"""

# 地域范围约束（强制）
- 本次分析的地域范围为：{listing}。
- 分析对象、事实、主体与利益关系必须落在这个地域范围内；范围外的全国性背景最多用
  一句话交代，不得展开成主体章节。
- 材料中出现的范围外信息一律视为背景噪音，不得编造范围内不存在的事实。"""


def _structure_for(analysis_type: str) -> str:
    if analysis_type == "policy":
        return POLICY_STRUCTURE
    if analysis_type == "org":
        return ORG_STRUCTURE
    if analysis_type == "opinion":
        return OPINION_STRUCTURE
    if analysis_type == "combo":
        return COMBO_STRUCTURE
    return CASE_STRUCTURE


def build_system_prompt(analysis_type: str = "case", region_scope: list[str] | None = None) -> str:
    base = _read_prompt_template()
    structure = _structure_for(analysis_type)
    theory = _theory_context()
    guard = SENTINEL_SECTIONS.get(analysis_type, [])
    region_block = _region_scope_block(region_scope)
    sentinel_block = ""
    if guard:
        lines = "\n".join(f"## {s}" for s in guard)
        sentinel_block = f"""

# 类型一致性强制（必须原样包含以下 ## 二级标题，缺任一即视为生成失败）
{lines}
"""
    elif analysis_type == "combo":
        sentinel_block = """

# 类型一致性强制（组合模式：必须至少包含 2 类以上的哨兵章节，缺则视为生成失败）
例如：## 政策对象图谱、## 组织画像、## 事件与时间线、## 叙事竞争矩阵 等混编。
"""
    return f"""{base}

# 报告结构要求（必须严格遵守）
{structure}

# 理论语境（供概念与节点/边类型选择参考）
{theory}
{sentinel_block}
{region_block}
{REPORT_WRITING_STANDARD}
# 输出约束
- 仅输出 Markdown 正文，不要输出任何解释性文字，不要用代码围栏包裹整篇。
- 必须包含至少一个 ```DIAGRAM 利益关系图（合法 JSON，可被 json.loads 解析）。
- 文末附版权声明行：分析框架：三元结构理论 © 2026, CC BY-NC-SA 4.0，国作登字-2026-A-00048134

# 不合格输出
- 不得用任何“未提供、未标注、建议补充、结构占位、依据不足”占位句填章节。
- 缺关键事实、关系或来源时，删去无法成立的断言，不要用套话伪装成完整报告。
"""
