"""
Unit tests for the Multi-Agent Travel Planning System.
"""

import pytest
import asyncio

from app.state import create_initial_state, TravelState
from app.agents.planner import PlannerAgent
from app.agents.flight_agent import FlightAgent
from app.agents.hotel_agent import HotelAgent
from app.agents.attraction_agent import AttractionAgent
from app.agents.food_agent import FoodAgent
from app.agents.weather_agent import WeatherAgent
from app.agents.budget_agent import BudgetAgent
from app.agents.route_agent import RouteAgent
from app.agents.critic_agent import CriticAgent
from app.agents.final_agent import FinalAgent


@pytest.fixture
def sample_user_input():
    return {
        "destination": "Tokyo",
        "days": 3,
        "budget": 2000,
        "preferences": ["food", "culture"],
        "origin": "Beijing",
        "language": "en",
    }


@pytest.fixture
def sample_state(sample_user_input):
    return create_initial_state(sample_user_input)


@pytest.mark.asyncio
async def test_planner_agent(sample_state):
    agent = PlannerAgent()
    result = await agent.run(sample_state)
    assert len(result["planner_tasks"]) > 0


@pytest.mark.asyncio
async def test_flight_agent(sample_state):
    agent = FlightAgent()
    result = await agent.run(sample_state)
    assert len(result["flights"]) > 0
    assert "price" in result["flights"][0]


@pytest.mark.asyncio
async def test_hotel_agent(sample_state):
    agent = HotelAgent()
    result = await agent.run(sample_state)
    assert len(result["hotels"]) > 0
    assert "price_per_night" in result["hotels"][0]


@pytest.mark.asyncio
async def test_attraction_agent(sample_state):
    agent = AttractionAgent()
    result = await agent.run(sample_state)
    assert "attractions" in result
    assert "attractions" in result["data_status"]
    assert result["data_status"]["attractions"]["status"] in {"ok", "unavailable"}


@pytest.mark.asyncio
async def test_food_agent(sample_state):
    agent = FoodAgent()
    result = await agent.run(sample_state)
    assert "food_recommendations" in result
    assert "food" in result["data_status"]
    assert result["data_status"]["food"]["status"] in {"ok", "partial", "unavailable"}


@pytest.mark.asyncio
async def test_weather_agent(sample_state):
    agent = WeatherAgent()
    result = await agent.run(sample_state)
    assert len(result["weather"]) > 0


@pytest.mark.asyncio
async def test_budget_agent(sample_state):
    # Pre-populate with flight and hotel data
    sample_state["flights"] = [{"price": 800}]
    sample_state["hotels"] = [{"total_price": 450}]
    sample_state["attractions"] = [{"price": 50}]
    sample_state["food_recommendations"] = [{"price_range": "$$"}]

    agent = BudgetAgent()
    result = await agent.run(sample_state)
    assert "total" in result["budget_breakdown"]


@pytest.mark.asyncio
async def test_budget_agent_train_only_counts_train_tickets(sample_state):
    sample_state["transport_strategy"] = {"train_only": True}
    sample_state["flights"] = [{"price": 900}, {"price": 700, "is_return": True}]
    sample_state["trains"] = [{"price": 300}, {"price": 280, "is_return": True}]

    agent = BudgetAgent()
    result = await agent.run(sample_state)

    assert result["budget_breakdown"]["flights"] == 0
    assert result["budget_breakdown"]["trains"] == 580


@pytest.mark.asyncio
async def test_budget_agent_mixed_transport_counts_only_flights(sample_state):
    sample_state["transport_strategy"] = {"train_only": False, "show_flights": True}
    sample_state["flights"] = [{"price": 900}, {"price": 700, "is_return": True}]
    sample_state["trains"] = [{"price": 300}, {"price": 280, "is_return": True}]

    agent = BudgetAgent()
    result = await agent.run(sample_state)

    assert result["budget_breakdown"]["flights"] == 1600
    assert result["budget_breakdown"]["trains"] == 0


