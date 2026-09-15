# 引力矩阵（Gravitational Matrix）— 工作手册

## 项目定位

引力矩阵引擎：三元结构理论驱动的社会事件/政策/组织/舆情结构化分析系统——**完整自包含项目**（分析内核 + 后端 API + Next.js 前端同仓）：

- **用户工作流**：丢关键词/链接 → AI 智能体读取本项目方法论 → **自动写完整报告 + 利益关系网络** → 内核排版 Word/PDF/交互式 HTML → 报告展览页（可下载/可编辑/版本留痕）。用户全程不手写成稿。
- **当前使用路径**：
  1. **本地浏览器工作台**：`start.bat` 同时启动 Next.js 前端（127.0.0.1:3000）与 FastAPI 后端（127.0.0.1:8000）。
  2. **命令行内核**：`cases/run_*.py` 脚本 + `engine.export_from_text()` 直出报告。
  3. **后端 API**：FastAPI 交互文档位于 `http://127.0.0.1:8000/docs`，供本地调试与前端联调。

**核心方法论**：三元结构理论（三维 × 八阶 × 六类利益）
**覆盖四类分析**：政策分析（8段式）、事件/案例分析（5段式 / 深度8段式）、组织诊断（9段式）、舆情分析（7段式）＋组合（源序）
**著作权**：© 2026 李政恒，国作登字-2026-A-00048134
**代码许可**：GNU AGPL v3

---

## 项目架构

```
project_root/（本仓库 = 内核 + 后端 API + Next.js 前端完整项目）
│
├── start.bat                    ← 一键启动前端 3000 + 后端 8000（均绑本机）
│
├── backend/                     ← 后端 API（FastAPI，5244 行级）
│   ├── app/
│   │   ├── main.py              ← FastAPI 装配（CORS/启动/任务恢复）
│   │   ├── settings.py          ← ENGINE_DIR 默认指向本项目根（内核同仓）
│   │   ├── queue.py             ← 任务队列（数据库即队列 + 崩溃恢复 + WS 进度）
│   │   ├── search.py            ← 联网检索（BING→BRAVE→DuckDuckGo 零 Key 降级）
│   │   ├── materials.py         ← 素材组装 + 来源清单
│   │   ├── generator.py         ← AI 生成编排（web_mode / revise 再改）
│   │   ├── prompt_builder.py    ← 5 类型提示词 + 哨兵章节护栏（双轨一致性）
│   │   ├── contract.py          ← 生成后契约校验（type_mismatch 重试）
│   │   ├── engine_bridge.py     ← 内核黑盒门面（调 export_from_text）
│   │   ├── models.py / db.py    ← SQLite（Task/Project/ReportVersion 版本留痕）
│   │   └── routers/             ← analyze/tasks/search/cases/reports/…
│   └── tests/                   ← 124 个后端测试
│
├── frontend/                    ← Next.js 15 本地工作台（只调用本仓库 backend API）
│   ├── src/app/                 ← 首页、分析、项目、报告、利益关系网络、设置等路由
│   ├── src/components/          ← 工作台页面与交互组件
│   ├── src/lib/                 ← API、实时进度、状态与领域类型
│   └── package.json             ← 前端开发、构建与测试命令
│
├── engine.py                    ← 内核引擎（编排流程，唯一出口 export_from_text）
├── parser.py                    ← Markdown → 结构化数据（章节自动路由）
├── docx_renderer.py             ← Word 渲染器
├── pdf_converter.py             ← PDF 转换（LibreOffice）
├── viz_network.py               ← 利益关系网络图（network/org/flow 三态）
├── config.py / theory_config.json（理论配置，不动）
├── analysis_prompt.md           ← 分析提示词模板
├── cases/                       ← 命令行案例脚本（run_*.py，12 篇真实案例）
├── tests/                       ← 内核测试（章节编号等）
├── reports/                     ← 内核命令行产物（不入库）
├── docs/                        ← 当前架构、项目边界与实施计划
├── _archived/                   ← 历史孤儿归档（仅本地留档，不入库）
└── AGENTS.md                    ← 本文件（工作手册）
```

> **方法论运行时真源**：当前后端 `prompt_builder.py` 只读取本仓库根目录的 `analysis_prompt.md` 与 `theory_config.json`，因此项目可以独立运行。兄弟目录中的 7 个方法论 Skill 如本机存在，仅作为研究与维护参考，当前不是运行时依赖，也不得在工作时跳转到其他项目寻找前后端代码。
> - `立场显影剂`：个体立场穿透补丁，与舆情 / 利益 / 组织互补（不接引擎，作模块加载）。
> - `舆情分析`：已接引擎为第 4 类报告类型（7 段式）。
> - `多主体利益分析工作台` 已并入 `利益分析 Skill.md` 的「多主体利益分析扩展（高级）」章节，利益分析现为本技能唯一真源。
> - 需要把外部方法论正式接入运行时时，必须先复制为本仓库内的版本化资产、补测试并更新本说明；禁止建立对兄弟项目绝对路径的隐式依赖。

