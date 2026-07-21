"""
Shared state definitions for the Multi-Agent Travel Planning System.
Uses TypedDict for LangGraph compatibility with strict typing.
"""

import operator
from typing import TypedDict, List, Dict, Any, Optional, Annotated
from datetime import date


def _merge_dicts(a: Dict, b: Dict) -> Dict:
    """Merge two dicts, with b taking precedence."""
    result = dict(a)
    result.update(b)
    return result


class FlightOption(TypedDict, total=False):
    """Structured flight option."""
    airline: str
    flight_number: str
    departure_city: str       # 出发城市（如 "北京"）
    arrival_city: str         # 到达城市（如 "东京"）
    departure_airport: str    # 起飞机场（如 "深圳宝安国际机场T3"）
    arrival_airport: str      # 落地机场（如 "成都天府国际机场T2"）
    departure_time: str       # 预计起飞时间（如 "08:30"）
    arrival_time: str         # 预计落地时间（如 "13:00"）
    departure: str            # 兼容旧字段
    arrival: str              # 兼容旧字段
    price: float
    duration: str
    layovers: int
    layover_cities: List[str]
    class_type: str
    booking_url: Optional[str]
    is_return: Optional[bool]    # 是否为返程航班


class HotelOption(TypedDict, total=False):
    """Structured hotel option."""
    name: str
    address: str
    price_per_night: float
    total_price: float
    rating: float
    distance_to_center_km: float
    amenities: List[str]
    booking_url: Optional[str]


class Attraction(TypedDict, total=False):
    """Tourist attraction or activity."""
    name: str
    description: str
    location: str
    estimated_duration: str
    price: float
    category: str
    best_time: str
    day: int


class FoodSpot(TypedDict, total=False):
    """Restaurant or food recommendation."""
    name: str
    cuisine: str
    price_range: str
    rating: float
    address: str
    why_recommended: str
    must_try_dishes: List[str]
    meal_type: str  # breakfast, lunch, dinner, snack


class WeatherDay(TypedDict, total=False):
    """Weather for a single day."""
    date: str
    condition: str
    temperature_high: float
    temperature_low: float
    precipitation_chance: float
    recommendation: str


class BudgetBreakdown(TypedDict, total=False):
    """Budget breakdown by category."""
    flights: float
    trains: float
    hotels: float
    food: float
    attractions: float
    transport: float
    miscellaneous: float
    total: float
    remaining: float
    within_budget: bool


class RouteDay(TypedDict, total=False):
    """Optimized route for a single day."""
    day: int
    morning: List[str]
    afternoon: List[str]
    evening: List[str]
    transport_between: List[str]
    estimated_walking_km: float


class CriticFeedback(TypedDict, total=False):
    """Feedback from the critic agent."""
    budget_feasible: bool
    schedule_balanced: bool
    no_missing_components: bool
    issues: List[str]
    suggestions: List[str]
    score: float  # 0-10
    needs_revision: bool


class TravelInsights(TypedDict, total=False):
    """Actionable trip insights rendered in the final report."""
    packing_checklist: List[str]
    risk_alerts: List[str]
    budget_tips: List[str]
    transport_tips: List[str]
    booking_reminders: List[str]


class DataStatus(TypedDict, total=False):
    """External data source status for transparent real-data reporting."""
    source: str
    status: str  # ok, partial, unavailable
    count: int
    reason: str


class TravelState(TypedDict, total=False):
    """
    Central shared state passed between all agents in the LangGraph workflow.
    All fields are optional to allow incremental population.
    """
    # Input
    user_input: Dict[str, Any]
    destination: str
    days: int
    budget: float
    preferences: List[str]
    travel_dates: Dict[str, str]
    origin: str
    local_currency: str

    # Agent outputs
    planner_tasks: List[Dict[str, Any]]
    city_info: Dict[str, Any]
    flights: List[FlightOption]
    trains: List[Dict[str, Any]]  # 高铁/动车车次（由 FlightAgent 填充）
    transport_strategy: Dict[str, Any]
    data_status: Annotated[Dict[str, DataStatus], _merge_dicts]
    hotels: List[HotelOption]
    attractions: List[Attraction]
    food_recommendations: List[FoodSpot]
    weather: List[WeatherDay]
    budget_breakdown: BudgetBreakdown
    route: List[RouteDay]
    critic_feedback: CriticFeedback
    travel_insights: TravelInsights

    # Final output
    final_plan: str
    final_plan_structured: Dict[str, Any]

    # Metadata
    status: str  # pending, in_progress, completed, failed
    current_agent: str
    errors: Annotated[List[str], operator.add]
    logs: Annotated[List[Dict[str, Any]], operator.add]
    retry_count: int
    cache_hits: Annotated[List[str], operator.add]


def create_initial_state(user_input: Dict[str, Any]) -> TravelState:
    """Initialize state from user input with defaults."""
    return TravelState(
        user_input=user_input,
        destination=user_input.get("destination", ""),
        days=user_input.get("days", 0),
        budget=user_input.get("budget", 0.0),
        preferences=user_input.get("preferences", []),
        travel_dates=user_input.get("travel_dates", {}),
        origin=user_input.get("origin", "北京"),
        local_currency="CNY",
        planner_tasks=[],
        city_info={},
        flights=[],
        trains=[],
        transport_strategy={},
        data_status={},
        hotels=[],
        attractions=[],
        food_recommendations=[],
        weather=[],
        budget_breakdown=BudgetBreakdown(),
        route=[],
        critic_feedback=CriticFeedback(),
        final_plan="",
        final_plan_structured={},
        status="pending",
        current_agent="",
        errors=[],
        logs=[],
        retry_count=0,
        cache_hits=[],
    )
