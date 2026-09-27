"""FastAPI 应用 — 后端（内部使用，仅监听 127.0.0.1）。

启动（在 backend/ 目录下，已配置 .env）：
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

路由已拆分为 app/routers/ 下的模块化路由（analyze / settings / projects /
reports / materials / system）。本文件只负责装配 app、CORS、startup 与统一异常处理。

安全说明：本服务仅监听 127.0.0.1，不直接对外暴露。
认证为双模式（PUBLIC_MODE 开关）：
- =0 本地单机：get_current_user 返回虚拟身份，界面无登录元素（零回归）；
- =1 公网/本地启用：JWT 会话 + 封禁校验 + owner_id 数据隔离，
  登录/注册/邮箱验证/管理后台由 app/routers/auth.py 提供（见 app/models.py）。
"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import queue as taskq
from app.db import init_db, seed_admin_user, seed_projects
from app.routers import admin_ops, analyze, auth, benchmarks, cases, collect, github_oauth, materials, monitoring, projects, regions, reports, search, settings, system, tasks
# 注意：上面 routers 里的 `settings` 是路由模块，此处配置实例必须另起别名，
# 否则会覆盖 `settings.router` 导致装配失败。
from app.settings import settings as app_settings

logger = logging.getLogger("app")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """启动/关停钩子（替代已弃用的 @app.on_event("startup")）。

    启动序：建表 → 种子项目 → admin 账号 + 存量归属回填 → 恢复中断任务 →
    启动工人池 + 持续追踪/维护调度。
    """
    logger.info(
        "[main] 启动：public_mode=%s admin_api=%s smtp=%s",
        app_settings.public_mode,
        ADMIN_API_ENABLED,
        app_settings.smtp_enabled,
    )
    if app_settings.public_mode and ADMIN_API_ENABLED:
        logger.warning(
            "[main] 公网模式下仍开启了管理端路由（/api/admin/*）。"
            "若这是对外发布的进程，请设置 ADMIN_API_ENABLED=0；仅在你自己的私有实例上保留开启。"
        )
    init_db()
    seed_projects()
    seed_admin_user()
    taskq.recover_interrupted()
    taskq.start_workers()
    from app.monitoring import start_monitor_scheduler

    start_monitor_scheduler()
    yield


# —— 管理端路由门控（A2/S5）——
# 公开部署的进程**不注册任何 /api/admin/* 路由**：管理面与用户面在路由层彻底分开，
# 避免「一个中间件漏挂 / 一个路由 bug」就把管理端点暴露给未登录访客。
# 取值（环境变量 ADMIN_API_ENABLED）：
#   "1"/true  → 强制开启（你自己的私有实例在 backend/.env 里显式设 1）
#   "0"/false → 强制关闭（对外发布建议显式设 0）
#   未设置    → 自动：本地单机(PUBLIC_MODE=0) 开启；公网(PUBLIC_MODE=1) 关闭
_raw_admin_flag = os.environ.get("ADMIN_API_ENABLED", "").strip().lower()
if _raw_admin_flag in {"1", "true", "yes", "on"}:
    ADMIN_API_ENABLED = True
elif _raw_admin_flag in {"0", "false", "no", "off"}:
    ADMIN_API_ENABLED = False
else:
    ADMIN_API_ENABLED = not app_settings.public_mode

app = FastAPI(title="引力矩阵引擎 - 后端（内部使用）", lifespan=_lifespan)

# 仅允许本机前端跨域，不外放。来源由 CORS_ORIGINS 配置（A1），
# 默认放行工作台 3000 + 独立运营后台 3001，localhost 与 127.0.0.1 均含。
# 因需带 cookie（credentials），来源必须是精确值，不能用通配符。
app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================ 统一异常处理（P1·异常处理不统一） ============================
# 未捕获异常统一返回 JSON 错误信封（不泄露堆栈），并保持 HTTPException /
# 请求校验错误的状态码可读。注意：显式返回 {"status": "not_found"}（HTTP 200）的
# 接口属既有契约，不会被此处理器拦截（它们不是异常）。


@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(request, exc: StarletteHTTPException):
    # dict detail（本项目的惯例：{"status": ..., "message": ...}）拆开展开，
    # 避免 str(dict) 把错误消息变成 Python repr 垃圾
    if isinstance(exc.detail, dict):
        detail = dict(exc.detail)
        status_code = detail.pop("status", "http_error")
        message = detail.pop("message", "")
        return JSONResponse(status_code=exc.status_code, content={"error": status_code, "message": message, **detail})
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "http_error", "message": str(exc.detail)},
    )


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "detail": exc.errors()},
    )


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request, exc: Exception):
    logger.exception("未捕获异常：%s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "message": "服务器内部错误，请稍后重试。"},
    )


# ============================ 路由装配 ============================

# —— 管理端路由门控（A2/S5）——
# 公开部署的进程**不注册任何 /api/admin/* 路由**：管理面与用户面在路由层彻底分开，
# 避免「一个中间件漏挂 / 一个路由 bug」就把管理端点暴露给未登录访客。
# 取值（环境变量 ADMIN_API_ENABLED）：
#   "1"/true  → 强制开启（你自己的私有实例在 backend/.env 里显式设 1）
#   "0"/false → 强制关闭（对外发布建议显式设 0）
#   未设置    → 自动：本地单机(PUBLIC_MODE=0) 开启；公网(PUBLIC_MODE=1) 关闭
_raw_admin_flag = os.environ.get("ADMIN_API_ENABLED", "").strip().lower()
if _raw_admin_flag in {"1", "true", "yes", "on"}:
    ADMIN_API_ENABLED = True
elif _raw_admin_flag in {"0", "false", "no", "off"}:
    ADMIN_API_ENABLED = False
else:
    ADMIN_API_ENABLED = not app_settings.public_mode

app.include_router(system.router)
app.include_router(settings.router)
app.include_router(auth.router)  # 用户认证：无论何种模式都注册
if ADMIN_API_ENABLED:
    app.include_router(auth.admin_router)
    app.include_router(admin_ops.admin_router)
else:
    logger.info("[main] 管理端路由已关闭：本进程不注册任何 /api/admin/* 端点")
app.include_router(github_oauth.router)  # GitHub OAuth：未配置时接口自返回 404，前端按钮隐藏

app.include_router(analyze.router)
app.include_router(projects.router)
app.include_router(reports.router)
app.include_router(materials.router)
app.include_router(collect.router)
app.include_router(regions.router)  # F10：行政区划码表（前端地域多选共用）
app.include_router(tasks.router)
app.include_router(search.router)
app.include_router(cases.router)
app.include_router(monitoring.router)
app.include_router(benchmarks.router)
