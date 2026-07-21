"""
高德地图 API 工具 - 面向中国用户的地理编码与路线规划。
提供中文地址解析、中国境内路线规划，支持无 Key 回退到 Nominatim。

API 文档: https://lbs.amap.com/api/webservice/guide/api/georegeo
免费额度: 个人开发者 5000 次/天（地理编码）
"""

import logging
from typing import Dict, Any, List, Optional, Tuple

import httpx

from app.config import get_settings
from app.tools.map_utils import MapUtils

logger = logging.getLogger(__name__)


class AmapAPI:
    """
    高德地图 Web Service API 封装。
    优先使用高德（中文地址更准），无 Key 或失败时回退到 Nominatim。
    """

    BASE_URL = "https://restapi.amap.com/v3"

    def __init__(self):
        self.settings = get_settings()
        self.key = self.settings.AMAP_KEY
        self.fallback_map = MapUtils()
        self.cache: Dict[str, Any] = {}

    async def geocode(self, address: str) -> Optional[Tuple[float, float]]:
        """
        地理编码：将中文地址转换为经纬度坐标。
        优先高德，无 Key 或失败时回退 Nominatim。
        """
        cache_key = f"amap_geo_{address}"
        if self.settings.CACHE_ENABLED and cache_key in self.cache:
            return self.cache[cache_key]

        # 优先使用高德
        if self.key:
            try:
                coords = await self._geocode_amap(address)
                if coords:
                    if self.settings.CACHE_ENABLED:
                        self.cache[cache_key] = coords
                    return coords
            except Exception as e:
                logger.warning("Amap geocode failed for '%s': %s", address, e)

        # 回退到 Nominatim（MapUtils 内置缓存）
        try:
            coords = await self.fallback_map.get_coordinates_async(address)
            if self.settings.CACHE_ENABLED:
                self.cache[cache_key] = coords
            return coords
        except Exception as e:
            logger.warning("Fallback geocoding also failed: %s", e)
            return None

    async def _geocode_amap(self, address: str) -> Optional[Tuple[float, float]]:
        """调用高德地理编码 API。"""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.BASE_URL}/geocode/geo",
                params={
                    "key": self.key,
                    "address": address,
                    "output": "JSON",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") == "1" and data.get("geocodes"):
                location = data["geocodes"][0].get("location", "")
                if "," in location:
                    lng, lat = location.split(",")
                    return (float(lat), float(lng))

            logger.warning("Amap geocode no result for '%s': %s", address, data.get("info"))
            return None

    async def get_route(
        self,
        origin: str,
        destination: str,
        mode: str = "driving",
    ) -> Optional[Dict[str, Any]]:
        """
        路线规划：获取两地之间的路线信息（距离、时间、交通方式）。
        mode: driving | bus | walking | riding
        """
        cache_key = f"amap_route_{origin}_{destination}_{mode}"
        if self.settings.CACHE_ENABLED and cache_key in self.cache:
            return self.cache[cache_key]

        # 优先高德
        if self.key:
            try:
                route = await self._route_amap(origin, destination, mode)
                if route:
                    if self.settings.CACHE_ENABLED:
                        self.cache[cache_key] = route
                    return route
            except Exception as e:
                logger.warning("Amap route failed: %s", e)

        # 回退：使用 MapUtils 估算
        try:
            dist = self.fallback_map.calculate_distance_km(origin, destination)
            time_mins = self.fallback_map.estimate_travel_time_minutes(origin, destination, mode)
            route = {
                "distance_km": dist,
                "duration_minutes": time_mins,
                "mode": mode,
                "source": "estimated",
                "steps": [],
            }
            if self.settings.CACHE_ENABLED:
                self.cache[cache_key] = route
            return route
        except Exception as e:
            logger.warning("Fallback route estimation failed: %s", e)
            return None

    async def _route_amap(
        self,
        origin: str,
        destination: str,
        mode: str = "driving",
    ) -> Optional[Dict[str, Any]]:
        """调用高德路线规划 API。"""
        # 先获取坐标
        origin_coords = await self.geocode(origin)
        dest_coords = await self.geocode(destination)

        if not origin_coords or not dest_coords:
            return None

        origin_str = f"{origin_coords[1]},{origin_coords[0]}"  # lng,lat
        dest_str = f"{dest_coords[1]},{dest_coords[0]}"

        # 映射 mode 到高德 API path
        mode_map = {
            "driving": "direction/driving",
            "bus": "direction/transit/integrated",
            "walking": "direction/walking",
            "riding": "direction/riding",
            "transit": "direction/transit/integrated",
        }
        path = mode_map.get(mode, "direction/driving")

        async with httpx.AsyncClient(timeout=15.0) as client:
            params = {
                "key": self.key,
                "origin": origin_str,
                "destination": dest_str,
                "output": "JSON",
            }
            # 公交需要城市参数，用目的地城市估算
            if "transit" in path:
                params["city"] = destination
                params["cityd"] = destination

            resp = await client.get(
                f"{self.BASE_URL}/{path}",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") == "1" and data.get("route"):
                route_data = data["route"]
                paths = route_data.get("paths", [])
                if paths:
                    best = paths[0]
                    distance_m = int(best.get("distance", 0))
                    duration_s = int(best.get("duration", 0))
                    steps = best.get("steps", [])

                    return {
                        "distance_km": round(distance_m / 1000, 2),
                        "duration_minutes": round(duration_s / 60, 1),
                        "mode": mode,
                        "source": "amap",
                        "steps": [s.get("instruction", "") for s in steps[:5]],
                        "toll_distance_km": round(int(best.get("toll_distance", 0)) / 1000, 2) if "toll_distance" in best else None,
                    }

            logger.warning("Amap route no result: %s", data.get("info"))
            return None

    async def get_district(self, keywords: str) -> Optional[Dict[str, Any]]:
        """
        行政区域查询：获取城市/区域的边界、中心点、行政级别等信息。
        用于 Planner Agent 了解目的地城市概况。
        """
        if not self.key:
            return None

        cache_key = f"amap_district_{keywords}"
        if self.settings.CACHE_ENABLED and cache_key in self.cache:
            return self.cache[cache_key]

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/config/district",
                    params={
                        "key": self.key,
                        "keywords": keywords,
                        "subdistrict": 1,
                        "extensions": "all",
                        "output": "JSON",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("status") == "1" and data.get("districts"):
                    district = data["districts"][0]
                    result = {
                        "name": district.get("name"),
                        "center": district.get("center"),
                        "level": district.get("level"),  # country, province, city, district
                        "adcode": district.get("adcode"),
                        "children": [d.get("name") for d in district.get("districts", [])],
                    }
                    if self.settings.CACHE_ENABLED:
                        self.cache[cache_key] = result
                    return result
        except Exception as e:
            logger.warning("Amap district query failed: %s", e)

        return None

    # ========== POI 搜索（酒店 + 餐厅） ==========

    async def search_hotels(
        self,
        city: str,
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        搜索城市内的酒店（POI）。
        使用高德 POI 分类码 100000（住宿服务）。
        无 Key 或非中国目的地时返回空列表，由调用方回退。
        """
        return await self._search_poi(
            city=city,
            keywords="酒店",
            types="100000",
            max_results=max_results,
        )

    async def search_restaurants(
        self,
        city: str,
        keywords: str = "美食",
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        搜索城市内的餐厅（POI）。
        使用高德 POI 分类码 050000（餐饮服务）。
        无 Key 或非中国目的地时返回空列表，由调用方回退。
        """
        return await self._search_poi(
            city=city,
            keywords=keywords,
            types="050000",
            max_results=max_results,
        )

    async def search_attractions(
        self,
        city: str,
        keywords: str = "景点",
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        搜索城市内的景点/风景名胜（POI）。
        使用高德 POI 分类码 110000（风景名胜）。
        无 Key 或非中国目的地时返回空列表，由调用方回退。
        """
        return await self._search_poi(
            city=city,
            keywords=keywords,
            types="110000",
            max_results=max_results,
        )

    async def _search_poi(
        self,
        city: str,
        keywords: str,
        types: str,
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """通用 POI 搜索（关键词搜索）。"""
        if not self.key:
            return []

        cache_key = f"amap_poi_{city}_{types}_{keywords}_{max_results}"
        if self.settings.CACHE_ENABLED and cache_key in self.cache:
            return self.cache[cache_key]

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/place/text",
                    params={
                        "key": self.key,
                        "keywords": keywords,
                        "types": types,
                        "city": city,
                        "offset": min(max_results, 25),
                        "page": 1,
                        "extensions": "all",  # 返回详细字段（含评分、价格等）
                        "output": "JSON",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("status") == "1" and data.get("pois"):
                    pois = []
                    for p in data["pois"][:max_results]:
                        poi = {
                            "name": p.get("name", ""),
                            "address": p.get("address", ""),
                            "location": p.get("location", ""),
                            "tel": p.get("tel", ""),
                            "type": p.get("type", ""),
                            "rating": self._extract_poi_rating(p),
                            "price": self._extract_poi_price(p),
                            "photos": p.get("photos", []),
                            "biz_ext": p.get("biz_ext", {}),
                        }
                        pois.append(poi)

                    if self.settings.CACHE_ENABLED:
                        self.cache[cache_key] = pois
                    return pois

        except Exception as e:
            logger.warning("Amap POI search failed for %s/%s: %s", city, types, e)

        return []

    def _extract_poi_rating(self, poi: Dict) -> Optional[float]:
        """从 POI 详情中提取评分。"""
        # biz_ext 中可能有 rating 字段
        biz_ext = poi.get("biz_ext", {}) or {}
        rating = biz_ext.get("rating")
        if rating:
            try:
                return float(rating)
            except (ValueError, TypeError):
                pass
        return None

    def _extract_poi_price(self, poi: Dict) -> Optional[float]:
        """从 POI 详情中提取人均消费/价格。"""
        biz_ext = poi.get("biz_ext", {}) or {}
        cost = biz_ext.get("cost")
        if cost:
            try:
                return float(cost)
            except (ValueError, TypeError):
                pass
        return None


# 全局单例
_amap_api: Optional[AmapAPI] = None


def get_amap_api() -> AmapAPI:
    """获取 AmapAPI 单例。"""
    global _amap_api
    if _amap_api is None:
        _amap_api = AmapAPI()
    return _amap_api
