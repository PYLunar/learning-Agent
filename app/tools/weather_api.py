"""
天气查询工具 - 接入真实 OpenWeatherMap API，支持 Mock 回退。
"""

import random
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

import httpx

from app.config import get_settings
from app.state import WeatherDay

logger = logging.getLogger(__name__)


class WeatherTool:
    """天气查询工具。优先使用 OpenWeatherMap 真实 API，无 Key 时回退 Mock 数据。"""

    def __init__(self):
        self.settings = get_settings()
        self.cache: Dict[str, Any] = {}

    async def get_forecast(
        self,
        city: str,
        days: int = 5,
    ) -> List[WeatherDay]:
        """获取天气预报。有 API Key 用真实数据，否则用 Mock。"""
        cache_key = f"weather_{city}_{days}"
        if self.settings.CACHE_ENABLED and cache_key in self.cache:
            return self.cache[cache_key]

        if self.settings.WEATHER_API_KEY and not self.settings.MOCK_MODE:
            try:
                results = await self._fetch_openweather(city, days)
            except Exception as e:
                logger.warning("OpenWeatherMap API failed: %s, using mock", e)
                results = self._generate_mock_weather(city, days)
        else:
            results = self._generate_mock_weather(city, days)

        if self.settings.CACHE_ENABLED:
            self.cache[cache_key] = results

        return results

    async def _fetch_openweather(self, city: str, days: int) -> List[WeatherDay]:
        """
        调用真实 OpenWeatherMap API 获取天气预报。

        API 文档: https://openweathermap.org/api/forecast5
        """
        api_key = self.settings.WEATHER_API_KEY

        async with httpx.AsyncClient(timeout=15.0) as client:
            # 先通过 geocoding 获取城市坐标
            geo_resp = await client.get(
                "http://api.openweathermap.org/geo/1.0/direct",
                params={"q": city, "limit": 1, "appid": api_key},
            )
            geo_resp.raise_for_status()
            geo_data = geo_resp.json()

            if not geo_data:
                logger.warning("OpenWeatherMap: city '%s' not found", city)
                return self._generate_mock_weather(city, days)

            lat = geo_data[0]["lat"]
            lon = geo_data[0]["lon"]
            city_name = geo_data[0].get("local_names", {}).get("zh", geo_data[0].get("name", city))

            # 获取 5 天 / 3 小时预报
            forecast_resp = await client.get(
                "https://api.openweathermap.org/data/2.5/forecast",
                params={
                    "lat": lat,
                    "lon": lon,
                    "appid": api_key,
                    "units": "metric",
                    "cnt": min(days * 8, 40),  # 每 3 小时一个数据点
                },
            )
            forecast_resp.raise_for_status()
            forecast_data = forecast_resp.json()

            # 按天聚合
            daily_map: Dict[str, dict] = {}
            for item in forecast_data.get("list", []):
                date_str = item["dt_txt"].split(" ")[0]
                if date_str not in daily_map:
                    daily_map[date_str] = {
                        "temps_high": float(item["main"]["temp_max"]),
                        "temps_low": float(item["main"]["temp_min"]),
                        "conditions": [],
                        "humidity": item["main"]["humidity"],
                        "wind": item["wind"]["speed"],
                    }
                else:
                    day = daily_map[date_str]
                    day["temps_high"] = max(day["temps_high"], float(item["main"]["temp_max"]))
                    day["temps_low"] = min(day["temps_low"], float(item["main"]["temp_min"]))

                # 天气状况
                weather_desc = item["weather"][0]["description"]
                weather_main = item["weather"][0]["main"]
                if weather_main.lower() not in [c.lower() for c in day["conditions"]]:
                    day["conditions"].append(weather_main)

            # 转换为 WeatherDay 格式
            weather_days = []
            sorted_dates = sorted(daily_map.keys())[:days]
            for date_str in sorted_dates:
                day_data = daily_map[date_str]
                condition = self._translate_condition(day_data["conditions"])
                high = day_data["temps_high"]
                low = day_data["temps_low"]
                recommendation = self._get_weather_recommendation(condition, high)

                weather_days.append(WeatherDay(
                    date=date_str,
                    condition=condition,
                    temperature_high=high,
                    temperature_low=low,
                    precipitation_chance=self._estimate_precipitation(day_data["conditions"]),
                    recommendation=recommendation,
                ))

            return weather_days

    def _translate_condition(self, conditions: list) -> str:
        """将 OpenWeatherMap 天气代码翻译为中文描述。"""
        if not conditions:
            return "未知"
        mapping = {
            "Clear": "晴",
            "Clouds": "多云",
            "Rain": "雨",
            "Drizzle": "小雨",
            "Thunderstorm": "雷阵雨",
            "Snow": "雪",
            "Mist": "薄雾",
            "Fog": "雾",
            "Haze": "霾",
        }
        primary = conditions[0]
        return mapping.get(primary, primary)

    def _estimate_precipitation(self, conditions: list) -> float:
        """根据天气状况估算降水概率。"""
        rain_conditions = ["rain", "drizzle", "thunderstorm", "snow"]
        for c in conditions:
            if c.lower() in rain_conditions:
                return random.uniform(40, 90)
        return random.uniform(5, 25)

    def _generate_mock_weather(self, city: str, days: int) -> List[WeatherDay]:
        """生成 Mock 天气数据（无 API Key 时使用，中文输出）。"""
        conditions = ["晴", "多云", "阴", "小雨", "晴"]
        base_temp = random.randint(15, 30)

        weather_days = []
        start_date = datetime.now()

        for i in range(days):
            condition = random.choice(conditions)
            high = base_temp + random.randint(-3, 5)
            low = high - random.randint(5, 12)

            recommendation = self._get_weather_recommendation(condition, high)

            day = WeatherDay(
                date=(start_date + timedelta(days=i)).strftime("%Y-%m-%d"),
                condition=condition,
                temperature_high=float(high),
                temperature_low=float(low),
                precipitation_chance=random.randint(0, 60) if "雨" in condition else random.randint(0, 20),
                recommendation=recommendation,
            )
            weather_days.append(day)

        return weather_days

    def _get_weather_recommendation(self, condition: str, temp: float) -> str:
        """根据天气生成中文出行建议。"""
        if "雨" in condition or "雷" in condition:
            return "🌧️ 记得带伞。适合室内活动，如博物馆、购物。"
        elif "雪" in condition:
            return "❄️ 下雪天。注意保暖，部分室外景点可能关闭。"
        elif temp > 28:
            return "🌡️ 高温天气。注意防暑，多安排室内休息。"
        elif temp < 10:
            return "🧥 天气寒冷。注意保暖，适合室内景点。"
        elif "晴" in condition:
            return "☀️ 天气晴好，非常适合户外观光和步行游览。"
        elif "雾" in condition or "霾" in condition:
            return "🌫️ 有雾/霾。建议戴口罩，减少户外长时间活动。"
        else:
            return "⛅ 天气舒适，适合大多数户外和室内活动。"
