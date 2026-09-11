# 独立运营后台 · 双前端分离与联网架构方案

> 状态：**部分实施**（2026-09-11 更新，见下方「实施进度」）　日期：2026-09-08　关联：[USER_SYSTEM_PLAN.md](../USER_SYSTEM_PLAN.md)
> 目标读者：本项目作者（自用 / 内测 → 对外运营）
> 本文件是「把管理员后台从前端工作台里拆成半独立项目」的完整落地方案，含目标架构、迁移清单、联网设计、标准 SaaS 做法对照。

---

## 〇·一、实施进度（2026-09-11 复核 / 收尾）

| 项 | 状态 | 落地位置 |
|---|---|---|
| **本地独立启动（隔离运行）** | ✅ **已实施** | `scripts/admin-console.ps1` + 根目录 `启动后台.bat` / `停止后台.bat`：后台跑 **127.0.0.1:3001**，独立进程 / 独立日志（`.runtime/admin-frontend*.log`）/ 独立状态文件，与工作台 3000 互不干扰；后端 8000 **共用**（一份 SQLite、一个任务队列，不起第二个后端）。 |
| **后台自带登录** | ✅ **已实施** | `frontend/admin-pages/admin-console/layout.tsx` 未登录时直接渲染登录卡（复用 `AuthCard`），不必先绕道 3000 工作台登录。 |
| **A1 CORS 可配置多源** | ✅ **已实施** | `backend/app/settings.py` 新增 `cors_origins`（env `CORS_ORIGINS`，默认放行 3000 + 3001 的 localhost/127.0.0.1）；`backend/app/main.py` 改用它。 |
| **A2 / S5 公开进程不注册 admin 路由** | ✅ **已实施** | `backend/app/main.py` 引入 `ADMIN_API_ENABLED` 三态（显式 1 / 显式 0 / 自动模式 = 本地开 / 公网关）。`backend/.env` 设 `ADMIN_API_ENABLED=1`（本地自用）；公开版设 0 → 进程里无 `/api/admin/*` 任何端点（验证：60  13 → 47  0）。 |
| **A5 admin 前端物理隔离** | ✅ **已实施**（2026-09-11） | admin 页面迁出 `src/app/`，物理放进 `frontend/admin-pages/admin-console/`；workbench 构建**根本不扫描**该路径，`.next/app-path-routes-manifest.json` 不含 `/admin-console`。`scripts/admin-console.ps1` 在 admin 构建时临时 `Copy-Item` 进 `src/app/admin-console/`，构建完（无论成败）`Remove-Item` 还原；`tsconfig.json` 做 snapshot/restore。 |
| **A6 公开前端去掉 admin 入口** | ✅ **已实施** | `frontend/src/components/app-shell.tsx` 的 `isAdmin` 用 `NEXT_PUBLIC_ADMIN_UI === "1"` 门控；admin 构建内联 "1"，工作台构建内联 "1" 缺失 → 入口与 `/.next/server/app/admin-console/*` 都不存在。 |
| **A4 Caddy 公开站拒绝 `/api/admin/*`** | ⬜ 待办（对外发布前） | 纵深兜底 |
| **B1 操作审计日志** | ✅ **已实施** | 新增 `AuditLog` 表（app/models.py:308）+ `app/audit.py` 自管 session 永不抛 + register/login-fail/login-blocked/change-password/forgot/reset/ban/unban/role/reset-link/project-archive/project-delete/task-delete 全留痕 + `/api/admin/audit` 按 action/actor_id 过滤 + 前端 `audit/page.tsx` 按动作过滤。 |
| **B5 找回密码 / 邮箱验证（SMTP）** | ✅ **已实施** | `forgot-password / reset-password / reset-password/validate` 三端点；令牌 sha256 哈希存储 + 单次使用 + 30 分钟过期 + `token_valid_after` 锚点踢掉旧 session；SMTP 配齐才发，否则只记日志 + 可选 dev 回显。 |

