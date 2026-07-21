"""
地图与路线计算工具 - 接入真实 Nominatim 地理编码 API，支持 Mock 回退。
"""

import math
import logging
from typing import List, Dict, Any, Optional, Tuple

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class MapUtils:
    """
    地图与路线计算工具。
    优先使用 Nominatim（OpenStreetMap）免费地理编码 API 获取真实坐标，
    内置热门城市缓存，未知城市回退到基于哈希的伪坐标。
    """

    # 热门城市坐标缓存
    CITY_COORDS: Dict[str, Tuple[float, float]] = {
        "tokyo": (35.6762, 139.6503),
        "osaka": (34.6937, 135.5023),
        "kyoto": (35.0116, 135.7681),
        "paris": (48.8566, 2.3522),
        "london": (51.5074, -0.1278),
        "new york": (40.7128, -74.0060),
        "beijing": (39.9042, 116.4074),
        "shanghai": (31.2304, 121.4737),
        "seoul": (37.5665, 126.9780),
        "bangkok": (13.7563, 100.5018),
        "singapore": (1.3521, 103.8198),
        "sydney": (-33.8688, 151.2093),
        "dubai": (25.2048, 55.2708),
        "rome": (41.9028, 12.4964),
        "barcelona": (41.3851, 2.1734),
        "hong kong": (22.3193, 114.1694),
        "taipei": (25.0330, 121.5654),
        "new delhi": (28.6139, 77.2090),
        "istanbul": (41.0082, 28.9784),
        "amsterdam": (52.3676, 4.9041),
    }

    def __init__(self):
        self.settings = get_settings()
        self.cache: Dict[str, Any] = {}

    async def get_coordinates_async(self, location: str) -> Tuple[float, float]:
        """
        异步获取地点坐标。
        优先：内置缓存 → 高德 API → Nominatim API → 哈希伪坐标
        """
        cache_key = f"coords_{location.lower()}"
        if self.settings.CACHE_ENABLED and cache_key in self.cache:
            return self.cache[cache_key]

        # 1. 内置城市缓存
        coords = self.CITY_COORDS.get(location.lower())
        if coords:
            if self.settings.CACHE_ENABLED:
                self.cache[cache_key] = coords
            return coords

        # 2. 高德 API（中文地址更准确）
        if not self.settings.MOCK_MODE and self.settings.AMAP_KEY:
            try:
                from app.tools.amap_api import get_amap_api
                amap = get_amap_api()
                coords = await amap.geocode(location)
                if coords:
                    if self.settings.CACHE_ENABLED:
                        self.cache[cache_key] = coords
                    return coords
            except Exception as e:
                logger.warning("Amap geocoding failed for '%s': %s", location, e)

        # 3. Nominatim API（免费，无需 Key）
        if not self.settings.MOCK_MODE:
            try:
                coords = await self._fetch_nominatim(location)
                if coords:
                    if self.settings.CACHE_ENABLED:
                        self.cache[cache_key] = coords
                    return coords
            except Exception as e:
                logger.warning("Nominatim geocoding failed for '%s': %s", location, e)

        # 3. 哈希伪坐标回退
        coords = self._hash_coordinates(location)
        if self.settings.CACHE_ENABLED:
            self.cache[cache_key] = coords
        return coords

    def get_coordinates(self, location: str) -> Tuple[float, float]:
        """同步获取坐标（使用缓存或回退）。"""
        cache_key = f"coords_{location.lower()}"
        if self.settings.CACHE_ENABLED and cache_key in self.cache:
            return self.cache[cache_key]

        coords = self.CITY_COORDS.get(location.lower())
        if coords:
            self.cache[cache_key] = coords
            return coords

        coords = self._hash_coordinates(location)
        self.cache[cache_key] = coords
        return coords

    async def _fetch_nominatim(self, location: str) -> Optional[Tuple[float, float]]:
        """
        调用 Nominatim（OpenStreetMap）免费地理编码 API。

        API 文档: https://nominatim.org/release-docs/develop/api/Search/
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q": location,
                    "format": "json",
                    "limit": 1,
                    "accept-language": "en",
                },
                headers={"User-Agent": "TravelAgent/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()

            if data:
                lat = float(data[0]["lat"])
                lon = float(data[0]["lon"])
                return (lat, lon)

            return None

    def _hash_coordinates(self, location: str) -> Tuple[float, float]:
        """基于哈希生成稳定的伪坐标（回退方案）。"""
        hash_val = hash(location.lower()) % 10000
        lat = (hash_val % 180) - 90 + (hash_val % 100) / 100
        lng = ((hash_val // 180) % 360) - 180 + ((hash_val // 100) % 100) / 100
        return (lat, lng)

    def calculate_distance_km(self, loc1: str, loc2: str) -> float:
        """计算两地之间的直线距离（公里），使用 Haversine 公式。"""
        cache_key = f"dist_{loc1.lower()}_{loc2.lower()}"
        if self.settings.CACHE_ENABLED and cache_key in self.cache:
            return self.cache[cache_key]

        coord1 = self.get_coordinates(loc1)
        coord2 = self.get_coordinates(loc2)

        lat1, lon1 = math.radians(coord1[0]), math.radians(coord1[1])
        lat2, lon2 = math.radians(coord2[0]), math.radians(coord2[1])

        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))
        r = 6371

        distance = round(c * r, 2)

        if self.settings.CACHE_ENABLED:
            self.cache[cache_key] = distance

        return distance

    async def calculate_distance_km_async(self, loc1: str, loc2: str) -> float:
        """异步计算两地之间的直线距离（先解析坐标再计算）。"""
        coord1 = await self.get_coordinates_async(loc1)
        coord2 = await self.get_coordinates_async(loc2)

        lat1, lon1 = math.radians(coord1[0]), math.radians(coord1[1])
        lat2, lon2 = math.radians(coord2[0]), math.radians(coord2[1])

        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))

        return round(6371 * c, 2)

    def estimate_travel_time_minutes(self, loc1: str, loc2: str, mode: str = "transit") -> int:
        """估算两地之间的交通时间（分钟）。"""
        distance = self.calculate_distance_km(loc1, loc2)

        speeds = {"walking": 5, "transit": 25, "driving": 35, "taxi": 30}
        speed = speeds.get(mode, 25)

        overhead = {"walking": 0, "transit": 15, "driving": 5, "taxi": 5}
        return int((distance / speed) * 60 + overhead.get(mode, 10))

    def optimize_route(self, locations: List[str], start_point: str) -> List[str]:
        """使用最近邻算法优化游览顺序。"""
        if not locations:
            return []

        unvisited = locations.copy()
        route = [start_point]
        current = start_point

        while unvisited:
            closest = min(unvisited, key=lambda loc: self.calculate_distance_km(current, loc))
            route.append(closest)
            unvisited.remove(closest)
            current = closest

        return route

    async def resolve_locations_async(self, locations: List[str]) -> Dict[str, Tuple[float, float]]:
        """批量异步解析多个地点的坐标。"""
        results = {}
        for loc in locations:
            coords = await self.get_coordinates_async(loc)
            results[loc] = coords
        return results
