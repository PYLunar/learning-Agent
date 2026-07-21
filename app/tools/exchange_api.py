"""
汇率 API 工具 - 获取实时汇率，支持多币种预算计算。
免费 API，无需 Key。
"""

import logging
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


# 常用货币代码
CURRENCY_MAP: dict[str, str] = {
    "USD": "USD",
    "EUR": "EUR",
    "GBP": "GBP",
    "JPY": "JPY",
    "CNY": "CNY",
    "KRW": "KRW",
    "THB": "THB",
    "SGD": "SGD",
    "HKD": "HKD",
    "TWD": "TWD",
    "AUD": "AUD",
    "CAD": "CAD",
    "INR": "INR",
    "RUB": "RUB",
}


class ExchangeRateTool:
    """
    汇率工具。
    使用 frankfurter.app 免费 API 获取实时汇率。
    支持将任何货币转换为 USD（系统内部统一用 USD 计算预算）。
    """

    def __init__(self):
        self.settings = get_settings()
        self.cache: dict = {}
        self._rates: Optional[dict] = None

    async def get_rate(self, from_currency: str, to_currency: str = "USD") -> Optional[float]:
        """
        获取两种货币之间的汇率。

        Args:
            from_currency: 源货币代码（如 CNY, JPY）
            to_currency: 目标货币代码（默认 USD）

        Returns:
            汇率（如 1 CNY = 0.14 USD），失败时返回 None
        """
        cache_key = f"fx:{from_currency}_{to_currency}"
        if self.settings.CACHE_ENABLED and cache_key in self.cache:
            return self.cache[cache_key]

        if self.settings.MOCK_MODE:
            # Mock 汇率
            mock_rates = {"CNY": 0.14, "JPY": 0.0067, "EUR": 1.09, "GBP": 1.27, "KRW": 0.00074}
            rate = mock_rates.get(from_currency, 1.0)
            self.cache[cache_key] = rate
            return rate

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"https://api.frankfurter.app/latest",
                    params={"from": from_currency, "to": to_currency},
                )

                if resp.status_code == 422:
                    logger.warning("Exchange rate: unsupported currency %s", from_currency)
                    return None
                resp.raise_for_status()
                data = resp.json()

                rate = data.get("rates", {}).get(to_currency)
                if rate:
                    self.cache[cache_key] = rate
                return rate

        except Exception as e:
            logger.warning("Exchange rate API error: %s", e)
            return None

    async def convert_to_usd(self, amount: float, from_currency: str) -> float:
        """将指定货币金额转换为 USD。"""
        if from_currency.upper() == "USD":
            return amount

        rate = await self.get_rate(from_currency.upper(), "USD")
        if rate:
            return round(amount * rate, 2)
        return amount  # 转换失败时返回原值

    async def convert_from_usd(self, amount: float, to_currency: str) -> float:
        """将 USD 金额转换为指定货币。"""
        if to_currency.upper() == "USD":
            return amount

        rate = await self.get_rate("USD", to_currency.upper())
        if rate:
            return round(amount * rate, 2)
        return amount

    async def get_all_rates(self, base: str = "USD") -> dict:
        """获取所有主要货币对 USD 的汇率。"""
        cache_key = f"fx_all:{base}"
        if self.settings.CACHE_ENABLED and cache_key in self.cache:
            return self.cache[cache_key]

        if self.settings.MOCK_MODE:
            return {}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"https://api.frankfurter.app/latest",
                    params={"from": base},
                )
                resp.raise_for_status()
                data = resp.json()

                rates = data.get("rates", {})
                if self.settings.CACHE_ENABLED:
                    self.cache[cache_key] = rates
                return rates

        except Exception as e:
            logger.warning("Exchange rate all-rates error: %s", e)
            return {}

    def detect_currency(self, destination: str) -> str:
        """
        根据目的地城市推断当地货币。

        Returns:
            货币代码（如 JPY, CNY, EUR）
        """
        mapping = {
            "tokyo": "JPY", "osaka": "JPY", "kyoto": "JPY", "japan": "JPY",
            "paris": "EUR", "london": "GBP", "rome": "EUR", "barcelona": "EUR",
            "beijing": "CNY", "shanghai": "CNY", "china": "CNY",
            "seoul": "KRW", "korea": "KRW",
            "bangkok": "THB", "thailand": "THB",
            "singapore": "SGD",
            "hong kong": "HKD", "taipei": "TWD",
            "sydney": "AUD", "australia": "AUD",
            "dubai": "AED",
            "new york": "USD", "los angeles": "USD",
            "mumbai": "INR", "new delhi": "IND",
            "moscow": "RUB",
        }
        return mapping.get(destination.lower(), "USD")


# 全局单例
_exchange: Optional[ExchangeRateTool] = None


def get_exchange_rate() -> ExchangeRateTool:
    """获取 ExchangeRateTool 单例。"""
    global _exchange
    if _exchange is None:
        _exchange = ExchangeRateTool()
    return _exchange
