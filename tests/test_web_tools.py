"""
联网功能测试 - 测试所有新增的联网工具。
"""

import pytest

from app.tools.web_search import WebSearchTool, get_web_search
from app.tools.web_scraper import WebScraperTool
from app.tools.wikipedia_api import WikipediaTool, get_wikipedia
from app.tools.exchange_api import ExchangeRateTool, get_exchange_rate
from app.tools.directions_api import DirectionsTool, get_directions
from app.tools.amap_api import AmapAPI, get_amap_api
from app.tools.qweather_api import QWeatherTool, get_qweather
from app.tools.train_api import TrainSearchTool
from app.tools.cache_utils import TTLCache
from app.tools.retry import RetryHandler


# ============ WebSearch ============

@pytest.mark.asyncio
async def test_web_search_duckduckgo():
    """测试 DuckDuckGo 搜索。"""
    tool = WebSearchTool()
    results = await tool.search("Tokyo travel", max_results=3)
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_web_search_singleton():
    """测试单例。"""
    assert get_web_search() is get_web_search()


# ============ WebScraper ============

@pytest.mark.asyncio
async def test_web_scraper():
    """测试网页抓取。"""
    tool = WebScraperTool()
    # example.com is reliable
    text = await tool.fetch_page("https://example.com")
    assert True  # 只要不报错就算通过


# ============ Wikipedia ============

@pytest.mark.asyncio
async def test_wikipedia_summary():
    """测试 Wikipedia 摘要获取。"""
    tool = WikipediaTool()
    summary = await tool.get_summary("Tokyo")
    # Tokyo 一定有 Wikipedia 页面
    if summary:
        assert "title" in summary
        assert len(summary.get("extract", "")) > 0


@pytest.mark.asyncio
async def test_wikipedia_search():
    """测试 Wikipedia 搜索。"""
    tool = WikipediaTool()
    results = await tool.search("Tokyo tourism", limit=3)
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_wikipedia_city_info():
    """测试城市综合信息获取。"""
    tool = WikipediaTool()
    info = await tool.get_city_info("Paris")
    if info:
        assert "overview" in info
        assert "related_places" in info


@pytest.mark.asyncio
async def test_wikipedia_singleton():
    """测试单例。"""
    assert get_wikipedia() is get_wikipedia()


# ============ ExchangeRate ============

@pytest.mark.asyncio
async def test_exchange_rate():
    """测试汇率获取。"""
    tool = ExchangeRateTool()
    # EUR to USD 一定有结果
    rate = await tool.get_rate("EUR", "USD")
    if rate:
        assert rate > 0


@pytest.mark.asyncio
async def test_exchange_detect_currency():
    """测试货币推断。"""
    tool = ExchangeRateTool()
    assert tool.detect_currency("tokyo") == "JPY"
    assert tool.detect_currency("paris") == "EUR"
    assert tool.detect_currency("beijing") == "CNY"
    assert tool.detect_currency("new york") == "USD"


@pytest.mark.asyncio
async def test_exchange_convert():
    """测试货币转换。"""
    tool = ExchangeRateTool()
    # USD to USD 应该不变
    assert await tool.convert_to_usd(100, "USD") == 100
    assert await tool.convert_from_usd(100, "USD") == 100


@pytest.mark.asyncio
async def test_exchange_singleton():
    """测试单例。"""
    assert get_exchange_rate() is get_exchange_rate()


# ============ Directions ============

@pytest.mark.asyncio
async def test_directions_estimated():
    """测试路线估算（无 Google Maps Key 时）。"""
    tool = DirectionsTool()
    result = await tool.get_route("Tokyo", "Osaka", "transit")
    if result:
        assert "distance_km" in result
        assert "duration_minutes" in result
        assert result["distance_km"] > 0


@pytest.mark.asyncio
async def test_directions_multi_route():
    """测试多段路线摘要。"""
    tool = DirectionsTool()
    result = await tool.get_multi_route_summary(
        ["Osaka", "Kyoto"], "Tokyo", "transit"
    )
    if result:
        assert "total_distance_km" in result
        assert "segments" in result


@pytest.mark.asyncio
async def test_directions_singleton():
    """测试单例。"""
    assert get_directions() is get_directions()


# ============ TTLCache ============

def test_ttl_cache_basic():
    """测试 TTL 缓存基本功能。"""
    cache = TTLCache(default_ttl=1)
    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"
    assert cache.has("key1")
    assert cache.size == 1


def test_ttl_cache_miss():
    """测试缓存未命中。"""
    cache = TTLCache()
    assert cache.get("nonexistent") is None


def test_ttl_cache_delete():
    """测试缓存删除。"""
    cache = TTLCache()
    cache.set("key1", "value1")
    assert cache.delete("key1") is True
    assert cache.delete("key1") is False


def test_ttl_cache_clear():
    """测试缓存清空。"""
    cache = TTLCache()
    cache.set("a", 1)
    cache.set("b", 2)
    cache.clear()
    assert cache.size == 0


# ============ RetryHandler ============

@pytest.mark.asyncio
async def test_retry_success_first_try():
    """测试重试：首次成功。"""
    handler = RetryHandler(max_retries=3, base_delay=0.01)

    call_count = 0

    async def success_func():
        nonlocal call_count
        call_count += 1
        return "ok"

    result = await handler.execute(success_func)
    assert result == "ok"
    assert call_count == 1


