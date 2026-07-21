"""
通用联网搜索工具 - 面向中国用户的搜索方案。
支持：搜狗搜索 → Bing 公开版 → DuckDuckGo → Google/Bing API（需要 Key）
"""

import json
import logging
import re
from typing import List, Dict, Any, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class WebSearchTool:
    """
    通用联网搜索工具（中国用户优化）。
    搜索优先级：
    1. Bing 公开版 HTML（免费，国内可达）
    2. Bing Web Search API（需要 Key）
    3. Google Custom Search API（需要 Key）
    4. DuckDuckGo HTML（免费，可能被墙）
    """

    def __init__(self):
        self.settings = get_settings()
        self.cache: Dict[str, Any] = {}
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

    async def search(
        self,
        query: str,
        max_results: int = 5,
        region: str = "",
    ) -> List[Dict[str, Any]]:
        """
        搜索互联网并返回结果列表。

        返回格式: [{"title": str, "url": str, "snippet": str}, ...]
        """
        cache_key = f"search:{query}:{region}:{max_results}"
        if self.settings.CACHE_ENABLED and cache_key in self.cache:
            return self.cache[cache_key]

        results = []

        if self.settings.MOCK_MODE:
            results = []
        else:
            # 1. Bing 公开版（免费，国内可达）
            try:
                results = await self._search_bing_public(query, max_results)
                if results:
                    logger.info("Bing 公开版返回 %d 条结果: %s", len(results), query[:30])
            except Exception as e:
                logger.warning("Bing 公开版搜索失败: %s", e)

            # 2. Bing API（如果有 Key）
            if not results and self.settings.BING_SEARCH_API_KEY:
                try:
                    results = await self._search_bing_api(query, max_results)
                except Exception as e:
                    logger.warning("Bing API 搜索失败: %s", e)

            # 3. Google API（如果有 Key）
            if not results and self.settings.GOOGLE_SEARCH_API_KEY and self.settings.GOOGLE_SEARCH_CX:
                try:
                    results = await self._search_google(query, max_results, region)
                except Exception as e:
                    logger.warning("Google Search failed: %s", e)

            # 4. DuckDuckGo（最后手段）
            if not results:
                try:
                    results = await self._search_duckduckgo(query, max_results)
                except Exception as e:
                    logger.warning("所有搜索引擎均失败: %s", e)

        if self.settings.CACHE_ENABLED:
            self.cache[cache_key] = results

        return results

    async def fetch_url(self, url: str, timeout: float = 10.0) -> Optional[str]:
        """直接抓取 URL 的 HTML 内容。"""
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=self.headers) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.text
        except Exception as e:
            logger.warning("抓取 URL 失败 %s: %s", url, e)
            return None

    async def _search_sogou(
        self, query: str, max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """使用搜狗搜索 HTML 版（免费，国内直接可达）。"""
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=self.headers) as client:
            resp = await client.get(
                "https://www.sogou.com/web",
                params={"query": query},
            )
            resp.raise_for_status()

            html = resp.text
            results = []

            # 搜狗搜索结果格式：
            # <h3><a href="URL">标题</a></h3>
            # <p class="str-time-info">摘要</p> 或 <div class="ft">摘要</div>
            h3_pattern = re.compile(
                r'<h3[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>\s*</h3>',
                re.DOTALL
            )

            # 摘要模式
            snippet_patterns = [
                re.compile(r'<p[^>]*class="[^"]*str_[^"]*"[^>]*>(.*?)</p>', re.DOTALL),
                re.compile(r'<div[^>]*class="[^"]*ft[^"]*"[^>]*>(.*?)</div>', re.DOTALL),
            ]

            h3_matches = h3_pattern.findall(html)

            for i, (url, title_html) in enumerate(h3_matches[:max_results * 2]):
                title = re.sub(r'<[^>]+>', '', title_html).strip()

                # 过滤搜狗自身的链接和非结果
                if not title or len(title) < 4:
                    continue
                if any(w in url for w in ["sogou.com", "baidu.com/link"]):
                    continue

                # 查找摘要：在 h3 匹配位置之后搜索
                start_pos = html.find(h3_matches[i][0]) if i < len(h3_matches) else 0
                context = html[start_pos:start_pos + 500]
                snippet = ""
                for sp in snippet_patterns:
                    sm = sp.search(context)
                    if sm:
                        snippet = re.sub(r'<[^>]+>', '', sm.group(1)).strip()
                        break

                results.append({
                    "title": title[:100],
                    "url": url,
                    "snippet": snippet[:300],
                })

                if len(results) >= max_results:
                    break

            return results

    async def _search_bing_public(
        self, query: str, max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """使用 Bing 公开版搜索 HTML（免费，国内可达）。"""
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=self.headers) as client:
            resp = await client.get(
                "https://cn.bing.com/search",
                params={"q": query, "count": str(max_results * 2)},
            )
            resp.raise_for_status()

            html = resp.text
            results = []

            # Bing 搜索结果格式：
            # <h2><a href="URL">标题</a></h2>
            # <p>摘要</p>
            h2_pattern = re.compile(
                r'<h2[^>]*>\s*<a[^>]*href="(https?://[^"]*)"[^>]*>(.*?)</a>\s*</h2>',
                re.DOTALL
            )

            h2_matches = h2_pattern.findall(html)

            for i, (url, title_html) in enumerate(h2_matches[:max_results * 2]):
                title = re.sub(r'<[^>]+>', '', title_html).strip()

                if not title or len(title) < 4:
                    continue
                # 过滤 Bing 自身链接
                if any(w in url for w in ["bing.com", "microsoft.com", "msn.com"]):
                    continue

                # 查找摘要：在 h2 后面搜索 <p> 标签
                start_pos = html.find(h2_matches[i][0]) if i < len(h2_matches) else 0
                context = html[start_pos:start_pos + 1000]
                snippet = ""
                # Bing 摘要在 <p> 或 class="b_caption" 中
                snippet_match = re.search(r'<p[^>]*class="[^"]*b[^"]*"[^>]*>(.*?)</p>', context, re.DOTALL)
                if not snippet_match:
                    snippet_match = re.search(r'<div[^>]*class="[^"]*b_caption[^"]*"[^>]*>(.*?)</div>', context, re.DOTALL)
                if not snippet_match:
                    snippet_match = re.search(r'<p[^>]*>(.{20,400})</p>', context, re.DOTALL)
                if snippet_match:
                    snippet = re.sub(r'<[^>]+>', '', snippet_match.group(1)).strip()

                results.append({
                    "title": title[:100],
                    "url": url,
                    "snippet": snippet[:300],
                })

                if len(results) >= max_results:
                    break

            return results

    async def _search_duckduckgo(
        self, query: str, max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """使用 DuckDuckGo HTML 搜索（免费，可能被墙）。"""
        async with httpx.AsyncClient(timeout=15.0, headers=self.headers) as client:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
            )
            resp.raise_for_status()

            results = []
            title_pattern = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL)
            snippet_pattern = re.compile(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', re.DOTALL)

            titles = title_pattern.findall(resp.text)
            snippets = snippet_pattern.findall(resp.text)

            for i, (raw_url, title) in enumerate(titles[:max_results]):
                snippet = snippets[i].strip() if i < len(snippets) else ""
                clean_title = re.sub(r'<[^>]+>', '', title).strip()
                clean_snippet = re.sub(r'<[^>]+>', '', snippet).strip()

                results.append({
                    "title": clean_title,
                    "url": raw_url if raw_url.startswith("http") else f"https://duckduckgo.com{raw_url}",
                    "snippet": clean_snippet,
                })

            return results

    async def _search_bing_api(
        self, query: str, max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """使用 Bing Web Search API（Azure）。"""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.bing.microsoft.com/v7.0/search",
                headers={"Ocp-Apim-Subscription-Key": self.settings.BING_SEARCH_API_KEY},
                params={
                    "q": query,
                    "count": min(max_results, 50),
                    "textDecorations": False,
                    "textFormat": "Plain",
                },
            )
            resp.raise_for_status()

            data = resp.json()
            results = []
            for item in data.get("webPages", {}).get("value", [])[:max_results]:
                results.append({
                    "title": item.get("name", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("snippet", ""),
                })

            return results

    async def _search_google(
        self, query: str, max_results: int = 5, region: str = ""
    ) -> List[Dict[str, Any]]:
        """使用 Google Custom Search API。"""
        async with httpx.AsyncClient(timeout=15.0) as client:
            params = {
                "key": self.settings.GOOGLE_SEARCH_API_KEY,
                "cx": self.settings.GOOGLE_SEARCH_CX,
                "q": query,
                "num": min(max_results, 10),
            }
            if region:
                params["gl"] = region

            resp = await client.get(
                "https://www.googleapis.com/customsearch/v1",
                params=params,
            )
            resp.raise_for_status()

            data = resp.json()
            results = []
            for item in data.get("items", [])[:max_results]:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                })

            return results


# 全局单例
_web_search: Optional[WebSearchTool] = None


def get_web_search() -> WebSearchTool:
    """获取 WebSearchTool 单例。"""
    global _web_search
    if _web_search is None:
        _web_search = WebSearchTool()
    return _web_search
