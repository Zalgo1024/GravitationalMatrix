"""Versionable evidence-to-judgment contract for generated research reports.

The LLM may propose ledger entries, but this module owns the trust boundary:
references are resolved deterministically and unsupported facts/relations are
downgraded before they reach storage or the UI.
"""

from __future__ import annotations

import json
import hashlib
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field


Confidence = Literal["high", "medium", "low", "unknown"]


class ResearchSource(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str = "未命名来源"
    url: str = ""
    excerpt: str = ""
    source_type: Literal[
        "official",
        "company",
        "mainstream_media",
        "self_media",
        "forum",
        "social_media",
        "user_material",
        "unknown",
    ] = "unknown"
    source_level: Literal["primary", "secondary", "tertiary", "user", "unknown"] = "unknown"
    published_at: str | None = None
    retrieved_at: str | None = None
    independence_group: str = ""
    material_id: str | None = None
    quality_tier: Literal["A", "B", "C", "D", "unknown"] = "unknown"
    quality_reasons: list[str] = Field(default_factory=list)
    canonical_url: str = ""
    original_url: str = ""
    content_fingerprint: str = ""
    duplicate_of: str | None = None


class ResearchClaim(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    text: str
    claim_type: Literal["fact", "source_view", "inference", "user_input"] = "inference"
    significance: Literal["key", "supporting"] = "key"
    confidence: Confidence = "unknown"
    confidence_reasons: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    counter_evidence_ids: list[str] = Field(default_factory=list)
    section: str = ""
    unsupported: bool = False


class ResearchRelation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    source_node: str
    target_node: str
    label: str = "关联"
    relation_type: str = "unknown"
    direction: Literal["directed", "undirected", "mutual", "unknown"] = "unknown"
    polarity: Literal["positive", "negative", "mixed", "neutral", "unknown"] = "unknown"
    confidence: Confidence = "unknown"
    evidence_ids: list[str] = Field(default_factory=list)
    claim_id: str | None = None
    status: Literal["confirmed", "inferred", "conflicted"] = "inferred"
    strength: int = Field(default=1, ge=1, le=5)
    interest_types: list[str] = Field(default_factory=list)
    valid_from: str | None = None
    valid_to: str | None = None
    evidence_count: int = 0


class ResearchStancePoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    at: str
    stance: str
    evidence_ids: list[str] = Field(default_factory=list)


class ResearchNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    label: str
    aliases: list[str] = Field(default_factory=list)
    role: str = ""
    interests: list[str] = Field(default_factory=list)
    stance: str = ""
    weight: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: Confidence = "unknown"
    evidence_ids: list[str] = Field(default_factory=list)
    first_seen: str | None = None
    last_seen: str | None = None
    stance_history: list[ResearchStancePoint] = Field(default_factory=list)


class ResearchTimelineEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    date: str | None = None
    title: str
    detail: str = ""
    event_type: str = "event"
    actor_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: Confidence = "unknown"
    turning_point: bool = False


class ResearchNarrative(BaseModel):
    """叙事份额条目（F15，账本 1.3 新增；舆情报告可选产出）。

    share 是 0~1 的份额值：必须有可核验口径（share_basis）与来源/证据支撑，
    否则 normalize 阶段降级为 None（定性叙事），绝不编造百分比。
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    summary: str = ""
    stance: Literal["supportive", "opposing", "neutral", "mixed", "unknown"] = "unknown"
    share: float | None = None
    share_basis: str = ""
    actor_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: Confidence = "unknown"
    confidence_reasons: list[str] = Field(default_factory=list)


class ResearchPolicyClause(BaseModel):
    """政策条款拆解条目（F15，账本 1.3 新增；政策报告可选产出）。

    逐条款记录条款号/影响对象/利益变化/地域层级/生效时间，全部绑定证据；
    来源不含条款原文时不应产出该条目。
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    clause_no: str = ""
    title: str
    content_digest: str = ""
    target_groups: list[str] = Field(default_factory=list)
    interest_change: Literal["benefit", "loss", "neutral", "mixed", "unknown"] = "unknown"
    region_level: Literal["national", "province", "city", "district", "unknown"] = "unknown"
    effective_at: str | None = None
    claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: Confidence = "unknown"


class ResearchGap(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    question: str
    reason: str = ""
    impact: list[str] = Field(default_factory=list)
    recommended_materials: list[str] = Field(default_factory=list)
    priority: Literal["critical", "high", "medium", "low"] = "medium"
    material_type: str = "unknown"


class ResearchAnalogue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    summary: str = ""
    period: str | None = None
    jurisdiction: str = ""
    domain: str = ""
    similarities: list[str] = Field(default_factory=list)
    differences: list[str] = Field(default_factory=list)
    response: str = ""
    outcome: str = ""
    relevance_reason: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    comparability: Literal["high", "medium", "low", "unknown"] = "unknown"
    confidence: Confidence = "unknown"
    confidence_reasons: list[str] = Field(default_factory=list)


class ResearchCounterfactual(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    premise: str
    changed_condition: str
    baseline_outcome: str = ""
    alternative_outcome: str = ""
    causal_chain: list[str] = Field(default_factory=list)
    supporting_claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    invalidation_signals: list[str] = Field(default_factory=list)
    confidence: Confidence = "unknown"
    confidence_reasons: list[str] = Field(default_factory=list)
    status: Literal["evidence_based", "modelled", "insufficient"] = "modelled"


class QuantitativeObservation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    metric_name: str
    value: int | float | str | None = None
    unit: str = ""
    observed_at: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    scope: str = ""
    methodology: str = ""
    formula: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    status: Literal["observed", "derived", "unknown", "conflicted"] = "unknown"
    caveats: list[str] = Field(default_factory=list)
    confidence: Confidence = "unknown"


class ResearchMetrics(BaseModel):
    source_count: int = 0
    independent_source_group_count: int = 0
    key_claim_count: int = 0
    key_claim_evidence_coverage: float = 0.0
    direct_fact_citation_rate: float = 0.0
    unsupported_inference_count: int = 0
    conflict_count: int = 0
    gap_count: int = 0
    duplicate_source_count: int = 0
    high_quality_source_count: int = 0
    relation_evidence_coverage: float = 0.0
    temporal_completeness: float = 0.0
    source_independence_rate: float = 0.0
    analogue_count: int = 0
    evidence_backed_analogue_count: int = 0
    counterfactual_count: int = 0
    evidence_backed_counterfactual_count: int = 0
    quantitative_observation_count: int = 0
    sourced_quantitative_rate: float = 0.0
    unknown_quantitative_count: int = 0
    narrative_count: int = 0
    policy_clause_count: int = 0


class ResearchLedger(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: str = "1.3"
    # ``fallback`` means the generation path degraded. ``no_evidence`` means
    # the report was generated normally but no verifiable source was supplied.
    # ``extraction_failed`` means sources existed but ledger extraction failed.
    status: Literal["verified", "fallback", "no_evidence", "extraction_failed"] = "verified"
    sources: list[ResearchSource] = Field(default_factory=list)
    claims: list[ResearchClaim] = Field(default_factory=list)
    nodes: list[ResearchNode] = Field(default_factory=list)
    relations: list[ResearchRelation] = Field(default_factory=list)
    timeline: list[ResearchTimelineEvent] = Field(default_factory=list)
    gaps: list[ResearchGap] = Field(default_factory=list)
    analogues: list[ResearchAnalogue] = Field(default_factory=list)
    counterfactuals: list[ResearchCounterfactual] = Field(default_factory=list)
    quantitative_observations: list[QuantitativeObservation] = Field(default_factory=list)
    narratives: list[ResearchNarrative] = Field(default_factory=list)
    policy_clauses: list[ResearchPolicyClause] = Field(default_factory=list)
    metrics: ResearchMetrics = Field(default_factory=ResearchMetrics)
    warnings: list[str] = Field(default_factory=list)


def parse_research_payload(value: str) -> dict:
    """Parse an LLM JSON response without accepting prose or array roots."""
    text = (value or "").strip()
    match = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL | re.IGNORECASE)
    if match:
        text = match.group(1).strip()
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("研究账本必须是 JSON 对象")
    return payload


def _unique_strings(values, valid: set[str] | None = None) -> list[str]:
    if isinstance(values, str):
        values = [values]
    result: list[str] = []
    for value in values or []:
        item = str(value).strip()
        if not item or item in result or (valid is not None and item not in valid):
            continue
        result.append(item)
    return result


def _safe_choice(value, allowed: set[str], fallback: str) -> str:
    return value if value in allowed else fallback


def _default_independence_group(url: str, source_id: str) -> str:
    if not url:
        return source_id
    split = urlsplit(url)
    host = split.netloc.lower().removeprefix("www.")
    return host or source_id


def _source_fingerprint(title: str, excerpt: str) -> str:
    value = excerpt or title
    normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value.lower())
    if not normalized:
        return ""
    return hashlib.sha1(normalized[:1200].encode("utf-8")).hexdigest()[:20]


def _classify_source(source_type: str, title: str, url: str) -> tuple[str, str, list[str]]:
    host = urlsplit(url).netloc.lower().removeprefix("www.")
    lowered = f"{title} {host}".lower()
    resolved = source_type
    if source_type == "unknown":
        if host.endswith(".gov.cn") or host == "gov.cn" or any(word in lowered for word in ("国务院", "政府公报", "政府网站")):
            resolved = "official"
        elif any(word in lowered for word in ("公司公告", "官方公告", "投资者关系")):
            resolved = "company"
        elif any(word in host for word in ("weibo.com", "zhihu.com", "douyin.com", "x.com", "twitter.com")):
            resolved = "social_media"
        elif any(word in host for word in ("bbs.", "tieba.", "reddit.com")):
            resolved = "forum"
    tiers = {
        "official": ("A", ["官方或法定发布渠道"]),
        "company": ("B", ["当事组织的一手公开材料，可能带有自身立场"]),
        "mainstream_media": ("B", ["具有编辑审核流程的媒体来源"]),
        "user_material": ("C", ["用户提供材料，需结合原件和出处复核"]),
        "self_media": ("C", ["自媒体来源，需寻找原始出处或独立印证"]),
        "forum": ("D", ["论坛内容通常缺少身份和事实核验"]),
        "social_media": ("D", ["社交媒体内容易受账号身份和传播语境影响"]),
        "unknown": ("unknown", ["来源类型尚未识别"]),
    }
    tier, reasons = tiers[resolved]
    return resolved, tier, reasons


def _metrics(
    sources: list[ResearchSource],
    claims: list[ResearchClaim],
    relations: list[ResearchRelation],
    gaps: list[ResearchGap],
    timeline: list[ResearchTimelineEvent],
    analogues: list[ResearchAnalogue],
    counterfactuals: list[ResearchCounterfactual],
    quantitative_observations: list[QuantitativeObservation],
    narratives: list[ResearchNarrative],
    policy_clauses: list[ResearchPolicyClause],
) -> ResearchMetrics:
    key_claims = [claim for claim in claims if claim.significance == "key"]
    supported_key = [claim for claim in key_claims if claim.evidence_ids]
    facts = [claim for claim in claims if claim.claim_type == "fact"]
    cited_facts = [claim for claim in facts if claim.evidence_ids]
    independent_groups = {source.independence_group for source in sources if not source.duplicate_of}
    supported_relations = [relation for relation in relations if relation.evidence_ids]
    dated_events = [event for event in timeline if event.date]
    known_quantitative = [item for item in quantitative_observations if item.status != "unknown"]
    sourced_quantitative = [
        item
        for item in known_quantitative
        if item.evidence_ids or item.id.startswith("system_")
    ]
    return ResearchMetrics(
        source_count=len(sources),
        independent_source_group_count=len(independent_groups),
        key_claim_count=len(key_claims),
        key_claim_evidence_coverage=round(len(supported_key) / len(key_claims), 3) if key_claims else 0.0,
        direct_fact_citation_rate=round(len(cited_facts) / len(facts), 3) if facts else 0.0,
        unsupported_inference_count=sum(
            1 for claim in claims if claim.claim_type == "inference" and claim.unsupported
        ),
        conflict_count=sum(1 for relation in relations if relation.status == "conflicted")
        + sum(1 for claim in claims if claim.counter_evidence_ids),
        gap_count=len(gaps),
        duplicate_source_count=sum(1 for source in sources if source.duplicate_of),
        high_quality_source_count=sum(1 for source in sources if source.quality_tier == "A"),
        relation_evidence_coverage=round(len(supported_relations) / len(relations), 3) if relations else 0.0,
        temporal_completeness=round(len(dated_events) / len(timeline), 3) if timeline else 0.0,
        source_independence_rate=round(len(independent_groups) / len(sources), 3) if sources else 0.0,
        analogue_count=len(analogues),
        evidence_backed_analogue_count=sum(1 for item in analogues if item.evidence_ids),
        counterfactual_count=len(counterfactuals),
        evidence_backed_counterfactual_count=sum(1 for item in counterfactuals if item.evidence_ids),
        quantitative_observation_count=len(quantitative_observations),
        sourced_quantitative_rate=(
            round(len(sourced_quantitative) / len(known_quantitative), 3)
            if known_quantitative
            else 0.0
        ),
        unknown_quantitative_count=sum(1 for item in quantitative_observations if item.status == "unknown"),
        narrative_count=len(narratives),
        policy_clause_count=len(policy_clauses),
    )


def _system_quantitative_observations(
    nodes: list[ResearchNode], relations: list[ResearchRelation]
) -> list[QuantitativeObservation]:
    """Derive graph measurements without asking the model to invent numbers."""
    actor_count = len(nodes)
    relation_count = len(relations)
    evidenced_count = sum(1 for relation in relations if relation.evidence_ids)
    evidence_ids = _unique_strings(
        [evidence_id for node in nodes for evidence_id in node.evidence_ids]
        + [evidence_id for relation in relations for evidence_id in relation.evidence_ids]
    )
    observations = [
        QuantitativeObservation(
            id="system_actor_count",
            metric_name="主体数量",
            value=actor_count,
            unit="个",
            scope="当前版本研究账本",
            methodology="对主体节点 ID 去重后计数",
            formula=f"N = {actor_count}",
            evidence_ids=evidence_ids,
            status="derived",
            confidence="high",
        ),
        QuantitativeObservation(
            id="system_relation_count",
            metric_name="关系数量",
            value=relation_count,
            unit="条",
            scope="当前版本研究账本",
            methodology="对关系边 ID 去重后计数",
            formula=f"E = {relation_count}",
            evidence_ids=evidence_ids,
            status="derived",
            confidence="high",
        ),
        QuantitativeObservation(
            id="system_evidenced_relation_count",
            metric_name="有证据关系数量",
            value=evidenced_count,
            unit="条",
            scope="当前版本研究账本",
            methodology="统计至少绑定一个有效来源的关系边",
            formula=f"E_supported = {evidenced_count}",
            evidence_ids=evidence_ids,
            status="derived",
            confidence="high",
        ),
    ]
    if actor_count > 1:
        density = round(relation_count / (actor_count * (actor_count - 1)), 3)
        observations.append(
            QuantitativeObservation(
                id="system_graph_density",
                metric_name="有向关系图谱密度",
                value=density,
                unit="",
                scope="当前版本研究账本",
                methodology="实际关系数除以不含自环的最大有向关系数",
                formula=f"E / (N * (N - 1)) = {relation_count} / ({actor_count} * {actor_count - 1})",
                evidence_ids=evidence_ids,
                status="derived",
                caveats=["该指标描述图谱连接程度，不代表关系强弱或结论质量"],
                confidence="high",
            )
        )
    return observations


def normalize_research_ledger(payload: dict) -> ResearchLedger:
    """Validate references and downgrade claims that exceed their evidence."""
    raw_sources = payload.get("sources") if isinstance(payload, dict) else []
    sources: list[ResearchSource] = []
    source_ids: set[str] = set()
    for index, raw in enumerate(raw_sources or [], 1):
        if not isinstance(raw, dict):
            continue
        source_id = str(raw.get("id") or f"s{index}").strip()
        if not source_id or source_id in source_ids:
            source_id = f"s{index}"
        while source_id in source_ids:
            source_id += "_"
        source_ids.add(source_id)
        url = str(raw.get("url") or "").strip()
        proposed_type = _safe_choice(
            raw.get("source_type"),
            {"official", "company", "mainstream_media", "self_media", "forum", "social_media", "user_material", "unknown"},
            "unknown",
        )
        resolved_type, quality_tier, quality_reasons = _classify_source(
            proposed_type, str(raw.get("title") or ""), url
        )
        source = ResearchSource.model_validate(
            {
                **raw,
                "id": source_id,
                "title": str(raw.get("title") or "未命名来源").strip(),
                "url": url,
                "source_type": resolved_type,
                "source_level": _safe_choice(
                    raw.get("source_level"),
                    {"primary", "secondary", "tertiary", "user", "unknown"},
                    "unknown",
                ),
                "independence_group": str(raw.get("independence_group") or _default_independence_group(url, source_id)),
                "quality_tier": quality_tier,
                "quality_reasons": _unique_strings(raw.get("quality_reasons")) or quality_reasons,
                "canonical_url": str(raw.get("canonical_url") or url),
                "original_url": str(raw.get("original_url") or ""),
                "content_fingerprint": _source_fingerprint(
                    str(raw.get("title") or ""), str(raw.get("excerpt") or "")
                ),
            }
        )
        sources.append(source)

    fingerprint_owner: dict[str, ResearchSource] = {}
    for source in sources:
        if not source.content_fingerprint:
            continue
        owner = fingerprint_owner.get(source.content_fingerprint)
        if owner is None:
            fingerprint_owner[source.content_fingerprint] = source
            continue
        source.duplicate_of = owner.id
        source.independence_group = owner.independence_group

    claims: list[ResearchClaim] = []
    claim_ids: set[str] = set()
    for index, raw in enumerate(payload.get("claims") or [], 1):
        if not isinstance(raw, dict) or not str(raw.get("text") or "").strip():
            continue
        claim_id = str(raw.get("id") or f"c{index}").strip()
        if not claim_id or claim_id in claim_ids:
            claim_id = f"c{index}"
        while claim_id in claim_ids:
            claim_id += "_"
        claim_ids.add(claim_id)
        evidence_ids = _unique_strings(raw.get("evidence_ids"), source_ids)
        counter_ids = _unique_strings(raw.get("counter_evidence_ids"), source_ids)
        claim_type = _safe_choice(
            raw.get("claim_type"), {"fact", "source_view", "inference", "user_input"}, "inference"
        )
        confidence = _safe_choice(raw.get("confidence"), {"high", "medium", "low", "unknown"}, "unknown")
        reasons = _unique_strings(raw.get("confidence_reasons"))
        unsupported = bool(raw.get("unsupported"))
        if claim_type in {"fact", "source_view"} and not evidence_ids:
            claim_type = "inference"
            confidence = "low"
            unsupported = True
            if "缺少可核验来源" not in reasons:
                reasons.append("缺少可核验来源")
        claims.append(
            ResearchClaim.model_validate(
                {
                    **raw,
                    "id": claim_id,
                    "text": str(raw.get("text")).strip(),
                    "claim_type": claim_type,
                    "significance": _safe_choice(raw.get("significance"), {"key", "supporting"}, "key"),
                    "confidence": confidence,
                    "confidence_reasons": reasons,
                    "evidence_ids": evidence_ids,
                    "counter_evidence_ids": counter_ids,
                    "unsupported": unsupported,
                }
            )
        )

    nodes: list[ResearchNode] = []
    node_ids: set[str] = set()
    for index, raw in enumerate(payload.get("nodes") or [], 1):
        if not isinstance(raw, dict):
            continue
        node_id = str(raw.get("id") or f"n{index}").strip()
        label = str(raw.get("label") or node_id).strip()
        if not node_id or not label or node_id in node_ids:
            continue
        node_ids.add(node_id)
        evidence_ids = _unique_strings(raw.get("evidence_ids"), source_ids)
        confidence = _safe_choice(raw.get("confidence"), {"high", "medium", "low", "unknown"}, "unknown")
        if confidence == "high" and not evidence_ids:
            confidence = "low"
        history = []
        for point in raw.get("stance_history") or []:
            if not isinstance(point, dict) or not str(point.get("at") or "").strip() or not str(point.get("stance") or "").strip():
                continue
            history.append(
                ResearchStancePoint(
                    at=str(point.get("at")).strip(),
                    stance=str(point.get("stance")).strip(),
                    evidence_ids=_unique_strings(point.get("evidence_ids"), source_ids),
                )
            )
        history.sort(key=lambda item: item.at)
        try:
            weight = max(0.0, min(1.0, float(raw.get("weight", 0.5))))
        except (TypeError, ValueError):
            weight = 0.5
        nodes.append(
            ResearchNode(
                id=node_id,
                label=label,
                aliases=_unique_strings(raw.get("aliases")),
                role=str(raw.get("role") or "").strip(),
                interests=_unique_strings(raw.get("interests")),
                stance=str(raw.get("stance") or "").strip(),
                weight=weight,
                confidence=confidence,
                evidence_ids=evidence_ids,
                first_seen=str(raw.get("first_seen") or "").strip() or None,
                last_seen=str(raw.get("last_seen") or "").strip() or None,
                stance_history=history,
            )
        )

    relations: list[ResearchRelation] = []
    relation_ids: set[str] = set()
    for index, raw in enumerate(payload.get("relations") or [], 1):
        if not isinstance(raw, dict):
            continue
        source_node = str(raw.get("source_node") or "").strip()
        target_node = str(raw.get("target_node") or "").strip()
        if not source_node or not target_node:
            continue
        relation_id = str(raw.get("id") or f"r{index}").strip()
        if not relation_id or relation_id in relation_ids:
            relation_id = f"r{index}"
        while relation_id in relation_ids:
            relation_id += "_"
        relation_ids.add(relation_id)
        evidence_ids = _unique_strings(raw.get("evidence_ids"), source_ids)
        status = _safe_choice(raw.get("status"), {"confirmed", "inferred", "conflicted"}, "inferred")
        confidence = _safe_choice(raw.get("confidence"), {"high", "medium", "low", "unknown"}, "unknown")
        if status == "confirmed" and not evidence_ids:
            status = "inferred"
            confidence = "low"
        claim_id = str(raw.get("claim_id") or "").strip() or None
        if claim_id not in claim_ids:
            claim_id = None
        relations.append(
            ResearchRelation.model_validate(
                {
                    **raw,
                    "id": relation_id,
                    "source_node": source_node,
                    "target_node": target_node,
                    "label": str(raw.get("label") or "关联").strip(),
                    "direction": _safe_choice(raw.get("direction"), {"directed", "undirected", "mutual", "unknown"}, "unknown"),
                    "polarity": _safe_choice(raw.get("polarity"), {"positive", "negative", "mixed", "neutral", "unknown"}, "unknown"),
                    "confidence": confidence,
                    "evidence_ids": evidence_ids,
                    "claim_id": claim_id,
                    "status": status,
                    "strength": max(1, min(5, int(raw.get("strength") or 1))) if str(raw.get("strength") or "1").isdigit() else 1,
                    "interest_types": _unique_strings(raw.get("interest_types")),
                    "valid_from": str(raw.get("valid_from") or "").strip() or None,
                    "valid_to": str(raw.get("valid_to") or "").strip() or None,
                    "evidence_count": len(evidence_ids),
                }
            )
        )

    timeline: list[ResearchTimelineEvent] = []
    timeline_ids: set[str] = set()
    for index, raw in enumerate(payload.get("timeline") or [], 1):
        if not isinstance(raw, dict) or not str(raw.get("title") or "").strip():
            continue
        event_id = str(raw.get("id") or f"t{index}").strip()
        if event_id in timeline_ids:
            event_id = f"t{index}"
        timeline_ids.add(event_id)
        timeline.append(
            ResearchTimelineEvent(
                id=event_id,
                date=str(raw.get("date") or "").strip() or None,
                title=str(raw.get("title")).strip(),
                detail=str(raw.get("detail") or "").strip(),
                event_type=str(raw.get("event_type") or "event").strip(),
                actor_ids=_unique_strings(raw.get("actor_ids"), node_ids) if node_ids else _unique_strings(raw.get("actor_ids")),
                claim_ids=_unique_strings(raw.get("claim_ids"), claim_ids),
                evidence_ids=_unique_strings(raw.get("evidence_ids"), source_ids),
                confidence=_safe_choice(raw.get("confidence"), {"high", "medium", "low", "unknown"}, "unknown"),
                turning_point=bool(raw.get("turning_point")),
            )
        )
    timeline.sort(key=lambda event: (event.date is None, event.date or "", event.id))

    gaps: list[ResearchGap] = []
    for index, raw in enumerate(payload.get("gaps") or [], 1):
        if not isinstance(raw, dict) or not str(raw.get("question") or "").strip():
            continue
        gaps.append(
            ResearchGap.model_validate(
                {
                    **raw,
                    "id": str(raw.get("id") or f"g{index}"),
                    "question": str(raw.get("question")).strip(),
                    "impact": _unique_strings(raw.get("impact")),
                    "recommended_materials": _unique_strings(raw.get("recommended_materials")),
                    "priority": _safe_choice(raw.get("priority"), {"critical", "high", "medium", "low"}, "medium"),
                    "material_type": str(raw.get("material_type") or "unknown").strip(),
                }
            )
        )

    gap_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    gaps.sort(key=lambda gap: (gap_order[gap.priority], gap.id))

    analogues: list[ResearchAnalogue] = []
    for index, raw in enumerate(payload.get("analogues") or [], 1):
        if not isinstance(raw, dict) or not str(raw.get("title") or "").strip():
            continue
        evidence_ids = _unique_strings(raw.get("evidence_ids"), source_ids)
        confidence = _safe_choice(raw.get("confidence"), {"high", "medium", "low", "unknown"}, "unknown")
        comparability = _safe_choice(raw.get("comparability"), {"high", "medium", "low", "unknown"}, "unknown")
        reasons = _unique_strings(raw.get("confidence_reasons"))
        if not evidence_ids:
            confidence = "low"
            comparability = "unknown"
            if "缺少可核验来源" not in reasons:
                reasons.append("缺少可核验来源")
        analogues.append(
            ResearchAnalogue(
                id=str(raw.get("id") or f"a{index}"),
                title=str(raw.get("title")).strip(),
                summary=str(raw.get("summary") or "").strip(),
                period=str(raw.get("period") or "").strip() or None,
                jurisdiction=str(raw.get("jurisdiction") or "").strip(),
                domain=str(raw.get("domain") or "").strip(),
                similarities=_unique_strings(raw.get("similarities")),
                differences=_unique_strings(raw.get("differences")),
                response=str(raw.get("response") or "").strip(),
                outcome=str(raw.get("outcome") or "").strip(),
                relevance_reason=str(raw.get("relevance_reason") or "").strip(),
                evidence_ids=evidence_ids,
                comparability=comparability,
                confidence=confidence,
                confidence_reasons=reasons,
            )
        )

    counterfactuals: list[ResearchCounterfactual] = []
    for index, raw in enumerate(payload.get("counterfactuals") or [], 1):
        if not isinstance(raw, dict) or not str(raw.get("premise") or "").strip():
            continue
        evidence_ids = _unique_strings(raw.get("evidence_ids"), source_ids)
        confidence = _safe_choice(raw.get("confidence"), {"high", "medium", "low", "unknown"}, "unknown")
        status = _safe_choice(raw.get("status"), {"evidence_based", "modelled", "insufficient"}, "modelled")
        reasons = _unique_strings(raw.get("confidence_reasons"))
        if not evidence_ids:
            confidence = "low"
            status = "insufficient"
            if "缺少可核验来源，反事实只能作为待验证假设" not in reasons:
                reasons.append("缺少可核验来源，反事实只能作为待验证假设")
        counterfactuals.append(
            ResearchCounterfactual(
                id=str(raw.get("id") or f"cf{index}"),
                premise=str(raw.get("premise")).strip(),
                changed_condition=str(raw.get("changed_condition") or raw.get("premise") or "").strip(),
                baseline_outcome=str(raw.get("baseline_outcome") or "").strip(),
                alternative_outcome=str(raw.get("alternative_outcome") or "").strip(),
                causal_chain=_unique_strings(raw.get("causal_chain")),
                supporting_claim_ids=_unique_strings(raw.get("supporting_claim_ids"), claim_ids),
                evidence_ids=evidence_ids,
                assumptions=_unique_strings(raw.get("assumptions")),
                invalidation_signals=_unique_strings(raw.get("invalidation_signals")),
                confidence=confidence,
                confidence_reasons=reasons,
                status=status,
            )
        )

    quantitative_observations: list[QuantitativeObservation] = []
    for index, raw in enumerate(payload.get("quantitative_observations") or [], 1):
        if not isinstance(raw, dict) or not str(raw.get("metric_name") or "").strip():
            continue
        evidence_ids = _unique_strings(raw.get("evidence_ids"), source_ids)
        status = _safe_choice(raw.get("status"), {"observed", "derived", "unknown", "conflicted"}, "unknown")
        formula = str(raw.get("formula") or "").strip()
        caveats = _unique_strings(raw.get("caveats"))
        value = raw.get("value")
        confidence = _safe_choice(raw.get("confidence"), {"high", "medium", "low", "unknown"}, "unknown")
        if status in {"observed", "conflicted"} and not evidence_ids:
            status = "unknown"
            value = None
            confidence = "low"
            if "缺少可核验来源" not in caveats:
                caveats.append("缺少可核验来源")
        if status == "derived" and (not evidence_ids or not formula):
            status = "unknown"
            value = None
            confidence = "low"
            if not evidence_ids and "缺少可核验来源" not in caveats:
                caveats.append("缺少可核验来源")
            if not formula and "派生值缺少透明公式" not in caveats:
                caveats.append("派生值缺少透明公式")
        quantitative_observations.append(
            QuantitativeObservation(
                id=str(raw.get("id") or f"q{index}"),
                metric_name=str(raw.get("metric_name")).strip(),
                value=value,
                unit=str(raw.get("unit") or "").strip(),
                observed_at=str(raw.get("observed_at") or "").strip() or None,
                period_start=str(raw.get("period_start") or "").strip() or None,
                period_end=str(raw.get("period_end") or "").strip() or None,
                scope=str(raw.get("scope") or "").strip(),
                methodology=str(raw.get("methodology") or "").strip(),
                formula=formula,
                evidence_ids=evidence_ids,
                status=status,
                caveats=caveats,
                confidence=confidence,
            )
        )
    existing_quant_ids = {item.id for item in quantitative_observations}
    for item in _system_quantitative_observations(nodes, relations):
        if item.id not in existing_quant_ids:
            quantitative_observations.append(item)

    # —— 账本 1.3：叙事份额（舆情可选）——
    # 降级铁律：share 必须有口径与来源/证据支撑，否则降为定性（None），不编造百分比。
    narratives: list[ResearchNarrative] = []
    for index, raw in enumerate(payload.get("narratives") or [], 1):
        if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
            continue
        evidence_ids = _unique_strings(raw.get("evidence_ids"), source_ids)
        narrative_source_ids = _unique_strings(raw.get("source_ids"), source_ids)
        share = raw.get("share")
        try:
            share_value = float(share) if share is not None else None
        except (TypeError, ValueError):
            share_value = None
        share_basis = str(raw.get("share_basis") or "").strip()
        reasons: list[str] = []
        confidence = _safe_choice(raw.get("confidence"), {"high", "medium", "low", "unknown"}, "unknown")
        if share_value is not None and not (0.0 <= share_value <= 1.0):
            share_value = None
            reasons.append("份额超出 0~1 范围，已降级为定性描述")
        if share_value is not None and not share_basis:
            share_value = None
            reasons.append("份额缺少计算口径，已降级为定性描述")
        if share_value is not None and not evidence_ids and not narrative_source_ids:
            share_value = None
            confidence = "low"
            reasons.append("份额缺少来源/证据支撑，已降级为定性描述")
        narratives.append(
            ResearchNarrative(
                id=str(raw.get("id") or f"nar{index}"),
                name=str(raw.get("name")).strip(),
                summary=str(raw.get("summary") or "").strip(),
                stance=_safe_choice(
                    raw.get("stance"),
                    {"supportive", "opposing", "neutral", "mixed", "unknown"},
                    "unknown",
                ),
                share=share_value,
                share_basis=share_basis,
                actor_ids=_unique_strings(raw.get("actor_ids"), node_ids),
                source_ids=narrative_source_ids,
                evidence_ids=evidence_ids,
                confidence=confidence,
                confidence_reasons=reasons,
            )
        )
    narratives.sort(key=lambda item: (item.share is None, -(item.share or 0.0), item.id))

    # —— 账本 1.3：政策条款拆解（政策可选）——
    policy_clauses: list[ResearchPolicyClause] = []
    for index, raw in enumerate(payload.get("policy_clauses") or [], 1):
        if not isinstance(raw, dict) or not str(raw.get("title") or "").strip():
            continue
        evidence_ids = _unique_strings(raw.get("evidence_ids"), source_ids)
        clause_confidence = _safe_choice(raw.get("confidence"), {"high", "medium", "low", "unknown"}, "unknown")
        if not evidence_ids:
            clause_confidence = "low"
        policy_clauses.append(
            ResearchPolicyClause(
                id=str(raw.get("id") or f"pc{index}"),
                clause_no=str(raw.get("clause_no") or "").strip(),
                title=str(raw.get("title")).strip(),
                content_digest=str(raw.get("content_digest") or "").strip(),
                target_groups=_unique_strings(raw.get("target_groups")),
                interest_change=_safe_choice(
                    raw.get("interest_change"),
                    {"benefit", "loss", "neutral", "mixed", "unknown"},
                    "unknown",
                ),
                region_level=_safe_choice(
                    raw.get("region_level"),
                    {"national", "province", "city", "district", "unknown"},
                    "unknown",
                ),
                effective_at=str(raw.get("effective_at") or "").strip() or None,
                claim_ids=_unique_strings(raw.get("claim_ids"), claim_ids),
                evidence_ids=evidence_ids,
                confidence=clause_confidence,
            )
        )
    # 条款保持 payload 原序（条款号有天然顺序，不重排）

    return ResearchLedger(
        schema_version="1.3",
        status=(
            payload.get("status")
            if payload.get("status") in {"fallback", "no_evidence", "extraction_failed"}
            else "verified"
        ),
        sources=sources,
        claims=claims,
        nodes=nodes,
        relations=relations,
        timeline=timeline,
        gaps=gaps,
        analogues=analogues,
        counterfactuals=counterfactuals,
        quantitative_observations=quantitative_observations,
        narratives=narratives,
        policy_clauses=policy_clauses,
        metrics=_metrics(
            sources,
            claims,
            relations,
            gaps,
            timeline,
            analogues,
            counterfactuals,
            quantitative_observations,
            narratives,
            policy_clauses,
        ),
        warnings=_unique_strings(payload.get("warnings")),
    )


def build_fallback_ledger(
    *,
    markdown: str,
    materials: dict | None,
    input_text: str = "",
    reason: str = "研究账本不可用",
    status: Literal["fallback", "no_evidence", "extraction_failed"] = "fallback",
) -> ResearchLedger:
    """Build an honest minimal ledger without inventing report-level evidence."""
    material_items = (materials or {}).get("items") or []
    item_by_url = {
        str(item.get("url") or ""): item
        for item in material_items
        if isinstance(item, dict) and item.get("kept", True)
    }
    raw_sources = []
    for index, source in enumerate((materials or {}).get("sources") or [], 1):
        title = getattr(source, "title", None) or (source.get("title") if isinstance(source, dict) else None)
        url = getattr(source, "url", None) or (source.get("url") if isinstance(source, dict) else None)
        item = item_by_url.get(str(url or ""), {})
        raw_sources.append(
            {
                "id": f"s{index}",
                "title": title or url or f"来源 {index}",
                "url": url or "",
                "excerpt": str(item.get("text") or item.get("snippet") or "")[:500],
                "source_type": "unknown",
                "source_level": "unknown",
            }
        )
    raw_claims = []
    if input_text.strip():
        raw_claims.append(
            {
                "id": "c1",
                "text": input_text.strip()[:1000],
                "claim_type": "user_input",
                "confidence": "unknown",
                "confidence_reasons": ["该信息由用户提供，尚未完成外部核验"],
                "significance": "key",
            }
        )
    raw_relations = []
    for block in re.findall(r"```DIAGRAM\s*\n(.*?)\n```", markdown or "", re.DOTALL | re.IGNORECASE):
        try:
            diagram = json.loads(block)
        except (TypeError, json.JSONDecodeError):
            continue
        for edge in diagram.get("edges") or [] if isinstance(diagram, dict) else []:
            if not isinstance(edge, dict):
                continue
            source_node = str(edge.get("source") or edge.get("from") or "").strip()
            target_node = str(edge.get("target") or edge.get("to") or "").strip()
            if not source_node or not target_node:
                continue
            raw_relations.append(
                {
                    "id": str(edge.get("relation_id") or f"r{len(raw_relations) + 1}"),
                    "source_node": source_node,
                    "target_node": target_node,
                    "label": str(edge.get("label") or "关联"),
                    "relation_type": str(edge.get("type") or "unknown"),
                    "direction": "directed",
                    "confidence": "low",
                    "evidence_ids": [],
                    "status": "inferred",
                }
            )
    payload = {
        "status": status,
        "sources": raw_sources,
        "claims": raw_claims,
        "relations": raw_relations,
        "gaps": [
            {
                "id": "g1",
                "question": "哪些关键判断仍缺少逐条证据绑定？",
                "reason": reason,
                "impact": ["关键结论可靠性", "关系图谱边级解释"],
                "recommended_materials": ["原始公告或文件", "能够直接支撑关键关系的独立来源"],
            }
        ],
        "warnings": [reason],
    }
    return normalize_research_ledger(payload)
