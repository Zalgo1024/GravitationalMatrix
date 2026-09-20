"""多平台采集器（F1/F2 · 第一阶段报告工具增强 第 1–2 周切片）。

设计边界（见 docs/往思通舆情方面的迭代 (1).md；舆情侧的全局采集见
docs/往思通舆情方面的迭代 (2).md）：
- L1 来源默认开放：websearch / rss / govdoc / hotlist（全部零 Key 或配置驱动）；
- L2 社交平台（微博/抖音等）不在此实现：合规要求外部进程 + 用户自担许可（MediaCrawler
  许可为研究/非商用），未来以适配器接入，默认 OFF；
- 所有采集器只返回「公开可检索的标题/摘要/链接」，不绕过登录、不抓私域内容；
- 去重三元组（content_fingerprint / canonical_url / independence_group）与
  research_ledger 的口径保持一致，采集结果入库 Material 后可被 F15 数据表直接复用。
"""
from app.connectors.base import CollectedItem, collect_kinds, dedupe_items

__all__ = ["CollectedItem", "collect_kinds", "dedupe_items"]
