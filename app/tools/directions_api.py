"""
路线规划 API 工具 - 获取真实交通路线和行驶时间。
支持 Google Maps Directions API（需 Key）和 Nominatim 回退（免费）。
"""

import logging
from typing import Optional

import httpx

from app.config import get_settings
from app.tools.map_utils import MapUtils

logger = logging.getLogger(__name__)


class DirectionsTool:
    """
    路线规划工具。
    优先使用 Google Maps Directions API，回退到基于坐标的估算。
    """

    def __init__(self):
        self.settings = get_settings()
        self.map_utils = MapUtils()
        self.cache: dict = {}

    async def get_route(
        self,
        origin: str,
        destination: str,
        mode: str = "transit",
    ) -> Optional[dict]:
        """
        获取两点之间的路线详情。

        Returns:
            {
                "distance_km": float,
                "duration_minutes": int,
                "mode": str,
                "steps": list[str],
                "source": str,  # "google_maps" 或 "estimated"
            }
        """
        cache_key = f"route:{origin}:{destination}:{mode}"
        if self.settings.CACHE_ENABLED and cache_key in self.cache:
            return self.cache[cache_key]

        # 优先尝试 Google Maps
        if self.settings.GOOGLE_MAPS_API_KEY and not self.settings.MOCK_MODE:
            try:
                result = await self._get_google_maps_route(origin, destination, mode)
                if result:
                    if self.settings.CACHE_ENABLED:
                        self.cache[cache_key] = result
                    return result
            except Exception as e:
                logger.warning("Google Maps Directions failed: %s, using fallback", e)

        # 回退到估算
        distance = await self.map_utils.calculate_distance_km_async(origin, destination)
        duration = self.map_utils.estimate_travel_time_minutes(origin, destination, mode)

        result = {
            "distance_km": distance,
            "duration_minutes": duration,
            "mode": mode,
            "steps": [f"Travel from {origin} to {destination} ({distance} km)"],
            "source": "estimated",
        }

        if self.settings.CACHE_ENABLED:
            self.cache[cache_key] = result

        return result

    async def _get_google_maps_route(
        self, origin: str, destination: str, mode: str
    ) -> Optional[dict]:
        """
        调用 Google Maps Directions API 获取真实路线。

        API 文档: https://developers.google.com/maps/documentation/directions/start
        """
        mode_map = {"transit": "transit", "driving": "driving", "walking": "walking", "taxi": "driving"}
        api_mode = mode_map.get(mode, "transit")

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://maps.googleapis.com/maps/api/directions/json",
                params={
                    "origin": origin,
                    "destination": destination,
                    "mode": api_mode,
                    "key": self.settings.GOOGLE_MAPS_API_KEY,
                    "language": "en",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "OK" or not data.get("routes"):
                return None

            route = data["routes"][0]
            leg = route["legs"][0]

            distance_km = leg["distance"]["value"] / 1000
            duration_minutes = leg["duration"]["value"] // 60

            # 提取步骤
            steps = []
            for step in leg.get("steps", []):
                instruction = step.get("html_instructions", "")
                # 清理 HTML
                import re
                clean = re.sub(r'<[^>]+>', '', instruction).strip()
                steps.append(clean)

            return {
                "distance_km": round(distance_km, 1),
                "duration_minutes": duration_minutes,
                "mode": mode,
                "steps": steps[:10],  # 最多保留 10 个步骤
                "source": "google_maps",
            }

    async def get_multi_route_summary(
        self,
        locations: list[str],
        start_point: str,
        mode: str = "transit",
    ) -> dict:
        """
        获取多段路线的总距离和时间摘要。

        Returns:
            {"total_distance_km": float, "total_duration_minutes": int, "segments": list}
        """
        total_distance = 0.0
        total_duration = 0
        segments = []

        ordered = [start_point] + locations
        for i in range(len(ordered) - 1):
            route = await self.get_route(ordered[i], ordered[i + 1], mode)
            if route:
                total_distance += route["distance_km"]
                total_duration += route["duration_minutes"]
                segments.append({
                    "from": ordered[i],
                    "to": ordered[i + 1],
                    "distance_km": route["distance_km"],
                    "duration_minutes": route["duration_minutes"],
                    "source": route.get("source", "estimated"),
                })

        return {
            "total_distance_km": round(total_distance, 1),
            "total_duration_minutes": total_duration,
            "segments": segments,
        }


# 全局单例
_directions: Optional[DirectionsTool] = None


def get_directions() -> DirectionsTool:
    """获取 DirectionsTool 单例。"""
    global _directions
    if _directions is None:
        _directions = DirectionsTool()
    return _directions