---

## 一键启动（本地工作台）

```
双击「启动工作台.bat」（推荐入口，指向 start.bat）或 start.bat
```
- 前端 Next.js :3000；启动后自动打开 `http://127.0.0.1:3000`
- 后端 FastAPI :8000（绑 127.0.0.1，优先用 `backend/.venv`；缺失则回退系统 python），交互文档位于 `http://127.0.0.1:8000/docs`
- `start.bat` 使用 Next.js 生产模式；构建缺失或源码较新时自动执行前端构建，健康服务会直接复用，不重复启动
- 双击 `status.bat` 查看端口、PID、归属和健康状态；双击 `stop.bat` 只停止经命令行确认属于本仓库的进程
- 运行日志和状态保存在 `.runtime/`（不入库）；端口被外部程序占用时启动器会报错并拒绝误杀
- 数据全本机：SQLite `backend/data/app.db` + 产物 `backend/generated/`（不入库）
- LLM/搜索密钥：仅存 `backend/.env` 或 `backend/data/llm_settings.json`，绝不提交
- 前端环境与构建产物：`frontend/node_modules/`、`frontend/.next/`、`frontend/.env*` 绝不提交
- 手动控制（不双击）：`powershell -NoProfile -ExecutionPolicy Bypass -File scripts\local-workbench.ps1 -Action start|status|stop`

### 项目边界

- 本仓库是唯一允许修改和运行的产品代码库；内核、后端、前端和项目文档均在本仓库内闭环。
- 不读取、不复制、不修改相邻的“Web 分析模型 codex”或其他历史项目，除非用户明确给出具体路径并要求迁移。
- 前端只能通过 `NEXT_PUBLIC_API_URL`（默认 `http://127.0.0.1:8000`）调用本仓库 `backend/` 的 API，不得引用仓库外源码。
- 开始工作前先阅读 `docs/PROJECT_ARCHITECTURE.md`；发现文档与磁盘状态冲突时，以用户最新要求为准并先修正文档，禁止擅自删除现有模块。

## 已有案例清单

| 脚本文件 | 案例名称 | 创建时间 | 备注 |
|---|---|---|---|
| `cases/run_report.py` | 模板脚本（空白模板） | 2026-06-18 | 新建案例时复制此文件 |
| `cases/run_trademark_law_2026.py` | 第七十七号主席令的政策逻辑——《商标法》修订（2026）分析 | 2026-06-27 | 政策分析（8段式模板） |
| `cases/run_government_work_report_2026.py` | 4.5%与4%的双重约束——2026年政府工作报告的政策逻辑 | 2026-07-14 | 政策分析（8段式） |
| `cases/run_one_person_company_gd.py` | 一人公司的制度突围——广东自贸区一人公司试点政策分析 | 2026-07-14 | 政策分析（8段式） |
| `cases/run_psychological_trauma.py` | 不被爱的幸存者：结构性创伤与防御性攻击的心理机制分析 | 2026-07-14 | 案例分析（5段式） |
| `cases/run_fat_cat.py` | 一场死亡的舆论分裂——胖猫事件的五主体叙事博弈分析 | 2026-07-14 | 案例分析（5段式），由 docx+html 反推补回 |
| `cases/run_paper_diaper.py` | 符合国标的有毒纸尿裤——甲酰胺事件的多主体制度博弈分析 | 2026-07-14 | 案例分析（5段式），由 docx+html 反推补回 |
| `cases/run_one_person_company_huizhou.py` | 一人公司的政策时差——惠州数字产业与惠城惠企奖补里的个体创业落点 | 2026-07-26 | 政策分析（8段式），基于惠市工信〔2024〕240号 + 惠城科工信一本通 |
| `cases/run_love_and_producer_lingxiao.py` | 被收回的新男主：恋与制作人凌肖七年维权与情感契约的单边改写 | 2026-07-26 | 深度事件分析（8段式：事实摘要/框架/利益主体识别/利益动线与转化/三元结构正文/制度与叙事作用/结论/附录），对标政策分析粒度 |
| `cases/run_mixue_org.py` | 平价帝国的暗线：蜜雪冰城组织诊断（总部、加盟商与品控的三元张力） | 2026-07-26 | 组织诊断（9段式），含 3 张 DIAGRAM（组织架构图 org + 资金流程图 flow + 利益关系网络 network） |
| `cases/run_fanquan_gender_mobilization_org.py` | 从饭圈到性别动员：一种平台动员能力迁移假说的结构评估 | 2026-07-27 | 组织诊断（9段式），将知乎回答降格为迁移假说评估，重点拆解证据边界、替代解释、协同操控识别与平台治理窗口，含 3 张 DIAGRAM |
| `cases/run_public_opinion_demo.py` | 一场平台算法限流争议的舆情七段式拆解（示例/模板） | 2026-07-27 | 舆情分析（7段式）模板与自测：演示七段结构，正文为占位示例；真实使用时替换 BODY 即可，引擎自动路由为舆情报告 |
| `cases/run_fang_xinghai_investigation_org_policy_opinion.py` | 方星海被查事件：任期政策取向与量化交易支持逻辑评估 | 2026-07-27 | 组合分析（舆情 + 组织 + 政策），区分调查事实、公开政策取向、制度性推断与未证实个人利益，含职务关系、利益网络与量化支持逻辑 |

