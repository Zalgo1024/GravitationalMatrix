"""数据模型 — 账本里的「账页」（Phase 2.1）。

- Task：每一条分析任务（分析报告）的完整记录，替代原进程内存 dict。
- User：会员系统预留表（Phase 2.3 未启用，仅建好骨架，不写注册/登录逻辑）。
- Project：项目（分析报告归属），为阶段三前端接真实数据铺路；此处先建表 + 种子数据。

⚠️ 会员系统（注册/登录/多用户隔离）按用户要求「仅预留、暂不设计」，
   User 表与 Task.owner_id / Task.project_id 仅占位，当前所有接口仍视为单用户、无鉴权。
"""
from datetime import datetime, timezone
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Float,
    Integer,
    Index,
    JSON,
    String,
    Text,
    text,
)
from sqlalchemy.orm import relationship

from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """用户表（Phase 2.3 预留结构 + 用户系统 Phase 0 激活）。

    - 本地单机模式（PUBLIC_MODE=0）：不写任何用户行，接口按 default_owner_id 归属；
    - 公共模式（PUBLIC_MODE=1）：注册/登录启用，所有写入数据按 owner_id 隔离。
    """

    __tablename__ = "users"

    id = Column(String(32), primary_key=True)
    email = Column(String(255), unique=True, nullable=False)
    display_name = Column(String(120), nullable=True)
    hashed_password = Column(String(255), nullable=False)  # bcrypt 哈希
    role = Column(String(16), default="user")  # user | admin
    is_banned = Column(Integer, default=0)  # 0=正常 1=封禁（封禁后所有接口拒绝）
    created_at = Column(DateTime(timezone=True), default=_now)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)  # 最后活跃（后台看板用）
    # 邮箱验证（Phase 1）：SMTP 未配置时注册直接置 1（验证功能关闭，零影响）；
    # verification_code 为 6 位数字码（单次使用，15 分钟过期）
    email_verified = Column(Integer, default=0)
    verification_code = Column(String(8), nullable=True)
    verification_code_expires = Column(DateTime(timezone=True), nullable=True)

    # 会话失效锚点（账户恢复流）：密码被修改/重置时置为当前时间，
    # 签发时间(iat)早于该时刻的 JWT 一律失效 —— 即「改密后其他设备立即下线」。
    token_valid_after = Column(DateTime(timezone=True), nullable=True)

    tasks = relationship("Task", back_populates="owner")


