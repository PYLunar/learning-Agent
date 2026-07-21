"""
Flight Agent - 航班 + 高铁推荐智能体。
短途城市自动推荐高铁出行。
"""

import json
import logging
from typing import List

from app.state import TravelState, FlightOption
from app.llm_client import get_llm_client
from app.prompts import get_system_prompt, get_user_prompt
from app.tools.flight_api import FlightSearchTool
from app.tools.train_api import TrainSearchTool

logger = logging.getLogger(__name__)


class FlightAgent:
    """Agent responsible for flight and train recommendations."""

    def __init__(self):
        self.llm = get_llm_client()
        self.tool = FlightSearchTool()
        self.train_tool = TrainSearchTool()

    async def run(self, state: TravelState) -> dict:
        """Search and recommend flights + trains (short distance)."""
        output = {}
        try:
            logger.info("FlightAgent: Searching flights")

            origin = state.get("origin") or state.get("user_input", {}).get("origin", "Beijing")
            destination = state.get("destination", "")
            budget = state.get("budget", 0)
            dates = state.get("travel_dates") or {}

            dep_date = dates.get("departure") if isinstance(dates, dict) else None
            ret_date = dates.get("return") if isinstance(dates, dict) else None

            # 先搜索高铁，基于最短直达时长决定是否展示航班
            train_result = await self.train_tool.search(
                origin=origin,
                destination=destination,
                departure_date=dep_date,
                return_date=ret_date,
                max_results=3,
            )

            flights = []
            if not train_result.get("train_only"):
                flights = await self.tool.search(
                    origin=origin,
                    destination=destination,
                    departure_date=dep_date,
                    return_date=ret_date,
                    max_results=5,
                )

            # Enhance with LLM reasoning
            lang = state.get("user_input", {}).get("language", "zh")
            from app.config import get_settings
            if get_settings().ENABLE_LLM_ENHANCEMENT and not flights and not train_result.get("train_only"):
                system_prompt = get_system_prompt("flight", lang)
                user_prompt = get_user_prompt("flight", lang).format(
                    origin=origin,
                    destination=destination,
                    budget=budget,
                    dates=dates,
                )

                response = await self.llm.chat_completion(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_format="json",
                )

                try:
                    llm_result = json.loads(response)
                    llm_flights = llm_result.get("flights", [])
                    if llm_flights:
                        flights = [FlightOption(**f) for f in llm_flights]
                except (json.JSONDecodeError, TypeError):
                    pass

            if train_result.get("train_only"):
                flights = []

            output["flights"] = flights

            if train_result.get("trains"):
                output["trains"] = train_result.get("trains", [])
                if train_result.get("return_trains"):
                    output["trains"].extend(train_result["return_trains"])
                output["transport_strategy"] = {
                    "train_only": bool(train_result.get("train_only")),
                    "show_flights": bool(train_result.get("show_flights", True)),
                    "min_train_duration_min": train_result.get("min_duration_min"),
                    "return_min_train_duration_min": train_result.get("return_min_duration_min"),
                    "reason": train_result.get("recommend_reason", ""),
                }
                logger.info("FlightAgent: 高铁策略 %s，共 %d 个车次",
                            output["transport_strategy"], len(output["trains"]))

            transport_count = len(output.get("flights", [])) + len(output.get("trains", []))
            transport_status = "ok" if transport_count else "unavailable"
            failure_reason = self.train_tool.flyai.last_error or getattr(self.tool, "last_error", "") or "no_real_transport_data"
            output["data_status"] = {
                "transport": {
                    "source": "FlyAI flight/train",
                    "status": transport_status,
                    "count": transport_count,
                    "reason": "" if transport_count else failure_reason,
                }
            }

            output["logs"] = [{
                "agent": "flight",
                "action": "flight_search",
                "output": f"Found {len(flights)} flight options" + (
                    f", {len(output.get('trains', []))} train options" if train_result.get("trains") else ""
                ),
                "status": "success",
            }]

            logger.info("FlightAgent: Found %d flight options, %d train options",
                        len(flights), len(output.get("trains", [])))

        except Exception as e:
            logger.error("FlightAgent error: %s", str(e))
            output["errors"] = [f"FlightAgent: {str(e)}"]
            output["flights"] = self._fallback_flights(state)

        return output

    def _fallback_flights(self, state: TravelState) -> List[FlightOption]:
        """生成回退航班（使用真实航司信息）。"""
        destination = state.get("destination", "目的地")
        origin = state.get("origin") or "出发地"
        return [
            FlightOption(
                airline="中国国航",
                flight_number="CA4314",
                departure_city=origin,
                arrival_city=destination,
                departure_time="08:00",
                arrival_time="10:30",
                departure=f"08:00 从 {origin}",
                arrival=f"10:30 到达 {destination}",
                price=800.0,
                duration="2h30m",
                layovers=0,
                layover_cities=[],
                class_type="经济舱",
            ),
            FlightOption(
                airline="南方航空",
                flight_number="CZ5387",
                departure_city=origin,
                arrival_city=destination,
                departure_time="16:00",
                arrival_time="18:40",
                departure=f"16:00 从 {origin}",
                arrival=f"18:40 到达 {destination}",
                price=650.0,
                duration="2h40m",
                layovers=0,
                layover_cities=[],
                class_type="经济舱",
            ),
        ]
