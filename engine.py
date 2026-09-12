"""
引擎 — CaseAnalysisEngine 核心编排器。

编排流程：
加载配置 → 解析正文 → 生成 Word → 转换 PDF → 返回文件路径

用法:
    from engine import CaseAnalysisEngine
    engine = CaseAnalysisEngine()
    result = engine.export_from_text("案例名称", "## 案例事实摘要\\n...")
    print(result["word"])  # 输出 .docx 路径
"""

import datetime
import os
import re
import shutil
from typing import Optional

from config import load_config, Config
from parser import parse_report, ParsedReport
from auto_number import auto_number_headings


_ENGINE_VERSION = "1.0.0"
_REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")
# 引擎自动时间戳目录的后缀：_YYYYMMDD_HHMMSS
_TS_SUFFIX_RE = re.compile(r"_\d{8}_\d{6}$")
# slug 只允许安全字符，防路径穿越（.. / 分隔符等）
_SLUG_SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_XML_ILLEGAL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def sanitize_xml_text(value: str | None) -> str:
    """移除 Word XML 1.0 不接受的控制字符，保留可读正文。"""
    return _XML_ILLEGAL_CHARS_RE.sub("", value or "")


def _sanitize_xml_value(value):
    if isinstance(value, str):
        return sanitize_xml_text(value)
    if isinstance(value, list):
        return [_sanitize_xml_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_xml_value(item) for item in value)
    if isinstance(value, dict):
        return {
            sanitize_xml_text(str(key)): _sanitize_xml_value(item)
            for key, item in value.items()
        }
    return value


def _sanitize_parsed_report(report: ParsedReport) -> ParsedReport:
    """在渲染前净化所有会进入 Word XML 的文本字段。"""
    report.title = sanitize_xml_text(report.title)
    for section in report.section_seq:
        section.title = sanitize_xml_text(section.title)
        for block in section.blocks:
            block.text = sanitize_xml_text(block.text)
            block.rows = _sanitize_xml_value(block.rows)
            block.items = _sanitize_xml_value(block.items)
            block.segments = _sanitize_xml_value(block.segments)
            block.diagram_data = _sanitize_xml_value(block.diagram_data)
    return report


