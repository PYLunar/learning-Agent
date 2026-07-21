"""
FastAPI server for the Multi-Agent Travel Planning System.
Supports async execution and streaming responses.
"""

import os
from pathlib import Path
# 在所有 import 之前加载 .env 文件，确保环境变量可用
from dotenv import load_dotenv
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

import logging
import json
import asyncio
from typing import AsyncGenerator, Optional
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.graph.workflow import TravelWorkflow
from app.state import TravelState
from app.config import get_settings

# 国内城市列表（用于校验目的地和出发地）
DOMESTIC_CITIES = {
    "北京", "上海", "广州", "深圳", "成都", "杭州", "西安", "重庆", "南京", "武汉",
    "长沙", "昆明", "厦门", "青岛", "大连", "三亚", "苏州", "丽江", "拉萨", "天津",
    "哈尔滨", "沈阳", "济南", "郑州", "福州", "南昌", "合肥", "贵阳", "太原", "石家庄",
    "呼和浩特", "南宁", "海口", "兰州", "银川", "西宁", "乌鲁木齐", "惠州", "珠海", "东莞",
    "佛山", "中山", "温州", "无锡", "常州", "徐州", "南通", "烟台", "潍坊", "洛阳",
    "桂林", "北海", "保定", "唐山", "绍兴", "嘉兴", "金华", "漳州", "泉州", "赣州",
    "遵义", "邯郸", "大同", "包头", "吉林", "长春", "延吉", "鞍山", "抚顺", "丹东",
    "营口", "齐齐哈尔", "大庆", "佳木斯", "四平", "赤峰", "岳阳", "常德", "张家界",
    "衡阳", "株洲", "湛江", "汕头", "潮州", "揭阳", "梅州", "河源", "清远", "肇庆",
    "江门", "阳江", "茂名", "湛江", "云浮", "汕尾", "惠州", "珠海", "中山", "东莞",
    "黄山", "芜湖", "蚌埠", "马鞍山", "安庆", "池州", "铜陵", "淮南", "淮北", "阜阳",
    "宿州", "亳州", "六安", "滁州", "宣城", "巢湖", "莆田", "龙岩", "三明", "南平",
    "宁德", "景德镇", "九江", "上饶", "抚州", "吉安", "萍乡", "新余", "鹰潭", "赣州",
    "宜昌", "襄阳", "荆州", "黄冈", "十堰", "恩施", "咸宁", "孝感", "荆门", "鄂州",
    "黄石", "洛阳", "开封", "许昌", "新乡", "焦作", "安阳", "南阳", "信阳", "驻马店",
    "平顶山", "漯河", "三门峡", "商丘", "周口", "鹤壁", "濮阳", "日照", "威海", "德州",
    "聊城", "滨州", "菏泽", "枣庄", "泰安", "莱芜", "临沂", "淄博", "东营", "济宁",
    "乐山", "绵阳", "德阳", "宜宾", "泸州", "南充", "达州", "广安", "自贡", "内江",
    "遂宁", "眉山", "资阳", "雅安", "巴中", "广元", "攀枝花", "凉山", "甘孜", "阿坝",
    "曲靖", "玉溪", "大理", "香格里拉", "西双版纳", "红河", "文山", "楚雄", "普洱", "保山",
    "临沧", "丽江", "昭通", "德宏", "怒江", "迪庆", "日喀则", "林芝", "昌都", "山南", "那曲",
    "榆林", "延安", "汉中", "安康", "商洛", "渭南", "咸阳", "宝鸡", "铜川", "天水",
    "酒泉", "嘉峪关", "张掖", "武威", "金昌", "白银", "定西", "陇南", "平凉", "庆阳",
    "固原", "中卫", "石嘴山", "吴忠", "海东", "格尔木", "德令哈", "玉树", "果洛", "海北",
    "吐鲁番", "喀什", "阿克苏", "和田", "伊犁", "克拉玛依", "博乐", "库尔勒", "哈密", "阿勒泰",
}

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global workflow instance
_workflow: Optional[TravelWorkflow] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    global _workflow
    logger.info("Starting up Travel Agent API...")
    _workflow = TravelWorkflow()
    logger.info("Travel Agent API ready")
    yield
    logger.info("Shutting down Travel Agent API...")