> **一句话现状（2026-09-11）**：**运行层 + 代码层均已分家**。workbench `.next` 与 admin `.next-admin` 是两套独立 distDir、两套构建产物、两套进程，公开版仓库里只有 `frontend/admin-pages/` 一个物理目录（workbench 完全不扫），外人 clone 后**不可能通过构建产物看到 admin**；管理路由层 `ADMIN_API_ENABLED=0` 时也不存在 `/api/admin/*` 任何端点。剩余 A4（Caddy 纵深）与对外部署 TLS/域名是 Phase B 任务。

> **构建层细节（2026-09-11 实测修复）**：
> 1. 早期 `*.admin.tsx` 命名方案 → `pageExtensions` 门控 → **失败**。Next 15.5.20 的类型生成 worker 扫描 `src/app/` 时**不应用 pageExtensions**，导致 `layout.admin.tsx` 仍被识别为 layout，触发 Next 内置类型 `LayoutConfig<Route extends "/">` 的 `"/admin-console"` 不匹配 → validator.ts 编译失败。
> 2. 物理迁出 `src/app/` 方案 → ✅ workbench 编译通过、admin 编译通过（admin 走 `scripts/admin-console.ps1` 的 Copy-Item / Remove-Item swap）。但 admin 编译仍卡 Next 15.5.20 已知的 `LayoutProps<Route extends "/">` 类型 bug（子路由 layout 都中招）→ 用 `typescript.ignoreBuildErrors: true` 仅在 admin 构建时打开（workbench 仍严格）。
> 3. `scripts/admin-console.ps1` 在构建期对 `tsconfig.json` 做 snapshot/restore（Next 会往 `include` 里追加 distDir 的 types），对 `frontend/src/app/admin-console/` 做构建前 swap + 构建后清理，`Remove-SafeBuildDirectory` 白名单限定四个 `.next*` 名称。
> 4. 验证脚本：`_trash_20260911/_buildtest.ps1` 跑两套构建 + 比对两个 manifest。结果（2026-09-11 17:10）：
>    - `WORKBENCH_EXIT=0 ADMIN_EXIT=0`
>    - `.next hasAdminRoutes=False`、`.next-admin hasAdminRoutes=True`

---

## 〇、一句话结论

把项目从「**单前端单容器**（公开工作台里藏着 admin 后台）」演进为「**单后端 + 双前端**」：

- **公开版前端**（不含任何 admin 代码/路由/入口）→ 这就是别人从 GitHub clone 后跑起来的东西，干净独立。
- **独立 admin 前端** → 你**自己单独跑**的一套控制台（独立域名或独立路径），普通用户既看不到、也摸不着。
- **两者共用同一个 FastAPI 后端 + 同一份 SQLite 数据库**（数据天然一份，无需同步）。

当前内置版（`/admin-console` 藏在前端里 + 后端 `/api/admin/*`）是过渡形态，作为功能真源保留到分拆完成。

---

## 一、为什么需要这次改造（现状的痛点）

### 1.1 现状架构（单容器三合一）

```
Docker 单容器（对外 1 个端口 ${PORT:10000}）
├── Caddy            反代：/api /ws → 后端 8000；其余 → 前端 3000
├── Next.js 前端       frontend/src/app/(app)/*（工作台）+ admin-console/*（后台）
└── FastAPI 后端        backend/app/（含 /api/admin/* 运营端点）
```

- 前端 `app-shell.tsx` 里：`isAdmin = authRequired && role==="admin"` 时头像菜单才出现「运营后台」入口（→ `/admin-console`）。
- 后端 `auth.py`（`/api/admin/*`）+ `admin_ops.py`（8 个端点）都 `Depends(require_admin)`，非 admin 一律 403。
- 数据库 `backend/data/app.db`（SQLite，`APP_DB_PATH` 可覆盖）。

### 1.2 痛点

| # | 痛点 | 后果 |
|---|---|---|
| P1 | **admin 代码和路由在公开前端里** | 别人 clone 后，前端包里**含** admin 页面代码与入口逻辑（虽需角色才显示）。作者想把「自己的管理后台」和「公开产品」物理分开。 |
| P2 | **admin 端点在同一后端进程** | 只要后端被公开访问，`/api/admin/*` 就存在。靠 CORS + role 挡，但端口/进程层面不隔离。 |
| P3 | **CORS 硬编码**只放行 `localhost:3000` / `127.0.0.1:3000` | 一旦公开站用正式域名、admin 站另一个域名，两者都无法跨域访问同一后端。**这是当前最卡联网的点**。 |
| P4 | 现状靠 `PUBLIC_MODE` 开关切「本地/公网」 | 开关让两种模式共用一套代码，边界模糊；要拆开后应各自明确自己的模式。 |

