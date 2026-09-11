# 下一代升级方案：数据接入 · 监测告警 · 复核推演 · 地域维度

日期：2026-09-12 ｜ 状态：设计定稿，待排期实施
适用范围：分析内核（engine/parser/viz_network）+ 后端（backend/app）+ 前端（frontend）

> **一句话定位**：本项目的分析深度与交付形态（Word/PPT/证据账本）已领先主流开源，
> 但**数据获取、持续告警、地域粒度**落后主流开源两个身位。本方案补齐这三块，
> 并把「推演」落在与理论自洽的「条件阈值推演」上，而不是照抄大成本仿真。

---

## 〇、总原则（所有实施必须遵守）

1. **采集与研判分离**：采集侧只产出统一的 `SourceItem`，研判侧永远只吃 `SourceItem`。
   现有 `research_ledger.ResearchSource` 已经是研判侧的抽象，本次只补采集侧与字段。
2. **新维度先落字段，再改提示词**：地域、平台、时间、互动量必须先成为结构化字段，
   否则就只是 LLM 编出来的形容词，污染证据链。
3. **只学思路，不抄代码**：所有外部项目（见第一章）仅参考其**架构范式与产品思路**，
   不复制、不内嵌、不 import 任何第三方项目源码。第三方工具一律走「外部进程 + 文件交换」。
4. **合规前置**：数据源分三级（见 2.2），默认只开 L1。地图绘制必须用自然资源部标准地图底图。
5. **BYOK 红线不变**：采集与监测不引入任何服务端 LLM 密钥；检索优先零 Key 公开源，
   沿用 `search.py` 的「降级不静默」协议（`degraded` 标记必须透传到 UI）。
6. **老报告零回归**：新章节一律用可选哨兵（写了才渲染），新字段一律走 `db.py`
   现有的幂等 ALTER 迁移循环，存量报告与存量库不迁移不报错。

---

## 一、外部参考：学什么、不学什么（2026-09-11 实测口径）

| 项目 | 实测星数 | 只学这条思路 | 明确不学/不做 |
|---|---|---|---|
| TrendRadar | 62,185 | ① 多源聚合层与 RSS 统一归一；② 关键词订阅语法（必须词/过滤词/配额）；③ 推送模式分 daily/current/incremental + 推送时间窗 + 增量去重 | 不抄它的抓取实现与站点清单，站点清单按我方合规口径自定 |
| 微舆 BettaFish | 42,197 | ① 多 Agent 分工 + 「论坛式辩论」避免观点被单一模型平均化；② 采集、分析、报告各自独立引擎 | 不做爬虫集群式全天候采集（成本与合规都不合适）；不引微调模型中间件 |
| MiroFish | 72,127 | ① 预测输入是结构化图谱而非原始文本；② 人设带活跃时段/发言频率/影响力权重；③ 仿真轮数上限（官方建议 ≤40 轮）防失控 | 不做百万级 OASIS 仿真、不依赖 Zep Cloud 等外部记忆服务 |
| MediaRadar | 6 | Analyst → Reviewer → Director 三角色复核链 | — |
| Bright Data social-listening-agent | 10 | ① 8 阶段流水线中 Collect 与 Rank 分离（先收后排，不边收边判）；② 分析单位从 sentiment 转向 narrative | 不依赖其商业 API |
| MediaCrawler | 58,200 | ① Playwright/CDP 复用登录态的思路；② search / detail / creator 三种采集模式正好对应「关键词监测 / 单事件深挖 / 主体画像」 | ⚠️ **其许可限定学习研究、非商业、禁止大规模采集**。绝不 import 其代码；仅作为可选外部进程适配器（3.3），默认关闭，使用者自负合规责任 |

**行业转向共识**（作为方向依据）：Dashboard 驱动 → Agent 驱动；sentiment →
narrative + evidence；单体工具 → 可安装 Skill/MCP；描述 → 可证伪推演。

---

## 二、能力一：数据接入 · 多平台采集

### 2.1 目录与模块

```
backend/app/connectors/
├── base.py          # SourceItem 契约 + Connector 基类 + 限流/降级协议
├── hotlist.py       # L1：公开热榜聚合
├── rss.py           # L1：RSS/Atom
├── websearch.py     # L1：包装现有 search.py，补齐 published_at/platform 字段
├── govdoc.py        # L1：政府公开文件（文号 + 发布机关 + 行政区划）★ 政策分析主粮
└── adapters/
    └── mediacrawler.py   # L2：外部进程适配器，默认关闭（ENABLE_SOCIAL_CRAWL=0）
```

### 2.2 数据源分级（写进 `docs/DATA_COMPLIANCE.md`，先于代码）