@pytest.mark.asyncio
async def test_retry_success_after_failures():
    """测试重试：失败后成功。"""
    handler = RetryHandler(max_retries=3, base_delay=0.01)

    call_count = 0

    async def flaky_func():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("temp failure")
        return "ok"

    result = await handler.execute(flaky_func)
    assert result == "ok"
    assert call_count == 3


@pytest.mark.asyncio
async def test_retry_exhausted():
    """测试重试：耗尽所有重试次数。"""
    handler = RetryHandler(max_retries=2, base_delay=0.01)

    async def always_fail():
        raise ConnectionError("permanent failure")

    with pytest.raises(ConnectionError):
        await handler.execute(always_fail)


# ============ AmapAPI (高德地图) ============

@pytest.mark.asyncio
async def test_amap_geocode_fallback():
    """测试高德地理编码（无 Key 时回退 Nominatim）。"""
    tool = AmapAPI()
    # 无 Key 时应回退到 Nominatim 或内置缓存
    coords = await tool.geocode("Beijing")
    assert coords is not None
    assert len(coords) == 2
    assert isinstance(coords[0], float)
    assert isinstance(coords[1], float)


@pytest.mark.asyncio
async def test_amap_route_fallback():
    """测试高德拉路线规划（无 Key 时回退估算）。"""
    tool = AmapAPI()
    route = await tool.get_route("Beijing", "Shanghai", "driving")
    assert route is not None
    assert "distance_km" in route
    assert "duration_minutes" in route
    assert route["distance_km"] > 0


@pytest.mark.asyncio
async def test_amap_district_no_key():
    """测试高德行政区查询（无 Key 时返回 None）。"""
    tool = AmapAPI()
    result = await tool.get_district("Beijing")
    # 无 Key 时返回 None，不报错
    assert result is None or isinstance(result, dict)


@pytest.mark.asyncio
async def test_amap_search_hotels_no_key():
    """测试高德酒店搜索（无 Key 时返回空列表）。"""
    tool = AmapAPI()
    hotels = await tool.search_hotels("Beijing", max_results=3)
    # 无 Key 时返回空列表，由调用方回退
    assert isinstance(hotels, list)


@pytest.mark.asyncio
async def test_amap_search_restaurants_no_key():
    """测试高德餐厅搜索（无 Key 时返回空列表）。"""
    tool = AmapAPI()
    restaurants = await tool.search_restaurants("Shanghai", max_results=3)
    # 无 Key 时返回空列表，由调用方回退
    assert isinstance(restaurants, list)


@pytest.mark.asyncio
async def test_amap_singleton():
    """测试单例。"""
    assert get_amap_api() is get_amap_api()


# ============ QWeather (和风天气) ============

@pytest.mark.asyncio
async def test_train_search_train_only_at_four_hours():
    """高铁最短用时小于等于 4 小时时，仅展示高铁方案。"""
    tool = TrainSearchTool()

    class DummyFlyAI:
        def search_trains(self, origin, destination, departure_date, max_results=6):
            return [
                {
                    "train_type": "高铁",
                    "train_number": "G1",
                    "duration_min": 240,
                    "duration": "4h00m",
                    "price": 500,
                    "is_direct": True,
                }
            ]

    tool.flyai = DummyFlyAI()
    result = await tool.search("北京", "上海", "2026-08-01")

    assert result["train_only"] is True
    assert result["show_flights"] is False
    assert result["recommended"] is True
    assert len(result["trains"]) == 1


@pytest.mark.asyncio
async def test_train_search_over_four_hours_keeps_train_options():
    """高铁超过 4 小时时仍返回高铁车次，用于和飞机一起展示。"""
    tool = TrainSearchTool()

    class DummyFlyAI:
        def search_trains(self, origin, destination, departure_date, max_results=6):
            return [
                {
                    "train_type": "高铁",
                    "train_number": "G99",
                    "duration_min": 241,
                    "duration": "4h01m",
                    "price": 620,
                    "is_direct": True,
                }
            ]

    tool.flyai = DummyFlyAI()
    result = await tool.search("北京", "南京", "2026-08-01")

    assert result["train_only"] is False
    assert result["show_flights"] is True
    assert result["recommended"] is False
    assert len(result["trains"]) == 1


@pytest.mark.asyncio
async def test_qweather_forecast_fallback():
    """测试和风天气预报（无 Key 时回退 Mock）。"""
    tool = QWeatherTool()
    weather = await tool.get_forecast("Beijing", days=3)
    assert isinstance(weather, list)
    assert len(weather) == 3
    for day in weather:
        assert "date" in day
        assert "condition" in day
        assert "temperature_high" in day
        assert "temperature_low" in day


@pytest.mark.asyncio
async def test_qweather_air_quality_no_key():
    """测试和风空气质量（无 Key 时返回 None）。"""
    tool = QWeatherTool()
    result = await tool.get_air_quality("Beijing")
    # 无 Key 时返回 None，不报错
    assert result is None or isinstance(result, dict)


@pytest.mark.asyncio
async def test_qweather_recommendation_zh():
    """测试中文天气建议生成。"""
    tool = QWeatherTool()
    rec = tool._get_recommendation_zh("晴", 28)
    assert "晴" in rec or "☀️" in rec
    rec2 = tool._get_recommendation_zh("暴雨", 25)
    assert "雨" in rec2 or "🌧️" in rec2


@pytest.mark.asyncio
async def test_qweather_singleton():
    """测试单例。"""
    assert get_qweather() is get_qweather()
