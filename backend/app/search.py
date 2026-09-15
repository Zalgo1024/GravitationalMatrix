"""联网检索模块（T1：检索 + 抓取 + 清洗 + 去重一体化）。

检索源自动选择（零 Key 恒可用）：
    BING_SEARCH_KEY → BRAVE_SEARCH_KEY → DuckDuckGo HTML（https://html.duckduckgo.com/html/）
任何源失败**不静默**：返回带 `degraded` 标记的 SearchResult，由调用方（queue / 前端
来源预览）拼装 PRD §6 的明确降级提示。

抓取正文三级降级：trafilatura.extract → readability-lxml → 去 script/style 后取文本。

设计要点：
- 仅用标准库 urllib（requests 可选）与 lxml / trafilatura，无浏览器依赖；
- 保留旧签名兼容包装 `search_web(query, provider, api_key, max_results)`；
- 兼容旧字段：`format_search_context` 仍可用（新 SearchResult 统一 hits 字段）。
"""
from __future__ import annotations

import base64
import difflib
import json
import logging
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger("search")

# 单次搜索最大阻塞时长（秒）。worker 线程池里调用，超时即放弃并降级标记。
SEARCH_TIMEOUT = 8
# 抓取单页超时（秒）
FETCH_TIMEOUT = 12
# 浏览器 UA（DDG HTML 对无 UA 请求容易限流）
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 错误脱敏：避免搜索异常里意外泄露 key 片段。
_SAFE_PAT = ("sk-", "api_key", "bearer ", "subscription-key", "x-subscription-token")


@dataclass
class SearchHit:
    """单条检索结果。"""

    title: str
    url: str
    snippet: str = ""


@dataclass
class SearchResult:
    """统一检索结果（替代旧 snippets/sources 分离）。

    degraded 非空表示本次检索降级（超时/限流/解析失败/缺 Key），调用方必须显式提示。
    """

    query: str
    hits: list[SearchHit] = field(default_factory=list)
    provider: str = ""  # "duckduckgo" | "bing" | "brave"
    degraded: str | None = None


def should_search(input_text: str) -> bool:
    """启发式：输入是否值得联网检索。有文本即搜（真正开关在 queue._process 的 web 判定）。"""
    return bool((input_text or "").strip())


def _safe_msg(e: Exception) -> str:
    msg = str(e)
    low = msg.lower()
    for s in _SAFE_PAT:
        if s in low:
            return "[已脱敏的检索/抓取错误]"
    return msg[:200]


def _assert_safe_url(url: str) -> None:
    """URL 白名单护栏：只允许 http/https，拒绝 file:// 等本地协议及本机回环地址，
    防止用户白名单/搜索结果被利用读取本地文件或探测本机服务（SSRF）。"""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        raise ValueError(f"无法解析的 URL: {url[:80]}")
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"不允许的 URL 协议: {scheme or '(空)'}")
    host = parsed.hostname or ""
    if not host:
        raise ValueError(f"URL 缺少主机名: {url[:80]}")
    if host.lower() == "localhost":
        raise ValueError("不允许访问本机回环地址")
    import ipaddress
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return  # 非 IP 字面量（域名），交给正常 HTTP 解析
    if not ip.is_global:
        raise ValueError("不允许访问本机、私有或链路本地地址")


