"""F15 结构化数据表派生（共享模块）。

来源证据/主体清单/关系清单/事件时间线/叙事份额/政策条款 六张表都由
ReportVersion.research_snapshot（研究账本 dict）**纯派生**，零 LLM 调用：
- /api/reports/{id}/tables/{table_id}（routers/reports.py）JSON/CSV 输出用；
- Word 附表「关键数据表」（generator → engine → docx_renderer）复用同一派生口径；
- /api/reports/{id}/geo 地图聚合的地域识别也复用 region_of，保证口径一致。

地域列为表内即时派生（recognize_region 对 title/excerpt 等字段识别），
不改账本模型——存量报告立即获得地域列，零迁移。
"""
from __future__ import annotations

from app.connectors.regions import recognize_region_detailed

_TABLE_DEFS: dict[str, dict] = {
    "sources": {
        "name": "来源证据表",
        "columns": ["编号", "标题", "链接", "来源类型", "质量档", "发布时间", "地域", "独立源组", "重复判定", "摘要"],
        # 适用报告类型（None=全部）；用于 applicable 判定
        "applicable": None,
    },
    "subjects": {
        "name": "主体清单表",
        "columns": ["编号", "主体", "角色", "立场", "权重", "置信度", "证据数", "地域", "利益诉求"],
        "applicable": None,
    },
    "relations": {
        "name": "关系清单表",
        "columns": ["源主体", "目标主体", "关系描述", "极性", "强度", "状态", "证据数", "利益类型"],
        "applicable": None,
    },
    "timeline": {
        "name": "事件时间线表",
        "columns": ["日期", "事件", "详情", "涉及主体", "证据数", "转折点"],
        "applicable": {"case", "opinion", "combo"},
    },
    "narratives": {
        "name": "叙事份额表",
        "columns": ["叙事", "立场", "份额", "口径", "代表来源数", "置信度"],
        "applicable": {"opinion", "combo"},
    },
    "policy_clauses": {
        "name": "政策条款表",
        "columns": ["条款", "标题", "要点", "影响对象", "利益变化", "地域层级", "生效时间", "置信度"],
        "applicable": {"policy", "combo"},
    },
}


def table_applicable(table_id: str, analysis_type: str | None) -> bool:
    """判定某张表对该报告类型是否适用（供前端区分「类型不适用」与「暂无数据」）。"""
    rule = _TABLE_DEFS.get(table_id, {}).get("applicable")
    if rule is None or not analysis_type:
        return True
    return analysis_type in rule


def table_exists(table_id: str) -> bool:
    return table_id in _TABLE_DEFS


def table_columns(table_id: str) -> list[str]:
    return list(_TABLE_DEFS[table_id]["columns"])


def table_name(table_id: str) -> str:
    return _TABLE_DEFS[table_id]["name"]


def region_of(item: dict) -> str:
    """对单条来源/主体派生地域标签（F10 表内即时派生，不改账本模型）。

    与 /geo 聚合共用同一 recognize_region_detailed 口径：命中市级显示市名
    （最具体），仅命中省级显示省名；未识别返回空串。
    """
    if not isinstance(item, dict):
        return ""
    text = " ".join(
        str(item.get(key) or "")
        for key in ("title", "excerpt", "label", "role", "interests")
    )
    if not text.strip():
        return ""
    region = recognize_region_detailed(text)
    return str(region.get("city_name") or region.get("region_name") or "")


def _labels_of(ledger: dict) -> dict:
    return {
        (n.get("id") if isinstance(n, dict) else None): (n.get("label") or "")
        for n in (ledger.get("nodes") or []) if isinstance(n, dict)
    }


