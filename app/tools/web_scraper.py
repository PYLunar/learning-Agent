"""
网页抓取工具 - 从搜索结果中提取有用信息。
支持 HTML 页面抓取和文本提取。
"""

import logging
import re
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class WebScraperTool:
    """
    网页抓取工具。
    获取指定 URL 的页面内容并提取纯文本。
    """

    def __init__(self):
        self.settings = get_settings()
        self.cache: dict = {}

    async def fetch_page(
        self,
        url: str,
        timeout: float = 10.0,
    ) -> Optional[str]:
        """
        获取网页内容并提取纯文本。

        Args:
            url: 目标 URL
            timeout: 超时时间（秒）

        Returns:
            提取的纯文本，失败时返回 None
        """
        cache_key = f"page:{url}"
        if self.settings.CACHE_ENABLED and cache_key in self.cache:
            return self.cache[cache_key]

        if self.settings.MOCK_MODE:
            return None

        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                },
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()

                text = self._extract_text(resp.text)

                if self.settings.CACHE_ENABLED:
                    self.cache[cache_key] = text

                return text

        except Exception as e:
            logger.warning("Failed to fetch page %s: %s", url, e)
            return None

    def _extract_text(self, html: str) -> str:
        """
        从 HTML 中提取纯文本。

        移除 script/style 标签、HTML 标签、多余空白。
        """
        # 移除 script 和 style 标签及其内容
        text = re.sub(r'<(script|style)[^>]*>[\s\S]*?</\1>', '', html, flags=re.IGNORECASE)
        # 移除 HTML 标签
        text = re.sub(r'<[^>]+>', ' ', text)
        # 解码 HTML 实体
        text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&nbsp;', ' ')
        text = text.replace('&quot;', '"').replace('&#39;', "'")
        # 合并多余空白
        text = re.sub(r'\s+', ' ', text)
        # 截断过长文本（避免占用过多 token）
        max_chars = 5000
        if len(text) > max_chars:
            text = text[:max_chars] + "..."
        return text.strip()

    async def fetch_multiple(
        self,
        urls: list[str],
        max_pages: int = 3,
    ) -> list[dict]:
        """
        批量抓取多个 URL。

        Returns:
            [{"url": str, "text": str}, ...]
        """
        results = []
        for url in urls[:max_pages]:
            text = await self.fetch_page(url)
            if text:
                results.append({"url": url, "text": text})
        return results


# 全局单例
_web_scraper: Optional[WebScraperTool] = None


def get_web_scraper() -> WebScraperTool:
    """获取 WebScraperTool 单例。"""
    global _web_scraper
    if _web_scraper is None:
        _web_scraper = WebScraperTool()
    return _web_scraper