| 级别 | 范围 | 默认 | 约束 |
|---|---|---|---|
| L1 公开可采 | 热榜聚合端点、RSS/Atom、政府公开文件、搜索引擎结果 | **开启** | 限速、UA 如实、遵守 robots |
| L2 受限源 | 社媒平台正文/评论（需登录态） | **默认关闭** | 外部进程隔离；单次少量；不批量账号、不绕风控；仅使用者自担合规责任的研究用途 |
| L3 禁止 | 绕过登录/付费墙、个人信息批量归集、验证码破解 | 永不实现 | 写入文档红线，代码评审卡点 |

### 2.3 `SourceItem` 统一契约（采集侧唯一输出）

```
id, platform, platform_id, url, title, text, author,
published_at, retrieved_at,                 ← 补齐现有 SearchHit 缺失的时间字段
region_code, region_name, region_level, region_source,   ← 见第五章
engagement {read, like, comment, share},    ← 声量/叙事份额的计算基础
lang,
fingerprint,          # 归一化文本指纹（SimHash 或 MD5），去重主键
canonical_url,        # 去 utm/尾斜杠后的规范链接
independence_group,   # 同源转载归并组（避免「100 条其实是 1 条」）
degraded,             # 沿用 search.py 降级协议：超时/限流/解析失败必须显式标记
raw                   # 原始载荷（JSON），供审计回放
```

→ 归一化后写入 `ResearchSource`（见第六章字段清单）。**去重三件套
（fingerprint / canonical_url / independence_group）是采集层第一优先级**——
现有 ledger 已预留这五个字段（`content_fingerprint` / `canonical_url` /
`original_url` / `duplicate_of` / `independence_group`），当前全部空置。

### 2.4 采集任务调度

- 采集走现有 `queue.py` 任务队列，新增阶段名 `collect`（排在检索之前），WS 进度可见；
- 每源独立限速（QPS）+ 每日配额；任何源失败返回 `degraded` 摘要，不静默、不中断整批；
- L2 适配器：subprocess 拉起外部工具（独立 venv / 独立配置），只读取其输出的
  SQLite/JSON 文件，映射为 `SourceItem`；进程超时即杀，输出目录不入库不入 git。

**验收**：一次分析任务能自动带回 ≥20 条带 URL / 时间 / 平台 / 指纹的原始条目，
且同一转载源在 `independence_group` 下归并为 1 条有效证据。

---

## 三、能力二：持续监测 · 预警推送

现状：`ResearchMonitor` 已支持定时重跑（interval 1–720h），
`compare_research_ledgers` 已做确定性差分（节点增删 / 立场变化 / 关系增删），
`research_changes._risk_level` 已有风险信号公式。缺「事件化」与「推送」。

### 3.1 四段设计

```
订阅(MonitorConfig) → 差分(diff) → 告警判定(AlertRule) → 推送(notifiers)
```

1. **订阅升级**：`ResearchMonitor` 增加 `keywords`（订阅语法：必须词/过滤词/配额，
   思路学 TrendRadar 的 frequency_words）、`region_scope`（第五章）、`platform_scope`、
   `push_window`（静默时间窗，避免夜间推送）。
2. **差分扩展**：在现有 diff 输出上补四类：新增叙事、叙事份额变化、极性翻转、新增关键主体。
3. **告警判定**（新表 `AlertRule` + `AlertEvent`）：规则必须是**可解释阈值**，
   绝不交给 LLM 判断重要性：

| 规则（默认集，可配） | 级别 |
|---|---|
| critical gap 新增 ≥1 | P0 |
| 负面关系 strength≥4 新增 | P1 |
| 某叙事份额 24h 内 Δ≥15pp | P1 |
| 同一主体立场 polarity 反向 | P2 |
| 声量 24h 环比 ≥3× | P2 |

   **去重与抑制**：同 `(subject, rule)` 冷却期 6h；相似事件按 fingerprint 合并；
   每次 monitor 运行最多产出 N 条告警（防刷屏）。
4. **推送**（`backend/app/notifiers/`）：`email`（复用 `email_sender.py` 的 SMTP）/
   `wecom` / `feishu` / `dingtalk` / `telegram` / `webhook`（通用）。
   每条告警强制三件套：**发生了什么**（diff 摘要）+ **为什么**（命中规则原文）+
   **去哪看**（报告版本链接 + 证据原文链接）。

### 3.2 落库与审计

`AlertEvent(monitor_id, rule_id, severity, payload, dedupe_key, channels, sent_at, status)`；
告警发送写 `AuditLog`（复用现有 `app/audit.py`）。

