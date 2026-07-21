"""
LangGraph workflow definition for the Multi-Agent Travel Planning System.
Orchestrates 10 specialized agents through a directed graph.
"""

import logging
from typing import Literal

from langgraph.graph import StateGraph, END

from app.state import TravelState, create_initial_state
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
from app.config import get_settings

logger = logging.getLogger(__name__)


class TravelWorkflow:
    """
    LangGraph-based workflow for travel planning.

    Graph structure:
        planner -> [flight, hotel, attraction, food, weather] (parallel)
        -> budget -> route -> critic -> final
    """

    def __init__(self):
        self.settings = get_settings()
        self._build_graph()

    def _build_graph(self):
        """Build the LangGraph state graph."""
        # Initialize agents
        self.planner = PlannerAgent()
        self.flight_agent = FlightAgent()
        self.hotel_agent = HotelAgent()
        self.attraction_agent = AttractionAgent()
        self.food_agent = FoodAgent()
        self.weather_agent = WeatherAgent()
        self.budget_agent = BudgetAgent()
        self.route_agent = RouteAgent()
        self.critic_agent = CriticAgent()
        self.final_agent = FinalAgent()

        # Create graph
        workflow = StateGraph(TravelState)

        # Add nodes
        workflow.add_node("planner", self.planner.run)
        workflow.add_node("flight", self.flight_agent.run)
        workflow.add_node("hotel", self.hotel_agent.run)
        workflow.add_node("attraction", self.attraction_agent.run)
        workflow.add_node("food", self.food_agent.run)
        workflow.add_node("weather", self.weather_agent.run)
        workflow.add_node("budget", self.budget_agent.run)
        workflow.add_node("route", self.route_agent.run)
        workflow.add_node("critic", self.critic_agent.run)
        workflow.add_node("final", self.final_agent.run)

        # Define edges
        # Planner runs first, then parallel data collection agents
        workflow.set_entry_point("planner")
        workflow.add_edge("planner", "flight")
        workflow.add_edge("planner", "hotel")
        workflow.add_edge("planner", "attraction")
        workflow.add_edge("planner", "food")
        workflow.add_edge("planner", "weather")

        # After all data collection, run budget and route optimization
        workflow.add_edge("flight", "budget")
        workflow.add_edge("hotel", "budget")
        workflow.add_edge("attraction", "budget")
        workflow.add_edge("food", "budget")
        workflow.add_edge("weather", "budget")

        # Budget feeds into route optimization
        workflow.add_edge("budget", "route")

        # Route feeds into critic review
        workflow.add_edge("route", "critic")

        # Critic feeds into final report
        workflow.add_edge("critic", "final")

        # Final is the end
        workflow.add_edge("final", END)

        self.graph = workflow.compile()
        logger.info("TravelWorkflow: Graph compiled successfully with 10 agents")

    async def run(self, user_input: dict) -> TravelState:
        """Execute the workflow with user input."""
        initial_state = create_initial_state(user_input)

        try:
            result = await self.graph.ainvoke(initial_state)
            return result
        except Exception as e:
            logger.error("Workflow execution error: %s", str(e))
            initial_state["status"] = "failed"
            initial_state["errors"] = initial_state.get("errors", []) + [f"Workflow: {str(e)}"]
            return initial_state

    def get_graph_visualization(self) -> str:
        """Return a Mermaid diagram of the workflow."""
        return """
graph TD
    P[规划师 Planner] --> F[航班 Flight]
    P --> H[酒店 Hotel]
    P --> A[景点 Attraction]
    P --> FD[美食 Food]
    P --> W[天气 Weather]
    F --> B[预算 Budget]
    H --> B
    A --> B
    FD --> B
    W --> B
    B --> R[路线 Route]
    R --> C[评审 Critic]
    C --> FN[最终报告 Final]
"""
