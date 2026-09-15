"""
利益关系网络图 — 可视化模块。

从 DIAGRAM JSON 数据生成：
1. 静态 PNG（matplotlib + networkx，嵌入 Word）
2. 交互式 HTML（vis.js，单独文件）

用法:
    from viz_network import generate_diagram
    data = {"viz": "network", "nodes": [...], "edges": [...]}
    generate_diagram(data, "output.png")  # 生成 PNG
    generate_diagram(data, "output.html") # 生成 HTML（自动检测扩展名）
"""

from html import escape
import json
import os
import re
from typing import Optional


# ── 默认样式 ────────────────────────────────────────────────

_NODE_COLORS = {
    "material": "#E74C3C",
    "security": "#F39C12",
    "political": "#2E86C1",
    "identity_culture": "#8E44AD",
    "institutional_future": "#1ABC9C",
    "public": "#27AE60",
    "actor": "#34495E",
    "event": "#E67E22",
}

_EDGE_STYLES = {
    "economic": {"color": "#2ECC71", "dash": False},
    "power": {"color": "#E74C3C", "dash": False},
    "cultural": {"color": "#9B59B6", "dash": "5,5"},
    "legal": {"color": "#3498DB", "dash": "2,4"},
}

_DEFAULT_NODE_COLOR = "#95A5A6"
_DEFAULT_EDGE_COLOR = "#BDC3C7"

# ── 统一视觉令牌（三类图 PNG 共用，保证风格一致） ──
_TITLE_COLOR = "#1B3A5C"       # 标题色（三类图统一）
_NODE_BORDER_W = 3              # 节点描边宽度（三类图统一）
_NODE_FONT_MIN = 12             # 节点字号下限，保证可读、不随长度塌陷
_EDGE_LABEL_SIZE = 11           # 边标签字号（三类图统一）
_TITLE_SIZE = 15                # 标题字号（三类图统一）
_LEGEND_SIZE = 11              # 图例字号（三类图统一）
_OVERLAP_SAFETY = 1.18        # 去重叠安全余量（>1 留白，防标签框相压）


