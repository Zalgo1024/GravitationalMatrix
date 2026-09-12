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

import re

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


# 每个省回传的来源条目上限（点省浮层够看即可，避免 /geo 载荷膨胀）
_GEO_ITEMS_PER_REGION = 8


def geo_aggregation(ledger: dict) -> dict:
    """F11 地图聚合（纯派生零 LLM）：来源按地域归并 → 独立源组计数 → 份额。

    口径与 region_of 一致（recognize_region_detailed，市级命中也归并到所属省，
    前端中国图按省级着色；city 明细保留在 groups 里供后续市级下钻）。
    - independent_sources：按 independence_group 去重后的独立源数（同组转载只算 1）；
    - share：该省独立源数 / 有地域的独立源总数（0~1，四舍五入 3 位）；
    - coverage：有地域的独立源数 / 全部独立源数（过低时前端灰显提示）；
    - polarity：立场极性聚合（初版空数组，等主体 stance 打通后填充）；
    - items：该省的代表来源条目（同组转载已去重，最多 _GEO_ITEMS_PER_REGION 条），
      供点省浮层直接展示；item_total 是该省实际条目总数，超出部分前端提示省略；
    - city_groups：市级独立源组计数（市级下钻着色用），cities 仍是市名数组（兼容）；
    - timeline：按月分桶的省级独立源累计口径原料（独立源组按代表条目月份归月，
      无日期的组不进时间轴，前端负责做累计播放）。
    """
    if not isinstance(ledger, dict):
        return {"regions": [], "coverage": 0.0, "polarity": []}
    # 独立源组 -> [地域命中]；无组的来源按自身 id 兜底（各自独立）
    groups: dict[str, dict] = {}
    for s in ledger.get("sources") or []:
        if not isinstance(s, dict):
            continue
        key = str(s.get("independence_group") or s.get("url") or s.get("id") or "")
        if not key:
            continue
        detail = recognize_region_detailed(
            " ".join(str(s.get(k) or "") for k in ("title", "excerpt"))
        )
        province_code = str(detail.get("region_code") or "")
        province_name = str(detail.get("region_name") or "")
        city_name = str(detail.get("city_name") or "")
        group = groups.setdefault(key, {"province": (province_code, province_name), "city": "", "city_seen": set(), "count": 0, "sample": None})
        group["count"] += 1
        # 同组转载只保留一条代表条目，避免点开一个省看到十条重复标题
        if group["sample"] is None:
            group["sample"] = s
            group["city"] = city_name
        if province_code:
            # 组内取第一个命中的省（同组转载地域一致）；无命中的组保持未识别
            if not group["province"][0]:
                group["province"] = (province_code, province_name)
            if city_name:
                group["city_seen"].add(city_name)

    by_province: dict[str, dict] = {}
    total_indep = 0
    located_indep = 0
    monthly: dict[str, dict[str, int]] = {}
    for group in groups.values():
        total_indep += 1
        pcode, pname = group["province"]
        if not pcode:
            continue
        located_indep += 1
        bucket = by_province.setdefault(
            pcode,
            {"region_code": pcode, "region_name": pname, "independent_sources": 0, "sources": 0, "city_groups": {}, "items": []},
        )
        bucket["independent_sources"] += 1
        bucket["sources"] += group["count"]
        for city in group["city_seen"]:
            bucket["city_groups"][city] = bucket["city_groups"].get(city, 0) + 1
        sample = group.get("sample")
        if isinstance(sample, dict):
            bucket["items"].append({
                "id": str(sample.get("id") or ""),
                "title": str(sample.get("title") or "未命名来源"),
                "url": str(sample.get("url") or ""),
                "published_at": str(sample.get("published_at") or ""),
                "source_type": str(sample.get("source_type") or "unknown"),
                "city": str(group.get("city") or ""),
            })
            month_match = re.match(r"^(\d{4}-\d{2})", str(sample.get("published_at") or ""))
            if month_match:
                monthly.setdefault(month_match.group(1), {}).setdefault(pcode, 0)
                monthly[month_match.group(1)][pcode] += 1

    regions = []
    for bucket in by_province.values():
        items = sorted(bucket["items"], key=lambda item: (item["published_at"] or "9999"), reverse=False)
        city_groups = sorted(
            ({"name": name, "groups": count} for name, count in bucket["city_groups"].items()),
            key=lambda entry: (-entry["groups"], entry["name"]),
        )
        regions.append(
            {
                "region_code": bucket["region_code"],
                "region_name": bucket["region_name"],
                "independent_sources": bucket["independent_sources"],
                "sources": bucket["sources"],
                "share": round(bucket["independent_sources"] / located_indep, 3) if located_indep else 0.0,
                "cities": [entry["name"] for entry in city_groups],
                "city_groups": city_groups,
                # 点省浮层用：只回代表条目（同组转载已去重），前端按 need 再要全量
                "items": items[:_GEO_ITEMS_PER_REGION],
                "item_total": len(items),
            }
        )
    regions.sort(key=lambda r: (-r["independent_sources"], r["region_name"]))
    name_by_code = {bucket["region_code"]: bucket["region_name"] for bucket in by_province.values()}
    timeline = [
        {
            "month": month,
            "regions": [
                {"region_code": code, "region_name": name_by_code.get(code, code), "independent_sources": count}
                for code, count in sorted(codes.items(), key=lambda item: (-item[1], item[0]))
            ],
        }
        for month, codes in sorted(monthly.items())
    ]
    return {
        "regions": regions,
        "coverage": round(located_indep / total_indep, 3) if total_indep else 0.0,
        "polarity": [],
        "timeline": timeline,
    }


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
