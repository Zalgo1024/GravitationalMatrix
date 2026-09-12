"""报告生成器 — 生成半的编排层。

职责：
1. 用 prompt_builder 装配系统提示词；
2. 把用户输入（材料/关键词）包装成用户提示词；
3. 调用 LLM 客户端产出 Markdown；
4. 交给域引擎导出 Word(+PDF)，并一并返回 Markdown 原文。

LLM 客户端可替换（DeepSeek / OpenAI / Mock），generator 本身不关心具体模型。
"""
import os
import json
import re
import time
import urllib.parse

from app.prompt_builder import build_system_prompt
from app.engine_bridge import export_report
from app.report_tables import word_data_tables
from app import rule_engine
from app.report_quality import (
    ReportQualityError,
    ReportQualityResult,
    evaluate_report_quality,
)


def _truncate(text: str | None, limit: int = 64000) -> str | None:
    """截断 LLM 原始响应，避免超大文本撑爆数据库。"""
    if not text:
        return None
    return text if len(text) <= limit else text[:limit] + "\n...[原始响应已截断]"


class ReportGenerator:
    def __init__(
        self,
        llm=None,
        analysis_type: str = "case",
        mode: str = "rule",
        structured=None,
        llm_config: dict | None = None,
        web_mode: bool = False,
        materials: dict | None = None,
    ) -> None:
        self.llm = llm
        self.analysis_type = analysis_type
        self.mode = mode
        self.structured = structured
        self.llm_config = llm_config
        # T3：联网写报告模式（素材注入 + 强制 [名称](url) 附录约束）
        self.web_mode = web_mode
        self.materials = materials

    @staticmethod
    def _coerce_bundle(materials):
        """把 queue 传入的 bundle.__dict__（dict）或 MaterialBundle 归一为 MaterialBundle。"""
        from app.materials import MaterialBundle

        if materials is None:
            return MaterialBundle(items=[], sources=[])
        if isinstance(materials, MaterialBundle):
            return materials
        if isinstance(materials, dict):
            return MaterialBundle(
                items=materials.get("items") or [],
                sources=materials.get("sources") or [],
            )
        return MaterialBundle(items=[], sources=[])

    def _build_user_prompt(
        self, input_text: str, title: str | None, materials: dict | None = None
    ) -> str:
        head = f"报告标题：{title}\n\n" if title else ""
        base = (
            f"{head}以下是待分析的材料（可能是事件描述、政策文本或关键词）：\n\n"
            f"{input_text}\n\n"
            f"请基于上述材料，按系统提示中的结构与铁律生成完整分析正文（Markdown）。"
        )
        if not self.web_mode:
            return base + (
                "\n\n当前没有可核验的联网或本地材料。严格限制：只能把用户原文中的内容写成事实；"
                "不得补写用户未提供的日期、金额、比例、评分、票房、人数、引用、公告内容或社交平台数据。"
                "事实摘要中的每条事实必须追加‘（来源：用户输入）’；缺少依据时写‘未知’或‘待验证’，"
                "并把机制分析明确标为推断，不得用看似具体的数字填空。"
            )

        from app.materials import format_materials_context, format_source_appendix

        bundle = self._coerce_bundle(materials if materials is not None else self.materials)
        mctx = format_materials_context(bundle)
        src_appendix = format_source_appendix(bundle.sources)
        extra = []
        if mctx:
            extra.append(mctx)
        extra.append(
            "引用约束：正文事实条目仅写「（来源：名称）」；不要在正文堆叠 URL 或整段复述素材。"
            "报告末尾附录使用「[名称](url)」可点击格式，禁止裸 URL 或无链接媒体名。"
        )
        if src_appendix:
            extra.append("附录来源清单（必须原样包含，可增补）：\n" + src_appendix)
        return base + "\n\n" + "\n\n".join(extra)

    @staticmethod
    def _strip_code_fence(markdown: str) -> str:
        # 去掉 LLM 可能额外包裹的 ```markdown ... ``` 整篇围栏
        m = re.match(r"^\s*```[a-zA-Z]*\s*\n(.*)\n```\s*$", markdown, re.DOTALL)
        return m.group(1) if m else markdown

    @staticmethod
    def _normalize(markdown: str, title: str | None) -> str:
        md = ReportGenerator._strip_code_fence(markdown)
        # 保证以一级标题开头，便于 parser 提取标题
        if not md.lstrip().startswith("# "):
            md = f"# {title or '未命名报告'}\n\n" + md
        return md

    def _build_structured(self, input_text: str, title: str | None):
        if isinstance(self.structured, rule_engine.StructuredInput):
            return self.structured
        if isinstance(self.structured, dict):
            return rule_engine.StructuredInput.model_validate(self.structured)
        # 无结构化输入时，用自由文本兜底（仅事件/标题）
        return rule_engine.StructuredInput(
            title=title or "", analysis_type=self.analysis_type, event=input_text or ""
        )

    def _used_web_sources(self) -> bool:
        return bool(self._coerce_bundle(self.materials).sources)

    @staticmethod
    def _source_url_identity(url: str) -> str:
        """Normalize a public source URL for verified-link matching."""
        try:
            parsed = urllib.parse.urlsplit((url or "").strip())
            host = (parsed.hostname or "").lower()
            if host.startswith("www."):
                host = host[4:]
            path = re.sub(r"/+$", "", parsed.path or "")
            return urllib.parse.urlunsplit((parsed.scheme.lower(), host, path, "", ""))
        except ValueError:
            return (url or "").strip().lower().rstrip("/")

    def _sanitize_unverified_links(self, markdown: str) -> str:
        """Remove Markdown links that were not verified in the evidence bundle.

        A model may write a plausible-looking URL without having fetched it. Such
        a link must never become a clickable evidence source merely because it
        appeared in the generated Markdown.
        """
        bundle = self._coerce_bundle(self.materials)
        verified = {
            self._source_url_identity(str(item.get("url") or ""))
            for item in bundle.items
            if isinstance(item, dict) and item.get("kept", True) and item.get("url")
        }
        verified.update(
            self._source_url_identity(str(getattr(source, "url", "") or (source.get("url") if isinstance(source, dict) else "")))
            for source in bundle.sources
        )

        def replace(match: re.Match) -> str:
            title, url = match.group(1), match.group(2)
            if self._source_url_identity(url) in verified:
                return match.group(0)
            return f"{title}（链接未通过本次抓取验证，已移除）"

        return re.sub(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)", replace, markdown or "")

    def _attach_source_appendix(self, markdown: str) -> str:
        bundle = self._coerce_bundle(self.materials)
        if not bundle.sources:
            return markdown
        from app.materials import format_source_appendix

        appendix = format_source_appendix(bundle.sources).strip()
        if not appendix or appendix in markdown:
            return markdown
        copyright_pos = markdown.find("分析框架：三元结构理论")
        if copyright_pos >= 0:
            return (
                markdown[:copyright_pos].rstrip()
                + "\n\n"
                + appendix
                + "\n\n"
                + markdown[copyright_pos:]
            )
        return markdown.rstrip() + "\n\n" + appendix + "\n"

    def _evaluate_quality(self, markdown: str) -> ReportQualityResult:
        bundle = self._coerce_bundle(self.materials)
        source_names = [
            str(item.get("title") or "")
            for item in bundle.items
            if isinstance(item, dict)
        ] + [
            str(getattr(source, "title", "") or (source.get("title") if isinstance(source, dict) else ""))
            for source in bundle.sources
        ]
        result = evaluate_report_quality(
            markdown,
            analysis_type=self.analysis_type,
            # 规则引擎只负责把结构化输入排版成报告，不会把联网素材
            # 自动改写成逐条带来源的事实摘要；来源仍会进入附录，但
            # “每条事实必须带来源”只对真正由 LLM 撰写的联网报告启用。
            used_web_sources=(self.mode == "llm" and self._used_web_sources()),
            strict_unverified_facts=(
                self.mode == "llm"
                and not self._used_web_sources()
                and len(getattr(self, "_current_input_text", "").strip()) >= 20
            ),
            input_text=getattr(self, "_current_input_text", ""),
            source_names=source_names,
        )
        self._last_quality = result
        return result

    @staticmethod
    def _retryable_llm_error(error: Exception) -> bool:
        """Return whether a failed request is likely to succeed on retry."""
        return getattr(error, "kind", "") in {
            "rate_limit",
            "timeout",
            "connection",
            "api_error",
        }

    def _generate_with_retry(self, llm, system: str, user: str, temperature: float) -> str:
        """Retry transient provider failures without retrying deterministic errors."""
        last_error: Exception | None = None
        for retry in range(3):
            try:
                return llm.generate(system, user, temperature=temperature)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if not self._retryable_llm_error(exc) or retry == 2:
                    raise
                time.sleep(0.25 * (retry + 1))
        raise last_error or RuntimeError("LLM 调用失败")

    @staticmethod
    def _quality_revision_prompt(markdown: str, result: ReportQualityResult) -> str:
        problems = "\n".join(
            f"- {issue.code}: {issue.message}"
            for issue in result.issues
            if issue.severity == "error"
        )
        return (
            "以下报告未通过质量闸门，请只修复列出的问题，不添加未经材料支持的事实。\n\n"
            f"质量问题：\n{problems}\n\n"
            f"待修订完整报告：\n\n{markdown}\n\n"
            "请返回修订后的完整 Markdown，不要解释，不要用代码围栏包裹整篇。"
        )

    def generate(self, input_text: str = "", title: str | None = None) -> str:
        self._current_input_text = input_text or ""
        if self.mode == "rule":
            si = self._build_structured(input_text, title)
            md = rule_engine.generate(si)
            md = self._normalize(md, title)
            md = self._attach_source_appendix(md)
            quality = self._evaluate_quality(md)
            if not quality.valid:
                raise ReportQualityError(quality)
            self._last_contract = {
                "valid": True,
                "diagram_ok": True,
                "diagram_synthetic": False,
                "missing_sections": [],
                "errors": [],
                "repaired": False,
                "mode": "rule",
                "engine_used": "rule",
                "degraded_from_llm": False,
                "degrade_reason": None,
                "quality": quality.model_dump(),
            }
            self._engine_meta = {
                "engine_used": "rule",
                "llm_model": None,
                "llm_temperature": None,
                "prompt_version": None,
                "degraded_from_llm": False,
                "degrade_reason": None,
                "raw_response": None,
            }
            return md

        # —— LLM 增强模式 ——
        from app.contract import validate_and_repair
        from app.llm_client import create_llm_from_config, MockClient
        from app.llm_settings_store import resolve_config
        from app.prompt_builder import PROMPT_VERSION

        cfg = resolve_config(self.llm_config)
        llm = create_llm_from_config(self.llm_config)
        self._generation_llm = llm

        # 无可用密钥 → 没有 LLM 可用，直接降级到规则引擎（核心不依赖 LLM）
        if isinstance(llm, MockClient):
            reason = (
                "未配置 LLM 密钥（请到设置页填写，或用 backend/.env 配置），已使用规则引擎"
            )
            return self._fallback_or_raise(input_text, title, reason)

        system = build_system_prompt(self.analysis_type)
        user = self._build_user_prompt(input_text, title, self.materials)
        try:
            raw = self._generate_with_retry(llm, system, user, cfg["temperature"])
        except Exception as e:  # noqa: BLE001
            # LLMError（限流/鉴权/余额/超时/连接）或任何调用异常 → 降级
            msg = getattr(e, "message", None) or str(e)
            return self._fallback_or_raise(
                input_text, title, f"LLM 调用失败：{msg}"
            )
        candidate_raw = raw
        contract = None
        quality = None
        md = ""
        # 修订阶段使用固定低温，避免“越修越随机”；最多 3 次修订机会。
        repair_temperature = min(max(float(cfg["temperature"]), 0.1), 0.3)
        for attempt in range(4):
            md = self._normalize(candidate_raw, title)
            md, contract = validate_and_repair(
                md, self.analysis_type, self.structured
            )
            md = self._sanitize_unverified_links(md)
            # 质量检查前先自动补齐来源附录（[标题](url)）：LLM 可能漏写链接，
            # 但 sources 是真实抓取的，由系统拼进附录，闸门就不会因格式误毙任务。
            md = self._attach_source_appendix(md)
            if not contract.get("degrade"):
                quality = self._evaluate_quality(md)
                if quality.valid:
                    break
            if attempt >= 3:
                if contract.get("degrade"):
                    reason = "LLM 输出连续三次不符合结构契约，无法形成正式报告"
                    return self._fallback_or_raise(
                        input_text, title, reason, raw=candidate_raw
                    )
                raise ReportQualityError(quality)
            if contract.get("degrade"):
                problems = "\n".join(f"- {error}" for error in contract.get("errors", []))
                revision_user = (
                    "以下报告不符合结构契约，请修复列出的问题并返回完整 Markdown。\n\n"
                    f"契约问题：\n{problems}\n\n待修订报告：\n\n{md}"
                )
            else:
                revision_user = self._quality_revision_prompt(md, quality)
            try:
                candidate_raw = self._generate_with_retry(
                    llm, system, revision_user, repair_temperature
                )
            except Exception as exc:  # noqa: BLE001
                msg = getattr(exc, "message", None) or str(exc)
                return self._fallback_or_raise(
                    input_text, title, f"LLM 定向修订失败：{msg}", raw=candidate_raw
                )

        # LLM 成功且契约可用
        contract["mode"] = "llm"
        contract["engine_used"] = "llm"
        contract["degraded_from_llm"] = False
        contract["degrade_reason"] = None
        contract["prompt_version"] = cfg["prompt_version"]
        contract["quality"] = quality.model_dump()
        self._last_contract = contract
        self._engine_meta = {
            "engine_used": "llm",
            "llm_model": cfg["model"],
            "llm_temperature": cfg["temperature"],
            "prompt_version": cfg["prompt_version"],
            "degraded_from_llm": False,
            "degrade_reason": None,
            "raw_response": _truncate(raw),
        }
        return md

    def revise(
        self,
        previous_markdown: str,
        instruction: str,
        title: str | None = None,
    ) -> str:
        """T13 AI 再改：基于上一版全文 + 修改指令，生成新 Markdown。

        system = build_system_prompt(同 analysis_type)（含哨兵护栏）；
        user = 上一版全文 + 「修改指令」+「仅输出修改后的完整报告 Markdown」。
        复用 generate 的契约校验/修复/降级链（type_mismatch 提高温度重试 1 次）。

        仅 llm 模式可用；未配置 LLM 密钥时抛出 ValueError（由 API 层转明确错误），不静默。
        """
        from app.contract import validate_and_repair
        from app.llm_client import MockClient, create_llm_from_config
        from app.llm_settings_store import resolve_config

        if self.mode != "llm":
            raise ValueError("AI 再改仅在 llm 模式可用（mode='llm'）")

        cfg = resolve_config(self.llm_config)
        llm = create_llm_from_config(self.llm_config)
        self._generation_llm = llm
        if isinstance(llm, MockClient):
            raise ValueError(
                "未配置 LLM 密钥，AI 再改不可用（请到设置页填写，或用 backend/.env 配置）"
            )

        system = build_system_prompt(self.analysis_type)
        user = (
            f"报告标题：{title or '未命名报告'}\n\n"
            f"以下是上一版报告全文：\n\n{previous_markdown}\n\n"
            f"修改指令：{instruction}\n\n"
            f"请基于上述修改指令，重写为完整报告 Markdown。"
            f"仅输出修改后的完整报告 Markdown，不要输出解释性文字，不要用代码围栏包裹整篇。"
        )

        def _run(temp: float) -> tuple[str, dict]:
            raw = llm.generate(system, user, temperature=temp)
            md = self._normalize(raw, title)
            md, contract = validate_and_repair(md, self.analysis_type, None)
            md = self._sanitize_unverified_links(md)
            return md, contract

        try:
            md, contract = _run(cfg["temperature"])
        except Exception as e:  # noqa: BLE001
            msg = getattr(e, "message", None) or str(e)
            raise ValueError(f"AI 再改调用失败：{msg}") from e

        # 缺哨兵/类型不一致 → 提高温度重试 1 次（双轨护栏第三层）
        if contract.get("type_mismatch") or contract.get("degrade"):
            try:
                md2, contract2 = _run(min(cfg["temperature"] + 0.2, 1.0))
                if not contract2.get("type_mismatch") and not contract2.get("degrade"):
                    md, contract = md2, contract2
                else:
                    contract = contract2
            except Exception:  # noqa: BLE001
                pass

        quality = None
        if not contract.get("type_mismatch") and not contract.get("degrade"):
            quality = self._evaluate_quality(md)
        for attempt in range(2):
            if quality is not None and quality.valid:
                break
            if quality is None:
                problems = "\n".join(
                    f"- {error}" for error in contract.get("errors", [])
                )
                revision_user = (
                    "以下修订稿不符合结构契约，请修复问题并返回完整 Markdown。\n\n"
                    f"契约问题：\n{problems}\n\n待修订报告：\n\n{md}"
                )
            else:
                revision_user = self._quality_revision_prompt(md, quality)
            try:
                raw = llm.generate(
                    system,
                    revision_user,
                    temperature=min(cfg["temperature"] + 0.1 * (attempt + 1), 1.0),
                )
            except Exception as exc:  # noqa: BLE001
                msg = getattr(exc, "message", None) or str(exc)
                raise ValueError(f"AI 再改质量修订失败：{msg}") from exc
            md = self._normalize(raw, title)
            md, contract = validate_and_repair(md, self.analysis_type, None)
            quality = (
                None
                if contract.get("type_mismatch") or contract.get("degrade")
                else self._evaluate_quality(md)
            )
        if quality is None or not quality.valid:
            if quality is not None:
                raise ReportQualityError(quality)
            raise ValueError("AI 再改连续三次不符合结构契约")

        contract["quality"] = quality.model_dump()
        self._last_contract = contract
        self._engine_meta = {
            "engine_used": "llm",
            "llm_model": cfg["model"],
            "llm_temperature": cfg["temperature"],
            "prompt_version": cfg["prompt_version"],
            "degraded_from_llm": False,
            "degrade_reason": None,
            "raw_response": None,
        }
        return md

    def enrich(
        self,
        previous_markdown: str,
        instruction: str,
        title: str | None = None,
    ) -> str:
        """Update a report from newly supplied evidence while preserving its structure."""
        from app.materials import format_materials_context, format_source_appendix

        bundle = self._coerce_bundle(self.materials)
        context = format_materials_context(bundle)
        if not context:
            raise ValueError("没有可供核验的新增材料，未创建补充版本")
        appendix = format_source_appendix(bundle.sources)
        evidence_instruction = (
            "这是一次证据补充，不是另写一篇报告。只修改新增材料能够支持或推翻的事实、"
            "判断、关系与资料缺口；保留无关章节和原有结构。区分事实、来源观点、系统推断"
            "和用户信息；找不到依据的关系不得升格为事实。新增或变更的重要判断必须能回溯"
            "到下面的材料。\n\n"
            f"用户本轮要求：{instruction or '核验并补充当前报告的证据缺口'}\n\n"
            f"新增研究材料：\n{context}"
        )
        if appendix:
            evidence_instruction += "\n\n新增来源附录（保留可点击链接）：\n" + appendix
        markdown = self.revise(previous_markdown, evidence_instruction, title)
        return self._attach_source_appendix(markdown)

    def _degrade_to_rule(
        self, input_text: str, title: str | None, reason: str, raw: str | None = None
    ) -> str:
        """LLM 不可用或产出不可信时，回退到规则引擎（核心流程不依赖 LLM）。

        返回规则引擎产出的 Markdown；元信息标注 engine_used=rule / degraded_from_llm=True。
        """
        from app.prompt_builder import PROMPT_VERSION

        si = self._build_structured(input_text, title)
        md = rule_engine.generate(si)
        md = self._normalize(md, title)
        md = self._attach_source_appendix(md)
        quality = self._evaluate_quality(md)
        if not quality.valid:
            raise ReportQualityError(quality)
        self._last_contract = {
            "valid": True,
            "diagram_ok": True,
            "diagram_synthetic": False,
            "missing_sections": [],
            "errors": [reason],
            "repaired": True,
            "mode": "llm",  # 用户请求的是 llm，但实际用了 rule
            "engine_used": "rule",
            "degraded_from_llm": True,
            "degrade_reason": reason,
            "prompt_version": PROMPT_VERSION,
            "quality": quality.model_dump(),
        }
        self._engine_meta = {
            "engine_used": "rule",
            "llm_model": None,
            "llm_temperature": None,
            "prompt_version": PROMPT_VERSION,
            "degraded_from_llm": True,
            "degrade_reason": reason,
            "raw_response": _truncate(raw),
        }
        return md

    def _fallback_or_raise(
        self, input_text: str, title: str | None, reason: str, raw: str | None = None
    ) -> str:
        if self.structured is None:
            raise ValueError(
                "自由输入的 LLM 生成失败，且没有可供规则引擎接管的结构化数据："
                + reason
            )
        return self._degrade_to_rule(input_text, title, reason, raw=raw)

    def extract_network(self, markdown: str) -> dict:
        """从已生成的 Markdown 中抽取「利益关系网络（DIAGRAM）」区块。

        纯文本解析，不调用域引擎（遵守项目铁律：不改动 engine 内部逻辑）。
        对应进度链第 4 步「利益关系网络拆解」里程碑。

        返回 {"diagram": <str|None>, "valid": <bool>}。
        """
        m = re.search(r"```DIAGRAM\s*\n(.*?)\n```", markdown, re.IGNORECASE | re.DOTALL)
        diagram = m.group(1).strip() if m else None
        return {"diagram": diagram, "valid": bool(diagram)}

    def _research_source_catalog(self, markdown: str) -> list[dict]:
        """Number only sources already present in materials or the final report."""
        bundle = self._coerce_bundle(self.materials)
        item_by_url = {}
        entries: list[dict] = []
        for item in bundle.items:
            if not isinstance(item, dict) or not item.get("kept", True):
                continue
            url = str(item.get("url") or "")
            material_id = str(item.get("material_id") or "") or None
            identity = url or (f"material:{material_id}" if material_id else "")
            if not identity:
                continue
            item_by_url[identity] = item
            entries.append(
                {
                    "title": str(item.get("title") or url or "本地材料"),
                    "url": url,
                    "material_id": material_id,
                    "identity": identity,
                }
            )
        for source in bundle.sources:
            title = getattr(source, "title", None) or (
                source.get("title") if isinstance(source, dict) else ""
            )
            url = getattr(source, "url", None) or (
                source.get("url") if isinstance(source, dict) else ""
            )
            if url:
                entries.append(
                    {"title": title or url, "url": url, "material_id": None, "identity": url}
                )
        # 不再从最终 Markdown 反向收录 URL。模型可能会自行补出看似合理
        # 的链接，但它们没有经过本次抓取，也没有可核验正文；来源目录只能
        # 来自 materials（已成功抓取的网页或用户明确提供的材料）。

        catalog: list[dict] = []
        seen: set[str] = set()
        for entry in entries:
            identity = entry["identity"]
            if not identity or identity in seen:
                continue
            seen.add(identity)
            item = item_by_url.get(identity) or item_by_url.get(entry["url"]) or {}
            catalog.append(
                {
                    "id": f"s{len(catalog) + 1}",
                    "title": entry["title"],
                    "url": entry["url"],
                    "excerpt": str(item.get("text") or item.get("snippet") or "")[:700],
                    "source_type": "user_material" if entry["material_id"] else "unknown",
                    "source_level": "user" if entry["material_id"] else "unknown",
                    "material_id": entry["material_id"],
                }
            )
        return catalog

    def build_research_ledger(self, markdown: str, input_text: str = ""):
        """Create the validated evidence-to-judgment snapshot for a report."""
        from app.research_ledger import (
            build_fallback_ledger,
            normalize_research_ledger,
            parse_research_payload,
        )

        fallback_input = input_text
        if not fallback_input and self.structured is not None:
            fallback_input = getattr(self.structured, "event", "") or ""
        if isinstance(self.structured, dict) and not fallback_input:
            fallback_input = str(self.structured.get("event") or "")
        fallback_bundle = self._coerce_bundle(self.materials)
        fallback_materials = {
            "items": fallback_bundle.items,
            "sources": fallback_bundle.sources,
        }

        llm = getattr(self, "_generation_llm", None)
        engine_used = (getattr(self, "_engine_meta", None) or {}).get("engine_used")
        if self.mode != "llm" or engine_used != "llm" or llm is None:
            return build_fallback_ledger(
                markdown=markdown,
                materials=fallback_materials,
                input_text=fallback_input,
                reason="当前生成路径未执行结构化证据提取",
            )

        catalog = self._research_source_catalog(markdown)
        if not catalog:
            return build_fallback_ledger(
                markdown=markdown,
                materials=fallback_materials,
                input_text=fallback_input,
                reason="当前没有可核验来源，已跳过结构化证据提取",
                status="no_evidence",
            )
        system = (
            "你是研究证据整理器。只返回 JSON 对象，不要 Markdown 或解释。"
            "只能引用给定来源索引中的 source id，不得新增来源。"
            "区分 fact、source_view、inference、user_input；没有直接证据的判断必须标为 inference。"
            "置信度只能是 high、medium、low、unknown，不得编造百分比。"
            "输出字段：sources, claims, nodes, relations, timeline, gaps, analogues, "
            "counterfactuals, quantitative_observations, narratives, policy_clauses。"
            "claim 包含 id,text,claim_type,significance,confidence,confidence_reasons,evidence_ids,"
            "counter_evidence_ids,section。"
            "node 包含 id,label,aliases,role,interests,stance,weight,confidence,evidence_ids,"
            "first_seen,last_seen,stance_history；weight 只能是 0 到 1，未知时用 0.5。"
            "relation 包含 id,source_node,target_node,label,relation_type,strength,interest_types,"
            "direction,polarity,confidence,evidence_ids,claim_id,status,valid_from,valid_to；"
            "strength 只能是 1 到 5，未知时用 1。"
            "timeline 包含 id,date,title,detail,event_type,actor_ids,claim_ids,evidence_ids,"
            "confidence,turning_point；没有可靠日期时 date 为 null。"
            "gap 包含 id,question,reason,impact,recommended_materials,priority,material_type；"
            "priority 只能是 critical、high、medium、low。"
            "analogue 包含 id,title,summary,period,jurisdiction,domain,similarities,differences,"
            "response,outcome,relevance_reason,evidence_ids,comparability,confidence,confidence_reasons；"
            "只收录来源索引确实支持的历史案例，没有可靠对照时返回空数组。"
            "counterfactual 包含 id,premise,changed_condition,baseline_outcome,alternative_outcome,"
            "causal_chain,supporting_claim_ids,evidence_ids,assumptions,invalidation_signals,"
            "confidence,confidence_reasons,status；status 只能是 evidence_based、modelled、insufficient。"
            "反事实必须写清假设和失效信号，不得生成百分比概率。"
            "quantitative_observation 包含 id,metric_name,value,unit,observed_at,period_start,"
            "period_end,scope,methodology,formula,evidence_ids,status,caveats,confidence；"
            "status 只能是 observed、derived、unknown、conflicted。外部观测值必须绑定来源，"
            "派生值必须同时绑定来源并给出可复算公式；无法获得时 value 为 null、status 为 unknown。"
            "narrative 包含 id,name,summary,stance,share,share_basis,actor_ids,source_ids,evidence_ids,"
            "confidence；stance 只能是 supportive、opposing、neutral、mixed、unknown；"
            "share 只能是 0 到 1 且必须同时给出 share_basis 计算口径，没有可核验依据时 share 为 null、"
            "只做定性描述；仅舆情报告且来源足以支撑时产出，否则返回空数组。"
            "policy_clause 包含 id,clause_no,title,content_digest,target_groups,interest_change,"
            "region_level,effective_at,claim_ids,evidence_ids,confidence；"
            "interest_change 只能是 benefit、loss、neutral、mixed、unknown；"
            "region_level 只能是 national、province、city、district、unknown；"
            "仅政策报告且来源含条款原文时逐条产出，否则返回空数组。"
            "主体、关系、时间事件没有证据时必须降低置信度，不得根据常识补造。"
        )
        user = (
            "来源索引（ID 与 URL 不可修改）：\n"
            + json.dumps(catalog, ensure_ascii=False)
            + "\n\n用户原始输入：\n"
            + (fallback_input or "（无）")[:6000]
            + "\n\n最终报告：\n"
            + (markdown or "")[:48000]
        )
        last_error = ""
        for attempt in range(2):
            try:
                raw = llm.generate(system, user, temperature=0.1)
                payload = parse_research_payload(raw)
                proposed_sources = {
                    str(source.get("id") or ""): source
                    for source in payload.get("sources") or []
                    if isinstance(source, dict)
                }
                # Source identity is owned by the application, not by the model.
                reconciled_sources = []
                for source in catalog:
                    proposed = proposed_sources.get(source["id"], {})
                    if proposed.get("url") not in (None, "", source["url"]):
                        proposed = {}
                    reconciled_sources.append({**source, **proposed, "id": source["id"], "url": source["url"], "title": source["title"]})
                payload["sources"] = reconciled_sources
                return normalize_research_ledger(payload)
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                user = (
                    "上一次输出不是符合要求的 JSON 对象。请只返回完整 JSON；"
                    "不要增加来源，不要解释。\n\n原始任务：\n" + user
                )
        return build_fallback_ledger(
            markdown=markdown,
            materials=fallback_materials,
            input_text=fallback_input,
            reason=f"结构化证据提取失败：{last_error or '未知错误'}",
            status="extraction_failed",
        )

    def validate(self, markdown: str | None = None, title: str | None = None) -> dict:
        """契约校验里程碑（进度链第 5 步「整理分析结果」）。

        ``generate()`` 已在两种模式下产出自检契约并存入 ``_last_contract``：
        - LLM 模式：内部已调用 ``validate_and_repair``，契约含真实校验结果；
        - rule 模式：已置为默认通过（结构由规则引擎保证）。

        此处返回该契约作为「整理 / 校验」阶段的可见节点，不二次解析以免与引擎重复。
        markdown / title 入参保留为未来内联校验预留（当前直接复用已算契约）。
        """
        return getattr(self, "_last_contract", None) or {
            "valid": False,
            "diagram_ok": False,
            "diagram_synthetic": False,
            "missing_sections": [],
            "errors": ["尚无契约校验结果（generate 未执行）"],
            "repaired": False,
            "mode": self.mode,
            "engine_used": None,
            "degraded_from_llm": False,
            "degrade_reason": None,
        }

    def quality(self) -> ReportQualityResult:
        return getattr(self, "_last_quality", None) or ReportQualityResult(
            valid=False,
            score=0,
            issues=[],
        )

    def export(
        self,
        markdown: str,
        title: str | None = None,
        output_dir: str | None = None,
        slug: str | None = None,
        data_tables: list[dict] | None = None,
    ) -> dict:
        """导出 Word/PDF（调用域引擎），并归一 PDF 可用状态。

        对应进度链第 6 步「输出分析结果」里程碑。
        data_tables：可选 Word 附表 [{name, columns, rows}]（F15 关键数据表），None 时输出不变。
        返回域引擎导出结果（含 ``pdf_available`` / ``pdf_reason`` 修正），不含原始 Markdown。
        """
        exp = export_report(
            title or "未命名报告",
            markdown,
            output_dir=output_dir,
            slug=slug,
            data_tables=data_tables,
        )
        # 归一 PDF：域引擎在转换失败时也会返回「幽灵路径」（文件并不存在）。
        # 此处以真实文件存在性为准：存在才保留 pdf 路径并标 pdf_available=true；
        # 否则去掉 pdf 字段、标 pdf_available=false，由前端明确提示「PDF 待配置」。
        # 这样若日后装好 LibreOffice 等转换器，PDF 会自动恢复可用，无需改前端。
        pdf_path = exp.get("pdf")
        exp["pdf_available"] = bool(pdf_path and os.path.exists(pdf_path))
        if not exp["pdf_available"]:
            exp.pop("pdf", None)
            # 明确原因，避免「静默失败」：告知前端/用户当前环境缺哪个转换器
            try:
                from app.engine_bridge import diagnose_pdf

                diag = diagnose_pdf()
                avail = [
                    n
                    for n, ok in (
                        ("LibreOffice", diag.get("libreoffice")),
                        ("pandoc", diag.get("pandoc")),
                        ("Word COM", diag.get("word_com")),
                    )
                    if ok
                ]
                exp["pdf_reason"] = (
                    "本机未安装任何可用 PDF 转换器（建议安装 LibreOffice 并加入 PATH）。"
                    if not avail
                    else f"已检测到 {', '.join(avail)}，但本次转换未成功（见后端日志）。"
                )
            except Exception:  # noqa: BLE001
                exp["pdf_reason"] = "PDF 不可用（原因诊断失败）。"
        return exp

    def generate_and_export(
        self,
        input_text: str = "",
        title: str | None = None,
        output_dir: str | None = None,
        slug: str | None = None,
        on_phase=None,
    ) -> dict:
        """生成报告并导出 Word/PDF。

        编排 ``generate → extract_network → validate → export`` 四个独立阶段，
        在边界以 ``on_phase(phase, pct)`` 回调推送阶段消息（回调异常被忽略，不影响流程）。

        阶段里程碑：
            - ("decompose", 25) — 开始拆解分析（generate 前）
            - ("network", 55)   — 利益关系网络构建（generate 后，extract_network）
            - ("organize", 75)  — 整理分析结果（validate 契约校验）
            - ("output", 85)    — 输出报告（export 导出开始）
        """
        def _safe_phase(phase: str, pct: int):
            if on_phase:
                try:
                    on_phase(phase, pct)
                except Exception:  # noqa: BLE001
                    pass

        _safe_phase("decompose", 25)
        started = time.monotonic()
        stage_started = started
        md = self.generate(input_text, title)
        generate_seconds = time.monotonic() - stage_started
        _safe_phase("network", 55)
        stage_started = time.monotonic()
        network = self.extract_network(md)
        network_seconds = time.monotonic() - stage_started
        stage_started = time.monotonic()
        research = self.build_research_ledger(md, input_text)
        research_seconds = time.monotonic() - stage_started
        _safe_phase("organize", 75)
        stage_started = time.monotonic()
        contract = self.validate(md, title)
        quality = self.quality()
        if not md.strip() or len(md.strip()) < 120 or not contract.get("valid") or not quality.valid:
            raise ValueError(
                "报告未形成可交付正文：生成结果为空或未通过结构/质量校验，未导出空报告。"
            )
        organize_seconds = time.monotonic() - stage_started
        _safe_phase("output", 85)
        stage_started = time.monotonic()
        exp = None
        for attempt in range(2):
            try:
                # F15：把研究账本派生的关键数据表（来源/主体/时间线或条款）作为 Word 附表
                data_tables = word_data_tables(research.model_dump(), self.analysis_type)
                exp = self.export(md, title, output_dir, slug, data_tables=data_tables)
                break
            except Exception:  # noqa: BLE001
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                raise
        export_seconds = time.monotonic() - stage_started
        # 合并：Markdown 原文 + 网络图抽取 + 契约校验 + 引擎导出结果 + 引擎元信息
        meta = getattr(self, "_engine_meta", None) or {}
        return {
            "markdown": md,
            "network": network,
            "research": research.model_dump(),
            "contract": contract,
            "quality": quality.model_dump(),
            # —— 阶段四：标注本次报告由哪个引擎生成，是否从 LLM 降级 ——
            "engine_used": meta.get("engine_used"),
            "degraded_from_llm": meta.get("degraded_from_llm", False),
            "degrade_reason": meta.get("degrade_reason"),
            "prompt_version": meta.get("prompt_version"),
            "llm_model": meta.get("llm_model"),
            "llm_temperature": meta.get("llm_temperature"),
            "timings": {
                "generate_seconds": round(generate_seconds, 3),
                "network_seconds": round(network_seconds, 3),
                "research_seconds": round(research_seconds, 3),
                "organize_seconds": round(organize_seconds, 3),
                "export_seconds": round(export_seconds, 3),
                "pipeline_seconds": round(time.monotonic() - started, 3),
            },
            # raw_response 仅落库（Task.llm_raw_response），不进前端响应
            "raw_response": meta.get("raw_response"),
            **exp,
        }
