"""数据库层 — 账本（Phase 2.1）。

本地 SQLite 文件（backend/data/app.db）：零配置、不外放，贴合「仅本地联调」安全约束。
SQLAlchemy 2.x ORM。所有 DB 操作通过 SessionLocal；在 FastAPI 异步路由里用
asyncio.to_thread 包一层，避免阻塞事件循环。

数据库即队列：任务行 status='queued' 即在排队（见 app/queue.py）。
"""
from pathlib import Path

import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# 数据库文件放在 backend/data/ 下（已加入 .gitignore，不提交）
# 可用 APP_DB_PATH 环境变量覆盖（便于隔离测试 / 多实例部署，避免共享同一库）
_DB_DEFAULT = Path(__file__).resolve().parent.parent / "data" / "app.db"
DB_PATH = Path(os.environ.get("APP_DB_PATH") or _DB_DEFAULT).resolve()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# check_same_thread=False：工人线程与事件循环会并发访问同一 SQLite 文件
# timeout=30：写锁等待，降低并发下的 "database is locked"
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False, "timeout": 30},
    future=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _record):
    """WAL 模式：多读者+单写者并发，显著降低多工人同时写时的 "database is locked"；
    并冗余设置 busy_timeout。"""
    cur = dbapi_conn.cursor()
    try:
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
    finally:
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """建表（幂等）。延迟导入模型，确保它们注册到 Base.metadata。"""
    from sqlalchemy import inspect, text

    from app import models  # noqa: F401  (注册表结构)

    Base.metadata.create_all(engine)

    # 2.4 迁移：为已有 tasks 表补齐 mode/structured/llm_config 列（SQLite 不自动加列）
    with engine.connect() as conn:
        cols = {c["name"] for c in inspect(engine).get_columns("tasks")}
        alters = []
        if "mode" not in cols:
            alters.append("ALTER TABLE tasks ADD COLUMN mode VARCHAR(16) DEFAULT 'rule'")
        if "structured" not in cols:
            alters.append("ALTER TABLE tasks ADD COLUMN structured JSON")
        if "llm_config" not in cols:
            alters.append("ALTER TABLE tasks ADD COLUMN llm_config JSON")
        # 2.3/阶段三预留：项目归属 / 会员系统外键列（旧库可能缺）
        if "project_id" not in cols:
            alters.append(
                "ALTER TABLE tasks ADD COLUMN project_id VARCHAR(64) "
                "REFERENCES projects(id)"
            )
        if "owner_id" not in cols:
            alters.append(
                "ALTER TABLE tasks ADD COLUMN owner_id VARCHAR(32) "
                "REFERENCES users(id)"
            )
        # 阶段三（项目闭环）：错误结构化字段 + 重试血缘
        for col in ("error_type", "error_phase", "error_detail", "retry_of"):
            if col not in cols:
                fk = " REFERENCES tasks(id)" if col == "retry_of" else ""
                alters.append(f"ALTER TABLE tasks ADD COLUMN {col} VARCHAR{fk}")
        if "attempt_no" not in cols:
            alters.append("ALTER TABLE tasks ADD COLUMN attempt_no INTEGER DEFAULT 1")
        # Project 新列（归档/软删除 + 会员归属）
        pcols = {c["name"] for c in inspect(engine).get_columns("projects")}
        for col, ddl in (
            ("is_archived", "INTEGER DEFAULT 0"),
            ("archived_at", "DATETIME"),
            ("owner_id", "VARCHAR(32) REFERENCES users(id)"),
        ):
            if col not in pcols:
                alters.append(f"ALTER TABLE projects ADD COLUMN {col} {ddl}")
        # 阶段三：material_ids（分析使用的材料列表，存 tasks）
        if "material_ids" not in cols:
            alters.append("ALTER TABLE tasks ADD COLUMN material_ids JSON")
        for col, ddl in (
            ("operation", "VARCHAR(24) DEFAULT 'analysis'"),
            ("target_task_id", "VARCHAR(32) REFERENCES tasks(id)"),
            ("base_version_id", "VARCHAR(32)"),
        ):
            if col not in cols:
                alters.append(f"ALTER TABLE tasks ADD COLUMN {col} {ddl}")
        # 阶段四：LLM 增强元信息（模型/温度/提示词版本/原始响应）
        for col, ddl in (
            ("llm_model", "VARCHAR(120)"),
            ("llm_temperature", "FLOAT"),
            ("prompt_version", "VARCHAR(32)"),
            ("llm_raw_response", "TEXT"),
        ):
            if col not in cols:
                alters.append(f"ALTER TABLE tasks ADD COLUMN {col} {ddl}")
        # 6 步分析进度链：phase（当前阶段）+ progress_pct（总进度百分比）
        if "phase" not in cols:
            alters.append("ALTER TABLE tasks ADD COLUMN phase VARCHAR(32)")
        if "progress_pct" not in cols:
            alters.append("ALTER TABLE tasks ADD COLUMN progress_pct INTEGER DEFAULT 0")
        if "input_mode" not in cols:
            alters.append("ALTER TABLE tasks ADD COLUMN input_mode VARCHAR(16)")
        if "requested_engine" not in cols:
            alters.append("ALTER TABLE tasks ADD COLUMN requested_engine VARCHAR(16)")
        if "quality_score" not in cols:
            alters.append("ALTER TABLE tasks ADD COLUMN quality_score INTEGER")
        if "quality_result" not in cols:
            alters.append("ALTER TABLE tasks ADD COLUMN quality_result JSON")
        # 阶段五：全网搜索（可选增强）
        if "search_enabled" not in cols:
            alters.append("ALTER TABLE tasks ADD COLUMN search_enabled BOOLEAN")
        if "search_results" not in cols:
            alters.append("ALTER TABLE tasks ADD COLUMN search_results JSON")
        # T8：联网写报告（web 开关 + 来源白名单）
        if "web" not in cols:
            alters.append("ALTER TABLE tasks ADD COLUMN web BOOLEAN DEFAULT 0")
        if "source_urls" not in cols:
            alters.append("ALTER TABLE tasks ADD COLUMN source_urls JSON")
        if "monitor_id" not in cols:
            alters.append(
                "ALTER TABLE tasks ADD COLUMN monitor_id VARCHAR(32) "
                "REFERENCES research_monitors(id)"
            )
        # T13：report_versions 版本管理扩展（version_no/edited_by/summary/is_current）
        vcols = {c["name"] for c in inspect(engine).get_columns("report_versions")}
        for col, ddl in (
            ("version_no", "INTEGER DEFAULT 1"),
            ("edited_by", "VARCHAR(16) DEFAULT 'ai'"),
            ("summary", "VARCHAR(500)"),
            ("is_current", "INTEGER DEFAULT 0"),
            ("research_snapshot", "JSON"),
            ("research_status", "VARCHAR(16) DEFAULT 'unavailable'"),
        ):
            if col not in vcols:
                alters.append(f"ALTER TABLE report_versions ADD COLUMN {col} {ddl}")
        # 阶段三：Material 来源/标签/解析告警
        mcols = {c["name"] for c in inspect(engine).get_columns("materials")}
        for col, ddl in (
            ("source", "VARCHAR(500)"),
            ("tags", "VARCHAR(500)"),
            ("warnings", "JSON"),
            ("owner_id", "VARCHAR(32) REFERENCES users(id)"),
        ):
            if col not in mcols:
                alters.append(f"ALTER TABLE materials ADD COLUMN {col} {ddl}")
        # 用户系统 Phase 0：users 表补 role / is_banned / last_seen_at（旧库可能缺）
        ucols = {c["name"] for c in inspect(engine).get_columns("users")}
        for col, ddl in (
            ("role", "VARCHAR(16) DEFAULT 'user'"),
            ("is_banned", "INTEGER DEFAULT 0"),
            ("last_seen_at", "DATETIME"),
            # 邮箱验证（Phase 1）
            ("email_verified", "INTEGER DEFAULT 0"),
            ("verification_code", "VARCHAR(8)"),
            ("verification_code_expires", "DATETIME"),
            # 账户恢复流：会话失效锚点（改密/重置后旧 JWT 失效）
            ("token_valid_after", "DATETIME"),
        ):
            if col not in ucols:
                alters.append(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
        for sql in alters:
            conn.execute(text(sql))
        if alters:
            conn.commit()

        # 2.6 迁移：report_versions (task_id, version_no) 唯一索引，
        # 防止并发保存产生重复版本号（对已有库同样生效）。
        # 先清理历史重复行（同任务同版本号仅保留最新一条），再建唯一索引。
        conn.execute(text(
            "DELETE FROM report_versions WHERE id IN ("
            "  SELECT rv.id FROM report_versions rv"
            "  JOIN report_versions rv2 ON rv.task_id = rv2.task_id"
            "   AND rv.version_no = rv2.version_no"
            "   AND (rv.created_at < rv2.created_at"
            "        OR (rv.created_at = rv2.created_at AND rv.id < rv2.id))"
            ")"
        ))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_report_versions_task_version "
            "ON report_versions (task_id, version_no)"
        ))
        # 历史库若曾出现多个 current，保留版本号最高的一条。
        conn.execute(text(
            "UPDATE report_versions SET is_current = 0 "
            "WHERE is_current = 1 AND EXISTS ("
            "  SELECT 1 FROM report_versions newer"
            "  WHERE newer.task_id = report_versions.task_id"
            "    AND newer.is_current = 1"
            "    AND newer.version_no > report_versions.version_no"
            ")"
        ))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_report_versions_one_current "
            "ON report_versions (task_id) WHERE is_current = 1"
        ))
        conn.commit()


