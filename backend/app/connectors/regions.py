"""省级地区识别（F10 前置轻量版）。

只做省级（34 个省级行政区）别名匹配：从标题/摘要里识别「该来源主要涉及哪个省」。
市级细化与全国码表属于 F10（地区粒度升级）的范围，此处不展开。
region_source 语义：issuer=发文机关、title=标题命中、body=正文命中、unknown=未识别。
"""
from __future__ import annotations

import json
import os
import re

_DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "regions.json")

# (标准名, 简称/别名, 行政区划码前缀 6 位省码)
_PROVINCES: list[tuple[str, str, str]] = [
    ("北京市", "北京", "110000"), ("天津市", "天津", "120000"), ("河北省", "河北", "130000"),
    ("山西省", "山西", "140000"), ("内蒙古自治区", "内蒙古", "150000"), ("辽宁省", "辽宁", "210000"),
    ("吉林省", "吉林", "220000"), ("黑龙江省", "黑龙江", "230000"), ("上海市", "上海", "310000"),
    ("江苏省", "江苏", "320000"), ("浙江省", "浙江", "330000"), ("安徽省", "安徽", "340000"),
    ("福建省", "福建", "350000"), ("江西省", "江西", "360000"), ("山东省", "山东", "370000"),
    ("河南省", "河南", "410000"), ("湖北省", "湖北", "420000"), ("湖南省", "湖南", "430000"),
    ("广东省", "广东", "440000"), ("广西壮族自治区", "广西", "450000"), ("海南省", "海南", "460000"),
    ("重庆市", "重庆", "500000"), ("四川省", "四川", "510000"), ("贵州省", "贵州", "520000"),
    ("云南省", "云南", "530000"), ("西藏自治区", "西藏", "540000"), ("陕西省", "陕西", "610000"),
    ("甘肃省", "甘肃", "620000"), ("青海省", "青海", "630000"), ("宁夏回族自治区", "宁夏", "640000"),
    ("新疆维吾尔自治区", "新疆", "650000"), ("台湾省", "台湾", "710000"),
    ("香港特别行政区", "香港", "810000"), ("澳门特别行政区", "澳门", "820000"),
]

# 发文机关模式：XX省人民政府 / XX省XX厅 / XX市委宣传部 / XX市人大常委会 等
_ISSUER_RE = re.compile(
    r"(?P<name>[\u4e00-\u9fff]{2,8}?(?:省|自治区|市|特别行政区))(?:人民政府|发展和改革委员会|教育厅|公安厅|"
    r"卫生健康委员会|市场监督管理局|生态环境厅|住房和城乡建设厅|交通运输厅|应急管理厅|农业农村厅|"
    r"人大常委会|人民政府办公厅|宣传部|办公厅)"
)


def _alias_map() -> dict[str, tuple[str, str]]:
    """别名 → (标准名, 省码)。注意「吉林」「海南」等既是省名也是市名，省级优先。"""
    mapping: dict[str, tuple[str, str]] = {}
    for full, alias, code in _PROVINCES:
        mapping.setdefault(alias, (full, code))
        mapping.setdefault(full, (full, code))
    return mapping


_ALIAS = _alias_map()

# 广西/新疆/内蒙古/西藏/宁夏 常见双简称
_EXTRA_ALIAS = {
    "广西": ("广西壮族自治区", "450000"),
    "新疆": ("新疆维吾尔自治区", "650000"),
    "内蒙古": ("内蒙古自治区", "150000"),
    "西藏": ("西藏自治区", "540000"),
    "宁夏": ("宁夏回族自治区", "640000"),
}
_ALIAS.update(_EXTRA_ALIAS)


def load_regions() -> dict:
    """读取 regions.json（存在时），供市级扩展与前端码表共用；缺失返回省级最小集。"""
    if os.path.exists(_DATA_PATH):
        try:
            with open(_DATA_PATH, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            pass
    return {
        "provinces": [
            {"code": code, "name": full, "aliases": [alias]}
            for full, alias, code in _PROVINCES
        ]
    }


def recognize_region(text: str) -> dict:
    """从文本识别省级地区。

    返回 {"region_code", "region_name", "region_source"}；未识别时 source=unknown、
    其余为 None。优先级：发文机关模式 > 省名直写（title 场景由调用方传入）。
    """
    body = (text or "").strip()
    if not body:
        return {"region_code": None, "region_name": None, "region_source": "unknown"}
    # 1) 发文机关：抓「XX省人民政府」这类署名，可信度最高
    m = _ISSUER_RE.search(body[:200])
    if m:
        hit = _ALIAS.get(m.group("name"))
        if hit:
            return {"region_code": hit[1], "region_name": hit[0], "region_source": "issuer"}
    # 2) 省名/简称直写（取最早出现的，避免正文罗列多省时误判）
    best: tuple[int, str, str] | None = None
    for alias, (full, code) in _ALIAS.items():
        idx = body.find(alias)
        if idx >= 0 and (best is None or idx < best[0]):
            best = (idx, full, code)
    if best:
        return {"region_code": best[2], "region_name": best[1], "region_source": "title" if len(body) <= 60 else "body"}
    return {"region_code": None, "region_name": None, "region_source": "unknown"}