> **2026-08-03 深度重写批次**：除方星海、饭圈到性别动员外，其余 9 个案例已按最新方法论深度重写并重新生成（补全景利益关系网络图、附录来源 URL 可点击、DIAGRAM 节点 type 六类利益配色、事件哨兵路由修正、标题冒号化与反 AI 味收敛、乱码修复）。产物在 `reports/` 下覆盖生成（旧产物已自动归档为 `.bak_时间戳`）。

**规则**：
- 新案例脚本统一存放在 `cases/` 目录，不要放在项目根目录
- 脚本为一次性产物，用完即弃；报告文件在 `reports/` 中持久保留
- 新增案例后立即更新此清单
- **任何报告必须先有 `cases/` 脚本再跑 engine，禁止临时脚本直出报告**（已发生胖猫/甲酰胺绕过事件）
- **正式交付用 `export_from_text(..., overwrite=True)`**，避免 reports/ 反复堆积同名多份

### 报告类型自动识别（无需传参）

引擎**不接收 `analysis_type` 参数**，而是根据 `parser.py` 解析出的章节 ID 自动选择章节顺序与渲染分支：

| 报告类型 | 触发章节（命中其一即路由） | 章节顺序模板 |
|---|---|---|
| 政策分析 | 含 `policy_portrait` / `case_portrait` 等 8 段式章节 | 8 段式 |
| 事件/案例分析 | 含 `case_portrait` / `case_flows` / `case_dynamics` 等事件章节（注意：哨兵前缀是 `case_`，不是 `event_`） | 5 段式 / 深度 8 段式 |
| 组织诊断 | 含 `org_portrait` / `org_structure` / `org_survival` / `org_reproduction` / `org_interest_network` / `org_reverse` / `org_transformation` 任一项 | 9 段式 |
| 舆情分析 | 含 `opinion_event` / `opinion_actors` / `opinion_narrative` / `opinion_trilife` / `opinion_reverse` / `opinion_evolution` 任一项 | 7 段式（事件与时间线 → 利益主体与沉默方 → 叙事竞争矩阵 → 三元生命维度 → 逆反性质与层级 → 演化曲线与系统回应 → 核心判断 → 附录） |
| **组合（源序）** | 同时命中 ≥2 种模式的哨兵（如 `opinion_event`+`case_portrait`+`org_portrait`+`policy_portrait`） | 按作者书写**源序**依次渲染各模式章节——命名空间互不重叠者直接拼；政策+事件共享「事实摘要/分析框架/三元结构分析正文」三件套，写一次=共享引言、写两次=各成一段，不再静默覆盖。单模式仍走上方 canonical 序（零回归）。详见 `组合报告模式_L2设计.md` |

新增分析维度时，只需同步改三处：`parser._SECTION_IDS`（章节映射）、`docx_renderer.render_docx`（section_order 分支）、`analysis_prompt.md`（提示词模板），引擎无需改。舆情分析引入「三元生命维度」：把舆论当活体，以**生存（定义权+解释权）/繁衍（话语权+叙事）/逆反（防御+反噬）**三层拆解其生命机制（详见 `../三元结构理论 本体/skill们/三元结构理论 舆情分析 Skill.md` 与 `analysis_prompt.md` 的七段式模板）。

### 章节序号统一规则

所有正式报告的一级章节序号由 `docx_renderer.py` 按该报告模式的渲染顺序统一生成，使用中文序号（如“一、”“二、”）。案例脚本可以写有序号，也可以不写；渲染器会先清理已有的中文或阿拉伯数字前缀，再按实际章节位置补齐，避免重复编号。政策、事件、组织等所有模式均适用，`三元结构分析正文` 也计入并显示为正式章节，保证目录和正文连续一致。

**两级编号来源并存（有意设计）**：一级（`##`）序号由渲染器统一生成；三级（`###`）子标题序号由 `engine.py` 调用的 `auto_number_headings` 按「每 H2 段落重置」的阿拉伯数字规则生成（H2 上的 auto_number 编号会被渲染器清掉重编，故 H2 实际以渲染器为准）。`auto_number_headings` 的编号表上限为「二十」（组合报告超 20 个 H2 时第 21 个起原样保留，不编号、不崩溃）。

