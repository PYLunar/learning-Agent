"""
Budget Agent - 基于联网搜索的真实消费数据计算预算。
"""

import json
import logging
from typing import List, Dict, Any

from app.state import TravelState, BudgetBreakdown
from app.llm_client import get_llm_client
from app.prompts import get_system_prompt, get_user_prompt
from app.tools.web_search import get_web_search

logger = logging.getLogger(__name__)


class BudgetAgent:
    """预算智能体。联网搜索目的地真实消费水平，基于实际数据计算预算。"""

    def __init__(self):
        self.llm = get_llm_client()
        self.web_search = get_web_search()

    async def run(self, state: TravelState) -> dict:
        """基于真实消费数据计算预算明细。"""
        output = {}
        try:
            logger.info("BudgetAgent: 正在计算预算")

            budget = state.get("budget", 0)
            days = state.get("days", 1)
            nights = max(days - 1, 1)
            destination = state.get("destination", "")

            # 从其他 Agent 的实际数据中获取
            flights = state.get("flights", [])
            trains = state.get("trains", [])
            transport_strategy = state.get("transport_strategy", {})
            hotels = state.get("hotels", [])
            attractions = state.get("attractions", [])
            food_spots = state.get("food_recommendations", [])

            # 航班和酒店使用真实数据
            # 航班费用：去程最低价 + 返程最低价（如果有返程）
            outbound_flights = [f for f in flights if not f.get("is_return", False)]
            return_flights = [f for f in flights if f.get("is_return", False)]

            outbound_min = min([f.get("price", 0) for f in outbound_flights], default=0) if outbound_flights else 0
            return_min = min([f.get("price", 0) for f in return_flights], default=0) if return_flights else 0

            # 如果有返程航班，按往返算；否则按去程单程算
            if return_flights and outbound_flights:
                flight_cost = outbound_min + return_min
            else:
                flight_cost = outbound_min

            outbound_trains = [t for t in trains if not t.get("is_return", False)]
            return_trains = [t for t in trains if t.get("is_return", False)]
            outbound_train_min = min(
                [t.get("price", 0) for t in outbound_trains if t.get("price", 0) > 0],
                default=0,
            )
            return_train_min = min(
                [t.get("price", 0) for t in return_trains if t.get("price", 0) > 0],
                default=0,
            )
            if return_trains and outbound_trains:
                train_cost = outbound_train_min + return_train_min
            else:
                train_cost = outbound_train_min

            # 交通预算规则：
            # - 高铁 <=4h 时仅展示高铁方案，预算按高铁票价计算。
            # - 高铁 >4h 时同时展示高铁和飞机，预算只计算机票价格。
            if transport_strategy.get("train_only"):
                flight_cost = 0
            else:
                train_cost = 0
            # 酒店只取一家（最低价）的价格 × 天数，而非把所有酒店加起来
            priced_hotels = [h for h in hotels if h.get("price_per_night", 0) > 0]
            if priced_hotels:
                cheapest_hotel = min(priced_hotels, key=lambda h: h.get("price_per_night", 9999))
                hotel_cost = cheapest_hotel.get("price_per_night", 0) * nights
            else:
                hotel_cost = 0
            attraction_cost = sum(a.get("price", 0) for a in attractions)

            # 联网搜索该城市的真实餐饮和交通消费水平
            local_costs = await self._search_local_costs(destination)

            # 餐饮费用：使用真实数据 or 已有数据的 price_range 推算
            if local_costs.get("food_per_meal"):
                food_cost = local_costs["food_per_meal"] * 3 * days  # 一天三餐
            elif food_spots:
                # 从 food_spots 的 price_range 推算（如 "人均¥60"）
                import re
                total_food = 0
                for s in food_spots:
                    pr = s.get("price_range", "")
                    m = re.search(r'(\d+)', pr)
                    if m:
                        total_food += float(m.group(1))
                    else:
                        total_food += 80  # 默认人均80
                food_cost = total_food  # 每家餐厅的人均费用
            else:
                food_cost = 0

            # 交通费用：使用真实数据
            transport_cost = local_costs.get("transport_per_day", 0) * days
            if not transport_cost:
                transport_cost = 0

            # 杂费：使用真实数据
            miscellaneous = local_costs.get("miscellaneous_per_day", 0) * days
            if not miscellaneous:
                miscellaneous = 0

            total = flight_cost + train_cost + hotel_cost + food_cost + attraction_cost + transport_cost + miscellaneous
            remaining = budget - total if budget > 0 else 0

            budget_breakdown = BudgetBreakdown(
                flights=round(flight_cost, 2),
                trains=round(train_cost, 2),
                hotels=round(hotel_cost, 2),
                food=round(food_cost, 2),
                attractions=round(attraction_cost, 2),
                transport=round(transport_cost, 2),
                miscellaneous=round(miscellaneous, 2),
                total=round(total, 2),
                remaining=round(remaining, 2),
                within_budget=total <= budget if budget > 0 else True,
            )

            # 如果超预算，LLM 建议省钱方案
            if budget > 0 and not budget_breakdown["within_budget"]:
                lang = state.get("user_input", {}).get("language", "zh")
                system_prompt = get_system_prompt("budget", lang)
                user_prompt = get_user_prompt("budget", lang).format(
                    flights=flight_cost,
                    hotels=hotel_cost,
                    attractions=attraction_cost,
                    food=food_cost,
                    budget=budget,
                )

                response = await self.llm.chat_completion(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_format="json",
                )

                try:
                    llm_result = json.loads(response)
                    llm_budget = llm_result.get("budget", {})
                    if llm_budget:
                        budget_breakdown = BudgetBreakdown(
                            flights=llm_budget.get("flights", flight_cost),
                            trains=llm_budget.get("trains", train_cost),
                            hotels=llm_budget.get("hotels", hotel_cost),
                            food=llm_budget.get("food", food_cost),
                            attractions=llm_budget.get("attractions", attraction_cost),
                            transport=llm_budget.get("transport", transport_cost),
                            miscellaneous=llm_budget.get("miscellaneous", miscellaneous),
                            total=llm_budget.get("total", total),
                            remaining=llm_budget.get("remaining", remaining),
                            within_budget=llm_budget.get("within_budget", total <= budget),
                        )
                except (json.JSONDecodeError, TypeError):
                    pass

            output["budget_breakdown"] = budget_breakdown
            output["logs"] = [{
                "agent": "budget",
                "action": "budget_calculation",
                "output": f"总费用: ¥{budget_breakdown.get('total', 0):.0f}，是否在预算内: {budget_breakdown.get('within_budget', False)} (联网消费数据: {'有' if local_costs else '无'})",
                "status": "success",
            }]

            logger.info("BudgetAgent: 总费用 ¥%.0f，联网消费数据: %s",
                       budget_breakdown.get("total", 0),
                       "有" if local_costs else "无")

        except Exception as e:
            logger.error("BudgetAgent error: %s", str(e))
            output["errors"] = [f"BudgetAgent: {str(e)}"]
            output["budget_breakdown"] = BudgetBreakdown(
                flights=0, trains=0, hotels=0, food=0, attractions=0, transport=0,
                miscellaneous=0, total=0, remaining=0, within_budget=True,
            )

        return output

    async def _search_local_costs(self, destination: str) -> Dict[str, float]:
        """
        联网搜索目的地的真实消费水平。
        返回每餐餐饮费用、每日交通费用、每日杂费。
        """
        try:
            import re

            query = f"{destination} 旅游消费水平 一天花费 餐饮价格 地铁公交费用 2026"
            results = await self.web_search.search(query=query, max_results=5)

            if not results:
                return {}

            costs = {}
            all_text = " ".join(
                r.get("snippet", "") + " " + r.get("title", "")
                for r in results
            )

            # 提取每餐费用
            food_patterns = [
                r'每人(?:每餐|一餐)\s*[¥￥]?(\d+)\s*元?',
                r'餐饮\s*[¥￥]?(\d+)\s*元?(?:/天|每天)',
                r'吃饭(?:每餐|一餐)\s*[¥￥]?(\d+)',
                r'人均消费\s*[¥￥]?(\d+)',
            ]
            for pattern in food_patterns:
                match = re.search(pattern, all_text)
                if match:
                    try:
                        costs["food_per_meal"] = float(match.group(1))
                        break
                    except ValueError:
                        continue

            # 提取每日交通费用
            transport_patterns = [
                r'交通\s*[¥￥]?(\d+)\s*元?(?:/天|每天)',
                r'地铁公交\s*[¥￥]?(\d+)',
                r'市内交通\s*[¥￥]?(\d+)',
            ]
            for pattern in transport_patterns:
                match = re.search(pattern, all_text)
                if match:
                    try:
                        costs["transport_per_day"] = float(match.group(1))
                        break
                    except ValueError:
                        continue

            # 提取每日总花费（用于估算杂费）
            total_patterns = [
                r'一天(?:总)?花费\s*[¥￥]?(\d+)',
                r'每天大约?\s*[¥￥]?(\d+)',
                r'日均消费\s*[¥￥]?(\d+)',
            ]
            for pattern in total_patterns:
                match = re.search(pattern, all_text)
                if match:
                    try:
                        daily_total = float(match.group(1))
                        # 杂费 = 日均总消费 - 餐饮 - 交通
                        food_daily = costs.get("food_per_meal", 0) * 3
                        transport_daily = costs.get("transport_per_day", 0)
                        misc = daily_total - food_daily - transport_daily
                        if misc > 0:
                            costs["miscellaneous_per_day"] = misc
                        break
                    except ValueError:
                        continue

            if costs:
                logger.info("BudgetAgent: 联网获取到 %s 消费数据: %s", destination, costs)

            return costs

        except Exception as e:
            logger.warning("BudgetAgent 联网消费数据搜索失败: %s", e)
            return {}
