"""
Planner Agent - 联网获取目的地信息 + LLM 任务分解。
"""

import json
import logging
from typing import Dict, Any

from app.state import TravelState
from app.llm_client import get_llm_client
from app.prompts import get_system_prompt, get_user_prompt
from app.tools.wikipedia_api import get_wikipedia
from app.tools.exchange_api import get_exchange_rate
from app.tools.web_search import get_web_search

logger = logging.getLogger(__name__)


class PlannerAgent:
    """规划师智能体。联网获取目的地城市概况和汇率，再由 LLM 分解任务。"""

    def __init__(self):
        self.llm = get_llm_client()
        self.wikipedia = get_wikipedia()
        self.exchange = get_exchange_rate()
        self.web_search = get_web_search()

    async def run(self, state: TravelState) -> dict:
        """分解用户请求为子任务。先联网获取目的地信息。"""
        output = {}
        try:
            logger.info("PlannerAgent: Starting task decomposition with web data")

            destination = state.get("destination", "")
            days = state.get("days", 0)
            budget = state.get("budget", 0)
            preferences = state.get("preferences", [])
            origin = state.get("origin") or state.get("user_input", {}).get("origin", "")
            dates = state.get("travel_dates", {})
            lang = state.get("user_input", {}).get("language", "zh")
            from app.config import get_settings
            settings = get_settings()

            # 1. 国内中文规划不依赖 Wikipedia/汇率，减少慢请求和无关英文来源。
            city_info = {}
            if lang != "zh":
                city_info = await self.wikipedia.get_city_info(destination, lang)

            # 2. 获取当地货币和汇率
            local_currency = "CNY" if lang == "zh" else self.exchange.detect_currency(destination)
            # 如果是中国目的地，货币固定为 CNY
            chinese_cities = ["beijing", "shanghai", "guangzhou", "shenzhen", "hangzhou", "chengdu", "xian", "nanjing", "wuhan", "chongqing", "suzhou", "xiamen", "qingdao", "dalian", "kunming", "guiyang", "changsha", "tianjin", "shenyang", "harbin", "zhengzhou", "jinan", "fuzhou", "hefei", "nanchang", "changchun", "taipei", "hongkong", "macau", "hainan"]
            if destination.lower() in chinese_cities or lang == "zh":
                local_currency = "CNY"
            currency_info = ""
            if local_currency != "USD" and lang != "zh":
                rate = await self.exchange.get_rate(local_currency, "USD")
                if rate:
                    local_budget = await self.exchange.convert_from_usd(budget, local_currency)
                    currency_info = f"当地货币: {local_currency} (1 {local_currency} = {rate} USD)。您的预算 ${budget} USD ≈ {local_budget:.0f} {local_currency}。"

            # 3. 可选联网搜索旅行攻略；默认关闭，避免搜索结果污染真实结构化数据。
            travel_tips = ""
            if settings.ENABLE_LLM_ENHANCEMENT:
                travel_tips = await self._search_travel_tips(destination, preferences, lang)

            # 4. 构建 LLM 提示词（注入联网数据）
            system_prompt = get_system_prompt("planner", lang)
            user_prompt = get_user_prompt("planner", lang).format(
                destination=destination,
                days=days,
                budget=budget,
                preferences=", ".join(preferences),
                origin=origin,
                dates=dates,
            )

            # 注入联网数据
            web_context = ""
            if city_info and city_info.get("overview"):
                web_context += f"\n**Destination Overview**:\n{city_info['overview'][:1000]}"
            if city_info and city_info.get("related_places"):
                web_context += f"\n**Related Places**: {', '.join(city_info['related_places'][:5])}"
            if currency_info:
                web_context += f"\n**Currency Info**: {currency_info}"
            if travel_tips:
                web_context += f"\n**Travel Tips**: {travel_tips}"

            if web_context:
                user_prompt += f"\n\n**参考信息（来自互联网）**:\n{web_context}"

            planner_tasks = []
            if settings.ENABLE_LLM_ENHANCEMENT:
                response = await self.llm.chat_completion(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_format="json",
                )

                try:
                    result = json.loads(response)
                except json.JSONDecodeError:
                    result = {"tasks": [], "summary": "Planning completed"}

                planner_tasks = result.get("tasks", [])

            # 确保核心任务存在
            essential_agents = ["flight", "hotel", "attraction", "food", "weather"]
            existing = {t.get("agent", "").lower() for t in planner_tasks}
            for agent in essential_agents:
                if agent not in existing:
                    planner_tasks.append({
                        "agent": agent,
                        "priority": "high" if agent in ["flight", "hotel"] else "medium",
                        "description": f"Execute {agent} agent tasks"
                    })

            output["planner_tasks"] = planner_tasks
            output["status"] = "in_progress"

            # 存储城市信息到状态供后续 agent 使用
            if city_info:
                output["city_info"] = city_info
            output["local_currency"] = local_currency

            output["logs"] = [{
                "agent": "planner",
                "action": "task_decomposition",
                "output": f"Planned {len(planner_tasks)} tasks (wiki: {'yes' if city_info else 'no'}, exchange: {'yes' if currency_info else 'no'})",
                "status": "success",
            }]

            logger.info("PlannerAgent: Decomposition complete, %d tasks, currency=%s",
                       len(planner_tasks), local_currency)

        except Exception as e:
            logger.error("PlannerAgent error: %s", str(e))
            output["errors"] = [f"PlannerAgent: {str(e)}"]
            output["planner_tasks"] = [
                {"agent": "flight", "priority": "high", "description": "Search flights"},
                {"agent": "hotel", "priority": "high", "description": "Find hotels"},
                {"agent": "attraction", "priority": "medium", "description": "Plan attractions"},
                {"agent": "food", "priority": "medium", "description": "Find restaurants"},
                {"agent": "weather", "priority": "low", "description": "Check weather"},
            ]

        return output

    async def _search_travel_tips(self, destination: str, preferences: list, lang: str = "zh") -> str:
        """联网搜索目的地旅行攻略。中文用户搜索中文攻略。"""
        try:
            pref_str = " ".join(preferences) if preferences else "travel"
            # 中文用户搜索中文内容
            if lang == "zh" or destination.lower() in ["beijing", "shanghai", "guangzhou", "shenzhen", "hangzhou", "chengdu", "xian", "nanjing", "wuhan", "chongqing"]:
                query = f"{destination} 旅游攻略 必去景点 美食推荐 2025"
            else:
                query = f"{destination} travel tips best time to visit {pref_str} guide 2025"
            results = await self.web_search.search(query=query, max_results=3)
            if results:
                parts = [f"- {r.get('title', '')}: {r.get('snippet', '')}" for r in results[:3] if r.get("snippet")]
                return "\n".join(parts)
        except Exception as e:
            logger.warning("PlannerAgent travel tips search error: %s", e)
        return ""