class CaseAnalysisEngine:
    """三元结构案例分析引擎。

    负责编排从原始文本到最终文件的完整流程。
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config or load_config()
        self._renderer = None   # 延迟导入 docx_renderer
        self._converter = None  # 延迟导入 pdf_converter
        self._diagrams: list[dict] = []  # 本次导出的图表信息

    def _pick_output_folder(
        self,
        safe_name: str,
        output_dir: Optional[str],
        slug: Optional[str],
        overwrite: bool,
        timestamp: str,
    ) -> str:
        """统一定位输出目录（export_from_text / export_from_parsed 共用）。

        - output_dir + slug：slug 消毒后拼子目录，防路径穿越。
        - overwrite：复用固定目录 reports/safe_name，并只清理本报告的历史
          时间戳目录（精确匹配 `_YYYYMMDD_HHMMSS` 后缀），避免前缀误删
          标题相近的其他报告（如「数据」vs「数据_备份」）。
        - 否则：output_dir 或 reports/safe_name_时间戳。
        """
        if output_dir and slug:
            slug_safe = _SLUG_SAFE_RE.sub("_", slug).strip("._")
            # 压掉可能残留的连续点（如 "x..y"），避免任何歧义
            while ".." in slug_safe:
                slug_safe = slug_safe.replace("..", "_")
            return os.path.join(output_dir, f"{safe_name}_{slug_safe}")
        if overwrite:
            try:
                old_entries = os.listdir(_REPORTS_DIR)
            except OSError:
                old_entries = []
            for name in old_entries:
                if not name.startswith(safe_name + "_"):
                    continue
                if not _TS_SUFFIX_RE.search(name):
                    continue  # 非引擎时间戳目录，不动
                full = os.path.join(_REPORTS_DIR, name)
                if not os.path.isdir(full):
                    continue
                try:
                    shutil.rmtree(full)
                except OSError:
                    # 沙箱 safe-delete 拦截删除时忽略，继续写到固定目录
                    pass
            return os.path.join(_REPORTS_DIR, safe_name)
        return output_dir or os.path.join(_REPORTS_DIR, f"{safe_name}_{timestamp}")

    # ── 核心接口 ──────────────────────────────────────────────

    def export_from_text(
        self,
        title: str,
        body: str,
        *,
        output_dir: Optional[str] = None,
        slug: Optional[str] = None,
        overwrite: bool = False,
        tone: str = "neutral",
        data_tables: Optional[list] = None,
    ) -> dict[str, str]:
        """从分析正文导出 Word + PDF 报告。

        Args:
            title: 报告标题（用于文件名和封面）。
            body: Markdown 格式的分析正文（含 ## 章节结构）。
            output_dir: 输出目录。默认自动创建 reports/标题_时间戳/。
            overwrite: 为 True 时复用固定目录名（reports/标题）并清理同名历史
                时间戳目录，始终只保留 1 份，避免反复运行堆积多份。
            tone: 分析基调。「neutral」=客观中立（默认）；「provocative」=煽动性。
                仅作为元数据与封面标注，不改变报告结构；具体行文由撰写者落实。
            data_tables: 可选 Word 附表 [{name, columns, rows}]（F15 关键数据表）。
                None/空列表时不渲染，输出与既有逐字一致。

        Returns:
            {
                "word": "path/to/report.docx",
                "pdf": "path/to/report.pdf",
                "pdf_ok": True/False,
                "folder": "path/to/output_dir",
                "title": "报告标题",
                "tone": "neutral/provocative"
            }
        """
        # 1. 解析正文。外部网页/附件可能混入不可见控制字符，必须在进入 Word 前剔除。
        title = sanitize_xml_text(title)
        body = auto_number_headings(sanitize_xml_text(body))
        report = parse_report(body)
        if not report.title and title:
            report.title = title
        report = _sanitize_parsed_report(report)
        # 分析基调（二选一）：neutral=客观中立 / provocative=煽动性，非法值回退 neutral
        if tone not in ("neutral", "provocative"):
            tone = "neutral"
        report.tone = tone

        # 2. 创建输出目录
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = self._safe_filename(title)
        folder = self._pick_output_folder(safe_name, output_dir, slug, overwrite, timestamp)
        os.makedirs(folder, exist_ok=True)

        # 3. 生成 Word
        word_path = self._render_docx(report, folder, tone=tone, data_tables=data_tables)

        # 4. 转换 PDF
        pdf_path = self._convert_to_pdf(word_path, folder)

        return {
            "word": word_path,
            "pdf": pdf_path,
            "pdf_ok": bool(pdf_path),
            "folder": folder,
            "title": title,
            "tone": tone,
            "diagrams": self._diagrams,
        }

    def export_from_parsed(
        self,
        report: ParsedReport,
        *,
        output_dir: Optional[str] = None,
        slug: Optional[str] = None,
        overwrite: bool = False,
        tone: str = "neutral",
    ) -> dict[str, str]:
        """从已解析的报告数据导出，跳过解析步骤。"""
        report = _sanitize_parsed_report(report)
        title = report.title or "未命名报告"
        if tone not in ("neutral", "provocative"):
            tone = "neutral"
        report.tone = tone
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = self._safe_filename(title)
        folder = self._pick_output_folder(safe_name, output_dir, slug, overwrite, timestamp)
        os.makedirs(folder, exist_ok=True)

        self._diagrams = []
        word_path = self._render_docx(report, folder, tone=tone)
        pdf_path = self._convert_to_pdf(word_path, folder)

        return {
            "word": word_path,
            "pdf": pdf_path,
            "pdf_ok": bool(pdf_path),
            "folder": folder,
            "title": title,
            "tone": tone,
            "diagrams": self._diagrams,
        }

    # ── 内部方法 ──────────────────────────────────────────────

    def _render_docx(self, report: ParsedReport, folder: str, tone: str = "neutral",
                     data_tables: Optional[list] = None) -> str:
        """渲染 Word 文档，保存网络图到输出目录。"""
        from docx_renderer import render_docx

        output_path = os.path.join(folder, f"{self._safe_filename(report.title)}.docx")
        # 重置图表列表
        self._diagrams = []
        render_docx(
            report, output_path, self.config,
            output_folder=folder,
            diagram_collector=self._diagrams,
            tone=tone,
            data_tables=data_tables,
        )
        return output_path

    def _convert_to_pdf(self, docx_path: str, folder: str) -> str:
        """将 .docx 转换为 .pdf。成功返回 pdf 路径，失败返回空字符串。"""
        try:
            from pdf_converter import convert_to_pdf

            pdf_path = os.path.join(
                folder,
                os.path.splitext(os.path.basename(docx_path))[0] + ".pdf",
            )
            result = convert_to_pdf(docx_path, pdf_path)
            return result or ""
        except (ImportError, Exception) as e:
            # PDF 转换失败时返回空字符串，不阻塞主流程，但显式告警
            import warnings
            warnings.warn(f"⚠️ PDF 转换失败（不影响 Word 输出，但本报告无 PDF 文件）: {e}")
            return ""

    @staticmethod
    def _safe_filename(name: str) -> str:
        """将任意字符串转为安全的文件名。"""
        safe = ""
        for ch in name:
            if ch.isalnum() or ch in "-_.":
                safe += ch
            elif ch in " ()（）":
                safe += "_"
            else:
                safe += "_"
        # 去除连续下划线
        import re
        safe = re.sub(r"_+", "_", safe).strip("_")
        return safe if safe else "report"

    @property
    def version(self) -> str:
        return _ENGINE_VERSION


# ── 快捷函数 ──────────────────────────────────────────────────

def export_report(
    title: str,
    body: str,
    *,
    output_dir: Optional[str] = None,
    slug: Optional[str] = None,
) -> dict[str, str]:
    """一键导出：创建引擎 → 导出报告。"""
    engine = CaseAnalysisEngine()
    return engine.export_from_text(title, body, output_dir=output_dir, slug=slug)


def diagnose_pdf() -> dict:
    """诊断当前环境可用的 PDF 转换器（避免静默失败）。"""
    from pdf_converter import diagnose_pdf as _diag

    return _diag()