def ledger_rows(table_id: str, ledger: dict) -> list[list]:
    """从研究账本 dict 派生表格行（与 _TABLE_DEFS 列序一一对应）。"""
    if not isinstance(ledger, dict):
        return []
    rows: list[list] = []
    if table_id == "sources":
        for i, s in enumerate(ledger.get("sources") or [], 1):
            if not isinstance(s, dict):
                continue
            dup = "重复" if s.get("duplicate_of") else ("首发" if s.get("content_fingerprint") else "")
            rows.append([
                s.get("id") or f"S{i}",
                s.get("title") or "",
                s.get("url") or s.get("canonical_url") or "",
                s.get("source_type") or "",
                s.get("quality_tier") or "",
                s.get("published_at") or "",
                region_of(s),
                s.get("independence_group") or "",
                dup,
                (s.get("excerpt") or "").strip()[:160],
            ])
    elif table_id == "subjects":
        for i, n in enumerate(ledger.get("nodes") or [], 1):
            if not isinstance(n, dict):
                continue
            evidence = n.get("evidence_ids") or []
            interests = n.get("interests") or []
            rows.append([
                n.get("id") or f"N{i}",
                n.get("label") or "",
                n.get("role") or "",
                n.get("stance") or "",
                n.get("weight") if n.get("weight") is not None else "",
                n.get("confidence") if n.get("confidence") is not None else "",
                len(evidence),
                region_of(n),
                "；".join(str(x) for x in interests)[:200],
            ])
    elif table_id == "relations":
        labels = _labels_of(ledger)
        for i, r in enumerate(ledger.get("relations") or [], 1):
            if not isinstance(r, dict):
                continue
            interest_types = r.get("interest_types") or []
            rows.append([
                labels.get(r.get("source_node")) or r.get("source_node") or "",
                labels.get(r.get("target_node")) or r.get("target_node") or "",
                r.get("label") or "",
                r.get("polarity") or "",
                r.get("strength") if r.get("strength") is not None else "",
                r.get("status") or "",
                r.get("evidence_count") if r.get("evidence_count") is not None else len(r.get("evidence_ids") or []),
                "；".join(str(x) for x in interest_types)[:200],
            ])
    elif table_id == "timeline":
        labels = _labels_of(ledger)
        for i, e in enumerate(ledger.get("timeline") or [], 1):
            if not isinstance(e, dict):
                continue
            actors = [labels.get(a) or str(a) for a in (e.get("actor_ids") or [])]
            rows.append([
                e.get("date") or "（未注明）",
                e.get("title") or "",
                (e.get("detail") or "").strip()[:200],
                "；".join(actors)[:120],
                len(e.get("evidence_ids") or []),
                "是" if e.get("turning_point") else "",
            ])
    elif table_id == "narratives":
        for i, nar in enumerate(ledger.get("narratives") or [], 1):
            if not isinstance(nar, dict):
                continue
            share = nar.get("share")
            share_text = f"{share:.0%}" if isinstance(share, (int, float)) else "定性"
            rows.append([
                nar.get("name") or "",
                nar.get("stance") or "",
                share_text,
                nar.get("share_basis") or "",
                len(nar.get("source_ids") or []),
                nar.get("confidence") or "",
            ])
    elif table_id == "policy_clauses":
        for i, c in enumerate(ledger.get("policy_clauses") or [], 1):
            if not isinstance(c, dict):
                continue
            targets = c.get("target_groups") or []
            rows.append([
                c.get("clause_no") or "",
                c.get("title") or "",
                (c.get("content_digest") or "").strip()[:160],
                "；".join(str(x) for x in targets)[:120],
                c.get("interest_change") or "",
                c.get("region_level") or "",
                c.get("effective_at") or "",
                c.get("confidence") or "",
            ])
    return rows


def word_data_tables(ledger: dict, analysis_type: str | None = None) -> list[dict]:
    """派生 Word 附表「关键数据表」：来源证据 + 主体清单 + 时间线（政策报告换条款表）。

    返回 [{name, columns, rows}]；空账本返回空列表（Word 输出与既有逐字一致）。
    """
    if not isinstance(ledger, dict):
        return []
    picks = ["sources", "subjects", "policy_clauses" if analysis_type == "policy" else "timeline"]
    tables: list[dict] = []
    for table_id in picks:
        rows = ledger_rows(table_id, ledger)
        if not rows:
            continue
        tables.append(
            {
                "name": table_name(table_id),
                "columns": table_columns(table_id),
                "rows": rows,
            }
        )
    return tables
