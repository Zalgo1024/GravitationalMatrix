"""域引擎桥接 — 把「活动版」域引擎目录加入 sys.path 并暴露 export_report。

架构原则：SaaS 层只做编排，不重写理论引擎。这里就是那个「import 现有 engine」的接入点。
引擎路径通过 ENGINE_DIR 环境变量注入（默认已指向实测确认的活动版目录）。
"""
import os
import sys

from app.settings import settings


def _ensure_engine_on_path() -> None:
    d = settings.engine_dir
    if d and os.path.isdir(d) and d not in sys.path:
        # 插到最前，确保 engine / config / parser 优先从域引擎目录解析
        sys.path.insert(0, d)


def get_engine():
    """导入并返回域引擎模块；失败时抛出清晰错误。"""
    _ensure_engine_on_path()
    try:
        import engine  # noqa: F401
        return engine
    except Exception as e:  # pragma: no cover - 依赖环境
        raise RuntimeError(
            f"无法导入域引擎(engine)。请检查 ENGINE_DIR={settings.engine_dir}。"
            f"原始错误：{e}"
        )


def export_report(
    title: str,
    markdown: str,
    output_dir: str | None = None,
    slug: str | None = None,
    data_tables: list | None = None,
) -> dict:
    """把生成好的 Markdown 交给域引擎渲染为 Word(+PDF)。

    slug（如 task_id）提供时，引擎在 output_dir 下建独立子目录，避免并发同名任务互相覆盖。
    data_tables：可选 Word 附表 [{name, columns, rows}]（F15 关键数据表），None 时输出不变。
    返回：{"word", "pdf", "folder", "title", "diagrams"}
    """
    engine = get_engine()
    eng = engine.CaseAnalysisEngine()
    return eng.export_from_text(
        title, markdown, output_dir=output_dir, slug=slug, data_tables=data_tables
    )


def diagnose_pdf() -> dict:
    """诊断当前环境可用的 PDF 转换器（避免静默失败）。"""
    engine = get_engine()
    return engine.diagnose_pdf()
