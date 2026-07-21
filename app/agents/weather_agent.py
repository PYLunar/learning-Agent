"""
Weather Agent - 联网搜索天气预报 + LLM 智能推荐。
"""

import json
import logging
from typing import List

from app.state import TravelState, WeatherDay
from app.llm_client import get_llm_client
from app.prompts import get_system_prompt, get_user_prompt
from app.tools.web_search import get_web_search

logger = logging.getLogger(__name__)


class WeatherAgent:
    """天气智能体。联网搜索天气预报，LLM 智能分析出行建议。"""

    def __init__(self):
        self.llm = get_llm_client()
        self.web_search = get_web_search()

    async def run(self, state: TravelState) -> dict:
        """获取天气预报。联网搜索优先，LLM 补充，Mock 兜底。"""
        output = {}
        try:
            logger.info("WeatherAgent: 正在获取天气预报")

            destination = state.get("destination", "")
            days = state.get("days", 5)
            lang = state.get("user_input", {}).get("language", "zh")
            dates = state.get("travel_dates") or {}

            if isinstance(dates, dict) and dates.get("departure"):
                from datetime import datetime
                try:
                    departure = datetime.strptime(dates["departure"], "%Y-%m-%d").date()
                    today = datetime.now().date()
                    if (departure - today).days > 7:
                        weather = self._unavailable_future_weather(days, dates["departure"], destination)
                        output["weather"] = weather
                        output["data_status"] = {
                            "weather": {
                                "source": "China Weather / Web search",
                                "status": "unavailable",
                                "count": 0,
                                "reason": "行程日期超出短期天气预报可查范围",
                            }
                        }
                        output["logs"] = [{
                            "agent": "weather",
                            "action": "weather_forecast",
                            "output": "行程日期超出短期天气预报可查范围",
                            "status": "success",
                        }]
                        return output
                except ValueError:
                    pass

            # 1. 联网搜索天气信息
            weather_context = await self._search_weather(destination, days, lang)

            # 2. 直接从真实天气上下文解析，默认不经 LLM，避免慢调用和改写数据。
            weather = self._fallback_weather(days, destination, weather_context)

            output["weather"] = weather
            has_real_weather = bool(weather) and any(w.get("condition") != "待查询" for w in weather)
            output["data_status"] = {
                "weather": {
                    "source": "China Weather / Web search",
                    "status": "ok" if has_real_weather else "unavailable",
                    "count": len(weather) if has_real_weather else 0,
                    "reason": "" if has_real_weather else "未获取到真实天气数据",
                }
            }
            output["logs"] = [{
                "agent": "weather",
                "action": "weather_forecast",
                "output": f"已获取 {len(weather)} 天天气预报 (联网搜索: {'有' if weather_context else '无'})",
                "status": "success",
            }]

            logger.info("WeatherAgent: 已获取 %d 天天气 (联网: %s)",
                       len(weather), "有" if weather_context else "无")

        except Exception as e:
            logger.error("WeatherAgent error: %s", str(e))
            output["errors"] = [f"WeatherAgent: {str(e)}"]
            output["weather"] = self._fallback_weather(state.get("days", 5), state.get("destination", ""))
            output["data_status"] = {
                "weather": {
                    "source": "China Weather / Web search",
                    "status": "unavailable",
                    "count": 0,
                    "reason": str(e),
                }
            }

        return output

    async def _search_weather(self, destination: str, days: int, lang: str = "zh") -> str:
        """联网搜索天气信息，返回文本摘要。"""
        try:
            if lang == "zh":
                # 尝试直接抓取中国天气网获取实时天气数据
                city_code_map = {
                    "北京": "101010100", "上海": "101020100", "广州": "101280101", "深圳": "101280601", 
                    "成都": "101270101", "西安": "101110101", "杭州": "101210101", "武汉": "101200101", 
                    "重庆": "101040100", "南京": "101050200", "昆明": "101290101",
                }
                # 先尝试直接抓取中国天气网获取真实数据
                city_code = city_code_map.get(destination, "")
                if city_code:
                    url = f"https://www.weather.com.cn/weather/{city_code}.shtml"
                    context = await self._fetch_china_weather(url, days)
                    if context:
                        logger.info("WeatherAgent: 成功从中国天气网获取 %s 天气", destination)
                        return context

                # 如果城市不在映射中，用 Bing 搜索找到天气预报页面
                query = f"{destination} 未来{days}天天气预报 气温 中国天气网"
            else:
                query = f"{destination} weather forecast {days} days temperature"

            search_results = await self.web_search.search(query=query, max_results=5)

            if not search_results:
                return ""

            context_parts = []
            for r in search_results[:5]:
                title = r.get("title", "")
                snippet = r.get("snippet", "")
                if snippet:
                    context_parts.append(f"- {title}: {snippet}")

            return "\n".join(context_parts) if context_parts else ""

        except Exception as e:
            logger.warning("WeatherAgent 联网搜索失败: %s", e)
            return ""

    async def _fetch_china_weather(self, url: str, days: int) -> str:
        """从中国天气网直接抓取天气数据。"""
        import httpx
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0, headers=headers, follow_redirects=True) as client:
                resp = await client.get(url)
                html = resp.text
                import re
                context_parts = []
                # 匹配每个 <li class="sky..."> 天气块
                # 结构: <h1>日期</h1> ... <p class="wea">天气</p> ... <p class="tem"><span>高温</span>/<i>低温℃</i></p>
                li_pattern = re.compile(
                    r'<li class="sky[^"]*"[^>]*>'
                    r'.*?<h1>([^<]+)</h1>'
                    r'.*?<p[^>]*class="wea"[^>]*>(?:<[^>]+>)*([^<]+)'
                    r'.*?<p class="tem">'
                    r'\s*<span>(\d+)</span>/<i>(\d+)℃</i>',
                    re.DOTALL
                )
                matches = li_pattern.findall(html)
                for date_text, condition, high, low in matches[:days]:
                    date = date_text.strip()
                    cond = condition.strip()
                    context_parts.append(f"{date}: {cond}, {low}~{high}℃")

                if context_parts:
                    logger.info("WeatherAgent: 成功从中国天气网解析 %d 天天气", len(context_parts))
                return "\n".join(context_parts)
        except Exception as e:
            logger.warning("中国天气网抓取失败: %s", e)
            return ""

    def _fallback_weather(self, days: int, destination: str = "", search_context: str = "") -> List[WeatherDay]:
        """
        从搜索上下文直接解析天气数据（不使用LLM）。
        如果搜索数据不可用，返回"待查询"占位。
        """
        from datetime import datetime, timedelta
        import re

        weather = []
        if search_context:
            # 解析中国天气网格式：13日（今天）: 雷阵雨转阵雨, 24~32℃
            lines = search_context.split("\n")
            for line in lines[:days]:
                # 提取日期号
                day_match = re.search(r'(\d{1,2})日', line)
                # 提取天气描述
                cond_match = re.search(r':\s*(.+?),\s*', line)
                # 提取温度
                temp_match = re.search(r'(\d{1,2})[~～](\d{1,2})℃', line)
                
                if day_match and temp_match:
                    day_num = int(day_match.group(1))
                    low = float(temp_match.group(1))
                    high = float(temp_match.group(2))
                    condition = cond_match.group(1).strip() if cond_match else "未知"
                    
                    # 构建日期
                    today = datetime.now()
                    # 如果日期号小于今天，可能是下个月，用简单处理
                    target_date = today + timedelta(days=day_num - today.day)
                    if day_num < today.day:
                        # 下个月
                        target_date = today + timedelta(days=day_num + 31 - today.day)
                    
                    date_str = target_date.strftime("%Y-%m-%d")
                    precip = 30 if "雨" in condition else 10
                    
                    weather.append(WeatherDay(
                        date=date_str,
                        condition=condition,
                        temperature_high=high,
                        temperature_low=low,
                        precipitation_chance=float(precip),
                        recommendation=self._get_weather_recommendation(condition, high, low),
                    ))

        if not weather:
            # 搜索数据也不可用，返回"待查询"
            start_date = datetime.now()
            for i in range(days):
                date_str = (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
                weather.append(WeatherDay(
                    date=date_str,
                    condition="待查询",
                    temperature_high=0.0,
                    temperature_low=0.0,
                    precipitation_chance=0.0,
                    recommendation=f"请搜索 {destination} {date_str} 天气获取最新预报",
                ))

        return weather

    def _unavailable_future_weather(self, days: int, departure_date: str, destination: str = "") -> List[WeatherDay]:
        """Return transparent placeholders when real forecast is not yet available."""
        from datetime import datetime, timedelta

        start_date = datetime.strptime(departure_date, "%Y-%m-%d")
        weather = []
        for i in range(days):
            date_str = (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
            weather.append(WeatherDay(
                date=date_str,
                condition="暂未到可查范围",
                temperature_high=0.0,
                temperature_low=0.0,
                precipitation_chance=0.0,
                recommendation=f"{destination} {date_str} 的真实天气预报暂未开放查询，请出行前 7 天内再查。",
            ))
        return weather

    def _get_weather_recommendation(self, condition: str, high: float, low: float) -> str:
        """根据天气条件生成出行建议。"""
        if "雨" in condition:
            return "建议带伞，适合室内活动如博物馆、美食探店"
        if high > 35:
            return "高温天气，注意防暑，多安排室内休息"
        if high > 30:
            return "天气较热，注意防晒补水"
        if low < 5:
            return "天气寒冷，注意保暖，适合室内活动"
        if "晴" in condition:
            return "适合户外活动和拍照"
        if "阴" in condition or "多云" in condition:
            return "适合出行，温度舒适"
        return "适合出行"