### DIAGRAM 可视化图表（三类）

引擎的 `viz_network.py` 支持 **三种图表布局**，通过 DIAGRAM JSON 的 `"viz"` 字段选择：

| viz | 名称 | 布局算法 | 适用场景 |
|---|---|---|---|
| `network`（默认） | 利益关系网络图 | 力导向（spring_layout） | 多主体复杂关系、利益流向全景、无固定层级 |
| `org` | 组织架构图 | 自上而下树形层级（BFS 分层） | 控制链/股权结构/组织版图；边标注控制权与资金流向；节点按利益集团角色着色 |
| `flow` | 流程图 | 自左向右分层流程（BFS 分层 LR） | 资金流转、决策链路、扩张路径等时序/因果过程 |

三种图共用六类节点颜色（利益角色）和四类边样式（经济/权力/文化/法律），区别仅在布局。组织诊断建议至少配 **org 架构图 + network 利益关系网络** 两张，可选配 **flow 流程图**。

**HTML 自包含（离线可开）**：交互式 HTML 已内联 vis-network 库（项目 `libs/vis-network.min.js`，689KB），不再依赖 unpkg CDN。生成前需保证 `libs/vis-network.min.js` 存在（缺失时回退 CDN）。

---

## 工作规范

1. **复用不重造** — 做任何事之前，先检查是否已有现成的工具/脚本能做到
2. **不要绕过 engine 生成报告** — 所有报告必须通过 `CaseAnalysisEngine.export_from_text()` 产出
3. **不要修改 theory_config.json** — 除非用户明确要求修改理论定义
4. **写新脚本时复制 run_report.py 模板**，不要另起炉灶
5. **未知时先问** — 不理解需求时先提问，不要猜测
6. **数据来源可溯源** — 附录中每条来源必须标注具体出处名称 + `[链接](url)`，禁止"综合网络信息"等笼统写法。确保每条来源在 Word 和 PDF 中均可点击打开

### 改代码防崩护栏（回归测试）

**目的**：改功能 / 优化 / 新增核心功能时，确保不把已跑通的核心能力搞崩。**任何改动交付前，必须跑一遍一键体检确认全绿。**

- **一键体检**：双击根目录 `体检.bat`（或 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-all.ps1`）。
  四层依次跑：内核测试（章节编号/交付章节/网络图安全/XML 消毒）→ 后端核心测试（质量闸门/路由/合同/规则引擎/搜索）→ 前端 vitest → 前端 build。全绿 = 核心功能未受影响。
- **核心模块红线**（动这些文件前先跑对应层测试，改完跑全测）：
  - 内核：`engine.py`（唯一出口 `export_from_text`）、`parser.py`、`docx_renderer.py`、`viz_network.py`、`pdf_converter.py` → 内核测试层
  - 后端：`backend/app/rule_engine.py`、`generator.py`、`report_quality.py`、`contract.py`、`generation_routing.py`、`prompt_builder.py`、`routers/analyze.py` → 后端核心测试层
  - 前端：`frontend/src/lib/`（workspace-api/realtime/store）、`frontend/src/components/` → 前端 vitest 层
- **标准动作**（改任何核心模块）：
  1. 改前：跑对应层测试，确认基线绿（现在就是绿）
  2. 改：小步改，改一处
  3. 改后：跑 `体检.bat` 全测，绿才交付
- **端到端测试**（`test_api.py`/`test_e2e.py`/`test_progress_chain.py`/`test_export.py`/`test_generator_split.py`）涉及真实 LLM 调用与 docx 导出，**不在一键体检内**（慢且碰外部服务），需要时单独在真机手动跑。
- **测试也要更新**：改了行为，同步改对应测试的断言，避免"测试过但测的是旧行为"。

### 命名规范

| 类型 | 格式 | 示例 |
|---|---|---|
| 案例脚本 | `run_报告名.py` | `run_datong_an.py` |
| 报告输出目录 | `reports/报告名_YYYYMMDD_HHMMSS/` | `reports/datong_an_20260618_143000/` |
| 变量/函数 | snake_case 英文 | `export_from_text()` |
| 核心类 | PascalCase | `CaseAnalysisEngine` |

### 分析写作铁律

- **案例先行**：每节先讲案例事实，再引入概念解释
- **概念限额**：最多选 3 个概念（特殊 ≤ 4），跨维度自由组合
- **事实驱动**：每一句分析必须有案例中的具体事实支撑
- **冲突式标题**：标题要引人入胜
- **禁止分层列举**：不用"第一层…第二层…第三层…"
- **可传播金句必写**：最后 1-2 句让人记住的核心观点
- **价值中立**：只描述机制，不做道德评价
