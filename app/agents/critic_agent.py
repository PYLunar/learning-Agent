"""
Critic / Reviewer Agent - reviews the full itinerary for quality.
"""

import json
import logging

from app.state import TravelState, CriticFeedback
from app.llm_client import get_llm_client
from app.prompts import get_system_prompt, get_user_prompt

logger = logging.getLogger(__name__)


class CriticAgent:
    """Agent responsible for reviewing and critiquing the travel plan."""

    def __init__(self):
        self.llm = get_llm_client()

    async def run(self, state: TravelState) -> dict:
        """Review the full itinerary and provide feedback."""
        output = {}
        try:
            logger.info("CriticAgent: Reviewing itinerary")

            destination = state.get("destination", "")
            budget = state.get("budget", 0)
            attractions = state.get("attractions", [])
            flights = state.get("flights", [])
            trains = state.get("trains", [])
            hotels = state.get("hotels", [])
            food = state.get("food_recommendations", [])
            route = state.get("route", [])
            budget_breakdown = state.get("budget_breakdown", {})

            # Build a summary itinerary for the critic
            itinerary_summary = []
            for r in route:
                day_plan = f"第{r.get('day', 0)}天: 上午: {r.get('morning', [])}, "
                day_plan += f"下午: {r.get('afternoon', [])}, 晚上: {r.get('evening', [])}"
                itinerary_summary.append(day_plan)

            # Perform rule-based checks first
            issues = []
            suggestions = []
            score = 10.0

            # Budget check
            total = budget_breakdown.get("total", 0)
            within_budget = budget_breakdown.get("within_budget", True)
            if not within_budget and budget > 0:
                issues.append(f"超出预算 ¥{total - budget:.0f}")
                score -= 2.0
                suggestions.append("建议选择更经济的酒店或航班")

            # Schedule balance check
            days = state.get("days", 1)
            attrs_per_day = len(attractions) / days if days > 0 else 0
            if attrs_per_day > 4:
                issues.append("行程安排可能过于紧凑")
                score -= 1.5
                suggestions.append("建议减少每天的景点数量")
            elif attrs_per_day < 2:
                issues.append("行程安排可能过于宽松")
                score -= 0.5
                suggestions.append("建议增加更多活动安排")

            # Missing components check
            if not flights and not trains:
                issues.append("缺少大交通信息")
                score -= 1.0
            if not hotels:
                issues.append("缺少酒店信息")
                score -= 1.0
            if not attractions:
                issues.append("缺少景点规划")
                score -= 2.0
            if not food:
                issues.append("缺少美食推荐")
                score -= 0.5

            feedback = CriticFeedback(
                budget_feasible=within_budget,
                schedule_balanced=2 <= attrs_per_day <= 4,
                no_missing_components=len(issues) == 0,
                issues=issues,
                suggestions=suggestions,
                score=max(0, min(10, score)),
                needs_revision=score < 7 or not within_budget,
            )

            from app.config import get_settings
            if get_settings().ENABLE_LLM_ENHANCEMENT:
                # Get optional LLM critique
                lang = state.get("user_input", {}).get("language", "zh")
                system_prompt = get_system_prompt("critic", lang)
                user_prompt = get_user_prompt("critic", lang).format(
                    destination=destination,
                    budget=budget,
                    itinerary="\n".join(itinerary_summary),
                    flights=len(flights),
                    hotels=len(hotels),
                    attractions=len(attractions),
                    food=len(food),
                )

                response = await self.llm.chat_completion(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_format="json",
                )

                try:
                    llm_result = json.loads(response)
                    llm_feedback = llm_result.get("feedback", {})

                    # Merge rule-based and LLM feedback
                    issues.extend(llm_feedback.get("issues", []))
                    suggestions.extend(llm_feedback.get("suggestions", []))
                    llm_score = llm_feedback.get("score", score)
                    score = (score + llm_score) / 2

                    feedback = CriticFeedback(
                        budget_feasible=within_budget,
                        schedule_balanced=2 <= attrs_per_day <= 4,
                        no_missing_components=len(issues) == 0 or all("No " not in i for i in issues),
                        issues=list(set(issues)),
                        suggestions=list(set(suggestions)),
                        score=max(0, min(10, score)),
                        needs_revision=score < 7 or not within_budget,
                    )
                except (json.JSONDecodeError, TypeError):
                    pass

            output["critic_feedback"] = feedback
            output["logs"] = [{
                "agent": "critic",
                "action": "itinerary_review",
                "output": f"Score: {feedback.get('score', 0)}/10, Issues: {len(feedback.get('issues', []))}",
                "status": "success",
            }]

            logger.info("CriticAgent: Review complete, score %.1f/10", feedback.get("score", 0))

        except Exception as e:
            logger.error("CriticAgent error: %s", str(e))
            output["errors"] = [f"CriticAgent: {str(e)}"]
            output["critic_feedback"] = CriticFeedback(
                budget_feasible=True,
                schedule_balanced=True,
                no_missing_components=True,
                issues=[],
                suggestions=[],
                score=7.0,
                needs_revision=False,
            )

        return output