app = FastAPI(
    title="AI Travel Agent API",
    description="Multi-Agent Travel Planning System powered by LangGraph",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (frontend)
import os
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Request/Response models
class TravelRequest(BaseModel):
    """User travel request."""
    destination: str = Field(..., description="旅行目的地城市")
    days: Optional[int] = Field(default=None, ge=1, le=30, description="旅行天数（可由日期自动计算）")
    budget: float = Field(..., gt=0, description="总预算（人民币 CNY）")
    preferences: list[str] = Field(default=[], description="旅行偏好 (如 美食、文化、购物)")
    origin: Optional[str] = Field(default="北京", description="出发城市")
    travel_dates: Optional[dict] = Field(default=None, description="旅行日期 {departure, return}")
    language: Optional[str] = Field(default="zh", description="输出语言 (zh 或 en)")


class TravelResponse(BaseModel):
    """Travel plan response."""
    status: str
    destination: str
    days: int
    budget: float
    final_plan: str
    structured_data: dict
    logs: list
    errors: list
    processing_time_ms: Optional[float] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    agents_ready: bool


def _validate_domestic_city(city_name: str, role: str) -> None:
    """Validate a city is supported by the domestic travel planner."""
    if city_name and city_name not in DOMESTIC_CITIES:
        raise HTTPException(
            status_code=400,
            detail=f"目前仅支持国内城市旅行规划，暂不支持国际旅行。「{city_name}」不是国内城市，请修改{role}为国内城市。",
        )


def _prepare_user_input(request: TravelRequest) -> dict:
    """Normalize and validate a travel request before it enters the workflow."""
    user_input = request.model_dump()

    _validate_domestic_city(user_input.get("destination", ""), "目的地")
    _validate_domestic_city(user_input.get("origin", ""), "出发地")

    dates = user_input.get("travel_dates")
    if not user_input.get("days") and dates:
        if isinstance(dates, dict) and dates.get("departure") and dates.get("return"):
            try:
                departure_date = datetime.strptime(dates["departure"], "%Y-%m-%d")
                return_date = datetime.strptime(dates["return"], "%Y-%m-%d")
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="旅行日期格式应为 YYYY-MM-DD") from exc

            calculated_days = (return_date - departure_date).days + 1
            if calculated_days < 1:
                raise HTTPException(status_code=422, detail="返回日期不能早于出发日期")

            user_input["days"] = calculated_days
            logger.info(
                "自动计算天数: %d（从 %s 到 %s）",
                calculated_days,
                dates["departure"],
                dates["return"],
            )

    if not user_input.get("days"):
        raise HTTPException(status_code=422, detail="请提供旅行天数或旅行日期（出发日期+返回日期）")

    return user_input


