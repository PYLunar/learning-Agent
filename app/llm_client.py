"""
LLM client wrapper supporting OpenAI API with mock fallback.
Easily swappable for different providers.
"""

import json
import logging
import random
from typing import Any, Dict, List, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Generic LLM client with OpenAI-compatible interface."""

    def __init__(self):
        self.settings = get_settings()
        self._openai_client = None

    def _get_client(self):
        """Lazy-load OpenAI client."""
        if self._openai_client is None:
            try:
                from openai import AsyncOpenAI
                self._openai_client = AsyncOpenAI(
                    api_key=self.settings.OPENAI_API_KEY or "mock-key",
                    base_url=self.settings.OPENAI_BASE_URL,
                    timeout=self.settings.LLM_TIMEOUT_SECONDS,
                )
            except ImportError:
                self._openai_client = None
        return self._openai_client

    async def chat_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[str] = None,
    ) -> str:
        """Send a chat completion request. Returns empty string if API key missing or call fails."""
        if not self.settings.OPENAI_API_KEY:
            return ""

        client = self._get_client()
        if not client:
            return ""

        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            kwargs = {
                "model": self.settings.LLM_MODEL,
                "messages": messages,
                "temperature": temperature or self.settings.LLM_TEMPERATURE,
                "max_tokens": max_tokens or self.settings.LLM_MAX_TOKENS,
            }

            if response_format == "json":
                kwargs["response_format"] = {"type": "json_object"}
                # 通义千问等模型要求 messages 中包含 "json" 字样才能使用 json_object 格式
                messages[-1]["content"] += "\n\n请以 JSON 格式返回结果。"

            response = await client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content or ""
            logger.info("LLM 返回 %d 字符: %s", len(content), content[:200] if content else "(empty)")
            return content
        except Exception as e:
            # LLM API 调用失败，返回空字符串（各Agent负责处理缺失数据）
            import logging
            logging.getLogger(__name__).warning("LLM API 调用失败: %s", e)
            return ""

    def _extract_destination(self, user_prompt: str) -> str:
        """从 user_prompt 中提取目的地名称。"""
        import re
        # 尝试匹配 "目的地: XXX" 或 "Destination: XXX"
        for pattern in [r"目的地[：:]\s*(.+?)[\n]", r"Destination[：:]\s*(.+?)[\n]"]:
            m = re.search(pattern, user_prompt)
            if m:
                return m.group(1).strip()
        # 尝试匹配 "从 X 到 Y"
        m = re.search(r"从.+?到\s*(.+?)[\n]", user_prompt)
        if m:
            return m.group(1).strip()
        # 尝试匹配 "为 X 的" (中文美食/景点提示词格式)
        m = re.search(r"为\s*(.+?)\s*的\s*\d+\s*天", user_prompt)
        if m:
            return m.group(1).strip()
        # 尝试匹配 "推荐X当地" (中文重要要求格式)
        m = re.search(r"推荐\s*(.+?)\s*当地", user_prompt)
        if m:
            return m.group(1).strip()
        # 尝试匹配 "在 X 查找" (中文酒店提示词格式)
        m = re.search(r"在\s*(.+?)\s*查找", user_prompt)
        if m:
            return m.group(1).strip()
        # 尝试匹配 "获取 X 未来" (中文天气提示词格式)
        m = re.search(r"获取\s*(.+?)\s*未来", user_prompt)
        if m:
            return m.group(1).strip()
        return "目的地"

    def _mock_response(self, system_prompt: str, user_prompt: str) -> str:
        """生成基于目的地名称的中文 Mock 响应（读取 user_prompt 中的城市名）。"""
        prompt_lower = (system_prompt + user_prompt).lower()
        dest = self._extract_destination(user_prompt)
        days = 3
        import re
        days_match = re.search(r"(?:天数|days)[：:]\s*(\d+)", user_prompt, re.IGNORECASE)
        if days_match:
            days = min(int(days_match.group(1)), 7)

        if "final" in prompt_lower or "report" in prompt_lower or "最终报告" in prompt_lower or "旅行计划" in prompt_lower:
            # 最终报告的 Mock：返回空字符串触发手动报告生成
            return ""
        elif "flight" in prompt_lower:
            return json.dumps({
                "flights": [
                    {"airline": "中国国航", "flight_number": f"CA{random.randint(1000,9999)}", "departure_city": dest, "arrival_city": dest, "departure_time": f"{random.randint(6,12):02d}:{random.choice([0,15,30,45]):02d}", "arrival_time": f"{random.randint(13,22):02d}:{random.choice([0,15,30,45]):02d}", "price": random.randint(800, 3000), "duration": f"{random.randint(2,5)}h{random.randint(0,59):02d}m", "layovers": 0, "class_type": "经济舱"},
                    {"airline": "东方航空", "flight_number": f"MU{random.randint(1000,9999)}", "departure_city": dest, "arrival_city": dest, "departure_time": f"{random.randint(6,14):02d}:{random.choice([0,15,30,45]):02d}", "arrival_time": f"{random.randint(14,23):02d}:{random.choice([0,15,30,45]):02d}", "price": random.randint(600, 2500), "duration": f"{random.randint(2,6)}h{random.randint(0,59):02d}m", "layovers": 0, "class_type": "经济舱"},
                    {"airline": "南方航空", "flight_number": f"CZ{random.randint(1000,9999)}", "departure_city": dest, "arrival_city": dest, "departure_time": f"{random.randint(7,15):02d}:{random.choice([0,15,30,45]):02d}", "arrival_time": f"{random.randint(15,23):02d}:{random.choice([0,15,30,45]):02d}", "price": random.randint(500, 2000), "duration": f"{random.randint(2,7)}h{random.randint(0,59):02d}m", "layovers": 1, "class_type": "经济舱"},
                ]
            })
        elif "hotel" in prompt_lower:
            return json.dumps({
                "hotels": [
                    {"name": f"{dest}国际大酒店", "price_per_night": random.randint(300, 800), "rating": round(random.uniform(4.0, 4.8), 1), "distance_to_center_km": round(random.uniform(0.5, 3.0), 1)},
                    {"name": f"{dest}市中心酒店", "price_per_night": random.randint(200, 600), "rating": round(random.uniform(3.8, 4.6), 1), "distance_to_center_km": round(random.uniform(0.3, 2.0), 1)},
                    {"name": f"{dest}商务精品酒店", "price_per_night": random.randint(250, 700), "rating": round(random.uniform(3.9, 4.7), 1), "distance_to_center_km": round(random.uniform(1.0, 5.0), 1)},
                ]
            })
        elif "attraction" in prompt_lower or "activity" in prompt_lower:
            attractions = []
            for day in range(1, days + 1):
                attractions.append({"name": f"{dest}标志性景点{day}", "day": day, "category": "文化", "price": 0, "estimated_duration": "2小时"})
                attractions.append({"name": f"{dest}知名景点{day}", "day": day, "category": "观光", "price": 50, "estimated_duration": "2小时"})
            return json.dumps({"attractions": attractions})
        elif "food" in prompt_lower or "restaurant" in prompt_lower:
            return json.dumps({
                "restaurants": [
                    {"name": f"{dest}老字号餐厅", "cuisine": "当地特色菜", "price_range": "¥¥", "meal_type": "dinner", "must_try_dishes": [f"{dest}招牌菜"], "why_recommended": "当地特色", "rating": 4.5},
                    {"name": f"{dest}特色小吃店", "cuisine": "街头美食", "price_range": "¥", "meal_type": "lunch", "must_try_dishes": [f"{dest}特色小吃"], "why_recommended": "体验当地美食", "rating": 4.3},
                    {"name": f"{dest}精品咖啡馆", "cuisine": "咖啡甜点", "price_range": "¥¥", "meal_type": "snack", "must_try_dishes": ["手工咖啡"], "why_recommended": "休息好去处", "rating": 4.4},
                ]
            })
        elif "weather" in prompt_lower:
            weather = []
            conditions = ["晴", "多云", "阴", "小雨"]
            for i in range(days):
                weather.append({
                    "date": f"第{i+1}天",
                    "condition": random.choice(conditions),
                    "temperature_high": random.randint(20, 32),
                    "temperature_low": random.randint(10, 20),
                    "recommendation": "适合游览"
                })
            return json.dumps({"weather": weather})
        elif "budget" in prompt_lower:
            budget = random.randint(3000, 10000)
            return json.dumps({
                "budget": {
                    "flights": int(budget * 0.3), "hotels": int(budget * 0.3),
                    "food": int(budget * 0.15), "attractions": int(budget * 0.1),
                    "transport": int(budget * 0.1), "miscellaneous": int(budget * 0.05),
                    "total": budget, "within_budget": True
                }
            })
        elif "route" in prompt_lower or "optimize" in prompt_lower:
            route = []
            for day in range(1, days + 1):
                route.append({
                    "day": day,
                    "morning": [f"{dest}上午景点"],
                    "afternoon": [f"{dest}下午景点"],
                    "evening": [f"{dest}夜景/美食"]
                })
            return json.dumps({"route": route})
        elif "critic" in prompt_lower or "review" in prompt_lower:
            return json.dumps({
                "feedback": {
                    "budget_feasible": True, "schedule_balanced": True, "no_missing_components": True,
                    "issues": [], "suggestions": [f"可以考虑增加{dest}周边一日游"], "score": 8.0, "needs_revision": False
                }
            })
        elif "planner" in prompt_lower:
            return json.dumps({
                "tasks": [
                    {"agent": "flight", "priority": "high", "description": f"搜索到{dest}的航班"},
                    {"agent": "hotel", "priority": "high", "description": f"查找{dest}的酒店"},
                    {"agent": "attraction", "priority": "medium", "description": f"规划{dest}景点"},
                    {"agent": "food", "priority": "medium", "description": f"查找{dest}美食"},
                    {"agent": "weather", "priority": "low", "description": f"查看{dest}天气"},
                ],
                "summary": f"一个关于{dest}的平衡旅行计划，注重文化和美食体验。"
            })
        else:
            return json.dumps({"response": f"Mock响应生成成功（目的地: {dest}）"})


# Singleton instance
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Get singleton LLM client instance."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