def seed_admin_user() -> str:
    """确保 admin 用户存在（用户系统 Phase 0）。

    - 本地单机模式：创建/复用 id='workbench'（settings.default_owner_id）的归属账号，
      password 为空串哈希（本地模式不参与登录）；
    - 公共模式：若 admin 尚无账号，创建初始管理员（密码取 ADMIN_INITIAL_PASSWORD 环境变量，
      未设置则生成随机密码打印到日志一次）。

    返回 admin 的 user id。"""
    import logging
    import secrets

    from app.auth import hash_password
    from app.models import User
    from app.settings import settings

    log = logging.getLogger("app")
    with SessionLocal() as db:
        admin = db.get(User, settings.default_owner_id)
        if admin is None:
            raw = os.environ.get("ADMIN_INITIAL_PASSWORD", "").strip()
            if not raw:
                raw = secrets.token_urlsafe(12)
                log.warning(
                    "[auth] ADMIN_INITIAL_PASSWORD 未设置，已生成随机管理员密码（仅本次打印）：\n  %s",
                    raw,
                )
            admin = User(
                id=settings.default_owner_id,
                email=os.environ.get("ADMIN_EMAIL", "admin@local"),
                display_name=settings.default_owner_name,
                hashed_password=hash_password(raw),
                role="admin",
                is_banned=0,
                email_verified=1,  # 初始管理员不做邮箱验证（本地可能没配 SMTP）
            )
            db.add(admin)
            db.commit()
            log.info("[auth] 已创建管理员账号 %s（%s）", admin.email, admin.id)
        # 存量数据归属迁移：owner_id 为空的行挂到 admin
        from sqlalchemy import text

        for table in ("tasks", "projects", "materials"):
            db.execute(
                text(f"UPDATE {table} SET owner_id = :aid WHERE owner_id IS NULL"),
                {"aid": settings.default_owner_id},
            )
        db.commit()
        return settings.default_owner_id


