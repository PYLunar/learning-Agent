"""
Food Agent - 联网搜索 + LLM 智能推荐。
"""

import json
import logging
from typing import List

from app.config import get_settings
from app.state import TravelState, FoodSpot
from app.llm_client import get_llm_client
from app.prompts import get_system_prompt, get_user_prompt
from app.tools.web_search import get_web_search

logger = logging.getLogger(__name__)


class FoodAgent:
    """美食智能体。联网搜索真实餐厅信息，LLM 智能推荐。"""

    # 各城市特色美食模板（用于 fallback 时区分城市）
    CITY_FOOD_MAP = {
        "tokyo": [("一兰拉面", "日式拉面", "人均¥80", 4.5, "博多风味的豚骨拉面", ["豚骨拉面", "叉烧饭"], "lunch"),
                  ("寿司大", "寿司", "人均¥300", 4.7, "筑地市场新鲜寿司", ["Omakase套餐", "金枪鱼大腹"], "lunch"),
                  ("叙叙苑", "日式烧肉", "人均¥250", 4.6, "高品质和牛烧肉", ["和牛拼盘", "牛舌"], "dinner")],
        "东京": [("一兰拉面", "日式拉面", "人均¥80", 4.5, "博多风味的豚骨拉面", ["豚骨拉面", "叉烧饭"], "lunch"),
                  ("寿司大", "寿司", "人均¥300", 4.7, "筑地市场新鲜寿司", ["Omakase套餐", "金枪鱼大腹"], "lunch"),
                  ("叙叙苑", "日式烧肉", "人均¥250", 4.6, "高品质和牛烧肉", ["和牛拼盘", "牛舌"], "dinner")],
        "osaka": [("章鱼烧道顿堀", "街头小吃", "人均¥30", 4.4, "大阪灵魂街头美食", ["章鱼烧", "明石烧"], "snack"),
                  ("蟹道乐", "日式螃蟹", "人均¥350", 4.5, "螃蟹全席套餐", ["螃蟹刺身", "螃蟹天妇罗"], "dinner")],
        "大阪": [("章鱼烧道顿堀", "街头小吃", "人均¥30", 4.4, "大阪灵魂街头美食", ["章鱼烧", "明石烧"], "snack"),
                  ("蟹道乐", "日式螃蟹", "人均¥350", 4.5, "螃蟹全席套餐", ["螃蟹刺身", "螃蟹天妇罗"], "dinner")],
        "bangkok": [("帕泰", "泰式炒粉", "人均¥40", 4.6, "曼谷最佳Pad Thai", ["泰式炒粉", "虾汤"], "dinner"),
                    ("杰菲", "街头美食", "人均¥50", 4.8, "米其林街头美食", ["蟹肉煎蛋", "冬阴功汤"], "dinner")],
        "曼谷": [("帕泰", "泰式炒粉", "人均¥40", 4.6, "曼谷最佳Pad Thai", ["泰式炒粉", "虾汤"], "dinner"),
                    ("杰菲", "街头美食", "人均¥50", 4.8, "米其林街头美食", ["蟹肉煎蛋", "冬阴功汤"], "dinner")],
        "seoul": [("明洞饺子", "韩式饺子", "人均¥60", 4.5, "明洞老字号", ["刀削面", "饺子"], "lunch"),
                  ("姜虎东白丁", "韩式烤肉", "人均¥180", 4.6, "人气烤肉店", ["五花肉", "牛排骨"], "dinner")],
        "首尔": [("明洞饺子", "韩式饺子", "人均¥60", 4.5, "明洞老字号", ["刀削面", "饺子"], "lunch"),
                  ("姜虎东白丁", "韩式烤肉", "人均¥180", 4.6, "人气烤肉店", ["五花肉", "牛排骨"], "dinner")],
        "chengdu": [("陈麻婆豆腐", "川菜", "人均¥60", 4.5, "麻婆豆腐发源地", ["麻婆豆腐", "宫保鸡丁"], "dinner"),
                    ("小龙坎火锅", "火锅", "人均¥100", 4.6, "成都网红火锅", ["毛肚", "鸭肠", "嫩牛肉"], "dinner"),
                    ("钟水饺", "成都小吃", "人均¥25", 4.4, "百年老字号", ["钟水饺", "担担面"], "lunch"),
                    ("玉芝兰", "川菜精品", "人均¥300", 4.7, "高端川菜代表", ["开水白菜", "鸡豆花"], "dinner"),
                    ("蓉锦一号公馆菜", "公馆菜", "人均¥200", 4.5, "老成都公馆菜", ["坛子肉", "甜烧白"], "dinner")],
        "成都": [("陈麻婆豆腐", "川菜", "人均¥60", 4.5, "麻婆豆腐发源地", ["麻婆豆腐", "宫保鸡丁"], "dinner"),
                    ("小龙坎火锅", "火锅", "人均¥100", 4.6, "成都网红火锅", ["毛肚", "鸭肠", "嫩牛肉"], "dinner"),
                    ("钟水饺", "成都小吃", "人均¥25", 4.4, "百年老字号", ["钟水饺", "担担面"], "lunch"),
                    ("玉芝兰", "川菜精品", "人均¥300", 4.7, "高端川菜代表", ["开水白菜", "鸡豆花"], "dinner"),
                    ("蓉锦一号公馆菜", "公馆菜", "人均¥200", 4.5, "老成都公馆菜", ["坛子肉", "甜烧白"], "dinner")],
        "hangzhou": [("楼外楼", "杭帮菜", "人均¥150", 4.4, "西湖边百年名店", ["西湖醋鱼", "东坡肉", "龙井虾仁"], "dinner"),
                     ("知味观", "杭州小吃", "人均¥50", 4.5, "传统杭帮点心", ["小笼包", "猫耳朵"], "lunch")],
        "杭州": [("楼外楼", "杭帮菜", "人均¥150", 4.4, "西湖边百年名店", ["西湖醋鱼", "东坡肉", "龙井虾仁"], "dinner"),
                     ("知味观", "杭州小吃", "人均¥50", 4.5, "传统杭帮点心", ["小笼包", "猫耳朵"], "lunch")],
        "xian": [("老孙家泡馍", "清真美食", "人均¥55", 4.5, "百年羊肉泡馍老店", ["羊肉泡馍", "糖蒜"], "lunch"),
                 ("回民街贾三灌汤包", "清真小吃", "人均¥30", 4.6, "回民街必吃", ["灌汤包", "酸梅汤"], "snack")],
        "西安": [("老孙家泡馍", "清真美食", "人均¥55", 4.5, "百年羊肉泡馍老店", ["羊肉泡馍", "糖蒜"], "lunch"),
                 ("回民街贾三灌汤包", "清真小吃", "人均¥30", 4.6, "回民街必吃", ["灌汤包", "酸梅汤"], "snack")],
        "beijing": [("全聚德", "北京烤鸭", "人均¥180", 4.4, "百年烤鸭老字号", ["北京烤鸭", "鸭架汤"], "dinner"),
                    ("东来顺", "涮羊肉", "人均¥150", 4.5, "百年涮羊肉", ["手切羊肉", "麻酱小料"], "dinner"),
                    ("护国寺小吃", "北京小吃", "人均¥25", 4.3, "地道北京早点", ["豆汁", "焦圈", "驴打滚"], "breakfast")],
        "北京": [("全聚德", "北京烤鸭", "人均¥180", 4.4, "百年烤鸭老字号", ["北京烤鸭", "鸭架汤"], "dinner"),
                    ("东来顺", "涮羊肉", "人均¥150", 4.5, "百年涮羊肉", ["手切羊肉", "麻酱小料"], "dinner"),
                    ("护国寺小吃", "北京小吃", "人均¥25", 4.3, "地道北京早点", ["豆汁", "焦圈", "驴打滚"], "breakfast")],
        "shanghai": [("南翔馒头店", "上海小笼", "人均¥60", 4.6, "城隍庙百年老店", ["蟹粉小笼", "鲜肉小笼"], "lunch"),
                     ("老克勒", "上海本帮菜", "人均¥200", 4.5, "经典本帮味道", ["红烧肉", "油爆虾", "腌笃鲜"], "dinner")],
        "上海": [("南翔馒头店", "上海小笼", "人均¥60", 4.6, "城隍庙百年老店", ["蟹粉小笼", "鲜肉小笼"], "lunch"),
                     ("老克勒", "上海本帮菜", "人均¥200", 4.5, "经典本帮味道", ["红烧肉", "油爆虾", "腌笃鲜"], "dinner")],
        "guangzhou": [("陶陶居", "粤式茶楼", "人均¥80", 4.6, "广州早茶代表", ["虾饺", "烧卖", "叉烧包"], "breakfast"),
                      ("炳胜品味", "粤菜", "人均¥180", 4.5, "高端粤菜", ["烧鹅", "白切鸡"], "dinner")],
        "广州": [("陶陶居", "粤式茶楼", "人均¥80", 4.6, "广州早茶代表", ["虾饺", "烧卖", "叉烧包"], "breakfast"),
                      ("炳胜品味", "粤菜", "人均¥180", 4.5, "高端粤菜", ["烧鹅", "白切鸡"], "dinner")],
        "shenzhen": [("润园四季椰子鸡", "椰子鸡火锅", "人均¥120", 4.6, "深圳本土网红椰子鸡", ["椰子鸡", "竹笙", "手打牛肉丸"], "dinner"),
                     ("光明乳鸽", "粤式乳鸽", "人均¥80", 4.5, "光明特产乳鸽，皮脆肉嫩", ["红烧乳鸽", "牛初乳"], "lunch"),
                     ("汕头八合里海记牛肉店", "潮汕牛肉火锅", "人均¥100", 4.7, "正宗潮汕牛肉火锅", ["吊龙", "匙柄", "手捶牛肉丸"], "dinner"),
                     ("点都德", "广式茶点", "人均¥70", 4.4, "广式早茶连锁名店", ["虾饺", "凤爪", "流沙包"], "breakfast")],
        "深圳": [("润园四季椰子鸡", "椰子鸡火锅", "人均¥120", 4.6, "深圳本土网红椰子鸡", ["椰子鸡", "竹笙", "手打牛肉丸"], "dinner"),
                     ("光明乳鸽", "粤式乳鸽", "人均¥80", 4.5, "光明特产乳鸽，皮脆肉嫩", ["红烧乳鸽", "牛初乳"], "lunch"),
                     ("汕头八合里海记牛肉店", "潮汕牛肉火锅", "人均¥100", 4.7, "正宗潮汕牛肉火锅", ["吊龙", "匙柄", "手捶牛肉丸"], "dinner"),
                     ("点都德", "广式茶点", "人均¥70", 4.4, "广式早茶连锁名店", ["虾饺", "凤爪", "流沙包"], "breakfast")],
        "chongqing": [("珮姐老火锅", "重庆火锅", "人均¥120", 4.7, "重庆九宫格老火锅", ["毛肚", "鸭肠", "黄喉"], "dinner"),
                     ("山城小汤圆", "重庆小吃", "人均¥20", 4.4, "传统山城甜食", ["小汤圆", "醪糟"], "snack"),
                     ("周师兄大刀腰片火锅", "重庆火锅", "人均¥140", 4.6, "大刀腰片火锅", ["大刀腰片", "嫩牛肉", "鲜鸭血"], "dinner")],
        "重庆": [("珮姐老火锅", "重庆火锅", "人均¥120", 4.7, "重庆九宫格老火锅", ["毛肚", "鸭肠", "黄喉"], "dinner"),
                     ("山城小汤圆", "重庆小吃", "人均¥20", 4.4, "传统山城甜食", ["小汤圆", "醪糟"], "snack"),
                     ("周师兄大刀腰片火锅", "重庆火锅", "人均¥140", 4.6, "大刀腰片火锅", ["大刀腰片", "嫩牛肉", "鲜鸭血"], "dinner")],
        "paris": [("L'Ami Jean", "法式小酒馆", "人均¥350", 4.6, "巴黎左岸传统小酒馆", ["红酒炖牛肉", "鹅肝"], "dinner"),
                  ("Pierre Hermé", "法式甜点", "人均¥80", 4.8, "巴黎顶级马卡龙", ["玫瑰荔枝覆盆子马卡龙", "伊斯法罕"], "snack"),
                  ("Le Comptoir du Panthéon", "法式早餐", "人均¥120", 4.4, "拉丁区经典早餐", ["可颂", "热巧克力", "法式吐司"], "breakfast"),
                  ("Breizh Café", "可丽饼", "人均¥150", 4.5, "巴黎最佳法式可丽饼", ["黄油焦糖可丽饼", "海鲜煎饼"], "lunch")],
        "巴黎": [("L'Ami Jean", "法式小酒馆", "人均¥350", 4.6, "巴黎左岸传统小酒馆", ["红酒炖牛肉", "鹅肝"], "dinner"),
                  ("Pierre Hermé", "法式甜点", "人均¥80", 4.8, "巴黎顶级马卡龙", ["玫瑰荔枝覆盆子马卡龙", "伊斯法罕"], "snack"),
                  ("Le Comptoir du Panthéon", "法式早餐", "人均¥120", 4.4, "拉丁区经典早餐", ["可颂", "热巧克力", "法式吐司"], "breakfast"),
                  ("Breizh Café", "可丽饼", "人均¥150", 4.5, "巴黎最佳法式可丽饼", ["黄油焦糖可丽饼", "海鲜煎饼"], "lunch")],
    }

    def __init__(self):
        self.llm = get_llm_client()
        self.web_search = get_web_search()

    async def run(self, state: TravelState) -> dict:
        """推荐美食。联网搜索 + LLM 推荐。"""
        output = {}
        try:
            logger.info("FoodAgent: 正在搜索美食推荐")

            destination = state.get("destination", "")
            days = state.get("days", 1)
            preferences = state.get("preferences", [])
            lang = state.get("user_input", {}).get("language", "zh")

            from app.config import get_settings
            if not get_settings().ENABLE_LLM_ENHANCEMENT:
                food_recommendations = []
                try:
                    from app.tools.amap_api import get_amap_api
                    amap = get_amap_api()
                    amap_food = await amap.search_restaurants(destination, max_results=8)
                    for h in amap_food:
                        if not self._is_travel_worthy_restaurant(h.get("name", "")):
                            continue
                        price = h.get("price") or 0
                        rating = h.get("rating") or 0
                        food_recommendations.append(FoodSpot(
                            name=h.get("name", ""),
                            cuisine=h.get("type", "餐饮"),
                            price_range=f"人均¥{int(price)}" if price and price > 0 else "价格未获取",
                            rating=float(rating) if rating else 0.0,
                            address=h.get("address", destination),
                            why_recommended="高德地图 POI 真实餐厅数据",
                            must_try_dishes=[],
                            meal_type="dinner",
                        ))
                except Exception as e:
                    logger.warning("FoodAgent 高德POI搜索失败: %s", e)

                priced_food = [f for f in food_recommendations if any(ch.isdigit() for ch in f.get("price_range", ""))]
                status = "ok" if priced_food else ("partial" if food_recommendations else "unavailable")
                output["food_recommendations"] = food_recommendations
                output["data_status"] = {
                    "food": {
                        "source": "Amap POI",
                        "status": status,
                        "count": len(food_recommendations),
                        "reason": "" if status == "ok" else (
                            "仅获取到餐厅名称，缺少真实人均价格" if food_recommendations else "未获取到真实美食数据"
                        ),
                    }
                }
                output["logs"] = [{
                    "agent": "food",
                    "action": "food_recommendation",
                    "output": f"找到 {len(food_recommendations)} 个真实餐厅 POI",
                    "status": "success",
                }]
                return output

            # 1. 联网搜索美食信息（大众点评/小红书/Google）
            web_context = await self._search_food(destination, preferences, lang)

            # 2. 构建 LLM 提示词（注入联网数据）
            system_prompt = get_system_prompt("food", lang)
            user_prompt = get_user_prompt("food", lang).format(
                destination=destination,
                days=days,
                preferences=", ".join(preferences),
            )

            # 将联网搜索结果注入
            if web_context:
                user_prompt += f"\n\n**参考信息（来自互联网搜索）**:\n{web_context}"

            # 强调必须是该城市的特色美食
            user_prompt += f"\n\n**重要要求：必须推荐{destination}当地的特色餐厅和菜品，不要推荐通用的、适用于任何城市的餐厅。每个推荐必须与{destination}的饮食文化相关。**"

            response = await self.llm.chat_completion(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format="json",
            )

            food_recommendations = []
            try:
                result = json.loads(response)
                # 尝试多个可能的字段名
                restaurants_data = (result.get("restaurants") or result.get("food")
                                   or result.get("recommendations") or [])
                # 如果LLM返回了itinerary格式，从中提取meal信息
                if not restaurants_data and isinstance(result, dict):
                    for key, val in result.items():
                        if isinstance(val, list):
                            for item in val:
                                if isinstance(item, dict) and "meals" in item:
                                    restaurants_data = item["meals"]
                                    break
                            if restaurants_data:
                                break
                for r in restaurants_data:
                    if not isinstance(r, dict):
                        continue
                    # 兼容多种字段名
                    name = r.get("name") or r.get("restaurant") or ""
                    if not name:
                        continue
                    spot = FoodSpot(
                        name=name,
                        cuisine=r.get("cuisine", r.get("type", "当地菜")),
                        price_range=r.get("price_range", r.get("price", "¥¥")),
                        rating=float(r.get("rating", r.get("score", 4.0))),
                        address=r.get("address", destination),
                        why_recommended=r.get("why_recommended", r.get("description", "当地特色")),
                        must_try_dishes=r.get("must_try_dishes", r.get("dishes", r.get("specialties", []))),
                        meal_type=r.get("meal_type", r.get("type", "dinner")),
                    )
                    food_recommendations.append(spot)

                # 检测是否为 Mock 数据（通用名称如"XX老字号餐厅"、"XX特色小吃店"）
                is_mock = any(
                    "老字号餐厅" in s.get("name", "") or
                    "特色小吃店" in s.get("name", "") or
                    "精品咖啡馆" in s.get("name", "")
                    for s in food_recommendations
                )

                if not food_recommendations or is_mock:
                    if is_mock:
                        logger.warning("FoodAgent: LLM 返回了通用 Mock 数据，放弃美食推荐")
                    else:
                        logger.warning("FoodAgent: LLM 返回空列表，放弃美食推荐")
                    food_recommendations = []
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.warning("FoodAgent: LLM 响应解析失败: %s，放弃美食推荐", e)
                food_recommendations = []

            # 确保覆盖不同餐次
            food_recommendations = self._ensure_meal_coverage(food_recommendations, days)

            # 联网搜索+LLM 均无结果时，回退到高德 POI 搜索餐厅
            if not food_recommendations:
                try:
                    from app.tools.amap_api import get_amap_api
                    amap = get_amap_api()
                    amap_food = await amap.search_restaurants(destination, max_results=5)
                    if amap_food:
                        for h in amap_food:
                            price = h.get("price")
                            if not price or price <= 0:
                                price = 0.0
                            rating = h.get("rating")
                            if not rating or rating <= 0:
                                rating = 0.0
                            food_recommendations.append(FoodSpot(
                                name=h.get("name", ""),
                                cuisine="当地特色",
                                price_range=f"人均¥{int(price)}",
                                rating=float(rating),
                                address=h.get("address", destination),
                                why_recommended="高德地图高分推荐",
                                must_try_dishes=[],
                                meal_type="dinner",
                            ))
                        logger.info("FoodAgent: 高德POI补充了 %d 个餐厅", len(amap_food))
                except Exception as e:
                    logger.warning("FoodAgent 高德POI搜索失败: %s", e)

            # MOCK_MODE 下使用数据库回退
            if not food_recommendations and get_settings().MOCK_MODE:
                food_recommendations = self._fallback_food(destination, days)

            output["food_recommendations"] = food_recommendations
            priced_food = [f for f in food_recommendations if any(ch.isdigit() for ch in f.get("price_range", ""))]
            status = "ok" if priced_food else ("partial" if food_recommendations else "unavailable")
            output["data_status"] = {
                "food": {
                    "source": "Web search / LLM extraction / Amap POI",
                    "status": status,
                    "count": len(food_recommendations),
                    "reason": "" if status == "ok" else (
                        "仅获取到餐厅名称，缺少真实人均价格" if food_recommendations else "未获取到真实美食数据"
                    ),
                }
            }
            output["logs"] = [{
                "agent": "food",
                "action": "food_recommendation",
                "output": f"找到 {len(food_recommendations)} 个美食推荐 (联网搜索: {'有' if web_context else '无'})",
                "status": "success",
            }]

            logger.info("FoodAgent: 找到 %d 个美食推荐 (联网: %s)",
                       len(food_recommendations), "有" if web_context else "无")

        except Exception as e:
            logger.error("FoodAgent error: %s", str(e))
            output["errors"] = [f"FoodAgent: {str(e)}"]
            output["food_recommendations"] = []
            output["data_status"] = {
                "food": {
                    "source": "Web search / LLM extraction / Amap POI",
                    "status": "unavailable",
                    "count": 0,
                    "reason": str(e),
                }
            }

        return output

    def _is_travel_worthy_restaurant(self, name: str) -> bool:
        """Filter generic chains that are real but poor travel recommendations."""
        if not name:
            return False
        generic_chains = [
            "麦当劳", "肯德基", "KFC", "必胜客", "星巴克", "瑞幸", "库迪",
            "汉堡王", "德克士", "赛百味", "CoCo都可", "蜜雪冰城",
        ]
        return not any(chain.lower() in name.lower() for chain in generic_chains)

    async def _search_food(self, destination: str, preferences: List[str], lang: str = "zh") -> str:
        """联网搜索美食信息，返回文本摘要。中文用户优先搜索大众点评/小红书。"""
        try:
            pref_str = " ".join(preferences) if preferences else "local food"

            # 中文目的地搜索国内平台
            chinese_cities = ["beijing", "shanghai", "guangzhou", "shenzhen", "hangzhou",
                             "chengdu", "xian", "nanjing", "wuhan", "chongqing", "suzhou",
                             "xiamen", "qingdao", "dalian", "kunming", "guiyang", "changsha"]
            is_chinese = destination.lower() in chinese_cities or lang == "zh"

            if is_chinese:
                query = f"{destination} 美食推荐 大众点评 必吃餐厅 必吃菜 特色 {pref_str} 2025"
            else:
                query = f"best restaurants local food {destination} {pref_str} must try dishes 2025"

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
            logger.warning("FoodAgent 联网搜索失败: %s", e)
            return ""

    def _ensure_meal_coverage(self, spots: List[FoodSpot], days: int) -> List[FoodSpot]:
        """确保覆盖不同餐次。"""
        if not spots:
            return spots
        return spots[:min(len(spots), days * 3 + 2)]

    def _fallback_food(self, destination: str, days: int) -> List[FoodSpot]:
        """Fallback：仅在 MOCK_MODE 下使用 CITY_FOOD_MAP，生产环境返回空列表。"""
        if get_settings().MOCK_MODE:
            dest_lower = destination.lower()
            city_data = self.CITY_FOOD_MAP.get(dest_lower) or self.CITY_FOOD_MAP.get(destination)
            if city_data:
                spots = []
                for name, cuisine, price_range, rating, why, dishes, meal in city_data:
                    spots.append(FoodSpot(
                        name=name, cuisine=cuisine, price_range=price_range,
                        rating=rating, address=destination, why_recommended=why,
                        must_try_dishes=dishes, meal_type=meal,
                    ))
                return spots[:min(len(spots), days * 3 + 2)]
        return []