class Project(Base):
    """项目（分析报告归属）。阶段三前端项目页将读取此表。"""

    __tablename__ = "projects"

    id = Column(String(64), primary_key=True)  # 例如 "saige"
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(32), default="active")  # 进行中 / 已完成 / active ...
    subjects = Column(String(16), default="0")  # 利益主体数（种子值）
    interests = Column(String(16), default="0")  # 利益项数
    chapters = Column(String(16), default="0")  # 报告章节数
    progress = Column(String(16), default="0")  # 完成度
    owner_name = Column(String(120), nullable=True)
    is_archived = Column(Integer, default=0)  # 0=活跃 1=已归档（软删除）
    archived_at = Column(DateTime(timezone=True), nullable=True)
    # 会员系统预留（与 Task.owner_id 对齐，当前默认「三元结构分析工作台」）
    owner_id = Column(String(32), ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    tasks = relationship("Task", back_populates="project")


class Task(Base):
    """分析任务 / 分析报告（核心账页）。"""

    __tablename__ = "tasks"

    id = Column(String(32), primary_key=True)  # uuid4().hex
    title = Column(String(500), nullable=False)
    input_text = Column(Text, nullable=False)
    analysis_type = Column(String(32), default="case")  # case | policy

    status = Column(String(16), default="queued")  # queued|generating|done|error
    # —— 6 步分析进度链（inspect→search→decompose→network→organize→output）——
    phase = Column(String(32), nullable=True)       # 当前所处阶段（null=尚未开始）
    progress_pct = Column(Integer, default=0)        # 0-100 总进度百分比
    result = Column(JSON, nullable=True)  # 完成后：{markdown,word,pdf,diagrams,title}
    error = Column(Text, nullable=True)  # 失败后：人类可读错误摘要（不含完整堆栈）
    # —— 结构化错误信息（前端展示「重试」按钮 + 可读原因）——
    error_type = Column(String(64), nullable=True)   # 异常类名：如 RuntimeError / ValueError
    error_phase = Column(String(32), nullable=True)  # 失败阶段：validate|generate|export
    error_detail = Column(Text, nullable=True)      # 安全摘要（已脱敏路径/密钥）

    # —— 重试血缘：当前任务是某失败任务的「重试版」时指向原任务 ——
    retry_of = Column(
        String(32), ForeignKey("tasks.id"), nullable=True, index=True
    )
    attempt_no = Column(Integer, default=1)  # 第几次尝试（1=首次）

    # —— 生成模式（2.4 内置规则引擎 + 可选 LLM 插件）——
    mode = Column(String(16), default="rule")  # 实际执行引擎：rule | llm
    input_mode = Column(String(16), nullable=True)  # freeform | structured
    requested_engine = Column(String(16), nullable=True)  # auto | rule | llm
    structured = Column(JSON, nullable=True)   # rule 模式：结构化输入
    llm_config = Column(JSON, nullable=True)    # llm 模式：每请求 {api_key,base_url,model}

    # —— 会员系统 / 项目归属预留（2.3 / 阶段三 未启用）——
    owner_id = Column(String(32), ForeignKey("users.id"), nullable=True)
    project_id = Column(String(64), ForeignKey("projects.id"), nullable=True)

    # —— 阶段三：分析使用到的材料（Material.id 列表，记录证据出处）——
    material_ids = Column(JSON, nullable=True)

    # —— 报告后续研究任务：基于指定版本补充证据，不与新分析混在一起 ——
    operation = Column(String(24), default="analysis")  # analysis | enrichment
    target_task_id = Column(String(32), ForeignKey("tasks.id"), nullable=True, index=True)
    base_version_id = Column(String(32), nullable=True, index=True)

    # —— 阶段五：全网搜索（可选增强）——
    search_enabled = Column(Boolean, nullable=True)  # None=自动 | True=强制搜索 | False=跳过
    search_results = Column(JSON, nullable=True)      # 搜索结果摘要 {query,snippets,sources,provider}

    # —— T8：联网写报告（web 开关 + 用户勾选来源白名单）——
    web = Column(Boolean, default=False)              # True=联网检索/抓取素材写报告
    source_urls = Column(JSON, nullable=True)          # 用户勾选白名单（null=自动检索全部）
    monitor_id = Column(String(32), ForeignKey("research_monitors.id"), nullable=True, index=True)

    # —— F2：自动取证（分析时同步跑多平台采集并把结果入库素材库）——
    auto_collect = Column(Boolean, default=False)     # True=本次分析附带多平台采集入库

    # —— 阶段四：LLM 增强模式元信息（仅在 llm 模式记录，便于复现与审计）——
    llm_model = Column(String(120), nullable=True)       # 实际使用的模型（如 deepseek-chat）
    llm_temperature = Column(Float, nullable=True)        # 采样温度
    prompt_version = Column(String(32), nullable=True)    # 提示词版本（可复现）
    llm_raw_response = Column(Text, nullable=True)        # LLM 原始响应（截断存储，调试用）

    # —— 报告写作规格的可执行质量闸门 ——
    quality_score = Column(Integer, nullable=True)
    quality_result = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)

    owner = relationship("User", back_populates="tasks")
    project = relationship("Project", back_populates="tasks")