---

## 二、目标架构（单后端 + 双前端）

### 2.1 顶层部署拓扑

```
                  ┌─────────────────────────────┐
  普通用户         │       后端（唯一）            │
  ├ 浏览器 → 公开站 │  FastAPI + 引擎 + 联网检索    │
  │   public.com   │  + SQLite（同一份数据）       │
  └───────────────▶│  /api/*        （公开端点）    │
                   │  /api/admin/*  （仅 admin 用） │
  ────────────     │                               │
  你(admin)         │  （Caddy/反代按来源分流）      │
  └ 浏览器 → admin站│                               │
      admin.com    └─────────────────────────────┘
```

- **一个后端**：公开站与 admin 站访问的是**同一个后端进程**（或同一镜像跑多副本连同一库）。数据只有一份，天然一致。
- **两个前端**：各自独立 Next.js 项目（或同一仓库两个独立前端目录）。公开前端不含 admin；admin 前端是专用控制台。
- **同一个库**：SQLite 文件即可支撑（自用内测规模）。数据归属靠 `owner_id` + `role` 隔离，不是靠数据库分库。

### 2.2 为什么是「单后端 + 双前端」而不是「双后端双库」

你已经选了这个方向，理由在工程上是对的：

- **数据一致性**：管理后台最怕看到和前台不一致的数据。共用一个后端+库，admin 看到的就是实时的真实数据，无需做跨库同步/ETL。
- **一套引擎/一套鉴权**：分析引擎、BYOK 逻辑、搜索降级、`require_admin` 都只维护一份。
- **成本**：自用内测规模，单后端足够；不必为 admin 单独起一套后端进程烧服务器。
- **隔离仍达成**：隔离发生在**前端代码层（admin 不进公开包）** + **反代层（admin API 不对公开域名暴露）** + **角色层（require_admin 403）** 三层。你要的「别人 clone 看不到 admin」由第一层保证。

### 2.3 「别人 clone 后跑什么」= 公开版（干净独立）

公开版应做到**从仓库拉下来即能单独跑**，且**不含任何 admin 痕迹**：

| 项 | 公开版要求 |
|---|---|
| 前端代码 | 不含 `admin-console/*` 目录、不含 admin 导航入口、不含 admin API 调用 |
| 前端入口 | 头像菜单只有「普通用户」视角；登录后是分析工作台 |
| 后端 | 保留 `/api/admin/*`（真源），但公开版默认**不暴露**（见 2.4 反代/开关） |
| 环境 | `PUBLIC_MODE=1`（BYOK，访客自带 LLM key，联网跑） |
| 联网检索 | `SEARCH_ENABLED=auto`，无 key 自动降级 DDG（已支持） |

> 「干净」指的是：**普通访问者（非 admin 账号）在公开站上既看不到 admin 入口，也访问不到 admin API**。代码是否打包进前端镜像，是反代/构建时可控的，见 §四迁移步骤。

### 2.4 「admin 后台你单独怎么跑」= 独立入口 + 独立访问

admin 不依赖公开站的前端，你是**单独跑一份 admin 前端**，可选两种部署拓扑：

**拓扑 A（推荐 · 独立域名）**
```
admin.你的域名.com ── Caddy ──▶ admin 前端(next 3001)
                                    │ 只代理 /api/admin/* + /api/auth/me 等 admin 所需
                                    ▼
                             同一后端 FastAPI(:8000) + SQLite
公开站域名 ── Caddy ──▶ 公开前端(next 3000)
```
- 最干净：admin 前端是独立进程/独立容器，公开前端里连 admin 代码都不打包。
- Caddy 对 `admin.域名` 只放行 admin 需要的路径；对公开站则**显式拒绝 `/api/admin/*`**。

