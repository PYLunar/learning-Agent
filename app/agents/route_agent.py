"""
Route Optimization Agent - 使用真实路线 API 优化每日行程顺序。
"""

import json
import logging
from typing import List, Dict, Any

from app.state import TravelState, RouteDay
from app.llm_client import get_llm_client
from app.prompts import get_system_prompt, get_user_prompt
from app.tools.map_utils import MapUtils
from app.tools.directions_api import get_directions
from app.tools.amap_api import get_amap_api

logger = logging.getLogger(__name__)


class RouteAgent:
    """路线优化智能体。优先使用高德地图 API（中国用户），回退到 Google Directions API。"""

    def __init__(self):
        self.llm = get_llm_client()
        self.map = MapUtils()
        self.directions = get_directions()
        self.amap = get_amap_api()

    async def run(self, state: TravelState) -> dict:
        """使用真实路线数据优化每日行程顺序。"""
        output = {}
        try:
            logger.info("RouteAgent: 正在优化路线")

            destination = state.get("destination", "")
            days = state.get("days", 1)
            attractions = state.get("attractions", [])
            hotels = state.get("hotels", [])
            food = state.get("food_recommendations", [])
            lang = state.get("user_input", {}).get("language", "zh")
            from app.config import get_settings

            llm_route_data = {}
            if get_settings().ENABLE_LLM_ENHANCEMENT and not attractions:
                llm_route_data = await self._get_llm_route(destination, days, attractions, hotels, food, lang)

            # Group attractions by day
            attractions_by_day: Dict[int, List[Dict[str, Any]]] = {}
            for a in attractions:
                day = a.get("day", 1)
                attractions_by_day.setdefault(day, []).append(a)

            # Build route for each day
            route = []
            hotel_name = hotels[0].get("name", destination) if hotels else destination

            for day in range(1, days + 1):
                day_attractions = attractions_by_day.get(day, [])
                attr_names = [a.get("name", f"景点{i+1}") for i, a in enumerate(day_attractions)]

                if attr_names:
                    # 有景点数据：优化顺序
                    optimized = self.map.optimize_route(attr_names, hotel_name)
                    optimized = optimized[1:] if len(optimized) > 1 else optimized

                    n = len(optimized)
                    morning = optimized[:max(1, n // 3)] if n > 0 else []
                    afternoon = optimized[max(1, n // 3):max(1, 2 * n // 3)] if n > 1 else []
                    evening = optimized[max(1, 2 * n // 3):] if n > 2 else []

                    # 按天分配不同美食推荐（避免重复）
                    day_food = [f.get("name", "") for f in food if f.get("meal_type") in ["lunch", "dinner"]]
                    if day_food:
                        # 按天轮换分配美食，每天取不同的餐厅
                        food_idx = (day - 1) % len(day_food)
                        assigned_food = day_food[food_idx]
                        if not afternoon:
                            afternoon = [assigned_food]
                        elif not evening:
                            evening = [assigned_food]

                    route.append(RouteDay(
                        day=day,
                        morning=morning,
                        afternoon=afternoon,
                        evening=evening,
                        transport_between=[],
                        estimated_walking_km=0.0,
                    ))
                else:
                    # 没有景点数据：用 LLM 生成的行程填充
                    llm_day = llm_route_data.get(day, {})
                    morning = llm_day.get("morning", [])
                    afternoon = llm_day.get("afternoon", [])
                    evening = llm_day.get("evening", [])

                    if not morning and not afternoon and not evening:
                        continue

                    route.append(RouteDay(
                        day=day,
                        morning=morning,
                        afternoon=afternoon,
                        evening=evening,
                        transport_between=llm_day.get("transport_between", []),
                        estimated_walking_km=float(llm_day.get("estimated_walking_km", 2.0)),
                    ))

            output["route"] = route
            output["logs"] = [{
                "agent": "route",
                "action": "route_optimization",
                "output": f"已优化 {len(route)} 天路线",
                "status": "success",
            }]

            logger.info("RouteAgent: 已优化 %d 天路线", len(route))

        except Exception as e:
            logger.error("RouteAgent error: %s", str(e))
            output["errors"] = [f"RouteAgent: {str(e)}"]
            output["route"] = self._fallback_route(state.get("days", 1), state.get("destination", ""))

        return output

    async def _get_llm_route(
        self, destination: str, days: int, attractions: list, hotels: list, food: list, lang: str
    ) -> Dict[int, Dict]:
        """调用 LLM 生成每日行程框架。"""
        try:
            system_prompt = get_system_prompt("route", lang)
            user_prompt = get_user_prompt("route", lang).format(
                destination=destination,
                attractions=[a.get("name", "") for a in attractions],
                hotels=[h.get("name", "") for h in hotels],
                food=[f.get("name", "") for f in food],
            )

            response = await self.llm.chat_completion(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format="json",
            )

            result = json.loads(response)
            llm_route = result.get("route", [])

            # 转为按天索引的字典
            by_day = {}
            for i, r in enumerate(llm_route):
                day_num = r.get("day", i + 1)
                by_day[day_num] = r

            return by_day
        except Exception as e:
            logger.warning("RouteAgent: LLM 路线生成失败: %s", e)
            return {}

    async def _calc_transport(self, hotel_name: str, stops: List[str]) -> List[str]:
        """计算交通信息。"""
        transport_between = []
        all_stops = [hotel_name] + stops
        for i in range(len(all_stops) - 1):
            route_info = None
            # 1. Try Amap
            try:
                route_info = await self.amap.get_route(all_stops[i], all_stops[i + 1], "transit")
            except Exception:
                pass
            # 2. Fallback to Google Directions
            if not route_info:
                try:
                    route_info = await self.directions.get_route(all_stops[i], all_stops[i + 1], "transit")
                except Exception:
                    pass
            if route_info:
                dist = route_info["distance_km"]
                time_mins = route_info["duration_minutes"]
                source = route_info.get("source", "estimated")
                transport_between.append(
                    f"{all_stops[i]} → {all_stops[i + 1]}: ~{time_mins} 分钟 ({dist} 公里)"
                )
            else:
                time_mins = self.map.estimate_travel_time_minutes(all_stops[i], all_stops[i + 1])
                transport_between.append(f"{all_stops[i]} → {all_stops[i + 1]}: ~{time_mins} 分钟")
        return transport_between

    async def _calc_walking_distance(self, stops: List[str]) -> float:
        """计算步行总距离。"""
        total_dist = 0.0
        for i in range(len(stops) - 1):
            try:
                dist = await self.map.calculate_distance_km_async(stops[i], stops[i + 1])
                total_dist += dist
            except Exception:
                total_dist += 1.0  # 固定估算 1km，不随机
        return total_dist

    def _fallback_route(self, days: int, destination: str = "") -> List[RouteDay]:
        """生成中文回退路线。"""
        route = []
        for day in range(1, days + 1):
            route.append(RouteDay(
                day=day,
                morning=[f"{destination}市区观光"] if destination else [f"第{day}天上午活动"],
                afternoon=[f"{destination}特色体验"] if destination else [f"第{day}天下午活动"],
                evening=[f"{destination}夜景美食"] if destination else [f"第{day}天晚上活动"],
                transport_between=[],
                estimated_walking_km=2.0,  # 固定估算，不随机
            ))
        return route
