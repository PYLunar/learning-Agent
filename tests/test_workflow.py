"""
Integration tests for the LangGraph workflow.
"""

import pytest

from app.graph.workflow import TravelWorkflow
from app.state import create_initial_state


@pytest.mark.asyncio
async def test_full_workflow():
    """Test the complete workflow execution."""
    workflow = TravelWorkflow()

    user_input = {
        "destination": "Paris",
        "days": 3,
        "budget": 1500,
        "preferences": ["culture", "food"],
        "origin": "London",
        "language": "en",
    }

    result = await workflow.run(user_input)

    assert result["status"] == "completed"
    assert result["destination"] == "Paris"
    assert len(result["flights"]) > 0
    assert len(result["hotels"]) > 0
    assert "attractions" in result
    assert "food_recommendations" in result
    assert "attractions" in result["data_status"]
    assert "food" in result["data_status"]
    assert len(result["weather"]) > 0
    assert "total" in result["budget_breakdown"]
    assert "route" in result
    assert "score" in result["critic_feedback"]
    assert len(result["final_plan"]) > 0
    assert len(result["logs"]) >= 10  # At least one log per agent


@pytest.mark.asyncio
async def test_workflow_with_mock_mode():
    """Test workflow runs successfully in mock mode."""
    workflow = TravelWorkflow()

    user_input = {
        "destination": "Bangkok",
        "days": 2,
        "budget": 800,
        "preferences": ["food", "shopping"],
        "origin": "Beijing",
        "language": "zh",
    }

    result = await workflow.run(user_input)

    assert result["status"] == "completed"
    assert len(result["final_plan"]) > 0
