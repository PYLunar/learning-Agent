"""
Final Report Agent - combines all outputs into a clean Markdown travel plan.
"""

import json
import logging
from typing import Dict, Any, List

from app.state import TravelState
from app.llm_client import get_llm_client
from app.prompts import get_system_prompt, get_user_prompt

logger = logging.getLogger(__name__)


class FinalAgent:
    """Agent responsible for generating the final formatted travel plan."""

    def __init__(self):
        self.llm = get_llm_client()

    async def run(self, state: TravelState) -> dict:
        """Combine all outputs into a final Markdown travel plan."""
        output = {}
        lang = state.get("user_input", {}).get("language", "zh")
        try:
            logger.info("FinalAgent: 正在生成最终报告")

            destination = state.get("destination", "")
            days = state.get("days", 0)
            budget = state.get("budget", 0)

            # Build structured data for the report
            all_data = self._build_data_summary(state)

            # Always build manual report first (guaranteed Chinese + ¥)
            manual_report = self._build_manual_report(state, lang)

            # Try LLM enhancement, but only use it if it passes strict validation
            report = manual_report  # default to manual report
            from app.config import get_settings
            if get_settings().ENABLE_LLM_ENHANCEMENT:
                try:
                    system_prompt = get_system_prompt("final", lang)
                    user_prompt = get_user_prompt("final", lang).format(
                        destination=destination,
                        all_data=json.dumps(all_data, indent=2, ensure_ascii=False),
                    )

                    response = await self.llm.chat_completion(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                    )

                    # Strict validation: LLM report must be Chinese with ¥
                    if response and len(response) > 500:
                        stripped = response.strip()
                        is_json = stripped.startswith('{') or stripped.startswith('[')
                        has_dollar = '$' in response
                        has_yuan = '¥' in response
                        exposes_route_optimization = (
                            '路线优化说明' in response
                            or 'Route Optimization' in response
                            or 'route optimization' in response
                        )
                        english_patterns = ['Overview', 'Day-by-Day', 'Flights', 'Hotels',
                                           'Food Recommendations', 'Budget Breakdown',
                                           'Local favorite', 'Consider adding']
                        has_english = any(p in response for p in english_patterns)

                        user_cities = {state.get("origin", ""), state.get("destination", ""), destination}
                        _FABRICATED_CITIES = {"武汉", "长沙", "郑州", "贵阳", "南昌", "合肥",
                                              "Wuhan", "Changsha", "Zhengzhou"}
                        has_fabricated_city = False
                        for fc in _FABRICATED_CITIES:
                            if fc not in user_cities and fc in response:
                                for transport_keyword in ["航班", "飞行", "起飞", "经停", "中转",
                                                          "flight", "stopover", "transfer",
                                                          "出发", "到达", "前往"]:
                                    if fc in response and transport_keyword in response:
                                        has_fabricated_city = True
                                        break
                            if has_fabricated_city:
                                break

                        if not is_json and not has_dollar and has_yuan and not has_english and not has_fabricated_city and not exposes_route_optimization:
                            report = response
                            logger.info("FinalAgent: 使用 LLM 生成的报告（通过验证）")
                        else:
                            reasons = []
                            if is_json: reasons.append("JSON格式")
                            if has_dollar: reasons.append("含美元符号")
                            if not has_yuan: reasons.append("无¥符号")
                            if has_english: reasons.append("含英文标题")
                            if has_fabricated_city: reasons.append("编造了非请求城市")
                            if exposes_route_optimization: reasons.append("包含路线优化说明")
                            logger.info("FinalAgent: LLM 报告未通过验证（%s），使用手动报告", ", ".join(reasons))
                except Exception as llm_err:
                    logger.warning("FinalAgent: LLM 调用失败: %s，使用手动报告", llm_err)

            # 强制替换交通部分（航班+高铁）：LLM 可能遗漏高铁数据或编造航线
            report = self._inject_transport_section(report, state, lang)

            output["final_plan"] = report
            output["final_plan_structured"] = all_data
            output["status"] = "completed"
            output["logs"] = [{
                "agent": "final",
                "action": "report_generation",
                "output": f"已生成最终报告（{len(report)} 字符）",
                "status": "success",
            }]

            logger.info("FinalAgent: 已生成报告（%d 字符）", len(report))

        except Exception as e:
            logger.error("FinalAgent error: %s", str(e))
            output["errors"] = [f"FinalAgent: {str(e)}"]
            output["final_plan"] = self._build_manual_report(state, lang)
            output["status"] = "completed"

        return output

    def _build_data_summary(self, state: TravelState) -> Dict[str, Any]:
        """Build a structured summary of all agent outputs."""
        return {
            "overview": {
                "destination": state.get("destination", ""),
                "days": state.get("days", 0),
                "budget": state.get("budget", 0),
                "preferences": state.get("preferences", []),
            },
            "flights": state.get("flights", []),
            "trains": state.get("trains", []),
            "transport_strategy": state.get("transport_strategy", {}),
            "data_status": state.get("data_status", {}),
            "hotels": state.get("hotels", []),
            "attractions": state.get("attractions", []),
            "food": state.get("food_recommendations", []),
            "weather": state.get("weather", []),
            "budget_breakdown": state.get("budget_breakdown", {}),
            "critic_feedback": state.get("critic_feedback", {}),
        }

    def _inject_transport_section(self, report: str, state: TravelState, lang: str) -> str:
        """
        强制替换报告中的交通部分（航班+高铁），确保数据准确。
        LLM 可能遗漏高铁数据或编造航线，所以交通部分必须用结构化数据渲染。
        """
        flights = state.get("flights", [])
        trains = state.get("trains", [])
        strategy = state.get("transport_strategy", {})

        if not flights and not trains:
            return report  # 无交通数据，不替换

        # 辅助函数：格式化价格
        def _price_str(p):
            return f"¥{p:.0f}" if p > 0 else "暂无"

        # 手动渲染交通部分
        if lang == "zh":
            transport_section = self._render_transport_zh(flights, trains, strategy)
        else:
            transport_section = self._render_transport_en(flights, trains, strategy)

        # 替换策略：找到报告中"## 航班"或"## Flights"开头的章节，替换到下一个"## "之前
        import re
        if lang == "zh":
            pattern = re.compile(r'## 航班.*?(?=\n## )', re.DOTALL)
        else:
            pattern = re.compile(r'## Flights.*?(?=\n## )', re.DOTALL)

        if pattern.search(report):
            report = pattern.sub(transport_section + "\n", report, count=1)
            logger.info("FinalAgent: 已替换交通部分（%d 航班, %d 高铁）", len(flights), len(trains))
        else:
            # 没找到章节标题，在"## 酒店"或"## Hotels"前面插入
            if lang == "zh":
                insert_point = report.find("\n## 酒店")
            else:
                insert_point = report.find("\n## Hotels")
            if insert_point > 0:
                report = report[:insert_point] + "\n" + transport_section + report[insert_point:]
                logger.info("FinalAgent: 已插入交通部分（%d 航班, %d 高铁）", len(flights), len(trains))

        return report

    def _render_transport_zh(self, flights, trains, strategy=None) -> str:
        """渲染中文交通部分（航班+高铁）。"""
        strategy = strategy or {}
        def _ps(p):
            return f"¥{p:.0f}" if p > 0 else "暂无"

        section = "## 交通方案\n\n"
        reason = strategy.get("reason")
        if reason:
            section += f"*{reason}。*\n\n"

        outbound = [f for f in flights if not f.get("is_return", False)]
        return_fl = [f for f in flights if f.get("is_return", False)]

        def _render_fl(flist, label):
            if not flist:
                return ""
            prices = [f.get("price", 0) for f in flist if f.get("price", 0) > 0]
            lines = []
            if prices:
                lines.append(f"\n### {label}（价格区间: ¥{min(prices):.0f} ~ ¥{max(prices):.0f}）\n\n")
            else:
                lines.append(f"\n### {label}\n\n")
            for f in flist:
                dep_time = f.get("departure_time", "")
                arr_time = f.get("arrival_time", "")
                dep_airport = f.get("departure_airport", "")
                arr_airport = f.get("arrival_airport", "")
                lines.append(f"- **{f.get('airline', '')} {f.get('flight_number', '')}**\n")
                if dep_airport:
                    lines.append(f"  - 起飞: {dep_time} {dep_airport}\n")
                else:
                    lines.append(f"  - 起飞: {dep_time}\n")
                if arr_airport:
                    lines.append(f"  - 落地: {arr_time} {arr_airport}\n")
                else:
                    lines.append(f"  - 落地: {arr_time}\n")
                lines.append(f"  - 价格: ¥{f.get('price', 0):.0f} | 飞行时长: {f.get('duration', '')} | 舱位: {f.get('class_type', '经济舱')}\n")
            return "\n".join(lines)

        if outbound or return_fl:
            section += "### 飞机方案\n"
        if outbound:
            section += _render_fl(outbound, "去程航班")
        if return_fl:
            section += _render_fl(return_fl, "返程航班")
        if not outbound and not return_fl and not trains:
            section += "\n*实时搜索未获取到航班数据，请稍后重试或前往携程/去哪儿查询*\n"

        # 往返总价区间
        all_out_prices = [f.get("price", 0) for f in outbound if f.get("price", 0) > 0]
        all_ret_prices = [f.get("price", 0) for f in return_fl if f.get("price", 0) > 0]
        if all_out_prices and all_ret_prices:
            min_total = min(all_out_prices) + min(all_ret_prices)
            max_total = max(all_out_prices) + max(all_ret_prices)
            section += f"\n**往返总价区间: ¥{min_total:.0f} ~ ¥{max_total:.0f}**\n"

        # 高铁部分
        if trains:
            outbound_trains = [t for t in trains if not t.get("is_return", False)]
            return_trains = [t for t in trains if t.get("is_return", False)]
            if outbound_trains or return_trains:
                if strategy.get("train_only"):
                    section += "\n### 高铁/动车方案（推荐）\n\n"
                    section += "*高铁直达用时小于等于 4 小时，本次仅展示高铁方案。*\n\n"
                else:
                    section += "\n### 高铁/动车备选\n\n"
                    section += "*高铁直达用时大于 4 小时，作为备选方案展示；预算仅按机票价格计算。*\n\n"
                if outbound_trains:
                    section += "### 去程\n\n"
                    train_prices = [t.get("price", 0) for t in outbound_trains if t.get("price", 0) > 0]
                    if train_prices:
                        section += f"（票价区间: ¥{min(train_prices):.0f} ~ ¥{max(train_prices):.0f}）\n\n"
                    for t in outbound_trains:
                        section += f"- **{t.get('train_type', '高铁')} {t.get('train_number', '')}**\n"
                        section += f"  - 出发: {t.get('departure_time', '')} {t.get('departure_station', '')}\n"
                        section += f"  - 到达: {t.get('arrival_time', '')} {t.get('arrival_station', '')}\n"
                        section += f"  - 票价: {_ps(t.get('price', 0))} | 用时: {t.get('duration', '')} | {t.get('seat_class', '二等座')}\n"
                if return_trains:
                    section += "\n### 返程\n\n"
                    for t in return_trains:
                        section += f"- **{t.get('train_type', '高铁')} {t.get('train_number', '')}**\n"
                        section += f"  - 出发: {t.get('departure_time', '')} {t.get('departure_station', '')}\n"
                        section += f"  - 到达: {t.get('arrival_time', '')} {t.get('arrival_station', '')}\n"
                        section += f"  - 票价: {_ps(t.get('price', 0))} | 用时: {t.get('duration', '')} | {t.get('seat_class', '二等座')}\n"
                out_tprices = [t.get("price", 0) for t in outbound_trains if t.get("price", 0) > 0]
                ret_tprices = [t.get("price", 0) for t in return_trains if t.get("price", 0) > 0]
                if out_tprices and ret_tprices:
                    train_total_min = min(out_tprices) + min(ret_tprices)
                    section += f"\n**高铁往返总价: ¥{train_total_min:.0f} 起**\n"

        return section

    def _render_transport_en(self, flights, trains, strategy=None) -> str:
        """渲染英文交通部分（备用）。"""
        strategy = strategy or {}
        def _ps(p):
            return f"¥{p:.0f}" if p > 0 else "N/A"

        section = "## Transport\n\n"
        if strategy.get("reason"):
            section += f"*{strategy.get('reason')}.*\n\n"
        if flights:
            section += "### Flights\n\n"
            for f in flights:
                section += f"- **{f.get('airline', '')} {f.get('flight_number', '')}**: {f.get('departure_time', '')} → {f.get('arrival_time', '')} ¥{f.get('price', 0):.0f}\n"
        if trains:
            section += "\n### High-Speed Train\n\n"
            for t in trains:
                section += f"- **{t.get('train_type', '')} {t.get('train_number', '')}**: {t.get('departure_time', '')} → {t.get('arrival_time', '')} {_ps(t.get('price', 0))} ({t.get('duration', '')})\n"
        return section

    def _build_manual_report(self, state: TravelState, lang: str = "zh") -> str:
        """Build a manual Markdown report as fallback."""
        destination = state.get("destination", "")
        days = state.get("days", 0)
        budget = state.get("budget", 0)
        flights = state.get("flights", [])
        hotels = state.get("hotels", [])
        attractions = state.get("attractions", [])
        food = state.get("food_recommendations", [])
        weather = state.get("weather", [])
        trains = state.get("trains", [])
        budget_bd = state.get("budget_breakdown", {})
        data_status = state.get("data_status", {})
        critic = state.get("critic_feedback", {})

        preferences = state.get('preferences', [])
        # 默认中文报告
        return self._build_chinese_report(destination, days, budget, flights, hotels, attractions, food, weather, budget_bd, data_status, critic, preferences, trains)

    def _build_chinese_report(self, destination, days, budget, flights, hotels, attractions, food, weather, budget_bd, data_status, critic, preferences, trains=None):
        """Build a Chinese Markdown report."""
        # 偏好翻译
        pref_map = {
            "culture": "文化", "food": "美食", "shopping": "购物", "nature": "自然",
            "history": "历史", "nightlife": "夜生活", "adventure": "冒险", "art": "艺术",
            "relax": "休闲",
        }
        pref_zh = [pref_map.get(p, p) for p in preferences] if preferences else []
        report = f"""# {destination} 旅行计划

## 概览

{destination} {days}天行程，预算 ¥{budget:.0f}。
偏好: {', '.join(pref_zh) or '一般观光'}。

## 每日行程

"""
        attractions_by_day = {}
        for attraction in attractions:
            day = attraction.get("day", 1) or 1
            attractions_by_day.setdefault(day, []).append(attraction)

        for day in range(1, days + 1):
            report += f"**第 {day} 天**\n"
            day_attractions = attractions_by_day.get(day, [])
            if day_attractions:
                for attraction in day_attractions:
                    name = attraction.get("name", "")
                    description = attraction.get("description", "")
                    duration = attraction.get("estimated_duration", "")
                    detail_parts = [p for p in [description, duration] if p]
                    detail = f": {' - '.join(detail_parts)}" if detail_parts else ""
                    report += f"- {name}{detail}\n"
            else:
                report += f"- {destination}自由探索与休整\n"
            report += "\n"

        report += "## 航班\n\n"
        # 分去程和返程
        outbound = [f for f in flights if not f.get("is_return", False)]
        return_fl = [f for f in flights if f.get("is_return", False)]

        def _p(p):
            return f"¥{p:.0f}" if p > 0 else "暂无"

        def _render_flight_list(report, flist, label):
            if not flist:
                return report
            prices = [f.get("price", 0) for f in flist if f.get("price", 0) > 0]
            if prices:
                report += f"\n### {label}（价格区间: ¥{min(prices):.0f} ~ ¥{max(prices):.0f}）\n\n"
            else:
                report += f"\n### {label}\n\n"
            for f in flist:
                dep_time = f.get("departure_time", "")
                arr_time = f.get("arrival_time", "")
                dep_airport = f.get("departure_airport", "")
                arr_airport = f.get("arrival_airport", "")
                report += f"- **{f.get('airline', '')} {f.get('flight_number', '')}**\n"
                report += f"  - 起飞: {dep_time} {dep_airport}\n" if dep_airport else f"  - 起飞: {dep_time}\n"
                report += f"  - 落地: {arr_time} {arr_airport}\n" if arr_airport else f"  - 落地: {arr_time}\n"
                report += f"  - 价格: ¥{f.get('price', 0):.0f} | 飞行时长: {f.get('duration', '')} | 舱位: {f.get('class_type', '经济舱')}\n"
            return report

        if outbound:
            report = _render_flight_list(report, outbound, "去程航班")
        if return_fl:
            report = _render_flight_list(report, return_fl, "返程航班")
        if not outbound and not return_fl:
            report += "\n*实时搜索未获取到航班数据，请稍后重试或前往携程/去哪儿查询*\n"

        # 往返总价区间
        all_out_prices = [f.get("price", 0) for f in outbound if f.get("price", 0) > 0]
        all_ret_prices = [f.get("price", 0) for f in return_fl if f.get("price", 0) > 0]
        if all_out_prices and all_ret_prices:
            min_total = min(all_out_prices) + min(all_ret_prices)
            max_total = max(all_out_prices) + max(all_ret_prices)
            report += f"\n**往返总价区间: ¥{min_total:.0f} ~ ¥{max_total:.0f}**\n"

        # 高铁出行
        if trains:
            outbound_trains = [t for t in trains if not t.get("is_return", False)]
            return_trains = [t for t in trains if t.get("is_return", False)]
            if outbound_trains or return_trains:
                report += "\n## 高铁/动车推荐\n\n"
                report += "*两地距离较近，高铁更便捷（省时、舒适、准点率高），推荐以下车次：*\n\n"

                if outbound_trains:
                    report += "### 去程\n\n"
                    train_prices = [t.get("price", 0) for t in outbound_trains if t.get("price", 0) > 0]
                    if train_prices:
                        report += f"（票价区间: ¥{min(train_prices):.0f} ~ ¥{max(train_prices):.0f}）\n\n"
                    for t in outbound_trains:
                        report += f"- **{t.get('train_type', '高铁')} {t.get('train_number', '')}**\n"
                        report += f"  - 出发: {t.get('departure_time', '')} {t.get('departure_station', '')}\n"
                        report += f"  - 到达: {t.get('arrival_time', '')} {t.get('arrival_station', '')}\n"
                        report += f"  - 票价: {_p(t.get('price', 0))} | 用时: {t.get('duration', '')} | {t.get('seat_class', '二等座')}\n"

                if return_trains:
                    report += "\n### 返程\n\n"
                    for t in return_trains:
                        report += f"- **{t.get('train_type', '高铁')} {t.get('train_number', '')}**\n"
                        report += f"  - 出发: {t.get('departure_time', '')} {t.get('departure_station', '')}\n"
                        report += f"  - 到达: {t.get('arrival_time', '')} {t.get('arrival_station', '')}\n"
                        report += f"  - 票价: {_p(t.get('price', 0))} | 用时: {t.get('duration', '')} | {t.get('seat_class', '二等座')}\n"

                # 高铁往返总价
                out_tprices = [t.get("price", 0) for t in outbound_trains if t.get("price", 0) > 0]
                ret_tprices = [t.get("price", 0) for t in return_trains if t.get("price", 0) > 0]
                if out_tprices and ret_tprices:
                    train_total_min = min(out_tprices) + min(ret_tprices)
                    report += f"\n**高铁往返总价: ¥{train_total_min:.0f} 起**\n"

        report += "\n## 酒店\n\n"
        if hotels:
            hotel_prices = [h.get("price_per_night", 0) for h in hotels if h.get("price_per_night", 0) > 0]
            if hotel_prices:
                report += f"（价格区间: ¥{min(hotel_prices):.0f} ~ ¥{max(hotel_prices):.0f}/晚）\n\n"
            for h in hotels:
                report += f"- **{h.get('name', '')}**: ¥{h.get('price_per_night', 0):.0f}/晚, 评分: {h.get('rating', 0)}/5\n"
        else:
            report += "*实时搜索未获取到酒店数据，请稍后重试或前往携程查询*\n"

        report += "\n## 美食推荐\n\n"
        if food:
            for f in food:
                report += f"- **{f.get('name', '')}** ({f.get('cuisine', '')}, {f.get('price_range', '')}, 评分{f.get('rating', 0)}/5): {f.get('why_recommended', '')}\n"
                if f.get("must_try_dishes"):
                    report += f"  - 必尝: {', '.join(f['must_try_dishes'])}\n"
        else:
            report += "*实时搜索未获取到美食推荐，请稍后重试或前往大众点评查询*\n"

        report += "\n## 景点\n\n"
        if attractions:
            for a in attractions:
                report += f"- **{a.get('name', '')}** (第 {a.get('day', 0)} 天): {a.get('description', '')} - {a.get('estimated_duration', '')}\n"
        else:
            report += "*实时搜索未获取到景点数据，请稍后重试*\n"

        report += "\n## 预算明细\n\n"
        report += f"- 机票: ¥{budget_bd.get('flights', 0):.0f}\n"
        if budget_bd.get("trains", 0) > 0:
            report += f"- 高铁/动车: ¥{budget_bd.get('trains', 0):.0f}\n"
        report += f"- 酒店: ¥{budget_bd.get('hotels', 0):.0f}\n"
        report += f"- 餐饮: ¥{budget_bd.get('food', 0):.0f}\n"
        report += f"- 景点: ¥{budget_bd.get('attractions', 0):.0f}\n"
        report += f"- 交通: ¥{budget_bd.get('transport', 0):.0f}\n"
        report += f"- 其他: ¥{budget_bd.get('miscellaneous', 0):.0f}\n"
        report += f"- **总计: ¥{budget_bd.get('total', 0):.0f}**\n"
        report += f"- 剩余: ¥{budget_bd.get('remaining', 0):.0f}\n"
        report += f"- 是否在预算内: {'是' if budget_bd.get('within_budget') else '否'}\n"

        report += "\n## 数据来源与状态\n\n"
        if data_status:
            status_label = {"ok": "已获取", "partial": "部分获取", "unavailable": "未获取"}
            for name, item in data_status.items():
                label_map = {
                    "transport": "大交通",
                    "hotels": "酒店",
                    "attractions": "景点",
                    "food": "美食",
                    "weather": "天气",
                }
                status = item.get("status", "unavailable")
                reason = item.get("reason", "")
                suffix = f"，说明: {reason}" if reason else ""
                report += f"- {label_map.get(name, name)}: {status_label.get(status, status)}，来源: {item.get('source', '未知')}，数量: {item.get('count', 0)}{suffix}\n"
        else:
            report += "- 暂无数据源状态记录。\n"

        report += "\n## 天气摘要\n\n"
        if weather:
            for w in weather:
                report += f"- {w.get('date', '')}: {w.get('condition', '')}, {w.get('temperature_low', 0):.0f}-{w.get('temperature_high', 0):.0f}°C。{w.get('recommendation', '')}\n"
        else:
            report += "*实时搜索未获取到天气数据*\n"

        report += "\n## 最终备注\n\n"
        if critic.get("suggestions"):
            report += "**建议:**\n"
            for s in critic.get("suggestions", []):
                report += f"- {s}\n"
        report += f"\n*计划质量评分: {critic.get('score', 0)}/10*\n"

        return report