**拓扑 B（同服务器 · 独立端口/路径）**
```
单服务器：:10000 公开站（Caddy 拒绝 /api/admin/*）
          :10001 admin 站（Caddy 放行 /api/admin/*）
```
- 省钱，但你自己的 admin 和公开站在同一台机/同一容器族，靠端口+路径隔离。适合内测期。

---

## 三、标准「联网的多用户 SaaS」是怎么设计的

这一节回答你「正常联网的用户系统 + 管理员后台都是怎么设计的」，并对照本项目当前取舍。

### 3.1 前台（用户端 / 公开工作台）

真正对外时，公开前端只做**用户自己的工作台**，职责单一：

1. **注册 / 登录 / 退出**（邮箱+密码；可选邮箱验证）。
2. **自带 Key 使用能力**（本项目 BYOK：访客在设置里填自己的 DeepSeek key，服务器不持有——这是本项目区别于普通 SaaS 的关键，**对外必须保留**，见红线 §5.2）。
3. **创建/管理自己的 project / task / report**，全部按 `owner_id` 隔离，**看不到别人的**。
4. 前端代码里**没有任何 admin 路由/入口/API 调用**。

### 3.2 后台（管理端 / 独立运营控制台）

标准 SaaS 的管理后台通常满足这几条，对照本项目：

| 标准设计 | 说明 | 本项目现状 / 需补 |
|---|---|---|
| **角色 RBAC** | 至少 `user` / `admin`；规模化可加 `moderator`（内容审核）/ `operator`（运营） | 现仅 user/admin 两档；Phase 1 够用，可预留 role 扩展 |
| **独立后台入口** | 独立域名或独立前端，**与用户端代码分离** | 本次改造核心（从藏在前端 → 独立前端） |
| **跨用户数据治理** | 后台能看/审/下架/删除**任何用户**的 project/task/report | 已做（admin_ops.py 跨用户豁免直查库） |
| **用户与审计** | 用户列表、封禁/解封、单用户明细、操作审计日志 | 用户管理已做；**操作审计日志待补** |
| **运营看板** | 注册/活跃趋势、报告产出、任务成功率、用量 | 已做 overview 趋势卡；可加任务成功率/用量明细 |
| **系统状态** | 健康、队列积压、存储、模式 | 已做（/api/admin/system） |
| **安全隔离** | 后台端点统一鉴权、防越权、防 admin 误删 | 已做 require_admin + 删除二次确认 |

### 3.3 前台与后台在「代码上」如何共存

业界两种主流组织方式，本项目可按需要二选一：

- **方案①（monorepo 双前端目录，推荐本项目）**：一个 git 仓库里放 `frontend/`（公开）+ `admin-console/`（独立前端）两个独立 Next.js 项目，各自 `package.json` / `next.config`，共享 `frontend/src/lib/` 的部分类型定义。后端一个。**别人 clone 到的是整个仓库**，但要「只跑公开版」只需按 §四把公开前端 + 后端起起来；admin 前端可起可不起。
- **方案②（两个独立仓库）**：公开仓库（前端+后端）一个，admin 仓库另一个。隔离最彻底，但维护两套 git、两套 CI、共享代码难同步。**现阶段不推荐**（你是单人）。

> 关键区分：**「仓库是否含 admin 代码」≠「别人能否访问 admin」**。即便仓库里有 admin 代码（monorepo），只要：(a) admin 前端默认不 build/不 serve，(b) 公开站反代拒绝 `/api/admin/*`，(c) 非 admin 账号登录 403——别人就既看不到入口也调不到数据。真正要「仓库里连 admin 代码都不出现」，才需要两个仓库或条件构建。

### 3.4 前后端如何通信（联网下的核心）

两个前端都访问**同一个后端**，靠 **CORS + 同源/跨域**策略区分：

| 部署 | 前端→后端请求 | CORS 需要 |
|---|---|---|
| 本地开发 | `http://127.0.0.1:8000`（跨域） | 放行 localhost:3000 + localhost:3001 |
| 同源公网（单域） | 相对路径 `/api/*`，由反代转发 | 无需 CORS（同源） |
| **双域公网（公开站 + admin 站，共享后端）** | 各自跨域到后端 | **后端 CORS 必须同时放行两个域名** |