def _http_get(url: str, timeout: int = FETCH_TIMEOUT, headers: dict | None = None) -> str:
    """GET 一个 URL 返回文本。优先 requests（若已安装），否则 urllib 兜底。"""
    _assert_safe_url(url)
    hdrs = {"User-Agent": BROWSER_UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
    if headers:
        hdrs.update(headers)
    try:
        import requests  # type: ignore

        resp = requests.get(url, headers=hdrs, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except ImportError:
        req = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")


def _extract_ddg_url(href: str) -> str:
    """DDG HTML 重定向链接（//duckduckgo.com/l/?uddg=...）还原真实 URL。"""
    if not href:
        return ""
    if "uddg=" in href:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        if qs.get("uddg"):
            return qs["uddg"][0]
    return href


def _parse_ddg_html(html: str, max_results: int) -> list[SearchHit]:
    """用 lxml 解析 DDG HTML：.result__a（标题+href）与 .result__snippet（摘要）。"""
    from lxml import html as lh

    tree = lh.fromstring(html)
    hits: list[SearchHit] = []
    for a in tree.cssselect("a.result__a")[:max_results]:
        title = "".join(a.itertext()).strip()
        url = _extract_ddg_url(a.get("href", "") or "")
        snippet = ""
        # 摘要位于所属 .result 容器内的 .result__snippet
        node: object = a
        for _ in range(5):
            node = node.getparent() if hasattr(node, "getparent") else None
            if node is None:
                break
            cls = (node.get("class") or "") if hasattr(node, "get") else ""
            if "result" in cls.split():
                break
        if node is not None:
            sn = node.cssselect("a.result__snippet") or node.cssselect(".result__snippet")
            if sn:
                snippet = "".join(sn[0].itertext()).strip()
        if url:
            hits.append(SearchHit(title=title or url, url=url, snippet=snippet))
    return hits


def _search_duckduckgo(query: str, max_results: int) -> list[SearchHit]:
    """GET https://html.duckduckgo.com/html/?q={query}（UA=浏览器），lxml 解析。

    超时 8s，重试 1 次；仍失败抛出异常由 search_web 统一降级标记。
    """
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            html = _http_get(url, timeout=SEARCH_TIMEOUT)
            return _parse_ddg_html(html, max_results)
        except Exception as e:  # noqa: BLE001
            last_exc = e
            if attempt == 0:
                time.sleep(1.0)
    raise last_exc  # type: ignore[misc]


def _extract_bing_url(href: str) -> str:
    """必应网页版 /ck/a 重定向链接还原真实 URL（u=a1<base64url> 参数）。

    必应对部分结果（尤其广告位与风险站点）返回 bing.com/ck/a 跳转壳，
    直接入库会出现「标题是整条跳转 URL」的垃圾来源；解不出来就原样返回。
    """
    if not href or "bing.com/ck/a" not in href:
        return href
    try:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        u = (qs.get("u") or [""])[0]
        if u.startswith("a1"):
            payload = u[2:]
            payload += "=" * (-len(payload) % 4)
            real = base64.urlsafe_b64decode(payload).decode("utf-8", "replace")
            if real.startswith("http"):
                return real
    except Exception:  # noqa: BLE001 — 解码失败一律回退原链接
        pass
    return href


def _search_bing_html(query: str, max_results: int) -> list[SearchHit]:
    """零 key 兜底：GET https://www.bing.com/search?q={query}（UA=浏览器），lxml 解析 b_algo。

    必应网页版对自动化请求偶发验证码/限流，因此只作为免费轮换源之一，
    不重试（失败即交给下一个源），超时缩短到 6s 以控制总耗时。
    """
    url = "https://www.bing.com/search?" + urllib.parse.urlencode(
        {"q": query, "count": "10", "setlang": "zh-hans"}
    )
    html = _http_get(url, timeout=6)
    from lxml import html as lh

    tree = lh.fromstring(html)
    hits: list[SearchHit] = []
    for li in tree.cssselect("li.b_algo")[:max_results]:
        a = li.cssselect("h2 a")
        if not a:
            continue
        title = "".join(a[0].itertext()).strip()
        url = _extract_bing_url((a[0].get("href") or "").strip())
        if not url:
            continue
        snippet = ""
        p = li.cssselect(".b_caption p") or li.cssselect(
            ".b_lineclamp2, .b_lineclamp3, .b_lineclamp4"
        )
        if p:
            snippet = "".join(p[0].itertext()).strip()
        hits.append(SearchHit(title=title or url, url=url, snippet=snippet))
    return hits


def _search_sogou(query: str, max_results: int) -> list[SearchHit]:
    """零 key 兜底：GET https://www.sogou.com/web?query={query}（UA=浏览器），lxml 解析 vrwrap。"""
    url = "https://www.sogou.com/web?" + urllib.parse.urlencode({"query": query})
    html = _http_get(url, timeout=6)
    from lxml import html as lh

    tree = lh.fromstring(html)
    hits: list[SearchHit] = []
    for node in tree.cssselect(".vrwrap")[:max_results]:
        a = node.cssselect("h3 a") or node.cssselect("h4 a")
        if not a:
            continue
        title = "".join(a[0].itertext()).strip()
        url = (a[0].get("href") or "").strip()
        if not url:
            continue
        snippet = ""
        s = node.cssselect(".text-layout") or node.cssselect(
            ".str_info"
        ) or node.cssselect(".fz-mid")
        if s:
            snippet = "".join(s[0].itertext()).strip()
        hits.append(SearchHit(title=title or url, url=url, snippet=snippet))
    return hits


def _search_bing(query: str, api_key: str, max_results: int) -> list[SearchHit]:
    """Bing Web Search API v7.0：GET https://api.bing.microsoft.com/v7.0/search
    Header Ocp-Apim-Subscription-Key。"""
    url = "https://api.bing.microsoft.com/v7.0/search?" + urllib.parse.urlencode(
        {"q": query, "count": max_results, "mkt": "zh-CN"}
    )
    html = _http_get(
        url,
        timeout=SEARCH_TIMEOUT,
        headers={"Ocp-Apim-Subscription-Key": api_key, "Accept": "application/json"},
    )
    data = json.loads(html)
    hits: list[SearchHit] = []
    for item in data.get("webPages", {}).get("value", [])[:max_results]:
        hits.append(
            SearchHit(
                title=item.get("name", ""),
                url=item.get("url", ""),
                snippet=item.get("snippet", ""),
            )
        )
    return hits


def _search_brave(query: str, api_key: str, max_results: int) -> list[SearchHit]:
    """Brave Search API：GET https://api.search.brave.com/res/v1/web/search
    Header X-Subscription-Token。"""
    url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
        {"q": query, "count": max_results}
    )
    html = _http_get(
        url,
        timeout=SEARCH_TIMEOUT,
        headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
    )
    data = json.loads(html)
    hits: list[SearchHit] = []
    for item in data.get("web", {}).get("results", [])[:max_results]:
        hits.append(
            SearchHit(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("description", ""),
            )
        )
    return hits


def _call_mock(query: str, _api_key: str, max_results: int) -> SearchResult:
    """本地演练/灰度 dry-run 用的占位提供方（仅显式 provider='mock' 时启用）。

    不发起任何网络请求，返回带明显标注的样例结果。样例数据为虚构，绝不可进入正式报告。
    """
    snippets = [
        f"[演练样例·非真实数据] 关于「{query}」的公开报道摘要一：各方对事件背景与处置进展的概述。",
        f"[演练样例·非真实数据] 关于「{query}」的政策/制度上下文：相关条款与主管部门的公开说明。",
    ]
    hits = [
        SearchHit(
            title=f"演练样例·{query}",
            url="https://example.com/mock-search-result-1",
            snippet=snippets[0],
        ),
        SearchHit(
            title=f"演练样例·{query}（政策上下文）",
            url="https://example.com/mock-search-result-2",
            snippet=snippets[1],
        ),
    ]
    return SearchResult(query=query, hits=hits[: max(1, min(max_results, len(hits)))], provider="mock")


def _call_serper(query: str, api_key: str, max_results: int) -> SearchResult:
    """Serper（Google）兼容保留：显式 provider='serper' 时使用。"""
    url = "https://google.serper.dev/search"
    payload = json.dumps({"q": query, "num": max_results}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=SEARCH_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    hits = [
        SearchHit(
            title=item.get("title", ""),
            url=item.get("link", ""),
            snippet=item.get("snippet", ""),
        )
        for item in data.get("organic", [])[:max_results]
    ]
    return SearchResult(query=query, hits=hits, provider="serper")


def _call_tavily(query: str, api_key: str, max_results: int) -> SearchResult:
    """Tavily 兼容保留：显式 provider='tavily' 时使用。"""
    url = "https://api.tavily.com/search"
    payload = json.dumps(
        {"api_key": api_key, "query": query, "max_results": max_results, "search_depth": "basic"}
    ).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=SEARCH_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    hits = [
        SearchHit(title=item.get("title", ""), url=item.get("url", ""), snippet=item.get("content", ""))
        for item in data.get("results", [])[:max_results]
    ]
    return SearchResult(query=query, hits=hits, provider="tavily")


def search_web(
    query: str,
    max_results: int = 5,
    provider: str | None = None,
    api_key: str | None = None,
) -> SearchResult | None:
    """执行一次网络搜索：检索源自动选择 BING_KEY → BRAVE_KEY → DDG（零 Key）。

    兼容旧签名 ``search_web(query, provider, api_key, max_results)``：
    当第二个位置参数是字符串（旧 provider）时按旧语义重排。

    任何源失败**不静默**：返回带 ``degraded`` 标记的 SearchResult（永不抛异常）。
    """
    from app.settings import settings

    # —— 兼容旧签名：(query, provider, api_key, max_results) ——
    if isinstance(max_results, str):
        provider, api_key, max_results = max_results, provider, api_key

    query = (query or "").strip()
    if not query:
        return SearchResult(query="", hits=[], provider=provider or "duckduckgo", degraded="查询为空")

    def _wrap(method: str, fn):
        try:
            hits = fn()
            return SearchResult(query=query, hits=hits or [], provider=method)
        except Exception as e:  # noqa: BLE001
            logger.warning("检索失败（%s，已降级标记）：%s", method, _safe_msg(e))
            return SearchResult(
                query=query,
                hits=[],
                provider=method,
                degraded=f"检索源 {method} 不可用：{_safe_msg(e)}（可配置 BING/BRAVE Key 或改用手动 URL 输入）",
            )

    if provider == "mock":
        return _call_mock(query, api_key, max_results)
    if provider == "serper":
        return _call_serper(query, api_key, max_results)
    if provider == "tavily":
        return _call_tavily(query, api_key, max_results)
    if provider == "bing":
        key = api_key or settings.bing_search_key
        if not key:
            return SearchResult(query=query, hits=[], provider="bing", degraded="未配置 BING_SEARCH_KEY")
        return _wrap("bing", lambda: _search_bing(query, key, max_results))
    if provider == "brave":
        key = api_key or settings.brave_search_key
        if not key:
            return SearchResult(query=query, hits=[], provider="brave", degraded="未配置 BRAVE_SEARCH_KEY")
        return _wrap("brave", lambda: _search_brave(query, key, max_results))
    if provider == "duckduckgo":
        return _wrap("duckduckgo", lambda: _search_duckduckgo(query, max_results))

    # —— auto 自动选择：BING → BRAVE → 免费零 key 源轮换（DDG → 必应网页版 → 搜狗）——
    if settings.bing_search_key:
        return _wrap("bing", lambda: _search_bing(query, settings.bing_search_key, max_results))
    if settings.brave_search_key:
        return _wrap("brave", lambda: _search_brave(query, settings.brave_search_key, max_results))
    # 免费源依次尝试：任一返回结果即停；全部失败返回统一降级消息，
    # 避免单个免费源（如 DDG）不可用时把整个搜索链路打瘫。
    last_result: SearchResult | None = None
    for method, fn in (
        ("duckduckgo", lambda: _search_duckduckgo(query, max_results)),
        ("bing_html", lambda: _search_bing_html(query, max_results)),
        ("sogou", lambda: _search_sogou(query, max_results)),
    ):
        result = _wrap(method, fn)
        if result.hits:
            return result
        last_result = result
    detail = f"：{last_result.degraded}" if last_result and last_result.degraded else ""
    return SearchResult(
        query=query,
        hits=[],
        provider="free",
        degraded=f"所有免费检索源均不可用（DuckDuckGo/必应网页版/搜狗）{detail}",
    )


def search_primary_and_analogue(
    primary_query: str,
    analogue_query: str,
    max_results: int = 5,
    *,
    search_fn: Callable[[str, int], SearchResult | None] | None = None,
    parallel: bool | None = None,
) -> tuple[SearchResult | None, SearchResult | None]:
    """Search the current event and historical analogues without doubling failure latency.

    Configured commercial providers are queried in parallel. The keyless DuckDuckGo
    fallback first checks the primary query because two consecutive timeout/retry
    cycles otherwise add no evidence and can delay one report by tens of seconds.
    Tests and callers may explicitly select either path with ``parallel``.
    """
    from app.settings import settings

    fn = search_fn or search_web
    if parallel is None:
        parallel = bool(settings.bing_search_key or settings.brave_search_key)

    if parallel:
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="triad-search") as pool:
            primary_future = pool.submit(fn, primary_query, max_results)
            analogue_future = pool.submit(fn, analogue_query, max_results)
            return primary_future.result(), analogue_future.result()

    primary = fn(primary_query, max_results)
    if primary is None or (not primary.hits and primary.degraded):
        return primary, None
    return primary, fn(analogue_query, max_results)


# ============================ 抓取 / 清洗 ============================


def _extract_trafilatura(html: str, url: str) -> str:
    """trafilatura 抽主文（纯规则，无浏览器依赖）。失败返回空串。"""
    try:
        import trafilatura

        return (
            trafilatura.extract(
                html,
                url=url or None,
                include_comments=False,
                include_tables=False,
                favor_precision=True,
            )
            or ""
        ).strip()
    except Exception:  # noqa: BLE001
        return ""


def _extract_readability(html: str) -> str:
    """readability-lxml 降级（可选依赖，未安装时跳过）。"""
    try:
        from readability import Document  # type: ignore

        doc = Document(html)
        return _strip_tags(doc.summary())
    except Exception:  # noqa: BLE001
        return ""


def _strip_tags(html: str) -> str:
    """兜底：去 script/style 与其余标签，压缩空白。"""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_title(html: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html or "")
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()[:200]
    return ""


def clean_text(html: str, url: str = "") -> str:
    """trafilatura → readability → 兜底去标签 三级降级抽取主文。"""
    text = _extract_trafilatura(html, url)
    if text and len(text) > 20:
        return text
    text = _extract_readability(html)
    if text and len(text) > 20:
        return text
    return _strip_tags(html)


def fetch_and_clean(
    urls: list[str],
    max_chars: int = 8000,
    max_workers: int = 4,
) -> list[dict]:
    """并发抓取公开网页正文，按输入 URL 顺序返回，失败条目原位保留。

    返回 [{title, url, text, snippet}]；text 截断 max_chars。
    抓取失败条目保留 {title, url, text:"", error} 供前端/附录过滤，不静默丢弃。
    """
    def _fetch_one(u: str) -> dict:
        entry: dict = {"title": "", "url": u, "text": "", "snippet": "", "error": None}
        try:
            html = _http_get(u)
            title = _extract_title(html) or u
            text = clean_text(html, u).strip()
            # 只有页面标题、空白页或拦截页不能作为证据。保留失败条目供
            # 前端显示，但绝不让它进入 materials.sources 或 LLM 证据池。
            if len(text) < 40 or text == title.strip():
                entry["title"] = title
                entry["error"] = "empty_content"
                return entry
            entry["text"] = text[:max_chars]
            entry["title"] = title
        except Exception as e:  # noqa: BLE001
            entry["error"] = _safe_msg(e)
            logger.warning("抓取失败 %s：%s", u, entry["error"])
        return entry

    ordered_urls = list(urls or [])
    if not ordered_urls:
        return []
    worker_count = max(1, min(max_workers, len(ordered_urls)))
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="triad-fetch") as pool:
        return list(pool.map(_fetch_one, ordered_urls))


