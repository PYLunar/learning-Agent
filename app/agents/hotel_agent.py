"""
Hotel Agent - 酒店推荐智能体。
"""

import json
import logging
from typing import List

from app.state import TravelState, HotelOption
from app.llm_client import get_llm_client
from app.prompts import get_system_prompt, get_user_prompt
from app.tools.hotel_api import HotelSearchTool

logger = logging.getLogger(__name__)


class HotelAgent:
    """酒店智能体。根据预算和位置推荐酒店。"""

    def __init__(self):
        self.llm = get_llm_client()
        self.tool = HotelSearchTool()

    async def run(self, state: TravelState) -> dict:
        """搜索并推荐酒店。"""
        output = {}
        try:
            logger.info("HotelAgent: 正在搜索酒店")

            destination = state.get("destination", "")
            days = state.get("days", 1)
            nights = max(days - 1, 1)
            budget = state.get("budget", 0)
            hotel_budget = budget * 0.3 if budget > 0 else None
            dates = state.get("travel_dates") or {}

            hotels = await self.tool.search(
                city=destination,
                check_in=dates.get("departure") if isinstance(dates, dict) else None,
                check_out=dates.get("return") if isinstance(dates, dict) else None,
                max_price=hotel_budget,
                max_results=5,
            )

            # 联网搜索无结果时，回退到高德 POI
            if not hotels or len(hotels) < 2:
                try:
                    from app.tools.amap_api import get_amap_api
                    amap = get_amap_api()
                    amap_hotels = await amap.search_hotels(destination, max_results=5)
                    if amap_hotels:
                        for h in amap_hotels:
                            price = h.get("price")
                            if not price or price <= 0:
                                price = 0.0
                            rating = h.get("rating")
                            if not rating or rating <= 0:
                                rating = 0.0
                            hotels.append(HotelOption(
                                name=h.get("name", ""),
                                address=h.get("address", destination),
                                price_per_night=float(price),
                                total_price=float(price) * nights,
                                rating=float(rating),
                                distance_to_center_km=1.0,
                                amenities=[],
                            ))
                        logger.info("HotelAgent: 高德POI补充了 %d 个酒店", len(amap_hotels))
                except Exception as e:
                    logger.warning("HotelAgent 高德POI搜索失败: %s", e)

            # 计算总价
            for hotel in hotels:
                ppn = hotel.get("price_per_night", 0)
                hotel["total_price"] = round(ppn * nights, 2)

            # LLM 增强默认关闭；真实酒店数据已获取时不再二次加工，避免慢调用和数据漂移。
            lang = state.get("user_input", {}).get("language", "zh")
            from app.config import get_settings
            if get_settings().ENABLE_LLM_ENHANCEMENT and not hotels:
                system_prompt = get_system_prompt("hotel", lang)
                user_prompt = get_user_prompt("hotel", lang).format(
                    destination=destination,
                    days=days,
                    hotel_budget=hotel_budget or "auto",
                    preferences=", ".join(state.get("preferences", [])),
                )

                response = await self.llm.chat_completion(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_format="json",
                )

                try:
                    llm_result = json.loads(response)
                    llm_hotels = llm_result.get("hotels", [])
                    if llm_hotels:
                        hotels = [HotelOption(**h) for h in llm_hotels]
                        for h in hotels:
                            h["total_price"] = round(h.get("price_per_night", 0) * nights, 2)
                except (json.JSONDecodeError, TypeError):
                    pass

            output["hotels"] = hotels
            priced_hotels = [h for h in hotels if h.get("price_per_night", 0) > 0]
            status = "ok" if priced_hotels else ("partial" if hotels else "unavailable")
            output["data_status"] = {
                "hotels": {
                    "source": "FlyAI hotel / Amap POI",
                    "status": status,
                    "count": len(hotels),
                    "reason": "" if status == "ok" else (
                        "仅获取到酒店名称/地址，缺少真实价格" if hotels else "未获取到真实酒店数据"
                    ),
                }
            }
            output["logs"] = [{
                "agent": "hotel",
                "action": "hotel_search",
                "output": f"找到 {len(hotels)} 个酒店选项",
                "status": "success",
            }]

            logger.info("HotelAgent: 找到 %d 个酒店选项", len(hotels))

        except Exception as e:
            logger.error("HotelAgent error: %s", str(e))
            output["errors"] = [f"HotelAgent: {str(e)}"]
            output["hotels"] = []
            output["data_status"] = {
                "hotels": {
                    "source": "FlyAI hotel / Amap POI",
                    "status": "unavailable",
                    "count": 0,
                    "reason": str(e),
                }
            }

        return output