def _detect_output_type(path: str) -> str:
    """根据文件扩展名判断输出类型。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".html", ".htm"):
        return "html"
    return "png"


def generate_diagram(data: dict, output_path: str) -> Optional[str]:
    """生成利益关系图。

    Args:
        data: DIAGRAM JSON 数据，格式:
            {
                "viz": "network",
                "title": "图标题",
                "nodes": [
                    {"id": "A", "label": "名称", "type": "actor"},
                    ...
                ],
                "edges": [
                    {"source": "A", "target": "B", "label": "流向", "type": "economic"},
                    ...
                ]
            }
        output_path: 输出路径（.png 或 .html）。

    Returns:
        成功时返回 output_path，失败时返回 None。
    """
    output_type = _detect_output_type(output_path)

    if output_type == "html":
        return _generate_html(data, output_path)
    else:
        viz = data.get("viz", "network")
        if viz == "geo":
            return _generate_geo_png(data, output_path)
        if viz in ("org", "flow"):
            return _generate_layered_png(data, output_path, viz)
        return _generate_png(data, output_path)


# ── F11 地域分布静态地图（GeoJSON + matplotlib 直接填色，不引 geopandas） ──

# 无数据省份的灰显色；有数据省份按值在浅蓝→深蓝之间取色
_GEO_NO_DATA = "#EFF1F4"
_GEO_COLOR_LOW = (232, 240, 251)
_GEO_COLOR_HIGH = (46, 95, 163)


def _locate_geojson() -> Optional[str]:
    """定位省级 GeoJSON：环境变量优先，其次前端 public 下那份（同仓共用一份底图）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.environ.get("SY_GEO_GEOJSON") or "",
        os.path.join(here, "data", "china.geo.json"),
        os.path.join(here, "frontend", "public", "geo", "china.json"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def _geo_polygons(geometry: dict) -> list[list[tuple[float, float]]]:
    """把 Polygon / MultiPolygon 摊平成一批外环坐标串（内环忽略，填色足够）。"""
    if not isinstance(geometry, dict):
        return []
    kind = geometry.get("type")
    coords = geometry.get("coordinates") or []
    rings: list[list[tuple[float, float]]] = []
    if kind == "Polygon":
        for ring in coords[:1]:
            rings.append([(float(p[0]), float(p[1])) for p in ring if len(p) >= 2])
    elif kind == "MultiPolygon":
        for polygon in coords:
            for ring in polygon[:1]:
                rings.append([(float(p[0]), float(p[1])) for p in ring if len(p) >= 2])
    return [ring for ring in rings if len(ring) > 2]


def _generate_geo_png(data: dict, output_path: str) -> Optional[str]:
    """渲染省级着色地图 PNG（Word 内嵌用）。

    data: {"viz": "geo", "title": ..., "regions": [{region_name, independent_sources, share}...], "coverage": 0~1}
    底图缺失或无地域数据时返回 None，由调用方决定是否插入——不静默造图。
    """
    geojson_path = _locate_geojson()
    if not geojson_path:
        return None
    regions = [r for r in (data.get("regions") or []) if isinstance(r, dict) and r.get("region_name")]
    if not regions:
        return None

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.colors  # noqa: F401  绑定 colors 子模块：color_for / 色阶图例都要用
        import matplotlib.pyplot as plt
        from matplotlib.patches import Polygon as MplPolygon
    except Exception:
        return None

    try:
        with open(geojson_path, "r", encoding="utf-8") as handle:
            geo = json.load(handle)
    except Exception:
        return None
    features = geo.get("features") if isinstance(geo, dict) else None
    if not features:
        return None

    value_by_name = {str(r["region_name"]): float(r.get("independent_sources") or 0) for r in regions}
    max_value = max(value_by_name.values()) if value_by_name else 0.0
    _setup_chinese_font(plt)

    def color_for(name: str) -> tuple[float, float, float]:
        value = value_by_name.get(name)
        if not value or max_value <= 0:
            return matplotlib.colors.to_rgb(_GEO_NO_DATA)
        ratio = min(1.0, value / max_value)
        return tuple(
            (_GEO_COLOR_LOW[i] + (_GEO_COLOR_HIGH[i] - _GEO_COLOR_LOW[i]) * ratio) / 255.0
            for i in range(3)
        )

    fig, ax = plt.subplots(figsize=(10.4, 6.4), dpi=150)
    ax.set_axis_off()
    ax.set_aspect("equal")
    ax.set_position([0.01, 0.09, 0.74, 0.84])
    for feature in features:
        props = feature.get("properties") or {}
        name = str(props.get("name") or "")
        # 无名字的要素是南海诸岛与九段线：主图不画，交给右侧小窗完整呈现
        if not name:
            continue
        rings = _geo_polygons(feature.get("geometry") or {})
        for ring in rings:
            ax.add_patch(MplPolygon(ring, closed=True, facecolor=color_for(name), edgecolor="#FFFFFF", linewidth=0.5, zorder=2))
        # 只标注有数据的省，避免全国 34 个名字糊成一片
        if name in value_by_name and rings:
            biggest = max(rings, key=len)
            xs = [p[0] for p in biggest]
            ys = [p[1] for p in biggest]
            ax.text(
                sum(xs) / len(xs), sum(ys) / len(ys), name.replace("省", "").replace("市", "").replace("自治区", "").replace("特别行政区", ""),
                fontsize=6.5, ha="center", va="center", color="#123A63", zorder=4,
            )

    ax.set_xlim(73, 136)
    ax.set_ylim(17, 54)

    # 南海诸岛小窗：同一份底图，视口压到南海范围（九段线按界线画，必须看得见）
    # 独立小窗（不做成主图内嵌，避免与台湾/海南叠在一起看不清）
    sea = fig.add_axes([0.765, 0.20, 0.215, 0.52])
    sea.set_aspect("equal")
    sea.patch.set_facecolor("#F7FAFD")  # 浅海域底色，与主图大陆区分
    sea.patch.set_alpha(1.0)
    for feature in features:
        props = feature.get("properties") or {}
        name = str(props.get("name") or "")
        boundary = not name
        for ring in _geo_polygons(feature.get("geometry") or {}):
            sea.add_patch(MplPolygon(
                ring, closed=True,
                facecolor="none" if boundary else color_for(name),
                # 九段线在小窗里是主角，用深蓝粗线，缩印后仍看得见
                edgecolor="#2E5FA3" if boundary else "#FFFFFF",
                linewidth=1.1 if boundary else 0.3,
                zorder=4 if boundary else 2,
            ))
    sea.set_xlim(105, 123)
    sea.set_ylim(2, 24)
    for spine in sea.spines.values():
        spine.set_color("#9FB2C6")
        spine.set_linewidth(0.8)
    sea.set_xticks([])
    sea.set_yticks([])
    sea.set_title("南海诸岛", fontsize=8, color="#3E4E62", pad=4)

    # 色阶图例：0 → 最大值
    gradient = fig.add_axes([0.12, 0.07, 0.34, 0.022])
    gradient.imshow(
        [[i / 100 for i in range(101)]],
        aspect="auto",
        cmap=matplotlib.colors.LinearSegmentedColormap.from_list(
            "geo", [tuple(c / 255 for c in _GEO_COLOR_LOW), tuple(c / 255 for c in _GEO_COLOR_HIGH)]
        ),
    )
    gradient.set_xticks([])
    gradient.set_yticks([])
    for spine in gradient.spines.values():
        spine.set_color("#C9D2DC")
        spine.set_linewidth(0.6)
    fig.text(0.115, 0.045, "少", fontsize=7, color="#5A6B80")
    fig.text(0.455, 0.045, f"多（最高 {int(max_value)} 个独立源）", fontsize=7, color="#5A6B80")
    fig.text(0.12, 0.098, "灰显 = 本次没有识别到该地区来源", fontsize=7, color="#5A6B80")

    coverage = data.get("coverage")
    title = str(data.get("title") or "来源地域分布")
    subtitle = ""
    if isinstance(coverage, (int, float)) and coverage < 0.5:
        subtitle = f"注：仅 {round(float(coverage) * 100)}% 的独立来源可定位到地区，下图只反映可定位部分"
    ax.set_title(title, fontsize=_TITLE_SIZE, fontweight="bold", color=_TITLE_COLOR, pad=14)
    if subtitle:
        fig.text(0.5, 0.925, subtitle, fontsize=8, ha="center", color="#8A6D1F")
    fig.text(
        0.5, 0.015,
        "示意图：底图为开源行政区划数据，非审图号标准地图，正式出版请使用自然资源部标准地图",
        fontsize=6.5, ha="center", color="#8A94A0",
    )

    try:
        fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white")
    except Exception:
        return None
    finally:
        plt.close(fig)
    return output_path


# ── 静态 PNG（matplotlib + networkx） ──────────────────────

def _estimate_node_radius(label: str) -> float:
    """估算节点标签框的近似半径（数据单位），用于去重叠。

    标签可能含换行（如「方星海\\n公开政策角色」），按行数算框高、
    按最长行算框宽，避免两行框被低估而压在一起。
    """
    lines = label.split("\n")
    max_len = max((len(l) for l in lines), default=1)
    n_lines = len(lines)
    if max_len <= 6:
        hw = 0.55
    elif max_len <= 12:
        hw = 0.78
    else:
        hw = 1.0
    hh = 0.28 * n_lines
    return 0.55 * (hw + hh) + 0.14  # 平均半径 + 余量


def _resolve_overlaps(pos: dict, node_labels: dict, iterations: int = 80) -> dict:
    """贪心推开重叠的节点框，保证标签框互不压住（圆形近似）。

    先按 spring 铺开，再对每对中心距小于两框半径之和的节点沿连线方向
    各推一半，多次迭代直至无重叠或达上限。O(n^2·iters)，n<=30 无压力。
    """
    import math
    ids = list(pos.keys())
    radius = {i: _estimate_node_radius(node_labels.get(i, i)) for i in ids}
    for _ in range(iterations):
        moved = False
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                dx = pos[a][0] - pos[b][0]
                dy = pos[a][1] - pos[b][1]
                d = math.hypot(dx, dy)
                need = (radius[a] + radius[b]) * _OVERLAP_SAFETY
                if d < need:
                    if d < 1e-6:
                        dx, dy = 0.013, 0.017
                        d = math.hypot(dx, dy)
                    push = (need - d) / 2.0 + 1e-3
                    ux, uy = dx / d, dy / d
                    pos[a] = (pos[a][0] + ux * push, pos[a][1] + uy * push)
                    pos[b] = (pos[b][0] - ux * push, pos[b][1] - uy * push)
                    moved = True
        if not moved:
            break
    return pos


def _generate_png(data: dict, output_path: str) -> Optional[str]:
    """使用 matplotlib + networkx 生成静态 PNG。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import networkx as nx
        from matplotlib.patches import FancyBboxPatch
    except ImportError:
        return None

    # 配置中文字体
    _setup_chinese_font(plt)

    nodes = data.get("nodes", [])
    edges = data.get("edges", [])

    if not nodes:
        return None

    G = nx.DiGraph()
    node_labels = {}
    node_colors = []

    for n in nodes:
        nid = n["id"]
        label = n.get("label", nid)
        ntype = n.get("type", "actor")
        G.add_node(nid)
        node_labels[nid] = label
        opacity = n.get("_opacity", 1.0)
        base_color = _NODE_COLORS.get(ntype, _DEFAULT_NODE_COLOR)
        if opacity < 1.0:
            from matplotlib.colors import to_rgba, to_hex
            rgba = list(to_rgba(base_color))
            rgba[3] = opacity
            node_colors.append(to_hex(rgba, keep_alpha=False))
        else:
            node_colors.append(base_color)

    for e in edges:
        G.add_edge(e["source"], e["target"], label=e.get("label", ""))

    node_count = len(nodes)
    max_label_len = max((len(n.get("label", n["id"])) for n in nodes), default=10)
    # k 放大：节点随数量增多也保持标签框间距，避免挤成一团
    scale = 1.15 + 2.4 / (node_count ** 0.5)
    fig_w = max(5.5, min(14.0, 2.4 * node_count ** 0.6))
    fig_h = max(4.5, min(10.0, 2.0 * node_count ** 0.6))
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    import math
    # 布局：spring 先铺开，再贪心去重叠保证标签框互不压住
    pos = nx.spring_layout(G, k=scale, iterations=300, seed=42)
    pos = _resolve_overlaps(pos, node_labels, iterations=150)

    # ── 画边（先画边，再画节点，确保节点在顶层） ──
    edge_colors = []
    edge_widths = []
    for e in G.edges():
        etype = None
        for edge_data in edges:
            if edge_data["source"] == e[0] and edge_data["target"] == e[1]:
                etype = edge_data.get("type", "")
                break
        style = _EDGE_STYLES.get(etype, {})
        edge_colors.append(style.get("color", _DEFAULT_EDGE_COLOR))
        # 边宽根据节点数自适应
        edge_widths.append(max(2.0, 4.0 - node_count * 0.15))

    # 用 FancyArrowPatch 画边以获得更好的箭头效果
    seen_edges = set()
    for idx, e in enumerate(G.edges()):
        if (e[1], e[0]) in seen_edges:
            rad = 0.3  # 双向边用更大弧度
        else:
            rad = 0.15
        seen_edges.add(e)

        nx.draw_networkx_edges(
            G, pos, ax=ax,
            edgelist=[e],
            edge_color=[edge_colors[idx]],
            width=edge_widths[idx],
            arrows=True,
            arrowsize=20,
            arrowstyle="->,head_length=0.5,head_width=0.5",
            connectionstyle=f"arc3,rad={rad}",
            min_source_margin=14,
            min_target_margin=14,
        )

    # ── 边标签（带白色背景框） ──
    edge_labels = {}
    for e in G.edges():
        for edge_data in edges:
            if edge_data["source"] == e[0] and edge_data["target"] == e[1]:
                lbl = edge_data.get("label", "")
                if lbl:
                    edge_labels[e] = lbl
                break
    if edge_labels:
        for (u, v), label in edge_labels.items():
            x = (pos[u][0] + pos[v][0]) / 2
            y = (pos[u][1] + pos[v][1]) / 2
            dx = pos[v][0] - pos[u][0]
            dy = pos[v][1] - pos[u][1]
            d = math.hypot(dx, dy) or 1.0
            ox, oy = -dy / d, dx / d  # 垂直连线方向偏移，避免标签压在连线上
            x += ox * 0.18
            y += oy * 0.18
            ax.text(
                x, y, label,
                fontsize=11, fontfamily="sans-serif",
                fontweight="bold",
                ha="center", va="center",
                color="#333333",
                bbox=dict(
                    boxstyle="round,pad=0.3",
                    facecolor="white",
                    edgecolor="#CCCCCC",
                    linewidth=0.5,
                    alpha=0.92,
                ),
            )

    # ── 画节点（带圆角矩形背景，文字在里面） ──
    for nid, (x, y) in pos.items():
        label = node_labels.get(nid, nid)
        color = _get_node_color(nid, nodes)
        # 放大字号：长标签也保持可读，不随长度塌陷（下限 _NODE_FONT_MIN）
        lbl_len = len(label)
        fs = 15 if lbl_len <= 8 else (13 if lbl_len <= 14 else _NODE_FONT_MIN)
        lbl_pad = 0.34 if lbl_len <= 8 else 0.44
        # 绘制圆角矩形节点
        ax.text(
            x, y, label,
            fontsize=fs, fontfamily="sans-serif",
            fontweight="bold",
            ha="center", va="center",
            color="white",
            bbox=dict(
                boxstyle=f"round,pad={lbl_pad}",
                facecolor=color,
                edgecolor="white",
                linewidth=3,
            ),
        )

    # ── 图例（边类型说明） ──
    legend_elements = []
    for etype_id, etype_style in _EDGE_STYLES.items():
        etype_name = {"economic": "经济", "power": "权力", "cultural": "文化", "legal": "法律"}
        label = etype_name.get(etype_id, etype_id)
        legend_elements.append(plt.Line2D(
            [0], [0], color=etype_style["color"],
            linewidth=2, label=label,
        ))
    if legend_elements:
        ax.legend(
            handles=legend_elements,
            loc="lower center",
            bbox_to_anchor=(0.5, -0.06),
            ncol=len(legend_elements),
            fontsize=_LEGEND_SIZE,
            frameon=True,
            facecolor="white",
            edgecolor="#DDDDDD",
        )

    # ── 标题 ──
    title = data.get("title", "")
    if title:
        ax.set_title(
            title, fontsize=_TITLE_SIZE, fontweight="bold", pad=25,
            color=_TITLE_COLOR,
        )

    ax.axis("off")
    plt.subplots_adjust(bottom=0.12)
    fig.savefig(output_path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path


def _flow_layout_plan(n: int) -> tuple[bool, int]:
    """flow 图布局计划：节点多时改用蛇形折返，避免压成一条横带。

    Returns:
        (use_snake, per_row)
        - 节点 <= 5：保持原横向(LR)，per_row 无效
        - 6~9 节点：蛇形，每行 4 个
        - >=10 节点：蛇形，每行 5 个
    """
    if n <= 5:
        return False, 0
    per_row = 4 if n <= 9 else 5
    return True, per_row


def _snake_positions(G, node_labels: dict, per_row: int) -> dict:
    """蛇形（地铁线式）布局：第一行从左到右，第二行从右到左折返，依次交错。

    沿 BFS 访问顺序把节点依次铺进每行，偶数行正序、奇数行反序，
    行与行之间用竖直间隔拉开。适用于流程图的长链路，比纯横向省空间、可读。
    """
    import collections
    roots = [n for n in G.nodes() if G.in_degree(n) == 0]
    if not roots:
        roots = [next(iter(G.nodes()))] if G.nodes() else []
    ordered = []
    visited = set(roots)
    q = collections.deque(roots)
    while q:
        u = q.popleft()
        ordered.append(u)
        for v in G.successors(u):
            if v not in visited:
                visited.add(v)
                q.append(v)
    for n in G.nodes():  # 兜底：环/孤立节点补到队尾
        if n not in visited:
            ordered.append(n)

    max_label_len = max((len(node_labels.get(n, n)) for n in G.nodes()), default=4)
    unit = max_label_len * 0.16 + 0.75
    x_gap = unit + 0.6
    y_gap = unit + 1.4  # 蛇形行距比列距略大，折返更清晰

    pos = {}
    for idx, nid in enumerate(ordered):
        row = idx // per_row
        within = idx % per_row
        x = within if row % 2 == 0 else (per_row - 1) - within
        y = -row
        pos[nid] = (x * x_gap, y * y_gap)
    return pos


# ── 层级图（组织架构图 / 流程图） ─────────────────────────

def _box_dims(label: str) -> tuple[float, float]:
    """根据标签长度估算节点框宽高（数据坐标）。"""
    w = max(2.0, len(label) * 0.34 + 0.7)
    h = 1.35
    return w, h


def _layered_positions(G, node_labels: dict, direction: str = "UD") -> dict:
    """层级布局：org=自上而下树形(UD)，flow=自左向右分层(LR)。

    x_gap/y_gap 采用**对称均衡**间距（仅由最大标签长度推导），
    不再强行压成固定宽高比——这样宽流程图自然变宽、高架构图自然变高，
    后续由 figsize 跟随内容真实比例，避免拉伸导致的浪费/紧凑。
    """
    import collections
    roots = [n for n in G.nodes() if G.in_degree(n) == 0]
    if not roots:
        roots = [next(iter(G.nodes()))] if G.nodes() else []

    level: dict = {}
    q = collections.deque(roots)
    for r in roots:
        level[r] = 0
    visited = set(roots)
    while q:
        u = q.popleft()
        for v in G.successors(u):
            if v not in visited:
                level[v] = level[u] + 1
                visited.add(v)
                q.append(v)
    max_lvl = max(level.values()) if level else 0
    for n in G.nodes():
        if n not in level:
            level[n] = max_lvl + 1

    levels: dict = collections.defaultdict(list)
    for n, lv in level.items():
        levels[lv].append(n)

    # 对称均衡间距：x/y 一致，仅由最长标签推导，保证节点框不重叠且密度均匀
    max_label_len = max((len(node_labels.get(n, n)) for n in G.nodes()), default=4)
    unit = max_label_len * 0.16 + 0.75
    x_gap = unit + 0.6
    y_gap = unit + 0.6

    pos = {}
    for lv, nodes_in_lvl in levels.items():
        count = len(nodes_in_lvl)
        for i, n in enumerate(nodes_in_lvl):
            if direction == "UD":
                x = (i - (count - 1) / 2.0) * x_gap
                y = -lv * y_gap
            else:
                x = lv * x_gap
                y = (i - (count - 1) / 2.0) * y_gap
            pos[n] = (x, y)
    return pos


def _generate_layered_png(data: dict, output_path: str, viz: str) -> Optional[str]:
    """生成组织架构图(org)或流程图(flow)的静态 PNG。

    org：自上而下层级树，正交(L型)连接线。
    flow：自左向右分层流程，正交(L型)连接线。
    节点用 text+bbox 自适应文字大小，六类利益配色，边沿用四类型样式。
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import networkx as nx
        from matplotlib.patches import FancyArrowPatch
    except ImportError:
        return None

    _setup_chinese_font(plt)

    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    if not nodes:
        return None

    G = nx.DiGraph()
    node_labels = {}
    for n in nodes:
        G.add_node(n["id"])
        node_labels[n["id"]] = n.get("label", n["id"])
    for e in edges:
        G.add_edge(e["source"], e["target"], label=e.get("label", ""))

    if viz == "org":
        direction = "UD"
        pos_raw = _layered_positions(G, node_labels, "UD")
    else:  # flow：节点多则蛇形折返
        use_snake, per_row = _flow_layout_plan(len(nodes))
        if use_snake:
            direction = "SNAKE"
            pos_raw = _snake_positions(G, node_labels, per_row)
        else:
            direction = "LR"
            pos_raw = _layered_positions(G, node_labels, "LR")

    # ── 画布宽高比跟随内容真实比例（夹紧），避免宽图压扁 / 高图拉伸 ──
    raw_xs = [p[0] for p in pos_raw.values()]
    raw_ys = [p[1] for p in pos_raw.values()]
    rmin_x, rmax_x = min(raw_xs), max(raw_xs)
    rmin_y, rmax_y = min(raw_ys), max(raw_ys)
    rspan_x = max(rmax_x - rmin_x, 0.01)
    rspan_y = max(rmax_y - rmin_y, 0.01)

    aspect = rspan_x / rspan_y if rspan_y > 0 else 1.3
    aspect = max(0.5, min(2.2, aspect))
    if aspect >= 1:
        CW = 9.0 * aspect   # 宽图：宽度随比例放大
        CH = 9.0
    else:
        CW = 9.0
        CH = 9.0 / aspect   # 高图：高度随比例放大
    CW = max(4.5, min(16.0, CW))
    CH = max(4.0, min(11.0, CH))

    scale = min(CW / rspan_x, CH / rspan_y) * 0.86  # 留 14% 边距
    offset_x = (CW - rspan_x * scale) / 2
    offset_y = (CH - rspan_y * scale) / 2
    pos = {
        nid: ((x - rmin_x) * scale + offset_x, (y - rmin_y) * scale + offset_y)
        for nid, (x, y) in pos_raw.items()
    }

    fig_w = max(4.5, min(15.0, CW * 0.95))
    fig_h = max(4.0, min(10.5, CH * 0.95))
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.set_xlim(0, CW)
    ax.set_ylim(0, CH)

    # 连接线缩短量（从节点中心到框边的近似距离）
    all_ys = [p[1] for p in pos.values()]
    all_xs = [p[0] for p in pos.values()]
    margin_y = abs(max(all_ys) - min(all_ys)) * 0.06 + 0.3 if len(all_ys) > 1 else 0.4
    margin_x = abs(max(all_xs) - min(all_xs)) * 0.08 + 0.3 if len(all_xs) > 1 else 0.4

    edge_color_map = {}
    for e in edges:
        style = _EDGE_STYLES.get(e.get("type", ""), {})
        edge_color_map[(e["source"], e["target"])] = style.get("color", _DEFAULT_EDGE_COLOR)

    # ── 画边：正交(L型)折线 + 箭头 ──
    for (u, v) in G.edges():
        color = edge_color_map.get((u, v), _DEFAULT_EDGE_COLOR)
        x1, y1 = pos[u]
        x2, y2 = pos[v]
        lbl = G[u][v].get("label", "")

        if direction == "UD":
            # 判断方向：u 在上(y大)还是下(y小)
            if y1 >= y2:
                sy, ty = y1 - margin_y, y2 + margin_y
            else:
                sy, ty = y1 + margin_y, y2 - margin_y
            mid_y = (sy + ty) / 2
            # 垂直段 + 水平段
            ax.plot([x1, x1], [sy, mid_y], color=color, linewidth=2, zorder=1, solid_capstyle="round")
            ax.plot([x1, x2], [mid_y, mid_y], color=color, linewidth=2, zorder=1, solid_capstyle="round")
            # 最后垂直段带箭头
            ax.add_patch(FancyArrowPatch(
                (x2, mid_y), (x2, ty), arrowstyle="-|>", mutation_scale=15,
                color=color, linewidth=2, zorder=1))
            if lbl:
                ax.text((x1 + x2) / 2, mid_y, lbl, fontsize=_EDGE_LABEL_SIZE, fontfamily="sans-serif",
                        fontweight="bold", ha="center", va="center", color="#444444", zorder=3,
                        bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                                  edgecolor="#DDDDDD", linewidth=0.5, alpha=0.95))
        else:  # LR / SNAKE：通用肘形连接（横竖均可，适配折返）
            if x1 <= x2:
                sx, tx = x1 + margin_x, x2 - margin_x
            else:
                sx, tx = x1 - margin_x, x2 + margin_x
            if y1 >= y2:
                sy, ty = y1 - margin_y, y2 + margin_y
            else:
                sy, ty = y1 + margin_y, y2 - margin_y
            if abs(x2 - x1) >= abs(y2 - y1):
                mid_x = (sx + tx) / 2
                ax.plot([sx, mid_x], [y1, y1], color=color, linewidth=2, zorder=1, solid_capstyle="round")
                ax.plot([mid_x, mid_x], [y1, y2], color=color, linewidth=2, zorder=1, solid_capstyle="round")
                ax.add_patch(FancyArrowPatch(
                    (mid_x, y2), (tx, y2), arrowstyle="-|>", mutation_scale=15,
                    color=color, linewidth=2, zorder=1))
                if lbl:
                    ax.text(mid_x, (y1 + y2) / 2, lbl, fontsize=_EDGE_LABEL_SIZE, fontfamily="sans-serif",
                            fontweight="bold", ha="center", va="center", color="#444444", zorder=3,
                            bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                                      edgecolor="#DDDDDD", linewidth=0.5, alpha=0.95))
            else:
                mid_y = (sy + ty) / 2
                ax.plot([x1, x1], [sy, mid_y], color=color, linewidth=2, zorder=1, solid_capstyle="round")
                ax.plot([x1, x2], [mid_y, mid_y], color=color, linewidth=2, zorder=1, solid_capstyle="round")
                ax.add_patch(FancyArrowPatch(
                    (x2, mid_y), (x2, ty), arrowstyle="-|>", mutation_scale=15,
                    color=color, linewidth=2, zorder=1))
                if lbl:
                    ax.text((x1 + x2) / 2, mid_y, lbl, fontsize=_EDGE_LABEL_SIZE, fontfamily="sans-serif",
                            fontweight="bold", ha="center", va="center", color="#444444", zorder=3,
                            bbox=dict(boxstyle="round,pad=0.2", facecolor="white",
                                      edgecolor="#DDDDDD", linewidth=0.5, alpha=0.95))

    # ── 画节点（text + bbox，框自适应文字） ──
    for nid, (x, y) in pos.items():
        label = node_labels[nid]
        color = _get_node_color(nid, nodes)
        lbl_len = len(label)
        fs = 14 if lbl_len <= 8 else (13 if lbl_len <= 14 else _NODE_FONT_MIN)
        ax.text(x, y, label, fontsize=fs, fontfamily="sans-serif",
                fontweight="bold", ha="center", va="center", color="white", zorder=5,
                bbox=dict(boxstyle="round,pad=0.35", facecolor=color,
                          edgecolor="white", linewidth=_NODE_BORDER_W))

    # ── 图例（边类型） ──
    legend_elements = []
    etype_names = {"economic": "经济/资金", "power": "权力/控制", "cultural": "文化", "legal": "法律"}
    for etype_id, etype_style in _EDGE_STYLES.items():
        label = etype_names.get(etype_id, etype_id)
        legend_elements.append(plt.Line2D([0], [0], color=etype_style["color"], linewidth=2, label=label))
    if legend_elements:
        ax.legend(handles=legend_elements, loc="lower center",
                  bbox_to_anchor=(0.5, -0.05), ncol=len(legend_elements),
                  fontsize=_LEGEND_SIZE, frameon=True, facecolor="white", edgecolor="#DDDDDD")

    title = data.get("title", "")
    if title:
        ax.set_title(title, fontsize=_TITLE_SIZE, fontweight="bold", pad=12, color=_TITLE_COLOR)

    ax.axis("off")
    plt.subplots_adjust(bottom=0.08, top=0.9, left=0.02, right=0.98)
    fig.savefig(output_path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path


def _get_node_color(node_id: str, nodes: list) -> str:
    """根据节点 id 查找节点颜色。"""
    for n in nodes:
        if n["id"] == node_id:
            return _NODE_COLORS.get(n.get("type", ""), _DEFAULT_NODE_COLOR)
    return _DEFAULT_NODE_COLOR


def _setup_chinese_font(plt) -> None:
    """配置 matplotlib 中文字体（防止方框乱码）。"""
    import matplotlib.font_manager as fm
    # 尝试常见中文字体
    candidates = [
        "SimHei", "Microsoft YaHei", "WenQuanYi Micro Hei",
        "Noto Sans CJK SC", "Source Han Sans SC",
        "STHeiti", "PingFang SC", "Apple LiGothic",
    ]
    for name in candidates:
        try:
            fm.findfont(name, fallback_to_default=False)
            plt.rcParams["font.sans-serif"] = [name] + plt.rcParams.get("font.sans-serif", [])
            plt.rcParams["axes.unicode_minus"] = False
            return
        except Exception:
            continue
    # 回退：使用默认字体
    plt.rcParams["axes.unicode_minus"] = False


# ── 交互式 HTML（vis.js） ──────────────────────────────────

# ── 交互式 HTML 模板（vis.js 库内联，离线可用） ──────────────
# 用占位符 @@TITLE@@ / @@LIB@@ / @@NODES@@ / @@EDGES@@ / @@OPTIONS@@ 注入，
# 避免 .format 对 CSS/JS 花括号的转义灾难。

_HTML_VIS_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>@@TITLE@@</title>
<style>
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; height: 100%; }
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; background: #fafafa; color: #1A1A2E; }
  .title { font-size: 18px; font-weight: 700; color: #1B3A5C; margin: 0; padding: 14px 16px 8px; text-align: center; }
  .toolbar { display: flex; gap: 8px; justify-content: center; align-items: center; padding: 0 12px 8px; flex-wrap: wrap; }
  .toolbar button { font-size: 13px; padding: 6px 12px; border: 1px solid #D5DAE0; background: #fff; color: #1B3A5C; border-radius: 7px; cursor: pointer; font-family: inherit; }
  .toolbar button:hover { background: #EEF3F8; }
  .toolbar .sep { width: 1px; height: 20px; background: #E0E5EA; }
  .toolbar .tip { font-size: 12px; color: #888; }
  .wrap { height: calc(100vh - 140px); position: relative; }
  #net { width: 100%; height: 100%; background: #fff; border-top: 1px solid #E5E7EB; }
  .legendbar { display: flex; flex-wrap: wrap; gap: 6px 18px; justify-content: center; align-items: center; padding: 7px 12px; background: #fff; border-top: 1px solid #E5E7EB; font-size: 12px; color: #555; }
  .legendbar .row { display: flex; align-items: center; gap: 6px; }
  .legendbar .sw { width: 18px; height: 3px; border-radius: 2px; display: inline-block; }
  .hint { position: absolute; right: 16px; top: 12px; font-size: 12px; color: #888; background: rgba(255,255,255,0.85); padding: 4px 8px; border-radius: 6px; }
</style>
</head>
<body>
  <h1 class="title">@@TITLE@@</h1>
  <div class="toolbar">
    <button id="btnFit">适应屏幕</button>
    <button id="btnRelayout">重新布局</button>
    <button id="btnPhysics">物理布局: <span id="physState">关</span></button>
    <span class="sep"></span>
    <button id="btnDownload">下载图片</button>
    <span class="sep"></span>
    <span class="tip">拖拽节点 · 滚轮缩放 · 拖动空白平移</span>
  </div>
  <div class="legendbar">
    <div class="row"><span class="sw" style="background:#2ECC71"></span>经济 / 资金</div>
    <div class="row"><span class="sw" style="background:#E74C3C"></span>权力 / 控制</div>
    <div class="row"><span class="sw" style="background:#9B59B6"></span>文化</div>
    <div class="row"><span class="sw" style="background:#3498DB"></span>法律</div>
  </div>
  <div class="wrap">
    <div id="net"></div>
    <div class="hint">拖拽节点调整位置 · 滚轮缩放</div>
  </div>
@@LIB@@
<script type="text/javascript">
  var nodes = new vis.DataSet(@@NODES@@);
  var edges = new vis.DataSet(@@EDGES@@);
  var container = document.getElementById('net');
  var data = { nodes: nodes, edges: edges };
  var options = @@OPTIONS@@;
  var network = new vis.Network(container, data, options);

  // 统一交互控制：三类图共用同一套逻辑，确保体验一致
  var viz = "@@VIZ@@";
  var fixedPos = @@FIXEDPOS@@;
  var physicsOn = (@@PHYSDEFAULT@@ === "true");

  function doFit() { try { network.fit({ animation: { duration: 300, easingFunction: 'easeInOutQuad' } }); } catch (e) {} }
  function doRelayout() {
    if (viz === 'network') {
      network.setOptions({ physics: { enabled: true } });
      network.stabilize();
      setTimeout(doFit, 450);
    } else {
      for (var id in fixedPos) {
        try { network.moveNode(id, fixedPos[id].x, fixedPos[id].y); } catch (e) {}
      }
      doFit();
    }
  }
  function togglePhysics() {
    physicsOn = !physicsOn;
    if (viz !== 'network' && physicsOn) {
      network.setOptions({
        physics: {
          enabled: true,
          solver: 'forceAtlas2Based',
          stabilization: { iterations: 200 },
          forceAtlas2Based: { gravitationalConstant: -85, centralGravity: 0.012, springLength: 210, springConstant: 0.035 }
        }
      });
    } else {
      network.setOptions({ physics: { enabled: physicsOn } });
    }
    document.getElementById('physState').textContent = physicsOn ? '开' : '关';
  }

  // 导出当前网络画布为 PNG（白底，保留当前缩放/平移视角）
  function downloadPNG() {
    try {
      var src = network.canvas.frame.canvas;
      if (!src || !src.width) { alert('画布尚未就绪，请稍后再试'); return; }
      var tmp = document.createElement('canvas');
      tmp.width = src.width;
      tmp.height = src.height;
      var ctx = tmp.getContext('2d');
      ctx.fillStyle = '#FFFFFF';
      ctx.fillRect(0, 0, tmp.width, tmp.height);
      ctx.drawImage(src, 0, 0);
      var url = tmp.toDataURL('image/png');
      var a = document.createElement('a');
      a.href = url;
      a.download = (document.title || 'diagram') + '.png';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch (e) {
      alert('导出失败：' + (e && e.message ? e.message : e));
    }
  }

  network.once('afterDrawing', doFit);
  window.addEventListener('resize', function () { network.redraw(); });
  document.getElementById('btnFit').onclick = doFit;
  document.getElementById('btnRelayout').onclick = doRelayout;
  document.getElementById('btnPhysics').onclick = togglePhysics;
  document.getElementById('btnDownload').onclick = downloadPNG;
</script>
</body>
</html>"""


def _generate_html(data: dict, output_path: str) -> Optional[str]:
    """使用 vis.js 生成交互式、可拖拽的 HTML（库内联，离线可用）。

    - network（利益关系网络）：力导向布局，自由展开。
    - org（组织架构图）：自上而下层级坐标（自算后喂给 vis 显式 x/y），
      物理关闭 —— 既保留自上而下观感，又避开 vis 层级布局遇环(双向边)算不出坐标而空白的坑。
    - flow（流程图）：自左向右分层坐标，同上。

    三者均可拖拽节点、滚轮缩放、拖动空白平移。
    """
    import json as _json

    nodes = data.get("nodes", [])
    edges = data.get("edges", [])
    if not nodes:
        return None

    viz = data.get("viz", "network")
    if viz not in ("network", "org", "flow"):
        viz = "network"  # 白名单兜底，防任意值注入 JS 字符串
    title = escape(str(data.get("title", "利益关系网络图")), quote=True)

    # ── org/flow：自算层级坐标，喂给 vis 显式 x/y（避环、保层级观感） ──
    fixed_pos: dict = {}
    if viz in ("org", "flow") and edges:
        try:
            import networkx as nx
            G = nx.DiGraph()
            nlabels = {}
            for n in nodes:
                G.add_node(n["id"])
                nlabels[n["id"]] = n.get("label", n["id"])
            for e in edges:
                G.add_edge(e["source"], e["target"])
            if viz == "org":
                pos_raw = _layered_positions(G, nlabels, "UD")
            else:
                use_snake, per_row = _flow_layout_plan(len(nodes))
                if use_snake:
                    pos_raw = _snake_positions(G, nlabels, per_row)
                else:
                    pos_raw = _layered_positions(G, nlabels, "LR")
            SCALE = 130.0
            fixed_pos = {nid: (x * SCALE, y * SCALE) for nid, (x, y) in pos_raw.items()}
        except Exception:
            fixed_pos = {}

    # ── 构建 vis 节点 ──
    vis_nodes = []
    for n in nodes:
        ntype = n.get("type", "actor")
        color = _NODE_COLORS.get(ntype, _DEFAULT_NODE_COLOR)
        node_obj = {
            "id": n["id"],
            "label": n.get("label", n["id"]),
            "color": {
                "background": color,
                "border": "#FFFFFF",
                "highlight": {"background": color, "border": "#FFD400"},
                "hover": {"background": color, "border": "#1B3A5C"},
            },
            "font": {"color": "#FFFFFF", "size": 15, "face": "Arial", "bold": True},
            "shape": "box",
            "margin": 10,
            "borderWidth": 3,
            "shadow": {"enabled": True, "size": 6, "x": 2, "y": 2, "color": "rgba(0,0,0,0.18)"},
        }
        if n["id"] in fixed_pos:
            x, y = fixed_pos[n["id"]]
            node_obj["x"] = x
            node_obj["y"] = y
        vis_nodes.append(node_obj)

    # ── 构建 vis 边 ──
    vis_edges = []
    for e in edges:
        etype = e.get("type", "")
        style = _EDGE_STYLES.get(etype, {})
        color = style.get("color", _DEFAULT_EDGE_COLOR)
        dashes = style.get("dash", False)
        edge_obj = {
            "from": e["source"],
            "to": e["target"],
            "color": {"color": color, "highlight": color, "hover": color},
            "arrows": {"to": {"enabled": True, "scaleFactor": 0.8}},
            "width": 2.5,
            "selectionWidth": 1.5,
        }
        label = e.get("label", "")
        if label:
            edge_obj["label"] = label
            edge_obj["font"] = {"size": 12, "color": "#555555", "bold": True,
                                "background": "rgba(255,255,255,0.85)", "strokeWidth": 0}
        if dashes:
            edge_obj["dashes"] = True
        vis_edges.append(edge_obj)

    # ── 布局选项 ──
    interaction = {
        "hover": True,
        "tooltipDelay": 120,
        "dragNodes": True,
        "dragView": True,
        "zoomView": True,
        "multiselect": True,
        "navigationButtons": True,
        "keyboard": {"enabled": True},
    }
    if viz in ("org", "flow"):
        options = {
            # 物理关闭 + 显式坐标：保留层级观感，遇环不空白
            "physics": {"enabled": False},
            "edges": {"smooth": {"enabled": True, "type": "cubicBezier",
                                 "forceDirection": "vertical" if viz == "org" else "horizontal",
                                 "roundness": 0.2}},
            "nodes": {"shape": "box"},
            "interaction": interaction,
        }
    else:
        options = {
        "physics": {
            "stabilization": {"iterations": 250},
            "solver": "forceAtlas2Based",
            "forceAtlas2Based": {"gravitationalConstant": -95, "centralGravity": 0.006,
                                 "springLength": 240, "springConstant": 0.028},
        },
            "edges": {"smooth": {"enabled": True, "type": "curvedCW", "roundness": 0.15}},
            "interaction": interaction,
        }

    # ── 内联 vis 库（离线可用，不依赖 CDN） ──
    lib_script = _load_vis_lib_script()

    # 嵌入内联 <script> 的 JSON 一律转义 '<'（\u003c）：防止数据中的
    # '</script>' 提前闭合脚本标签造成注入（json.dumps 不转义 ASCII '<'）。
    def _js_safe_json(obj):
        return _json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c")

    # org/flow 的初始层级坐标 JSON（供"重新布局"还原）；network 为空
    fixed_pos_json = _js_safe_json(
        {k: {"x": v[0], "y": v[1]} for k, v in fixed_pos.items()}
    )
    physics_default = "true" if viz == "network" else "false"

    nodes_json = _js_safe_json(vis_nodes)
    edges_json = _js_safe_json(vis_edges)
    options_json = _js_safe_json(options)

    html = (_HTML_VIS_TEMPLATE
            .replace("@@TITLE@@", title)
            .replace("@@LIB@@", lib_script)
            .replace("@@NODES@@", nodes_json)
            .replace("@@EDGES@@", edges_json)
            .replace("@@OPTIONS@@", options_json)
            .replace("@@VIZ@@", viz)
            .replace("@@FIXEDPOS@@", fixed_pos_json)
            .replace("@@PHYSDEFAULT@@", physics_default))

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


def _load_vis_lib_script() -> str:
    """返回用于 <script> 的 vis-network 库内容（内联）或 CDN 回退。"""
    lib_path = os.path.join(os.path.dirname(__file__), "libs", "vis-network.min.js")
    if os.path.exists(lib_path):
        try:
            with open(lib_path, "r", encoding="utf-8") as _f:
                content = _f.read()
            if content.strip():
                return '<script type="text/javascript">\n' + content + "\n</script>"
        except Exception:
            pass
    # 回退：仍依赖 CDN（仅当本地库缺失时）
    return (
        '<script type="text/javascript" '
        'src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js">'
        "</script>"
    )


# ── 辅助 ────────────────────────────────────────────────────

def generate_both(data: dict, png_path: str, html_path: str) -> tuple[Optional[str], Optional[str]]:
    """同时生成 PNG 和 HTML。"""
    viz = data.get("viz", "network")
    if viz in ("org", "flow"):
        png = _generate_layered_png(data, png_path, viz)
    else:
        png = _generate_png(data, png_path)
    html = _generate_html(data, html_path)
    return png, html


def highlight_perspective(data: dict, focus_id: str) -> dict:
    """从全景数据中提取以 focus_id 为中心的局部子图。

    返回新数据，包含：
    - 焦点主体及其直接相连的所有一级邻居
    - 焦点节点的 label 后标注 "(焦点)"
    - 邻居节点半透明描边

    Args:
        data: 原始 DIAGRAM JSON 数据。
        focus_id: 焦点主体 ID（必须存在于 data["nodes"] 中）。

    Returns:
        新的 DIAGRAM 数据 dict。
    """
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])

    # 找到焦点节点
    focus_node = None
    for n in nodes:
        if n["id"] == focus_id:
            focus_node = dict(n)
            focus_node["label"] = f"{n.get('label', n['id'])}"  # 原文不变，由 viz 自行高亮
            break
    if focus_node is None:
        # 找不到焦点 → 返回原数据
        return dict(data)

    # 找到所有与焦点相连的一级邻居
    neighbor_ids: set[str] = {focus_id}
    keep_edges: list[dict] = []
    for e in edges:
        if e["source"] == focus_id:
            neighbor_ids.add(e["target"])
            keep_edges.append(e)
        elif e["target"] == focus_id:
            neighbor_ids.add(e["source"])
            keep_edges.append(e)

    # 保留子图中的节点
    keep_nodes: list[dict] = []
    for n in nodes:
        if n["id"] in neighbor_ids:
            nn = dict(n)
            # 非焦点节点用半透明描边色
            if n["id"] != focus_id:
                nn["_opacity"] = 0.6  # 供渲染器参考
            keep_nodes.append(nn)

    result = dict(data)
    result["nodes"] = keep_nodes
    result["edges"] = keep_edges
    result["title"] = f"{data.get('title', '关系图')}（{focus_node.get('label', focus_id)}视角）"
    return result