class ReportVersion(Base):
    """报告版本 — 支持「原始生成版 / 人工修订版」双轨。

    - 每篇报告（Task）至少有一个 kind='original' 的版本，内容来自生成引擎产出的 Markdown；
      首次访问报告版本接口时自动播种，确保原始稿永不丢失。
    - 用户在编辑器里保存的修订，写入 kind='revised' 的新行；可有多条。
    - content_markdown 为权威文本（用于引擎再导出 Word/PDF）；content_html 为编辑器富文本快照。
    """

    __tablename__ = "report_versions"
    __table_args__ = (
        Index(
            "uq_report_versions_task_version",
            "task_id",
            "version_no",
            unique=True,
        ),
        Index(
            "uq_report_versions_one_current",
            "task_id",
            unique=True,
            sqlite_where=text("is_current = 1"),
        ),
    )
    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    task_id = Column(
        String(32),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind = Column(String(16), default="revised")  # original | revised | enriched
    content_markdown = Column(Text, nullable=False)
    content_html = Column(Text, nullable=True)
    note = Column(String(500), nullable=True)  # 修订说明
    editor = Column(String(120), nullable=True)  # 修订人（当前单用户；保存时取 settings.default_owner_name，可配置）
    created_at = Column(DateTime(timezone=True), default=_now)

    # —— T13：版本管理扩展（version_no 从 1 起；original 恒为 v1；is_current 回滚语义）——
    version_no = Column(Integer, default=1)              # v1/v2/v3…
    edited_by = Column(String(16), default="ai")         # human | ai
    summary = Column(String(500), nullable=True)         # 改动摘要
    is_current = Column(Integer, default=0)              # 0/1 当前版本标记
    research_snapshot = Column(JSON, nullable=True)      # 与本版本正文绑定的证据—判断账本
    research_status = Column(String(16), default="unavailable")  # verified | fallback | stale | unavailable

    task = relationship("Task")


class ResearchMonitor(Base):
    """Local scheduled re-analysis configuration for one project."""

    __tablename__ = "research_monitors"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    project_id = Column(
        String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    seed_task_id = Column(String(32), ForeignKey("tasks.id"), nullable=False)
    enabled = Column(Boolean, default=False)
    interval_hours = Column(Integer, default=24)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    last_task_id = Column(String(32), ForeignKey("tasks.id"), nullable=True)
    last_success_task_id = Column(String(32), ForeignKey("tasks.id"), nullable=True)
    latest_change = Column(JSON, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)


class BenchmarkRun(Base):
    """One repeatable same-task comparison across system, general AI and human work."""

    __tablename__ = "benchmark_runs"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    task_id = Column(String(32), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    version_id = Column(String(32), ForeignKey("report_versions.id", ondelete="SET NULL"), nullable=True)
    system_snapshot = Column(JSON, nullable=False)
    general_snapshot = Column(JSON, nullable=True)
    human_snapshot = Column(JSON, nullable=True)
    audits = Column(JSON, nullable=True)
    durations = Column(JSON, nullable=True)
    candidate_metadata = Column(JSON, nullable=True)
    preference = Column(String(16), default="unset")
    notes = Column(Text, nullable=True)
    result = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)


class Material(Base):
    """输入材料 — 用户手动粘贴的长文本或上传的文件（.txt/.md/.docx/.pdf）。

    - 作为分析的证据 / 上下文来源，可在向导「证据与依据」步骤一键插入。
    - content_text 为解析后的纯文本（docx/pdf 已抽取正文），便于检索与插入。
    - source_type：paste(粘贴) | txt | md | docx | pdf。
    """

    __tablename__ = "materials"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    project_id = Column(
        String(64),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # 用户系统 Phase 0：材料归属（与 Task.owner_id / Project.owner_id 对齐）
    owner_id = Column(String(32), ForeignKey("users.id"), nullable=True)
    title = Column(String(200), nullable=False, default="未命名素材")
    content_text = Column(Text, nullable=False, default="")
    source_type = Column(String(16), default="paste")  # paste|txt|md|docx|pdf
    # —— 阶段三：来源 / 标签 / 解析告警 ——
    source = Column(String(500), nullable=True)        # 来源出处：链接 / 文号 / 出处说明
    tags = Column(String(500), nullable=True)          # 逗号分隔标签（如：政策,业主陈述）
    original_filename = Column(String(255), nullable=True)
    char_count = Column(Integer, default=0)
    # 解析告警（JSON 数组，如 ["pdf_text_empty","pdf_garbled","pdf_too_large"]）
    warnings = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now)

    project = relationship("Project")


class PasswordResetToken(Base):
    """忘记密码 → 一次性重置令牌（账户恢复流）。

    安全设计（对齐业界通行做法）：
    - 数据库只存 token 的 sha256 十六进制哈希，明文仅存在于发往用户邮箱的链接里；
      即便数据库泄露，也无法据此直接重置任何账号。
    - 单次使用：used_at 非空即作废；同一用户再次申请时，此前未用的令牌一并作废。
    - 短时效：默认 30 分钟过期。
    """

    __tablename__ = "password_reset_tokens"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    user_id = Column(
        String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash = Column(String(64), nullable=False, index=True)  # sha256 hex
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now)


class AuditLog(Base):
    """运营审计日志：谁 / 何时 / 对谁 / 做了什么（只追加，不修改）。

    敏感操作（封禁、角色变更、删除、重置密码等）全部留痕，供后台追溯。
    actor_id / actor_email 冗余存快照——即使用户后来被删，日志仍可读。
    """

    __tablename__ = "audit_logs"

    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    actor_id = Column(String(32), nullable=True, index=True)
    actor_email = Column(String(255), nullable=True)
    action = Column(String(64), nullable=False, index=True)  # 如 user.ban / project.delete
    target_type = Column(String(32), nullable=True)  # user | project | task | auth
    target_id = Column(String(64), nullable=True)
    detail = Column(JSON, nullable=True)  # 动作附加信息（前后值等）
    ip = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now, index=True)