def seed_projects() -> None:
    """种子项目（阶段三前端项目页将读取）。仅当 projects 表为空时写入。"""
    from app.models import Project

    seed = [
        {
            "id": "saige",
            "name": "赛格事件分析",
            "description": "基于三元结构理论对赛格商场事件的参与主体、利益配置与博弈终局进行结构化拆解。",
            "status": "进行中",
            "subjects": "3",
            "interests": "12",
            "chapters": "8",
            "progress": "68%",
            "owner_name": "三元结构分析工作台",
            "owner_id": "workbench",
        },
        {
            "id": "trademark",
            "name": "商标管理保护条例修订",
            "description": "对《商标管理与保护条例》修订的条文进行利益动线与制度影响分析。",
            "status": "已完成",
            "subjects": "4",
            "interests": "15",
            "chapters": "8",
            "progress": "100%",
            "owner_name": "三元结构分析工作台",
            "owner_id": "workbench",
        },
        {
            "id": "relocation",
            "name": "旧城改造搬迁补偿",
            "description": "围绕旧城改造搬迁补偿方案，拆解政府、开发商、居民等多方利益博弈。",
            "status": "进行中",
            "subjects": "5",
            "interests": "20",
            "chapters": "8",
            "progress": "45%",
            "owner_name": "三元结构分析工作台",
            "owner_id": "workbench",
        },
    ]
    with SessionLocal() as db:
        if db.query(Project).count() == 0:
            for s in seed:
                db.add(Project(**s))
            db.commit()