@pytest.mark.asyncio
async def test_budget_agent_ignores_unpriced_hotels(sample_state):
    sample_state["hotels"] = [{"name": "真实POI酒店", "price_per_night": 0}]

    agent = BudgetAgent()
    result = await agent.run(sample_state)

    assert result["budget_breakdown"]["hotels"] == 0


@pytest.mark.asyncio
async def test_route_agent(sample_state):
    sample_state["attractions"] = [
        {"name": "Senso-ji", "day": 1},
        {"name": "Skytree", "day": 1},
        {"name": "Meiji Shrine", "day": 2},
    ]
    sample_state["hotels"] = [{"name": "Grand Hotel Tokyo"}]

    agent = RouteAgent()
    result = await agent.run(sample_state)
    assert len(result["route"]) > 0


@pytest.mark.asyncio
async def test_critic_agent(sample_state):
    sample_state["flights"] = [{"price": 800}]
    sample_state["hotels"] = [{"total_price": 450}]
    sample_state["attractions"] = [{"price": 50, "day": 1}]
    sample_state["food_recommendations"] = [{"price_range": "$$"}]
    sample_state["budget_breakdown"] = {"total": 1500, "within_budget": True}
    sample_state["route"] = [{"day": 1, "morning": ["Attraction"], "afternoon": [], "evening": []}]

    agent = CriticAgent()
    result = await agent.run(sample_state)
    assert "score" in result["critic_feedback"]


@pytest.mark.asyncio
async def test_final_agent(sample_state):
    sample_state["flights"] = [{"price": 800, "airline": "ANA", "flight_number": "NH101"}]
    sample_state["hotels"] = [{"name": "Grand Hotel", "price_per_night": 150, "total_price": 450}]
    sample_state["attractions"] = [{"name": "Temple", "day": 1, "description": "Historic temple"}]
    sample_state["food_recommendations"] = [{"name": "Sushi Place", "cuisine": "Sushi"}]
    sample_state["weather"] = [{"date": "Day 1", "condition": "Sunny"}]
    sample_state["budget_breakdown"] = {"total": 1500, "within_budget": True}
    sample_state["route"] = [{"day": 1, "morning": ["Temple"], "afternoon": [], "evening": []}]
    sample_state["critic_feedback"] = {"score": 8.5, "suggestions": []}

    agent = FinalAgent()
    result = await agent.run(sample_state)
    assert len(result["final_plan"]) > 0
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_final_agent_hides_route_optimization_output(sample_state):
    sample_state["flights"] = [{"price": 800, "airline": "ANA", "flight_number": "NH101"}]
    sample_state["hotels"] = [{"name": "Grand Hotel", "price_per_night": 150, "total_price": 450}]
    sample_state["attractions"] = [{"name": "Temple", "day": 1, "description": "Historic temple"}]
    sample_state["food_recommendations"] = [{"name": "Sushi Place", "cuisine": "Sushi"}]
    sample_state["weather"] = [{"date": "Day 1", "condition": "Sunny"}]
    sample_state["budget_breakdown"] = {"total": 1500, "within_budget": True}
    sample_state["route"] = [{
        "day": 1,
        "morning": ["Optimized Morning Stop"],
        "afternoon": ["Optimized Afternoon Stop"],
        "evening": ["Optimized Evening Stop"],
    }]
    sample_state["critic_feedback"] = {"score": 8.5, "suggestions": []}
    sample_state["data_status"] = {
        "hotels": {
            "source": "FlyAI hotel / Amap POI",
            "status": "partial",
            "count": 1,
            "reason": "仅获取到酒店名称/地址，缺少真实价格",
        }
    }

    agent = FinalAgent()
    result = await agent.run(sample_state)

    assert "route" not in result["final_plan_structured"]
    assert "data_status" in result["final_plan_structured"]
    assert "数据来源与状态" in result["final_plan"]
    assert "路线优化说明" not in result["final_plan"]
    assert "Optimized Morning Stop" not in result["final_plan"]
    assert "Temple" in result["final_plan"]
