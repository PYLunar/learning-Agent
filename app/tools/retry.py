"""
HTTP 重试工具 - 为 API 调用提供自动重试机制。
支持指数退避和自定义重试策略。
"""

import asyncio
import logging
import functools
from typing import Optional, Callable, TypeVar

from app.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryHandler:
    """
    HTTP 请求重试处理器。
    支持指数退避策略，自动跳过非幂等错误。
    """

    def __init__(
        self,
        max_retries: Optional[int] = None,
        base_delay: Optional[float] = None,
        max_delay: float = 30.0,
        exponential_base: float = 2.0,
    ):
        self.settings = get_settings()
        self.max_retries = max_retries or self.settings.MAX_RETRIES
        self.base_delay = base_delay or self.settings.RETRY_DELAY_SECONDS
        self.max_delay = max_delay
        self.exponential_base = exponential_base

        # 不应重试的 HTTP 状态码
        self.non_retryable_codes = {400, 401, 403, 404, 422}

    async def execute(
        self,
        func: Callable[..., T],
        *args,
        retry_on_exceptions: tuple = (Exception,),
        **kwargs,
    ) -> T:
        """
        带重试的异步执行器。

        Args:
            func: 要执行的异步函数
            *args: 函数参数
            retry_on_exceptions: 需要重试的异常类型元组
            **kwargs: 函数关键字参数

        Returns:
            函数执行结果

        Raises:
            最后一次异常（重试耗尽后）
        """
        last_exception = None

        for attempt in range(1, self.max_retries + 1):
            try:
                result = await func(*args, **kwargs)
                if attempt > 1:
                    logger.info("Retry succeeded on attempt %d/%d", attempt, self.max_retries)
                return result

            except Exception as e:
                last_exception = e

                # 检查是否应该重试
                if not self._should_retry(e, retry_on_exceptions):
                    raise

                if attempt >= self.max_retries:
                    logger.warning("Retry exhausted after %d attempts: %s", self.max_retries, e)
                    break

                delay = self._calculate_delay(attempt)
                logger.info(
                    "Attempt %d/%d failed: %s. Retrying in %.1fs...",
                    attempt, self.max_retries, str(e), delay,
                )
                await asyncio.sleep(delay)

        raise last_exception  # type: ignore

    def _should_retry(self, exception: Exception, retry_on_exceptions: tuple) -> bool:
        """判断是否应该重试。"""
        # 检查异常类型
        if not isinstance(exception, retry_on_exceptions):
            return False

        # 检查 httpx 状态码
        if hasattr(exception, "response"):
            status = getattr(exception.response, "status_code", None)
            if status and status in self.non_retryable_codes:
                return False

        return True

    def _calculate_delay(self, attempt: int) -> float:
        """计算指数退避延迟。"""
        delay = self.base_delay * (self.exponential_base ** (attempt - 1))
        # 加随机抖动避免惊群效应
        import random
        delay *= random.uniform(0.8, 1.2)
        return min(delay, self.max_delay)


def with_retry(
    max_retries: Optional[int] = None,
    base_delay: Optional[float] = None,
):
    """
    重试装饰器（用于同步/异步函数）。

    Usage:
        @with_retry(max_retries=3)
        async def fetch_data():
            ...
    """
    handler = RetryHandler(max_retries=max_retries, base_delay=base_delay)

    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            return await handler.execute(func, *args, **kwargs)
        return async_wrapper

    return decorator
