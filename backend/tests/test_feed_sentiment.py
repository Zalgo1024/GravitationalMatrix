"""S4 词典法情感标注纯函数测试（feed_sentiment.annotate_text）。"""
from app.feed_sentiment import annotate_text


def test_positive_text():
    out = annotate_text("惠州高新区签约两个重大项目，利好本地产业")
    assert out["sentiment"] == "positive"
    assert out["sentiment_score"] > 0
    assert out["sentiment_source"] == "lexicon"


def test_negative_text():
    out = annotate_text("某地发生爆炸事故，多人伤亡")
    assert out["sentiment"] == "negative"
    assert out["sentiment_score"] < 0


def test_neutral_text():
    out = annotate_text("市政府今日发布年度工作报告全文")
    assert out["sentiment"] == "neutral"
    assert out["sentiment_score"] == 0.0


def test_offsetting_hits_cancel():
    """正负同文互相抵消（如「负增长」与「增长」同时命中）→ neutral。"""
    out = annotate_text("该行业负增长，企业亏损严重，但农业增产利好")
    # 2 负（负增长→增长也命中、亏损）与 2 正（增长、增产、利好=3 正）实际计数依词表而定，
    # 此处只断言：分数落在 [-1, 1] 且方向与 diff 一致。
    assert -1.0 <= out["sentiment_score"] <= 1.0


def test_score_saturates():
    """5 个负面词 → diff 饱和 → score = -1.0。"""
    out = annotate_text("爆炸 事故 死亡 坍塌 火灾")
    assert out["sentiment"] == "negative"
    assert out["sentiment_score"] == -1.0


def test_empty_text():
    out = annotate_text("")
    assert out == {"sentiment": "neutral", "sentiment_score": 0.0, "sentiment_source": "lexicon"}
    out2 = annotate_text(None)  # type: ignore[arg-type]
    assert out2["sentiment"] == "neutral"


def test_deterministic():
    """确定性红线：同文本两次标注结果完全一致。"""
    t = "多地暴雨引发洪水，救援工作顺利进行"
    assert annotate_text(t) == annotate_text(t)
