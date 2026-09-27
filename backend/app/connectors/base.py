"""采集器基座：统一来源契约 + 去重三元组。

去重口径与 research_ledger 保持一致（_source_fingerprint / _default_independence_group）：
- content_fingerprint：标题+摘要规范化后的 sha1，同文异链判重；
- canonical_url：去掉 utm/spm 等跟踪参数后的规范化链接，同链异文判重；
- independence_group：按主机名聚簇，用于「独立来源数」统计（同一 host 的
  多条转载只算一个独立源）。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

# 常见跟踪参数：canonical_url 阶段剥离
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "spm", "spm_id_from", "share_token", "share_source", "share_medium",
    "from", "fr", "refer", "ref", "is_from_app", "app_platform",
}
_HOST_SUFFIX_RE = re.compile(r"\.(com|cn|net|org|gov|edu|co|io|info)\.?$")


@dataclass
class CollectedItem:
    """一条采集结果（F1 预览/F2 自动取证的统一契约）。

    platform：采集渠道（websearch / rss:<名称> / govdoc / hotlist:<榜单名>）；
    region_name：省份级地区识别结果（title/snippet 命中省级别名时填充）；
    engagement：热度值（榜单类来源提供，检索类为 None）。
    """

    kind: str
    platform: str
    title: str
    url: str
    snippet: str = ""
    published_at: str | None = None
    region_code: str | None = None
    region_name: str | None = None
    region_source: str = "unknown"  # issuer/title/body/unknown（recognize_region 口径）
    engagement: int | None = None
    content_text: str = ""
    # 去重三元组（dedupe_items 填充）
    content_fingerprint: str = ""
    canonical_url: str = ""
    independence_group: str = ""
    duplicate_of: str = ""
    extra: dict = field(default_factory=dict)

    def to_row(self) -> dict:
        """前端预览行（不含正文，正文入库才有意义）。"""
        return {
            "kind": self.kind,
            "platform": self.platform,
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet[:200],
            "published_at": self.published_at,
            "region_code": self.region_code,
            "region_name": self.region_name,
            "engagement": self.engagement,
            "duplicate": bool(self.duplicate_of),
        }


def canonicalize_url(url: str) -> str:
    """规范化链接：协议归一 https、去跟踪参数、去 fragment、host 小写。"""
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw
    scheme = "https" if parts.scheme in ("http", "https") else (parts.scheme or "https")
    host = (parts.netloc or "").lower()
    kept: list[tuple[str, str]] = []
    if parts.query:
        for pair in parts.query.split("&"):
            if not pair:
                continue
            key = pair.split("=", 1)[0].lower()
            if key in _TRACKING_PARAMS:
                continue
            kept.append(tuple(pair.split("=", 1)) if "=" in pair else (pair, ""))
    query = "&".join(f"{k}={v}" if v else k for k, v in kept)
    return urlunsplit((scheme, host, parts.path or "/", query, ""))


def host_of(url: str) -> str:
    try:
        host = urlsplit(url).netloc.lower()
    except ValueError:
        return ""
    return host.split("@")[-1].split(":")[0]


def _default_independence_group(url: str) -> str:
    """按注册域聚簇（zh.wikipedia.org 与 en.wikipedia.org 同组；简版取去前缀主机）。"""
    host = host_of(url)
    if not host:
        return ""
    parts = host.split(".")
    # 去掉常见国家/双段后缀下的前缀主体：news.xxx.gov.cn → xxx.gov.cn
    if len(parts) >= 3 and _HOST_SUFFIX_RE.search(".".join(parts[-2:])):
        core = ".".join(parts[-3:]) if parts[-1] in ("cn", "com", "net", "org", "gov", "edu") and len(parts) >= 3 else ".".join(parts[-2:])
        return core
    return host


def _norm_text(value: str) -> str:
    return re.sub(r"\s+", "", re.sub(r"[^\w\u4e00-\u9fff]+", "", value or "")).lower()


def content_fingerprint(title: str, snippet: str) -> str:
    """与 research_ledger 同思路：规范化文本哈希（标题为主，摘要增强）。"""
    norm = f"{_norm_text(title)}|{_norm_text(snippet)[:120]}"
    if not norm.strip("|"):
        return ""
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


def fill_dedupe_fields(items: list[CollectedItem]) -> list[CollectedItem]:
    """为每条结果补齐去重三元组。"""
    for item in items:
        item.canonical_url = canonicalize_url(item.url)
        item.independence_group = _default_independence_group(item.url)
        item.content_fingerprint = content_fingerprint(item.title, item.snippet)
    return items


def dedupe_items(items: list[CollectedItem]) -> list[CollectedItem]:
    """跨渠道去重：canonical_url 相同 或 content_fingerprint 相同 → 判重保留首条。"""
    fill_dedupe_fields(items)
    seen_url: dict[str, str] = {}
    seen_fp: dict[str, str] = {}
    for item in items:
        key = item.canonical_url or item.url
        dup_key = ""
        if key and key in seen_url:
            dup_key = seen_url[key]
        elif item.content_fingerprint and item.content_fingerprint in seen_fp:
            dup_key = seen_fp[item.content_fingerprint]
        if dup_key:
            item.duplicate_of = dup_key
            continue
        if key:
            seen_url[key] = item.canonical_url or key
        if item.content_fingerprint:
            seen_fp[item.content_fingerprint] = item.canonical_url or key
    return items


COLLECT_KINDS = ("websearch", "rss", "govdoc", "hotlist")


def collect_kinds() -> tuple[str, ...]:
    """当前支持的 L1 采集渠道（L2 社交适配器未来追加，默认不启用）。"""
    return COLLECT_KINDS
