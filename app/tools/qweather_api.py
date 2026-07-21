"""
和风天气 API 工具 - 面向中国用户的中文天气数据源。
支持中文城市名直接查询，无需先转坐标，天气描述原生中文。
免费开发版: 1000 次/天

API 文档: https://dev.qweather.com/docs/api/
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

import httpx

from app.config import get_settings
from app.state import WeatherDay

logger = logging.getLogger(__name__)


class QWeatherTool:
    """
    和风天气 API 封装。
    优先使用和风（中文城市名直接查，描述原生中文），无 Key 时回退 OpenWeatherMap 或 Mock。
    """

    # 开发版免费 API 地址
    GEO_API = "https://geoapi.qweather.com/v2"
    DEV_API = "https://devapi.qweather.com/v7"

    def __init__(self):
        self.settings = get_settings()
        self.key = self.settings.QWEATHER_KEY
        self.cache: Dict[str, Any] = {}

    async def get_forecast(
        self,
        city: str,
        days: int = 7,
    ) -> List[WeatherDay]:
        """
        获取天气预报。优先和风天气，无 Key 或失败时回退 OpenWeatherMap/Mock。
        """
        cache_key = f"qweather_{city}_{days}"
        if self.settings.CACHE_ENABLED and cache_key in self.cache:
            return self.cache[cache_key]

        # 优先和风天气
        if self.key and not self.settings.MOCK_MODE:
            try:
                results = await self._fetch_qweather(city, days)
                if results:
                    if self.settings.CACHE_ENABLED:
                        self.cache[cache_key] = results
                    return results
            except Exception as e:
                logger.warning("QWeather API failed: %s, will fallback", e)

        # 回退到 OpenWeatherMap（如果配置了 Key）
        if self.settings.WEATHER_API_KEY and not self.settings.MOCK_MODE:
            try:
                from app.tools.weather_api import WeatherTool
                tool = WeatherTool()
                results = await tool._fetch_openweather(city, days)
                if self.settings.CACHE_ENABLED:
                    self.cache[cache_key] = results
                return results
            except Exception as e:
                logger.warning("OpenWeatherMap fallback failed: %s", e)

        # 最终回退 Mock
        from app.tools.weather_api import WeatherTool
        tool = WeatherTool()
        results = tool._generate_mock_weather(city, days)
        if self.settings.CACHE_ENABLED:
            self.cache[cache_key] = results
        return results

    async def _fetch_qweather(self, city: str, days: int) -> Optional[List[WeatherDay]]:
        """调用和风天气 API 获取天气预报。"""
        # 1. 城市查询：中文城市名 → LocationID
        location_id = await self._lookup_city(city)
        if not location_id:
            logger.warning("QWeather: city '%s' not found", city)
            return None

        # 2. 7天天气预报
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{self.DEV_API}/weather/7d",
                params={
                    "location": location_id,
                    "key": self.key,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != "200":
                logger.warning("QWeather API error: %s", data.get("code"))
                return None

            daily = data.get("daily", [])
            weather_days = []

            for item in daily[:days]:
                # 和风天气原生中文描述
                condition = item.get("textDay", "Unknown")
                high = float(item.get("tempMax", 0))
                low = float(item.get("tempMin", 0))
                wind_dir = item.get("windDirDay", "")
                wind_scale = item.get("windScaleDay", "")
                humidity = item.get("humidity", "")

                # 生成中文出行建议
                recommendation = self._get_recommendation_zh(condition, high)

                weather_days.append(WeatherDay(
                    date=item.get("fxDate", ""),
                    condition=condition,
                    temperature_high=high,
                    temperature_low=low,
                    precipitation_chance=self._estimate_precip(condition),
                    recommendation=f"{recommendation} 风向{wind_dir}{wind_scale}级，湿度{humidity}%",
                ))

            return weather_days

    async def _lookup_city(self, city: str) -> Optional[str]:
        """城市查询：返回 LocationID。"""
        cache_key = f"qweather_city_{city}"
        if self.settings.CACHE_ENABLED and cache_key in self.cache:
            return self.cache[cache_key]

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.GEO_API}/city/lookup",
                params={
                    "location": city,
                    "key": self.key,
                    "range": "cn",  # 优先中国
                },
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") == "200" and data.get("location"):
                location_id = data["location"][0]["id"]
                if self.settings.CACHE_ENABLED:
                    self.cache[cache_key] = location_id
                return location_id

        return None

    def _estimate_precip(self, condition: str) -> float:
        """根据中文天气描述估算降水概率。"""
        rain_keywords = ["雨", "阵雨", "雷阵雨", "暴雨", "大雨", "中雨", "小雨", "雪", "暴雪"]
        for kw in rain_keywords:
            if kw in condition:
                return 70.0
        cloudy_keywords = ["多云", "阴", "雾", "霾"]
        for kw in cloudy_keywords:
            if kw in condition:
                return 30.0
        return 10.0

    def _get_recommendation_zh(self, condition: str, temp: float) -> str:
        """根据中文天气生成中文出行建议。"""
        if any(k in condition for k in ["暴雨", "大雨", "雷阵雨"]):
            return "🌧️ 雨势较大，建议减少外出，安排室内景点或购物。"
        elif any(k in condition for k in ["小雨", "中雨", "阵雨"]):
            return "🌦️ 有雨，记得带伞，可安排室内外结合的活动。"
        elif any(k in condition for k in ["雪", "暴雪", "大雪"]):
            return "❄️ 降雪天气，注意保暖防滑，部分景点可能关闭。"
        elif temp > 35:
            return "🌡️ 高温天气，注意防暑降温，多安排室内休息。"
        elif temp < 0:
            return "🥶 严寒天气，务必做好保暖，室内景点优先。"
        elif temp < 10:
            return "🧥 天气较冷，注意保暖，适合室内景点和美食探索。"
        elif any(k in condition for k in ["晴", "少云"]):
            return "☀️ 天气晴好，非常适合户外观光和拍照。"
        elif any(k in condition for k in ["雾", "霾"]):
            return "🌫️ 能见度较低，建议戴口罩，减少户外长时间活动。"
        else:
            return "⛅ 天气尚可，适合大多数户外和室内活动。"

    async def get_air_quality(self, city: str) -> Optional[Dict[str, Any]]:
        """
        获取实时空气质量（AQI）。
        需要城市 LocationID。
        """
        if not self.key:
            return None

        location_id = await self._lookup_city(city)
        if not location_id:
            return None

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.DEV_API}/air/now",
                    params={
                        "location": location_id,
                        "key": self.key,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("code") == "200" and data.get("now"):
                    now = data["now"]
                    return {
                        "aqi": now.get("aqi"),
                        "level": now.get("category"),  # 优/良/轻度污染...
                        "pm25": now.get("pm2p5"),
                        "pm10": now.get("pm10"),
                        "primary_pollutant": now.get("primary"),
                    }
        except Exception as e:
            logger.warning("QWeather air quality failed: %s", e)

        return None


# 全局单例
_qweather: Optional[QWeatherTool] = None


def get_qweather() -> QWeatherTool:
    """获取 QWeatherTool 单例。"""
    global _qweather
    if _qweather is None:
        _qweather = QWeatherTool()
    return _qweather
