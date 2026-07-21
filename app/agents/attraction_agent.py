"""
Attraction / Activity Agent - 联网搜索景点信息 + LLM 智能编排。
"""

import json
import logging
from typing import List

from app.state import TravelState, Attraction
from app.llm_client import get_llm_client
from app.prompts import get_system_prompt, get_user_prompt
from app.tools.web_search import get_web_search

logger = logging.getLogger(__name__)


class AttractionAgent:
    """景点智能体。联网搜索真实景点信息，再用 LLM 智能编排。"""

    def __init__(self):
        self.llm = get_llm_client()
        self.web_search = get_web_search()

    async def run(self, state: TravelState) -> dict:
        """推荐景点。先联网搜索，再用 LLM 编排。"""
        output = {}
        try:
            logger.info("AttractionAgent: 正在搜索景点信息")

            destination = state.get("destination", "")
            days = state.get("days", 1)
            preferences = state.get("preferences", [])
            lang = state.get("user_input", {}).get("language", "zh")

            attractions = []
            web_context = ""

            # 1. 优先使用 FlyAI POI / 高德 POI 的真实结构化景点数据
            try:
                from app.tools.flyai_cli import get_flyai_client
                flyai = get_flyai_client()
                pois = flyai.search_poi(destination, "景点", max_results=min(days * 4, 12))
                for idx, poi in enumerate(pois):
                    if not self._is_valid_real_attraction(poi.get("name", "")):
                        continue
                    attractions.append(Attraction(
                        name=poi.get("name", ""),
                        description=poi.get("address", destination),
                        location=poi.get("address", destination),
                        estimated_duration="",
                        price=float(poi.get("price", 0) or 0),
                        category="景点",
                        best_time="",
                        day=min(idx % days + 1, days),
                    ))
                if attractions:
                    logger.info("AttractionAgent: FlyAI POI 获取到 %d 个景点", len(attractions))
            except Exception as e:
                logger.warning("AttractionAgent FlyAI POI 搜索失败: %s", e)

            min_attractions = min(days * 2, 6)
            if len(attractions) < min_attractions:
                try:
                    from app.tools.amap_api import get_amap_api
                    amap = get_amap_api()
                    amap_attr = await amap.search_attractions(destination, max_results=8)
                    seen_names = {a.get("name") for a in attractions}
                    for idx, h in enumerate(amap_attr):
                        if h.get("name", "") in seen_names:
                            continue
                        if not self._is_valid_real_attraction(h.get("name", "")):
                            continue
                        attractions.append(Attraction(
                            name=h.get("name", ""),
                            description=h.get("address", destination),
                            location=h.get("address", destination),
                            estimated_duration="",
                            price=float(h.get("price", 0) or 0),
                            category="景点",
                            best_time="",
                            day=min(idx % days + 1, days),
                        ))
                        seen_names.add(h.get("name", ""))
                    if attractions:
                        logger.info("AttractionAgent: 高德POI获取到 %d 个景点", len(attractions))
                except Exception as e:
                    logger.warning("AttractionAgent 高德POI搜索失败: %s", e)

            from app.config import get_settings
            if not get_settings().ENABLE_LLM_ENHANCEMENT:
                output["attractions"] = self._balance_attractions(attractions, days)
                output["data_status"] = {
                    "attractions": {
                        "source": "FlyAI POI / Amap POI",
                        "status": "ok" if attractions else "unavailable",
                        "count": len(attractions),
                        "reason": "" if attractions else "未获取到真实景点数据",
                    }
                }
                output["logs"] = [{
                    "agent": "attraction",
                    "action": "attraction_planning",
                    "output": f"找到 {len(attractions)} 个真实景点",
                    "status": "success",
                }]
                return output

            # 2. 可选：联网搜索 + LLM 提取
            web_context = await self._search_attractions(destination, preferences, lang)

            # 2. 构建 LLM 提示词（注入联网数据）
            system_prompt = get_system_prompt("attraction", lang)
            user_prompt = get_user_prompt("attraction", lang).format(
                destination=destination,
                days=days,
                preferences=", ".join(preferences),
            )

            # 将联网搜索结果注入到 user_prompt 中
            if web_context:
                user_prompt += f"\n\n**参考信息（来自互联网搜索）**:\n{web_context}"

            response = await self.llm.chat_completion(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format="json",
            )

            try:
                result = json.loads(response)
                attractions_data = result.get("attractions", []) or result.get("recommendations", []) or result.get("data", [])
                # 如果LLM返回了itinerary格式，尝试从中提取景点
                if not attractions_data and isinstance(result, dict):
                    for key, val in result.items():
                        if isinstance(val, list) and val and isinstance(val[0], dict):
                            if any("name" in item for item in val[:3]):
                                attractions_data = val
                                break
                if isinstance(attractions_data, list):
                    for a in attractions_data:
                        if not isinstance(a, dict):
                            continue
                        name = a.get("name", "").strip()
                        if not name or len(name) < 2:
                            continue
                        attraction = Attraction(
                            name=name,
                            description=a.get("description", a.get("details", "")),
                            location=a.get("location", destination),
                            estimated_duration=a.get("estimated_duration", "2h"),
                            price=float(a.get("price", 0) or 0),
                            category=a.get("category", "general"),
                            best_time=a.get("best_time", "anytime"),
                            day=min(int(a.get("day", 1) or 1), days),
                        )
                        attractions.append(attraction)
                if not attractions:
                    logger.warning("AttractionAgent: LLM 返回了 JSON 但景点列表为空")
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.warning("AttractionAgent: LLM 响应解析失败: %s", e)
                # fallback: 从联网搜索结果中直接提取景点
                attractions = await self._fallback_from_web(destination, days, preferences)

            # 如果还是空的，用联网搜索直接提取
            if not attractions:
                logger.warning("AttractionAgent: LLM 未返回有效数据，从联网搜索提取")
                attractions = await self._fallback_from_web(destination, days, preferences)

            # 联网搜索也失败时，回退到高德 POI 搜索景点
            if not attractions:
                try:
                    from app.tools.amap_api import get_amap_api
                    amap = get_amap_api()
                    amap_attr = await amap.search_attractions(destination, max_results=8)
                    if amap_attr:
                        for idx, h in enumerate(amap_attr):
                            attractions.append(Attraction(
                                name=h.get("name", ""),
                                description=h.get("address", destination),
                                location=h.get("address", destination),
                                estimated_duration="2-3小时",
                                price=0,
                                category="景点",
                                best_time="全天",
                                day=min(idx % days + 1, days),
                            ))
                        logger.info("AttractionAgent: 高德POI补充了 %d 个景点", len(amap_attr))
                except Exception as e:
                    logger.warning("AttractionAgent 高德POI搜索失败: %s", e)

            # 确保每天 2-4 个景点
            attractions = self._balance_attractions(attractions, days)

            # 最终过滤：移除包含垃圾关键词的景点
            garbage_words = ["不止有", "不仅仅是", "不只是", "你知道", "告诉你",
                             "热门景点", "必去景点", "十大", "景点大全", "攻略",
                             "百科", "知乎", "百度", "下载", "APP"]
            attractions = [a for a in attractions
                          if not any(w in a.get("name", "") for w in garbage_words)]

            output["attractions"] = attractions
            output["data_status"] = {
                "attractions": {
                    "source": "Web search / Amap POI",
                    "status": "ok" if attractions else "unavailable",
                    "count": len(attractions),
                    "reason": "" if attractions else "未获取到真实景点数据",
                }
            }
            output["logs"] = [{
                "agent": "attraction",
                "action": "attraction_planning",
                "output": f"找到 {len(attractions)} 个景点，覆盖 {days} 天 (联网搜索: {'有' if web_context else '无'})",
                "status": "success",
            }]

            logger.info("AttractionAgent: 找到 %d 个景点 (联网: %s)",
                       len(attractions), "有" if web_context else "无")

        except Exception as e:
            logger.error("AttractionAgent error: %s", str(e))
            output["errors"] = [f"AttractionAgent: {str(e)}"]
            output["attractions"] = []
            output["data_status"] = {
                "attractions": {
                    "source": "Web search / Amap POI",
                    "status": "unavailable",
                    "count": 0,
                    "reason": str(e),
                }
            }

        return output

    def _is_valid_real_attraction(self, name: str) -> bool:
        """Filter event ads, sub-POIs, and generic non-attraction results."""
        if not name:
            return False
        bad_words = [
            "影像盛宴", "展览", "展", "演出", "赛事", "售票", "门票",
            "入口", "出口", "停车场", "游客中心", "服务中心", "售卖",
        ]
        if any(word in name for word in bad_words):
            return False
        if "-" in name or "－" in name:
            return False
        return True

    def _extract_attraction_name(self, title: str) -> str:
        """从搜索结果标题中提取景点名。"""
        import re
        # 过滤非景点结果（广泛覆盖）
        skip_words = [
            "wikipedia", "tripadvisor", "reddit", "quora", "cambridge", "collins",
            "旅游攻略大全", "携程", "去哪儿", "马蜂窝", "门票预订", "线路", "一日游",
            "百度百科", "百度百科", "翻译", "词典", "字典", "英语", "英文",
            "TOP", "BEST", "NEWS", "VIDEO", "LIVE", "FREE", "FULL", "HD",
            "百度", "搜狗", "必应", "谷歌", "Bing", "Google",
            "知乎", "小红书", "抖音", "微博", "bilibili", "哔哩哔哩",
            "下载", "APP", "app", "软件", "注册", "登录",
            "崔胜铉", "_BIGBANG", "男团", "女团", "明星", "偶像", "综艺",
            "最新消息", "今日热点", "热搜", "新闻", "资讯", "快讯",
            "_翻译", "_中文", "简体", "繁体", "meaning", "definition",
            "What is", "How to", "Why does", "Where is",
            "待查询", "景点大全", "必去景点", "旅游推荐", "旅游景点",
            "排名", "排行榜", "榜单", "TOP10", "十大",
            "km2", "平方公里", "人口", "GDP", "面积",
            "个必去", "个好玩", "大盘点", "全攻略", "避坑",
            "市人民政府", "百科",
            "不止有", "不仅仅是", "不只是", "你知道", "告诉你",
            "热门景点", "成都景点", "深圳景点", "广州景点", "北京景点",
        ]
        for word in skip_words:
            if word.lower() in title.lower():
                return ""

        # 清理标题
        clean = re.sub(r'[-|].*$', '', title).strip()
        clean = re.sub(r'\d+\.\s*', '', clean).strip()
        clean = re.sub(r'[【\]【】]', '', clean).strip()
        clean = re.sub(r'成都.*?成都', '', clean).strip()
        clean = re.sub(r'_{2,}', '', clean).strip()

        # 景点名应至少包含一个中文字符
        has_chinese = any('\u4e00' <= c <= '\u9fff' for c in clean)

        if has_chinese and 2 <= len(clean) <= 30:
            return clean
        return ""

    async def _search_attractions(self, destination: str, preferences: List[str], lang: str = "zh") -> str:
        """联网搜索景点信息，返回文本摘要。"""
        try:
            pref_str = " ".join(preferences) if preferences else "旅游"

            chinese_cities = ["beijing", "shanghai", "guangzhou", "shenzhen", "hangzhou",
                             "chengdu", "xian", "nanjing", "wuhan", "chongqing", "suzhou",
                             "xiamen", "qingdao", "dalian", "kunming", "guiyang", "changsha",
                             "北京", "上海", "广州", "深圳", "杭州", "成都", "西安", "南京",
                             "武汉", "重庆", "苏州", "厦门", "青岛", "大连", "昆明"]
            is_chinese = destination.lower() in chinese_cities or destination in chinese_cities or lang == "zh"

            if is_chinese:
                # 使用更精确的搜索词
                queries = [
                    f"{destination} 著名景点 门票 2026",
                    f"{destination} 有什么好玩的地方 旅游景点",
                ]
            else:
                queries = [
                    f"top tourist attractions {destination} tickets hours 2026",
                    f"best things to do {destination} tourist guide",
                ]

            all_results = []
            for query in queries:
                search_results = await self.web_search.search(query=query, max_results=5)
                all_results.extend(search_results)

            logger.info("AttractionAgent: 搜索返回 %d 条结果", len(all_results))
            if not all_results:
                return ""

            context_parts = []
            for r in all_results[:8]:
                title = r.get("title", "")
                snippet = r.get("snippet", "")
                if snippet:
                    context_parts.append(f"- {title}: {snippet}")

            return "\n".join(context_parts) if context_parts else ""

        except Exception as e:
            logger.warning("AttractionAgent 联网搜索失败: %s", e)
            return ""

    async def _fallback_from_web(self, destination: str, days: int, preferences: List[str]) -> List[Attraction]:
        """
        从联网搜索结果中直接提取真实景点作为 fallback。
        策略：搜索后抓取攻略页面，从摘要中提取具体景点名。
        """
        try:
            queries = [
                f"{destination} 有什么好玩的地方 著名景点",
                f"{destination} 旅游攻略 必去景点 门票",
            ]

            all_attractions = []
            seen_names = set()

            for query in queries:
                try:
                    results = await self.web_search.search(query=query, max_results=5)
                    for r in results:
                        # 从标题和摘要中提取所有可能的景点名
                        title = r.get("title", "")
                        snippet = r.get("snippet", "")
                        combined = f"{title} {snippet}"

                        # 策略1：从摘要文本中用正则提取「XX景区」「XX公园」「XX博物馆」等模式
                        names = self._extract_attraction_names_from_text(combined, destination)
                        for name in names:
                            if name and name not in seen_names:
                                seen_names.add(name)
                                price = self._extract_attraction_price(combined)
                                category = self._guess_category(name, combined)
                                all_attractions.append(Attraction(
                                    name=name,
                                    description=f"{destination}热门景点",
                                    location=destination,
                                    estimated_duration="2-3小时",
                                    price=price,
                                    category=category,
                                    best_time="上午",
                                    day=1,
                                ))

                        # 策略2：如果正则没匹配到，尝试从标题中提取（如"宽窄巷子-成都必去景点"）
                        if not names:
                            clean_name = self._extract_attraction_name(title)
                            if clean_name and clean_name not in seen_names and len(clean_name) >= 2:
                                seen_names.add(clean_name)
                                all_attractions.append(Attraction(
                                    name=clean_name,
                                    description=f"{destination}热门景点",
                                    location=destination,
                                    estimated_duration="2-3小时",
                                    price=0,
                                    category="观光",
                                    best_time="上午",
                                    day=1,
                                ))
                except Exception:
                    continue

            # 均匀分配到各天
            if all_attractions:
                for i, a in enumerate(all_attractions):
                    a["day"] = (i % days) + 1
                return all_attractions[:min(len(all_attractions), days * 4)]

        except Exception as e:
            logger.warning("AttractionAgent fallback 搜索失败: %s", e)

        # 仅在 MOCK_MODE 下使用城市数据库
        from app.config import get_settings
        if get_settings().MOCK_MODE:
            return self._get_city_attractions(destination, days)
        return []

    def _extract_attraction_names_from_text(self, text: str, city: str) -> List[str]:
        """从文本中用正则提取景点名（景区、公园、博物馆、古镇等）。"""
        import re
        patterns = [
            # 匹配"XX景区/公园/博物馆/纪念馆/美术馆"等后缀
            r'([\u4e00-\u9fff]{2,8}(?:景区|景点|公园|博物馆|纪念馆|美术馆|古镇|古街|遗址|名胜|风景区|世界遗产|乐园|故居|庙|寺|塔|楼|阁|水族馆|动物园|植物园))',
            # 匹配成都/重庆/北京等知名景点
            r'([\u4e00-\u9fff]{2,6}(?:大熊猫|宽窄巷子|春熙路|锦里|武侯祠|杜甫草堂|都江堰|青城山|熊猫基地|太古里|人民公园|天府广场|金沙遗址|望江楼|文殊院|昭觉寺|宝光寺|三星堆|九寨沟|乐山大佛|峨眉山|黄龙溪|安仁古镇|平乐古镇|西岭雪山|天台山|石象湖|龙池森林公园|海螺沟|稻城亚丁|蜀南竹海))',
            # 匹配通用的著名景点模式
            r'([\u4e00-\u9fff]{2,6}(?:广场|步行街|老街|风情街|艺术区|创意园|海洋世界|欢乐谷|世界之窗|华侨城|野生动物园|科技馆))',
            # 匹配"XX山/XX湖/XX岛"等自然景观
            r'([\u4e00-\u9fff]{1,4}(?:山|湖|岛|海滩|瀑布|溶洞|峡谷|草原|湿地|森林|温泉))',
        ]
        names = []
        seen = set()
        for pattern in patterns:
            matches = re.findall(pattern, text)
            for m in matches:
                clean = m.strip()
                if clean not in seen and len(clean) >= 2 and clean != city:
                    seen.add(clean)
                    names.append(clean)
        return names

    def _get_city_attractions(self, destination: str, days: int = 4) -> List[dict]:
        """城市知名景点备选库（仅在 MOCK_MODE 下使用）。"""
        city_map = {
            "成都": [
                {"name": "宽窄巷子", "description": "成都三大历史文化保护区之一，清代古街道", "estimated_duration": "2-3小时", "price": 0, "category": "人文街区", "best_time": "上午", "day": 1},
                {"name": "武侯祠", "description": "中国唯一的君臣合祀祠庙，纪念诸葛亮和刘备", "estimated_duration": "2-3小时", "price": 50, "category": "历史古迹", "best_time": "上午", "day": 1},
                {"name": "杜甫草堂", "description": "唐代诗人杜甫流寓成都时的故居，中国文学史上的圣地", "estimated_duration": "2-3小时", "price": 50, "category": "历史古迹", "best_time": "下午", "day": 2},
                {"name": "锦里古街", "description": "成都知名商业步行街，西蜀历史上最古老的商业街之一", "estimated_duration": "2-3小时", "price": 0, "category": "人文街区", "best_time": "下午", "day": 1},
                {"name": "大熊猫繁育研究基地", "description": "世界著名的大熊猫迁地保护基地，可近距离观看大熊猫", "estimated_duration": "3-4小时", "price": 55, "category": "自然风光", "best_time": "上午", "day": 2},
                {"name": "都江堰", "description": "世界文化遗产，战国时期李冰父子修建的大型水利工程", "estimated_duration": "半天", "price": 80, "category": "历史古迹", "best_time": "上午", "day": 3},
                {"name": "青城山", "description": "中国四大道教名山之一，世界文化遗产，以幽著称", "estimated_duration": "半天", "price": 80, "category": "自然风光", "best_time": "上午", "day": 3},
                {"name": "春熙路", "description": "成都最繁华的商业街，时尚购物和美食中心", "estimated_duration": "2-3小时", "price": 0, "category": "购物", "best_time": "下午", "day": 2},
                {"name": "金沙遗址博物馆", "description": "商周时期古蜀文化遗址，太阳神鸟金饰出土地", "estimated_duration": "2-3小时", "price": 70, "category": "博物馆", "best_time": "下午", "day": 4},
                {"name": "人民公园", "description": "成都市民休闲中心，鹤鸣茶社体验地道成都生活", "estimated_duration": "2小时", "price": 0, "category": "人文街区", "best_time": "上午", "day": 4},
                {"name": "九眼桥", "description": "成都夜生活地标，酒吧一条街，府南河畔夜景", "estimated_duration": "2-3小时", "price": 0, "category": "人文街区", "best_time": "晚上", "day": 2},
                {"name": "文殊院", "description": "长江流域四大禅林之一，始建于隋朝的千年古刹", "estimated_duration": "1-2小时", "price": 0, "category": "宗教文化", "best_time": "上午", "day": 3},
            ],
            "北京": [
                {"name": "故宫博物院", "description": "中国明清两代的皇家宫殿，世界五大宫之首", "estimated_duration": "3-4小时", "price": 60, "category": "历史古迹", "best_time": "上午", "day": 1},
                {"name": "天安门广场", "description": "世界最大的城市广场之一，中国国家象征", "estimated_duration": "1-2小时", "price": 0, "category": "地标建筑", "best_time": "上午", "day": 1},
                {"name": "颐和园", "description": "中国清朝时期皇家园林，世界文化遗产", "estimated_duration": "3-4小时", "price": 30, "category": "园林", "best_time": "上午", "day": 2},
                {"name": "长城(八达岭)", "description": "世界七大奇迹之一，中华民族的象征", "estimated_duration": "半天", "price": 40, "category": "历史古迹", "best_time": "上午", "day": 3},
                {"name": "天坛公园", "description": "明清两代皇帝祭天祈谷的场所，世界文化遗产", "estimated_duration": "2-3小时", "price": 15, "category": "历史古迹", "best_time": "上午", "day": 2},
                {"name": "南锣鼓巷", "description": "北京最古老的街区之一，胡同文化代表", "estimated_duration": "2-3小时", "price": 0, "category": "人文街区", "best_time": "下午", "day": 1},
                {"name": "798艺术区", "description": "北京当代艺术地标，废旧工厂改造的艺术园区", "estimated_duration": "2-3小时", "price": 0, "category": "艺术", "best_time": "下午", "day": 2},
                {"name": "什刹海", "description": "北京老城区著名水域，周边有众多胡同和名人故居", "estimated_duration": "2-3小时", "price": 0, "category": "人文街区", "best_time": "下午", "day": 3},
            ],
            "上海": [
                {"name": "外滩", "description": "上海标志性景观，万国建筑博览群", "estimated_duration": "2-3小时", "price": 0, "category": "地标建筑", "best_time": "晚上", "day": 1},
                {"name": "东方明珠", "description": "上海地标建筑，上海广播电视塔", "estimated_duration": "2-3小时", "price": 199, "category": "地标建筑", "best_time": "下午", "day": 1},
                {"name": "豫园", "description": "上海知名古典园林，明代私家花园", "estimated_duration": "2-3小时", "price": 40, "category": "园林", "best_time": "上午", "day": 2},
                {"name": "南京路步行街", "description": "中国第一条商业步行街，中华商业第一街", "estimated_duration": "2-3小时", "price": 0, "category": "购物", "best_time": "下午", "day": 1},
                {"name": "上海博物馆", "description": "中国古代艺术博物馆，馆藏珍贵文物14万件", "estimated_duration": "2-3小时", "price": 0, "category": "博物馆", "best_time": "上午", "day": 2},
                {"name": "田子坊", "description": "上海特色创意园区，石库门里弄与创意文化的结合", "estimated_duration": "2-3小时", "price": 0, "category": "人文街区", "best_time": "下午", "day": 3},
                {"name": "城隍庙", "description": "上海老城隍庙旅游区，特色小吃和古建筑群", "estimated_duration": "2-3小时", "price": 0, "category": "人文街区", "best_time": "上午", "day": 3},
                {"name": "迪士尼乐园", "description": "中国大陆首座迪士尼主题乐园", "estimated_duration": "全天", "price": 475, "category": "乐园", "best_time": "上午", "day": 4},
            ],
            "西安": [
                {"name": "兵马俑博物馆", "description": "世界第八大奇迹，秦始皇陵的陪葬坑", "estimated_duration": "3-4小时", "price": 120, "category": "历史古迹", "best_time": "上午", "day": 1},
                {"name": "大雁塔", "description": "唐代玄奘法师翻译佛经的场所，西安地标", "estimated_duration": "2-3小时", "price": 25, "category": "历史古迹", "best_time": "下午", "day": 1},
                {"name": "华清宫", "description": "唐代皇家温泉行宫，唐玄宗与杨贵妃的爱情故事", "estimated_duration": "2-3小时", "price": 120, "category": "历史古迹", "best_time": "上午", "day": 2},
                {"name": "回民街", "description": "西安著名美食文化街区，千年历史", "estimated_duration": "2-3小时", "price": 0, "category": "美食", "best_time": "下午", "day": 1},
                {"name": "西安城墙", "description": "中国现存最完整的古代城垣，可骑行环城", "estimated_duration": "2-3小时", "price": 54, "category": "历史古迹", "best_time": "下午", "day": 2},
                {"name": "陕西历史博物馆", "description": "中国第一座大型现代化国家级博物馆", "estimated_duration": "2-3小时", "price": 0, "category": "博物馆", "best_time": "上午", "day": 3},
            ],
            "杭州": [
                {"name": "西湖", "description": "世界文化遗产，中国十大风景名胜之一", "estimated_duration": "半天", "price": 0, "category": "自然风光", "best_time": "上午", "day": 1},
                {"name": "灵隐寺", "description": "杭州最早的名刹，江南著名古寺", "estimated_duration": "2-3小时", "price": 75, "category": "宗教文化", "best_time": "上午", "day": 2},
                {"name": "西溪湿地", "description": "国家湿地公园，城市中的自然湿地", "estimated_duration": "3-4小时", "price": 80, "category": "自然风光", "best_time": "上午", "day": 3},
                {"name": "河坊街", "description": "杭州历史文化街区，清末民初风貌", "estimated_duration": "2-3小时", "price": 0, "category": "人文街区", "best_time": "下午", "day": 1},
                {"name": "雷峰塔", "description": "西湖十景之一，白蛇传故事发生地", "estimated_duration": "1-2小时", "price": 40, "category": "地标建筑", "best_time": "下午", "day": 2},
                {"name": "断桥残雪", "description": "西湖十景之一，白蛇传中许仙与白娘子相遇之地", "estimated_duration": "1小时", "price": 0, "category": "自然风光", "best_time": "上午", "day": 3},
            ],
            "广州": [
                {"name": "广州塔(小蛮腰)", "description": "广州新地标，中国第一高塔", "estimated_duration": "2-3小时", "price": 150, "category": "地标建筑", "best_time": "晚上", "day": 1},
                {"name": "陈家祠", "description": "广东民间工艺博物馆，岭南建筑艺术明珠", "estimated_duration": "2-3小时", "price": 10, "category": "历史古迹", "best_time": "上午", "day": 1},
                {"name": "沙面岛", "description": "广州欧陆风情旅游区，150多座欧式建筑", "estimated_duration": "2-3小时", "price": 0, "category": "人文街区", "best_time": "下午", "day": 2},
                {"name": "白云山", "description": "广州著名的风景名胜区，羊城第一秀", "estimated_duration": "半天", "price": 5, "category": "自然风光", "best_time": "上午", "day": 2},
                {"name": "北京路步行街", "description": "广州商业地标，地下埋藏千年古道遗址", "estimated_duration": "2-3小时", "price": 0, "category": "购物", "best_time": "下午", "day": 1},
                {"name": "长隆旅游度假区", "description": "世界级主题乐园和野生动物世界", "estimated_duration": "全天", "price": 350, "category": "乐园", "best_time": "上午", "day": 3},
            ],
            "深圳": [
                {"name": "世界之窗", "description": "汇集世界各大景观微缩版的大型主题公园", "estimated_duration": "半天", "price": 200, "category": "主题乐园", "best_time": "上午", "day": 1},
                {"name": "大梅沙海滨公园", "description": "深圳最受欢迎的海滨浴场，金色沙滩绵延数公里", "estimated_duration": "3-4小时", "price": 0, "category": "自然风光", "best_time": "下午", "day": 1},
                {"name": "欢乐谷", "description": "大型现代化主题乐园，拥有上百个游乐项目", "estimated_duration": "全天", "price": 230, "category": "主题乐园", "best_time": "上午", "day": 2},
                {"name": "东部华侨城", "description": "集生态旅游、休闲度假于一体的大型综合性旅游区", "estimated_duration": "半天", "price": 180, "category": "自然风光", "best_time": "上午", "day": 2},
                {"name": "深圳湾公园", "description": "滨海休闲带，可远眺香港，观鸟胜地", "estimated_duration": "2-3小时", "price": 0, "category": "自然风光", "best_time": "下午", "day": 3},
                {"name": "华强北步行街", "description": "中国最大的电子产品集散地，科技爱好者天堂", "estimated_duration": "2-3小时", "price": 0, "category": "购物", "best_time": "下午", "day": 3},
                {"name": "锦绣中华民俗村", "description": "中国各地名胜古迹和民俗文化的微缩景区", "estimated_duration": "半天", "price": 180, "category": "人文街区", "best_time": "上午", "day": 4},
                {"name": "莲花山公园", "description": "深圳市中心公园，山顶可俯瞰城市全景", "estimated_duration": "2小时", "price": 0, "category": "自然风光", "best_time": "上午", "day": 4},
            ],
            "重庆": [
                {"name": "洪崖洞", "description": "重庆地标，巴渝传统建筑特色的吊脚楼群", "estimated_duration": "2-3小时", "price": 0, "category": "人文街区", "best_time": "晚上", "day": 1},
                {"name": "磁器口古镇", "description": "千年古镇，重庆古城的缩影", "estimated_duration": "2-3小时", "price": 0, "category": "人文街区", "best_time": "上午", "day": 1},
                {"name": "长江索道", "description": "横跨长江的空中公交，俯瞰山城风光", "estimated_duration": "1小时", "price": 20, "category": "地标建筑", "best_time": "下午", "day": 2},
                {"name": "武隆天生三桥", "description": "世界自然遗产，喀斯特地貌奇观", "estimated_duration": "半天", "price": 125, "category": "自然风光", "best_time": "上午", "day": 2},
                {"name": "解放碑步行街", "description": "重庆最繁华的商业中心", "estimated_duration": "2-3小时", "price": 0, "category": "购物", "best_time": "下午", "day": 3},
                {"name": "大足石刻", "description": "世界文化遗产，唐宋时期石刻艺术瑰宝", "estimated_duration": "半天", "price": 115, "category": "历史古迹", "best_time": "上午", "day": 3},
            ],
            "东京": [
                {"name": "浅草寺", "description": "东京最古老的寺庙，雷门大灯笼是标志", "estimated_duration": "2-3小时", "price": 0, "category": "宗教文化", "best_time": "上午", "day": 1},
                {"name": "东京塔", "description": "东京地标建筑，可俯瞰全城美景", "estimated_duration": "2小时", "price": 120, "category": "地标建筑", "best_time": "晚上", "day": 1},
                {"name": "明治神宫", "description": "供奉明治天皇和昭宪皇太后的神社，都市中的绿洲", "estimated_duration": "2-3小时", "price": 0, "category": "宗教文化", "best_time": "上午", "day": 2},
                {"name": "涩谷十字路口", "description": "世界上最繁忙的十字路口，东京时尚文化中心", "estimated_duration": "1-2小时", "price": 0, "category": "人文街区", "best_time": "下午", "day": 1},
                {"name": "上野公园", "description": "东京最大的公园，内有博物馆和动物园", "estimated_duration": "3-4小时", "price": 0, "category": "自然风光", "best_time": "上午", "day": 2},
                {"name": "秋叶原", "description": "日本电器和动漫文化中心，御宅族圣地", "estimated_duration": "2-3小时", "price": 0, "category": "购物", "best_time": "下午", "day": 2},
                {"name": "皇居", "description": "日本天皇居所，东御苑对外开放", "estimated_duration": "2小时", "price": 0, "category": "历史古迹", "best_time": "上午", "day": 3},
                {"name": "银座", "description": "东京最繁华的商业区，高档购物和美食中心", "estimated_duration": "2-3小时", "price": 0, "category": "购物", "best_time": "下午", "day": 3},
                {"name": "台场", "description": "东京湾人造岛上的娱乐购物区，有彩虹桥和高达像", "estimated_duration": "3-4小时", "price": 0, "category": "人文街区", "best_time": "下午", "day": 3},
                {"name": "新宿御苑", "description": "东京最大的日式庭园，赏樱胜地", "estimated_duration": "2-3小时", "price": 50, "category": "自然风光", "best_time": "上午", "day": 3},
            ],
            "巴黎": [
                {"name": "埃菲尔铁塔", "description": "巴黎地标，世界著名 Iron Lady，可俯瞰全城", "estimated_duration": "2-3小时", "price": 170, "category": "地标建筑", "best_time": "下午", "day": 1},
                {"name": "卢浮宫", "description": "世界四大博物馆之首，蒙娜丽莎和断臂维纳斯所在地", "estimated_duration": "3-4小时", "price": 170, "category": "博物馆", "best_time": "上午", "day": 1},
                {"name": "巴黎圣母院", "description": "哥特式建筑杰作，雨果同名小说背景地", "estimated_duration": "1-2小时", "price": 0, "category": "宗教文化", "best_time": "上午", "day": 2},
                {"name": "凯旋门", "description": "拿破仑为纪念法军胜利而建，香榭丽舍大街西端", "estimated_duration": "1-2小时", "price": 130, "category": "地标建筑", "best_time": "上午", "day": 2},
                {"name": "凡尔赛宫", "description": "法国王宫，世界五大宫殿之一，镜厅极为壮观", "estimated_duration": "半天", "price": 200, "category": "历史古迹", "best_time": "上午", "day": 3},
                {"name": "蒙马特高地", "description": "艺术家聚集地，圣心大教堂俯瞰巴黎", "estimated_duration": "2-3小时", "price": 0, "category": "人文街区", "best_time": "下午", "day": 2},
                {"name": "塞纳河游船", "description": "乘船游览巴黎两岸风光，途经各大地标", "estimated_duration": "1-2小时", "price": 150, "category": "观光", "best_time": "晚上", "day": 1},
                {"name": "奥赛博物馆", "description": "印象派艺术殿堂，收藏莫奈、梵高名作", "estimated_duration": "2-3小时", "price": 160, "category": "博物馆", "best_time": "下午", "day": 3},
            ],
        }

        pinyin_map = {
            "chengdu": "成都", "beijing": "北京", "shanghai": "上海",
            "xian": "西安", "hangzhou": "杭州", "guangzhou": "广州",
            "shenzhen": "深圳", "chongqing": "重庆",
            "tokyo": "东京", "paris": "巴黎",
        }
        city_key = pinyin_map.get(destination.lower()) or destination
        attrs = city_map.get(city_key, [])

        if not attrs:
            return []

        result = []
        for i, a in enumerate(attrs):
            entry = dict(a)
            entry["day"] = (i % days) + 1
            entry.setdefault("location", destination)
            result.append(entry)
        return result[:min(len(result), days * 4)]

    def _extract_attraction_price(self, text: str) -> float:
        """从文本中提取门票价格。"""
        import re
        # 匹配 "门票XX元" 或 "XX元/人"
        patterns = [
            r'门票\s*[¥￥]?\s*(\d+)',
            r'(\d+)\s*元(?:/人)?(?:\s*门票)?',
            r'[¥￥]\s*(\d+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    price = int(match.group(1))
                    if 0 <= price <= 2000:
                        return float(price)
                except ValueError:
                    continue
        return 0.0

    def _guess_category(self, name: str, text: str) -> str:
        """根据景点名和描述推断类别。"""
        name_lower = name.lower()
        if any(w in name for w in ["寺", "庙", "教堂", "宫"]):
            return "宗教文化"
        elif any(w in name for w in ["博物馆", "美术馆", "艺术馆"]):
            return "博物馆"
        elif any(w in name for w in ["公园", "花园", "湖", "山", "岛", "海滩", "海滩"]):
            return "自然风光"
        elif any(w in name for w in ["街", "巷", "城", "广场", "市场"]):
            return "人文街区"
        elif any(w in name for w in ["塔", "楼", "桥", "门"]):
            return "地标建筑"
        elif "美食" in name_lower or "小吃" in name_lower:
            return "美食"
        elif "购物" in name_lower or "商场" in name_lower:
            return "购物"
        else:
            return "观光"

    def _balance_attractions(self, attractions: List[Attraction], days: int) -> List[Attraction]:
        """确保每天景点数量平衡（2-4个）。"""
        if not attractions or days <= 0:
            return attractions

        unassigned = [a for a in attractions if not a.get("day") or a.get("day", 0) > days]
        assigned = [a for a in attractions if a.get("day", 0) >= 1 and a.get("day", 0) <= days]

        if unassigned:
            for i, a in enumerate(unassigned):
                a["day"] = (i % days) + 1
            assigned.extend(unassigned)

        by_day = {}
        for a in assigned:
            d = a.get("day", 1)
            by_day.setdefault(d, []).append(a)

        balanced = []
        for day in range(1, days + 1):
            day_attrs = by_day.get(day, [])
            if len(day_attrs) > 4:
                day_attrs = day_attrs[:4]
            if not day_attrs:
                for other_day in range(1, days + 1):
                    if other_day != day and len(by_day.get(other_day, [])) > 2:
                        moved = by_day[other_day].pop()
                        moved["day"] = day
                        day_attrs = [moved]
                        break
            balanced.extend(day_attrs)

        return balanced