> ⚠️ **当前 CORS 是硬编码 `["http://localhost:3000","http://127.0.0.1:3000"]`**，只能放一个前端源。共享后端 + 双域部署时，**必须把 CORS 来源改成可配置**（见 §4.1 改造点 #3）。这是本次最不能漏的一项。

---

## 四、迁移步骤（从「内置版」到「双前端」）

按「先架构铺对、能上生产、能扩展；本次不必一次塞满」原则。分两阶段：

### Phase A：代码层拆离（本次建议做，风险低、收益明确）

| # | 改动 | 文件/动作 | 风险 |
|---|---|---|---|
| A1 | **CORS 可配置多源** | `backend/app/main.py` CORS `allow_origins` 改为读 `settings.cors_origins`（env `CORS_ORIGINS`，逗号分隔，默认 `http://localhost:3000,http://127.0.0.1:3000`） | 低（加默认值零回归） |
| A2 | **后端 admin 路由按 env 条件注册（S5）** | `backend/app/main.py` 只在 `ADMIN_API_ENABLED=1` 时才 `include_router(admin_ops.admin_router)` 与 `auth.admin_router`；公开版设 0 → **进程里无任何 /api/admin/*** | 低（默认开，本地不受影响；公开设 0 即摘除） |
| A3 | **确认 admin API 依赖 `require_admin`** | 已做；跑测试确认 `test_admin_ops.py` 7 例全绿 | 低 |
| A4 | **公开版 Caddy 拒绝 admin（纵深兜底）** | 即使 A2 漏配，`deploy/Caddyfile` 公开站仍对 `/api/admin/*` 返 404 不分流——双保险 | 低 |
| A5 | **把独立 admin 前端骨架建出来** | 新建 `admin-console/frontend/`（独立 Next.js，复用现 `/admin-console/*` 页面逻辑）——本次可先做目录+路由壳，暂不搬全量页面 | 中（新项目，工作量） |
| A6 | **公开前端去掉 admin 入口** | `app-shell.tsx` 删「运营后台」Link（或环境变量控制）；公开 build 不含 admin | 低 |

> A5/A6 让 admin 从前端真正独立；A2(S5) 让公开后端进程**彻底无 admin 路由**，A4 是纵深兜底。**若本次时间有限，至少做 A2 + A1 + A6**（达成「公开进程无 admin + 公开站干净」），CORS 收口与 A5 后续补。应用层 DoS 三件套 S1–S3 是独立的安全加固，见 §四·五。

### Phase B：独立部署与运营加固（对外公测前）

| # | 改动 | 说明 |
|---|---|---|
| B1 | **后台操作审计日志** | admin 每做一次封禁/删除/归档记一条 log（谁、何时、对谁、动作）——对外运营必须 |
| B2 | **角色预留 moderator** | 数据模型 role 加 `moderator`（只审内容，不能封号），后端 require_admin 拆 `require_any(admin, moderator)` |
| B3 | **用量统计粒度** | 按天聚合每用户任务数/报告数，供 overview 更细的活跃图 |
| B4 | **admin 前端独立域名 + TLS** | 用 Render/Caddy 给 admin.域名配 https |
| B5 | **找回密码 / 邮箱验证（SMTP）** | 已预留开关，公开时填 SMTP 启用 |
| B6 | **配额与限流** | 单用户任务频率、登录/注册限速（部分已做） |

---

## 四·五、安全加固（DDoS / 滥用 / 渗透）——按你真实代码定，不烧钱

> 这一节专答「这样安全吗 / 防 DDoS / 防黑客渗透」。**判断原则**：你现在是单容器 FastAPI + SQLite、自用/内测体量，真正的云层 DDoS（高防 CDN / WAF / 防火墙）**现阶段对你没用也没必要**——你没有被大流量盯上的价值，且那些是「更上层」的事，不是应用代码能解决的。**真正要防的是两类**：① 应用层滥用（脚本刷接口、占满队列 = 应用层 DoS）；② 渗透/越权（摸 admin、跨用户）。下面全部对应你现有代码的具体洞，可落地，不虚。

### 4.5.0 现状核查结论（2026-09-08 读码）

| 项 | 现状 | 判定 |
|---|---|---|
| admin 端点鉴权 | `admin_ops.py` 8 个端点全 `Depends(require_admin)` | ✅ 扎实 |
| 登录/注册/验证码/改密码限流 | `_RateLimiter`（auth.py:119）已覆盖 | ✅ |
| **核心业务限流**（/api/analyze、搜索、轮询） | **无限流** | ❌ **最大洞** |
| **用户级配额**（防灌爆队列） | **无**（登录用户可无限提交） | ❌ 应用层 DoS |
| 全局并发/队列上限 | WORKER_COUNT=6，队列**无上限** | ❌ 可被占满拖死 |
| cookie 安全 | httponly + secure(public) + samesite=lax | ✅ |
| admin 端点是否在公开进程 | 目前是（同一后端进程） | ⚠️ 需摘除 |
| 操作审计 | **无** | ⚠️ 上线前补 |

### 4.5.1 应用层 DoS / 滥用防护（你现在就该补，成本低）

> 你项目真实风险：任何登录用户可无限调 `/api/analyze`（每次触发 LLM 调用 + 占用 6 worker），脚本能持续灌队列，把你（和所有用户）的任务**永远堵在排队**——这是最现实的 DoS。

| # | 措施 | 对应代码 | 做法 |
|---|---|---|---|
| S1 | **核心接口限流** | `/api/analyze` POST、`/api/analyze/{id}/retry`、搜索 | 复用现成 `_RateLimiter`（auth.py:119），加 `ip` + `user_id` 双键：如每用户 10 次/分钟提交、搜索 20 次/分钟 |
| S2 | **用户级排队配额** | `analyze.py` 提交处 | 查该用户 `status in (queued,running)` 的任务数，超上限（如 5）→ 429「任务过多请稍等」 |
| S3 | **全局并发闸门** | `queue.py` | 设全局排队上限（如 200），超阈值直接 429 拒新任务，**不无限堆积** |
| S4 | **日配额（防持续刷）** | 用户表或内存计数 | 每用户每日分析次数上限（如 50），超了次日重置；配合 BYOK 用户自己花钱，纯浪费服务器资源也有限 |

> ⚠️ 注意：登录/注册限流已按 IP，但**分析等业务接口被刷时，攻击者可换 IP**，所以 S2/S3（用户级配额 + 全局闸门）比纯 IP 限流更关键——它们不依赖 IP，靠账号 + 全局总量兜底。

### 4.5.2 渗透 / 越权防护（上线前必做）

| # | 措施 | 对应洞 | 做法 |
|---|---|---|---|
| S5 | **公开进程彻底无 admin 路由** | admin 端点在公网进程存在（哪怕 403） | 后端启动按 env（如 `ADMIN_API_ENABLED`，公开版设 0）**条件注册** `admin_ops` / `auth.admin_router` → 公开站那个进程里**连 /api/admin/* 都不存在**，渗透无从下手（你已选此路线） |
| S6 | **CORS 精确收口 + Origin 二次校验** | CORS 硬编码 / 双域放开易裸奔 | 只放行你控制的精确源（非 `*`）+ `allow_credentials=True`；admin 请求**再校验 `Origin` 头**必须等于 admin 域名，防跨站带 cookie |
| S7 | **admin 独立域名 + 独立会话** | 共用 cookie 域风险 | admin 走独立域名，登录会话 cookie 与公开站隔离；admin 域名强制 https |
| S8 | **操作审计** | 删内容无日志 | admin 封禁/删除/归档记一条 `(who, action, target, ts)`，可追溯误删与盗号 |
| S9 | **错误信息不泄露内部** | FastAPI 默认可能吐堆栈 | 已做统一异常处理器（main.py），确认公网不返堆栈/表结构 |

### 4.5.3 分层落地（别一次全做，也别乱烧钱）

| 时机 | 做哪些 |
|---|---|
| **现在（代码层，低成本）** | S1 核心限流 + S2 用户排队配额 + S3 全局闸门（堵应用层 DoS 三件套） |
| **这次分拆一起做** | S5 公开进程无 admin + S6 CORS 收口 + S7 admin 独立会话 |
| **对外公测前** | S4 日配额 + S8 操作审计 + admin 域名 https |
| **真有流量/被盯上再考虑（现在别烧钱）** | 云 CDN/WAF/高防、迁 PostgreSQL/Redis、加图形验证码、上云厂商 DDoS 防护 |

### 4.5.4 一句话安全结论

> **架构方向安全**（比「公开仓库藏 admin」强）；把 **S1–S3（应用层滥用三件套）** 和 **S5–S6（admin 摘除 + CORS 收口）** 做掉，就能扛住你体量下真实的 DoS 与渗透。云层高防等有真实公网流量再上。

---

## 五、红线与不可违背约束（务必先读再改）

### 5.1 BYOK（对外核心红线，来自 USER_SYSTEM_PLAN / settings.py）

- 本项目是**访客自带 key**：`PUBLIC_MODE=1` 时 `resolve_config()` 直接返回 `api_key:""`，服务器**不持有、不回退**任何 LLM 密钥，也不烧用户的钱。
- 分拆后**必须保持**：公开版、admin 版访问的都是同一个后端，后端在 `PUBLIC_MODE=1` 下**一律不给访客回退服务器 key**。
- 谁要分析，谁填自己的 key（DeepSeek）。这是公开版能独立给陌生访客用、而服务器不担账的前提。

### 5.2 本地零回归

- 分拆不能破坏你本地现有体验。CORS 改造、admin 开关都必须有默认值，`PUBLIC_MODE=0`（本地）时一切照旧可跑。
- 数据库路径 `backend/data/app.db` 不变；`APP_DB_PATH` 覆盖能力保留（隔离测试/多实例）。

### 5.3 数据库与并发

- SQLite 单文件，`timeout=30` 写锁。自用内测规模够；若未来真实多用户并发高，再迁 PostgreSQL（后端 ORM 用 SQLAlchemy，迁移成本可控，但**本次不动**）。

---

## 六、风险与回滚

| 风险 | 概率 | 缓解 |
|---|---|---|
| CORS 改坏导致前端连不上 | 低 | A1 默认值保持原样；改完本地起双前端验证 |
| admin 前端独立后功能不全 | 中 | 先做骨架壳，页面逻辑从内置版逐步搬；内置版 `/admin-console` 保留为真源直到搬完 |
| 公开仓库仍含 admin 代码被质疑 | 低（monorepo） | 用「反代拒 + role 拒 + 不 serve」证明访问隔离；确需代码级移除再走双仓库 |
| 误删数据（admin 删用户内容） | 低 | 删除一律先归档 + confirm 二次确认（已做） |

**回滚**：本次改动都是「加默认值」型（CORS 可配置、admin 开关、Caddy 规则、独立目录），不删除现有文件。任一步不满意，把 env 恢复 + 撤回新增目录即可回到内置版。

---

## 七、本次建议先做哪些（对应你选「1+3」）

你选了「前端分开后端共用」+「独立域名跑」+「先出方案不急着全拆」，并追加要求**更安全 / 防 DDoS / 防渗透**。据此，**本次落地优先级**：

1. **先读通本方案**（现在这份），尤其 §四·五 安全加固。
2. **立刻可做（低风险，先堵最现实的洞）**：
   - **S1 核心接口限流 + S2 用户排队配额 + S3 全局闸门**（应用层 DoS 三件套，堵「刷接口占满队列」）——最真实的风险，独立于分拆，可先做。
   - **A2 后端 admin 路由条件注册 + A6 公开前端去 admin 入口**（让「公开进程无 admin + 公开站干净」成立）。
3. **分拆一起做**：A1 CORS 可配置（精确源收口）+ A4 Caddy 兜底 + A5 admin 独立前端骨架。
4. **对外公测前**（Phase B）：S4 日配额、S8 操作审计、admin 独立域名 https、角色/用量细化。
5. **现在别烧钱**：云 CDN/WAF/高防 DDoS、迁 PostgreSQL/Redis——等真有公网流量 / 被盯上再上（见 §四·五 分层）。

---

*本方案所有「现状」均经 2026-09-08 读码核实（Dockerfile / render.yaml / deploy/* / settings.py / main.py / db.py / admin_ops.py / auth.py / app-shell.tsx / admin-console/*）。*
