"""
Wikipedia API 工具 - 获取城市/景点的详细信息、历史背景、文化介绍。
免费 API，无需 Key。
"""

import logging
import re
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class WikipediaTool:
    """
    Wikipedia API 工具。
    用于获取目的地城市的概览信息、历史背景、文化介绍、实用旅行信息等。
    完全免费，无需 API Key。
    """

    BASE_URL = "https://en.wikipedia.org/api/rest_v1"

    def __init__(self):
        self.settings = get_settings()
        self.cache: dict = {}

    async def get_summary(
        self,
        title: str,
        lang: str = "en",
    ) -> Optional[dict]:
        """
        获取 Wikipedia 页面摘要。

        Returns:
            {"title": str, "extract": str, "url": str, "thumbnail": str}
            失败时返回 None
        """
        cache_key = f"wiki:{lang}:{title}"
        if self.settings.CACHE_ENABLED and cache_key in self.cache:
            return self.cache[cache_key]

        if self.settings.MOCK_MODE or not self.settings.WIKIPEDIA_ENABLED:
            return None

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/page/summary/{title}",
                    params={"redirect": "true"},
                    headers={"User-Agent": "TravelAgent/1.0"},
                )

                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                data = resp.json()

                result = {
                    "title": data.get("title", title),
                    "extract": self._clean_text(data.get("extract", "")),
                    "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                    "thumbnail": data.get("thumbnail", {}).get("source", ""),
                    "description": data.get("description", ""),
                }

                if self.settings.CACHE_ENABLED:
                    self.cache[cache_key] = result

                return result

        except Exception as e:
            logger.warning("Wikipedia API error for '%s': %s", title, e)
            return None

    async def search(
        self,
        query: str,
        limit: int = 3,
    ) -> list[dict]:
        """
        搜索 Wikipedia 并返回匹配的页面标题。

        Returns:
            [{"title": str, "description": str}, ...]
        """
        cache_key = f"wiki_search:{query}:{limit}"
        if self.settings.CACHE_ENABLED and cache_key in self.cache:
            return self.cache[cache_key]

        if self.settings.MOCK_MODE or not self.settings.WIKIPEDIA_ENABLED:
            return []

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/page/search/{query}",
                    params={"limit": limit, "redirect": "true"},
                    headers={"User-Agent": "TravelAgent/1.0"},
                )
                resp.raise_for_status()
                data = resp.json()

                results = [
                    {
                        "title": page.get("title", ""),
                        "description": page.get("description", ""),
                        "snippet": page.get("snippet", ""),
                    }
                    for page in data.get("pages", [])
                ]

                if self.settings.CACHE_ENABLED:
                    self.cache[cache_key] = results

                return results

        except Exception as e:
            logger.warning("Wikipedia search error for '%s': %s", query, e)
            return []

    async def get_city_info(self, city: str, lang: str = "en") -> Optional[dict]:
        """
        获取城市的综合旅行信息（合并摘要 + 搜索相关条目）。

        Returns:
            {"overview": str, "culture": str, "tips": list[str], "related_places": list[str]}
        """
        # 1. 获取城市主页面摘要
        summary = await self.get_summary(city, lang)

        # 2. 搜索旅游相关条目
        search_results = await self.search(f"{city} tourism travel guide", limit=3)

        overview = summary.get("extract", "") if summary else ""
        description = summary.get("description", "") if summary else ""

        # 3. 搜索景点相关条目
        places_results = await self.search(f"tourist attractions {city}", limit=5)
        related_places = [p.get("title", "") for p in places_results if p.get("title")]

        # 4. 组合返回
        info = {
            "overview": overview[:2000] if overview else "",
            "description": description,
            "tips": [],
            "related_places": related_places[:5],
            "source": summary.get("url", "") if summary else "",
        }

        return info

    def _clean_text(self, text: str) -> str:
        """清理 Wikipedia 文本。"""
        if not text:
            return ""
        # 移除多余的空白
        text = re.sub(r'\s+', ' ', text)
        # 截断过长文本
        if len(text) > 3000:
            text = text[:3000] + "..."
        return text.strip()


# 全局单例
_wikipedia: Optional[WikipediaTool] = None


def get_wikipedia() -> WikipediaTool:
    """获取 WikipediaTool 单例。"""
    global _wikipedia
    if _wikipedia is None:
        _wikipedia = WikipediaTool()
    return _wikipedia
