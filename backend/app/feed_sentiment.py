"""S4 情感标注：中文词典法最小实现（方案 (1) S4 第一阶段）。

设计口径：
- 纯确定性规则，零 LLM 调用、零网络依赖——与引擎「确定性优先」风格一致；
- 正负词表为**最小种子集**（中文舆情高频词），可持续补充；后续若接
  model/llm 重标，只需替换 sentiment_source 并回填三字段，接口不变；
- 打分：diff = 正词命中数 − 负词命中数，score = clip(diff / 3, −1, 1)
  （3 词差即饱和，避免长文词频堆出极端分）；diff=0 → neutral；
- 边界声明：词典法对反讽、否定前缀（「不容乐观」）、语境反转
  （「失业率上涨」）无能为力，score 只供排序/徽标等辅助展示，
  **不得**作为严肃舆情结论的依据（与「地域不编造」同级红线）。
"""
from __future__ import annotations

# 最小种子词表：按词收录（子串匹配，含该词的更长词会同时命中，如「增长」命中「负增长」——
# 负面表里的「负增长」与正面表里的「增长」同文命中时 diff 互相抵消，属可接受的保守行为）
_POSITIVE_WORDS: tuple[str, ...] = (
    "增长", "增产", "回升", "上涨", "突破", "创新", "成功", "达成", "签约",
    "合作", "获奖", "夺冠", "冠军", "表彰", "嘉奖", "晋级", "复苏", "好转",
    "改善", "优化", "提升", "完善", "落地", "启用", "开通", "通车", "通航",
    "盈利", "创收", "红利", "利好", "扶持", "补贴", "减税", "降费", "惠民",
    "圆满", "顺利", "喜讯", "新高", "首创", "领先", "造福", "安居", "乐业",
)

_NEGATIVE_WORDS: tuple[str, ...] = (
    "事故", "爆炸", "坍塌", "倒塌", "死亡", "伤亡", "遇难", "受伤", "中毒",
    "火灾", "洪水", "地震", "疫情", "暴跌", "崩盘", "亏损", "破产", "倒闭",
    "裁员", "失业", "欠薪", "讨薪", "维权", "投诉", "举报", "造假", "假冒",
    "抄袭", "侵权", "违规", "违法", "处罚", "罚款", "立案", "停产", "停业",
    "召回", "污染", "泄漏", "诈骗", "传销", "腐败", "落马", "被查", "行贿",
    "受贿", "谣言", "争议", "质疑", "抗议", "冲突", "纠纷", "诉讼", "判刑",
    "逮捕", "拘留", "恶性", "悲剧", "自杀", "欺诈", "愤怒", "谴责", "塌方",
    "殉职",
)

_SENTINEL = {"sentiment": "neutral", "sentiment_score": 0.0, "sentiment_source": "lexicon"}


def annotate_text(text: str) -> dict:
    """对文本做词典法情感标注。

    返回 {"sentiment": positive|neutral|negative,
          "sentiment_score": float ∈ [-1, 1],
          "sentiment_source": "lexicon"}。
    空文本/零命中返回 neutral + 0.0（source 仍为 lexicon，表示「经过标注」）。
    """
    body = (text or "").strip()
    if not body:
        return dict(_SENTINEL)
    pos = sum(body.count(w) for w in _POSITIVE_WORDS)
    neg = sum(body.count(w) for w in _NEGATIVE_WORDS)
    diff = pos - neg
    score = max(-1.0, min(1.0, diff / 3.0))
    label = "positive" if diff > 0 else ("negative" if diff < 0 else "neutral")
    return {
        "sentiment": label,
        "sentiment_score": round(score, 4),
        "sentiment_source": "lexicon",
    }