**验收**：监测周期跑完，能在企业微信/邮箱收到一条带可点链接的告警；
同一事件 6h 内不重复推送；静默时间窗内零打扰。

---

## 四、能力三：复核 · 推演与预测

### 4.1 复核环（先做，便宜且立刻提质量）

三角色两阶段（思路参考三角色复核链与论坛辩论，**实现完全自有**）：

```
Analyst（现有生成，产出 ledger + 正文）
   → Reviewer（只挑错，不重写）
   → Director（返工或放行，最多 2 轮）
```

Reviewer 的 issue 类型表——**能算的绝不问 LLM**：

| issue 类型 | 判定方式 |
|---|---|
| key 级 claim 无 evidence_ids | 确定性（遍历 ledger） |
| conflicted relation 未解决 | 确定性（`status == "conflicted"`） |
| tertiary 及以下来源支撑 key claim | 确定性（source_level × claim.significance） |
| 同 independence_group 被重复计数 | 确定性（分组计数） |
| 地域/时间标注缺失 | 确定性（字段判空） |
| 叙事矩阵内部观点被平均化 | LLM（唯一必须 LLM 的检查项） |

Reviewer 意见进审计日志；Director 决定返工（定向重生成对应章节）或放行并附保留意见。
**验收**：评测集上 unsupported claim 占比下降、contract 返工率下降。

### 4.2 推演：条件阈值推演（不引入 OASIS 大仿真）

每条推演强制绑定三要素：**触发条件（可观测）+ 阈值（可计算）+ 失效条件（可证伪）**。
示例：*若 X 方 48h 内未公开回应（可观测），则叙事 B 份额超过 A（可计算）；
72h 内出现官方回应则本推演作废（可证伪）。*

- 数据基础：ledger 的关系图（polarity / strength / status）+ 叙事份额时序；
- 呈现：新增可选章节 `scenario_simulation`（情景推演），用可选哨兵接入；
- **优势叙事**（对外可讲）：我们的推演每条挂 `evidence_ids`，可证伪、可追责；
  仿真式预测给不出证据链。
- （可选，P2）最小仿真：20–50 个 persona（直接从 ledger actor 节点生成，带利益类型/
  立场/影响力权重/活跃时段），跑 5–10 轮观点交互，只输出「立场分布变化」一个指标，
  不引入外部仿真框架。

---

## 五、能力四：地域维度（省 / 市 / 区县）

**战略判断**：主流开源地域能力集体偏弱；而政策分析天然地域化（省级/市级/试点、
政策时差、谁先试点谁跟进）。地域化是本项目**反超的口子**，不是补丁。

### 5.1 数据模型（最小改动，全部走幂等 ALTER）

| 位置 | 新增字段 |
|---|---|
| `ResearchSource` | `region_code`（GB/T 2260 六位）、`region_name`、`region_level`（national/province/city/district/unknown）、`region_source`（识别依据） |
| `Project` / `Task` | `region_scope`（JSON 数组，如 `["440000","441300"]`，空=全国） |
| `ResearchNode`（ledger） | `region_code`（主体属地） |
| `ResearchRelation`（ledger） | `cross_region`（布尔，跨地域关系） |
| `Material` | `url`、`published_at`、`region_code`（人工素材与抓取数据同池） |

### 5.2 地域识别：三级流水线，LLM 只兜底

1. **规则优先**：行政区划三级词典（省/市/区县 + 别名，"粤"→440000、"惠州"→441300）；
   政策文号正则抽发布机关→行政区划码（`粤府〔2024〕xx号`）。零成本、最高准确率。
2. **结构化字段**：政府公开文件/政策库接口直接带发布机关与行政区划字段——优先接。
3. **LLM 兜底**：仅对前两级未命中的条目调用；必须输出 `region_code` + 理由；
   置信度不达标 → `unknown`。**宁可 unknown 不可猜**——地域被编造会污染整条证据链。
4. `region_source` 取值固定枚举：`issuer`（发布机关）/ `title` / `body` / `account`（账号属地）/ `unknown`。

### 5.3 章节：三个「地域锚点」（全部可选哨兵，老报告零回归）

| 模式 | 改动 |
|---|---|
| 政策 | `policy_portrait` 增加子维度「适用地域与层级」（国家级/省级/市级/试点）；新增可选章节 `policy_region`（地域适用性与扩散路径：谁先试点、谁跟进、谁没动） |
| 事件/舆情 | `opinion_actors` 增加「主体属地」标注；新增可选章节 `opinion_region`（声量/叙事份额按省分布 + **沉默地区识别**）；`opinion_evolution` 增加「地域扩散顺序」 |
| 组织 | 组织属地与跨地域利益动线（总部/分支/供应链地域） |