@app.get("/", response_model=HealthResponse)
async def root():
    """Root endpoint - serves the frontend page or returns health status."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path, media_type="text/html")
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        agents_ready=_workflow is not None,
    )


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        agents_ready=_workflow is not None,
    )


@app.post("/plan", response_model=TravelResponse)
async def create_travel_plan(request: TravelRequest):
    """
    Create a complete travel plan.

    Example request:
    ```json
    {
        "destination": "东京",
        "days": 5,
        "budget": 10000,
        "preferences": ["美食", "文化", "购物"],
        "origin": "北京",
        "language": "zh"
    }
    ```
    """
    if _workflow is None:
        raise HTTPException(status_code=503, detail="Workflow not initialized")

    import time
    start_time = time.time()

    try:
        user_input = _prepare_user_input(request)

        timeout_seconds = getattr(_workflow, "settings", None)
        timeout_seconds = getattr(timeout_seconds, "PLAN_TIMEOUT_SECONDS", get_settings().PLAN_TIMEOUT_SECONDS)
        try:
            result = await asyncio.wait_for(_workflow.run(user_input), timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail=f"真实数据获取超过 {timeout_seconds:.0f} 秒，请稍后重试或缩短行程范围。",
            ) from exc

        processing_time = (time.time() - start_time) * 1000

        return TravelResponse(
            status=result.get("status", "unknown"),
            destination=result.get("destination", ""),
            days=result.get("days", 0),
            budget=result.get("budget", 0),
            final_plan=result.get("final_plan", ""),
            structured_data=result.get("final_plan_structured", {}),
            logs=result.get("logs", []),
            errors=result.get("errors", []),
            processing_time_ms=round(processing_time, 2),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error processing travel plan: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def _stream_plan(user_input: dict) -> AsyncGenerator[str, None]:
    """Stream travel plan generation progress."""
    agent_order = [
        ("planner", "正在分析您的旅行需求..."),
        ("flight", "正在搜索最佳航班..."),
        ("hotel", "正在查找理想酒店..."),
        ("attraction", "正在发现必去景点..."),
        ("food", "正在搜寻当地美食..."),
        ("weather", "正在查询天气预报..."),
        ("budget", "正在核算预算..."),
        ("route", "正在整理每日安排..."),
        ("critic", "正在检查行程质量..."),
        ("final", "正在生成旅行计划报告..."),
    ]

    for agent_name, message in agent_order:
        yield json.dumps({
            "agent": agent_name,
            "status": "running",
            "message": message,
        }) + "\n"
        await asyncio.sleep(0.3)  # Simulate processing time

    # Run actual workflow
    timeout_seconds = getattr(_workflow, "settings", None)
    timeout_seconds = getattr(timeout_seconds, "PLAN_TIMEOUT_SECONDS", get_settings().PLAN_TIMEOUT_SECONDS)
    try:
        result = await asyncio.wait_for(_workflow.run(user_input), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        yield json.dumps({
            "agent": "final",
            "status": "failed",
            "message": f"真实数据获取超过 {timeout_seconds:.0f} 秒，请稍后重试或缩短行程范围。",
            "plan": "",
            "structured": {},
            "errors": [f"真实数据获取超过 {timeout_seconds:.0f} 秒"],
        }) + "\n"
        return

    yield json.dumps({
        "agent": "final",
        "status": "completed",
        "message": "旅行计划已生成！",
        "plan": result.get("final_plan", ""),
        "structured": result.get("final_plan_structured", {}),
        "errors": result.get("errors", []),
    }) + "\n"


@app.post("/plan/stream")
async def stream_travel_plan(request: TravelRequest):
    """
    Stream travel plan generation with real-time progress updates.

    Returns Server-Sent Events (SSE) with progress updates from each agent.
    """
    if _workflow is None:
        raise HTTPException(status_code=503, detail="Workflow not initialized")

    user_input = _prepare_user_input(request)

    async def event_generator():
        async for chunk in _stream_plan(user_input):
            yield {"data": chunk}

    return EventSourceResponse(event_generator())


@app.get("/workflow/graph")
async def get_workflow_graph():
    """Get the workflow architecture visualization (Mermaid diagram)."""
    if _workflow is None:
        raise HTTPException(status_code=503, detail="Workflow not initialized")

    return {
        "mermaid": _workflow.get_graph_visualization(),
        "description": "Multi-Agent Travel Planning Workflow using LangGraph",
    }


@app.get("/agents")
async def list_agents():
    """List all available agents and their descriptions."""
    return {
        "agents": [
            {"name": "planner", "description": "Decomposes user requirements into subtasks"},
            {"name": "flight", "description": "Recommends optimal flight options"},
            {"name": "hotel", "description": "Recommends hotels based on budget and location"},
            {"name": "attraction", "description": "Recommends tourist attractions grouped by day"},
            {"name": "food", "description": "Recommends authentic local restaurants"},
            {"name": "weather", "description": "Provides weather forecasts for travel dates"},
            {"name": "budget", "description": "Calculates total costs and checks feasibility"},
            {"name": "critic", "description": "Reviews the full itinerary for quality"},
            {"name": "final", "description": "Combines all outputs into a Markdown report"},
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8088)