# ============================ 去重 ============================


def _normalize_url(url: str) -> str:
    """URL 归一：去协议差异、去 query 参数、去尾斜杠、去 www。"""
    try:
        p = urllib.parse.urlsplit((url or "").strip())
        host = (p.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = re.sub(r"/+$", "", p.path or "")
        return urllib.parse.urlunsplit((p.scheme.lower(), host, path, "", ""))
    except Exception:  # noqa: BLE001
        return (url or "").strip().lower().rstrip("/")


def dedupe_hits(hits: list[SearchHit]) -> list[SearchHit]:
    """按 URL 归一（去 query 参数/协议差异）+ 标题相似度（difflib ratio>0.9 判重）。"""
    seen_url: set[str] = set()
    seen_titles: list[str] = []
    out: list[SearchHit] = []
    for h in hits or []:
        nu = _normalize_url(h.url)
        if not nu or nu in seen_url:
            continue
        if any(
            t and h.title and difflib.SequenceMatcher(None, t, h.title).ratio() > 0.9
            for t in seen_titles
        ):
            continue
        seen_url.add(nu)
        seen_titles.append(h.title)
        out.append(h)
    return out


# ============================ 上下文拼装（兼容旧调用方） ============================


def format_search_context(result: SearchResult | None) -> str:
    """把检索结果拼成可读背景块（兼容新 SearchResult{hits} 与旧 {snippets,sources}）。

    无结果返回空串；降级时明确标注 degraded，不静默。
    """
    if not result:
        return ""
    if result.degraded:
        return f"[联网检索补充背景]\n（检索降级：{result.degraded}）"
    lines = ["[联网检索补充背景]"]
    for i, h in enumerate(result.hits, 1):
        if h.snippet:
            lines.append(f"{i}. {h.title}：{h.snippet}（{h.url}）")
        else:
            lines.append(f"{i}. {h.title}（{h.url}）")
    return "\n".join(lines)


def derive_query(input_text: str) -> str:
    """从输入派生检索词：优先取首个 http(s) 链接，否则取首行/前 80 字。"""
    text = (input_text or "").strip()
    m = re.search(r"https?://\S+", text)
    if m:
        return m.group(0)
    first_line = text.splitlines()[0].strip() if text else ""
    return first_line or text[:80]


def derive_analogue_query(input_text: str) -> str:
    """Build a bounded second query for historical handling and outcomes."""
    base = re.sub(r"https?://\S+", " ", (input_text or "")).strip()
    base = re.sub(r"\s+", " ", base)
    if not base:
        base = derive_query(input_text)
    suffix = " 类似案例 历史处置 处理结果"
    return (base[: 180 - len(suffix)] + suffix).strip()