实现路径：`parser._SECTION_IDS` 加映射 → `analysis_prompt.md` 加模板段 →
`docx_renderer.render_docx` 加 section_order 分支（三处同步，见 AGENTS.md 既有规则）。

### 5.4 可视化：第四种 viz 类型 `geo`（分两步）

- **第一步（零风险）**：Word/HTML 出「地域分布表 + 横向条形排行」，不碰边界数据；
- **第二步（地图）**：交互 HTML 用 ECharts 中国地图。**合规红线：底图必须来自
  自然资源部标准地图服务并标注审图号，禁止随手抓取 GeoJSON 画边界。**
- 前置修正：README 技术栈写的是 D3.js + ECharts，实际 `package.json` 只有
  `vis-network`——引入地图库前先修 README，避免按错误前提选型。
- 配色：沿用六类利益色；地图只表达**一个**变量（份额或强度）的色阶。

### 5.5 地域化告警（监测与地域的联动，价值最大处）

把 `region_code` 作为 AlertRule 的过滤与分组维度：
- 「A 省政策落地后，B 省 24h 内出现同源叙事」→ 跨省扩散告警；
- 「试点地区声量异常但邻省沉默」→ 沉默地区本身即信号。

---

## 六、数据模型与迁移清单（汇总）

全部走 `db.py` 既有幂等 ALTER 循环（`if col not in cols: alters.append(...)`）：

| 表 | 新列 |
|---|---|
| `research_sources`（ledger 存储） | platform, published_at, region_code, region_name, region_level, region_source, engagement(JSON) |
| `projects` / `tasks` | region_scope(JSON) |
| `research_monitors` | keywords(JSON), region_scope(JSON), platform_scope(JSON), push_window(JSON) |
| `materials` | url, published_at, region_code |
| 新表 | `alert_rules` / `alert_events` |
| 新文件 | `connectors/*`、`notifiers/*`、`reviewer.py`、`region_dict.py`（行政区划词典） |

---

## 七、实施排期（6 周，验收写死）

| 周 | 交付 | 验收标准 |
|---|---|---|
| 1–2 | connectors L1（hotlist/rss/govdoc/websearch）+ SourceItem 归一 + 去重三件套 | 单次分析自动带回 ≥20 条带指纹条目；转载归并生效 |
| 2–3 | 地域字段 + 行政区划词典 + 政策地域识别 + `policy_region` 可选章节 | 10 份政策样本中发布机关地域识别 ≥90%，未命中一律 unknown |
| 3–4 | AlertRule/AlertEvent + notifiers（email + 企微先行）+ 冷却去重 | 收到带三件套的告警；同事件 6h 不重复 |
| 5 | Reviewer 复核环（确定性检查优先） | 评测集 unsupported claim 占比下降 |
| 6 | 地域分布条形图进 Word + `viz=geo` 第一步 + 条件阈值推演章节 | 推演每条可点回证据链接 |

**明确不做**：百万级仿真、绕登录态采集、批量账号池、引入外部仿真/记忆框架、
把任何第三方项目源码复制进本仓库。

---

## 八、配套文档（实施时逐份产出）

1. `docs/CONNECTOR_DESIGN.md` — SourceItem 契约、三级数据源、限流/降级协议
2. `docs/DATA_COMPLIANCE.md` — 采集红线、L2 隔离原则、robots/ToS/个人信息边界
3. `docs/ALERTING_DESIGN.md` — 订阅模型、规则表、冷却去重、渠道规范
4. `docs/REVIEW_LOOP.md` — 三角色契约、issue 类型表、返工上限
5. `docs/FORECAST_DESIGN.md` — 条件阈值推演规范、可证伪要求、与 ledger 绑定
6. `docs/REGION_MODEL.md` — 行政区划码规范、三级识别策略、地域章节与 viz=geo 规范、地图合规红线
7. `docs/EVALUATION.md` — golden set、评分维度、回归门槛（复核环验收依赖它）

---

## 九、风险与红线（复查清单）

- [ ] **不复制外部代码**：只实现思路；第三方工具仅外部进程调用，默认关闭
- [ ] **MediaCrawler 许可**：学习研究/非商业——适配器文档必须写明「使用者自负合规责任」
- [ ] **地图合规**：标准地图底图 + 审图号；PNG 阶段用条形图规避
- [ ] **BYOK 不破坏**：采集/监测不新增服务端密钥；BYOK 面向 LLM 调用不变
- [ ] **地域不编造**：LLM 兜底必须给理由，否则 unknown
- [ ] **零回归**：可选哨兵章节 + 幂等 ALTER；改完跑 `体检.bat` + 后端全量 pytest
