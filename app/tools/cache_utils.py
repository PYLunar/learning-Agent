"""
带 TTL 过期的缓存工具 - 替代简单的 dict 缓存。
支持按 key 设置过期时间。
"""

import time
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class TTLCache:
    """带 TTL（Time To Live）的缓存。"""

    def __init__(self, default_ttl: int = 3600):
        """
        Args:
            default_ttl: 默认过期时间（秒）
        """
        self._cache: dict[str, tuple[float, Any]] = {}
        self.default_ttl = default_ttl

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值，过期返回 None。"""
        if key in self._cache:
            timestamp, value = self._cache[key]
            if time.time() - timestamp < self.default_ttl:
                return value
            else:
                del self._cache[key]
                logger.debug("TTLCache: key '%s' expired", key)
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """设置缓存值。"""
        effective_ttl = ttl or self.default_ttl
        self._cache[key] = (time.time(), value)

    def delete(self, key: str) -> bool:
        """删除缓存值。"""
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def clear(self) -> None:
        """清空所有缓存。"""
        self._cache.clear()

    def has(self, key: str) -> bool:
        """检查缓存是否存在且未过期。"""
        return self.get(key) is not None

    @property
    def size(self) -> int:
        """当前缓存数量（包括过期的）。"""
        return len(self._cache)

    def cleanup(self) -> int:
        """清理过期缓存，返回清理数量。"""
        now = time.time()
        expired_keys = [
            k for k, (ts, _) in self._cache.items()
            if now - ts >= self.default_ttl
        ]
        for k in expired_keys:
            del self._cache[k]
        return len(expired_keys)

    def __repr__(self) -> str:
        return f"TTLCache(size={self.size}, default_ttl={self.default_ttl}s)"
