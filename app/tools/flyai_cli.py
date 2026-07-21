"""
飞猪 FlyAI CLI 封装器。
通过调用本地安装的 @fly-ai/flyai-cli 获取真实航班、酒店、景点数据。
"""

import json
import logging
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

# flyai CLI 可能的路径（npm 全局安装位置）
_FLYAI_PATHS = [
    shutil.which("flyai"),  # 标准 PATH 查找
    r"C:\Users\pengyi\AppData\Roaming\TRAE SOLO CN\ModularData\ai-agent\vm\tools\node\flyai.cmd",
]


def _find_flyai() -> Optional[str]:
    """查找 flyai CLI 可执行文件路径。"""
    for p in _FLYAI_PATHS:
        if p and os.path.isfile(p):
            return p
    return None


class FlyAIClient:
    """封装 flyai CLI 调用，返回结构化数据。"""

    def __init__(self):
        self.api_key = os.getenv("FLYAI_API_KEY", "")
        self._flyai_bin = _find_flyai()
        self.timeout = get_settings().FLYAI_TIMEOUT_SECONDS
        self.last_error = ""

    def _run(self, args: List[str]) -> Optional[Dict[str, Any]]:
        """运行 flyai CLI 命令并解析 JSON 输出。"""
        if not self._flyai_bin:
            self.last_error = "flyai_cli_not_found"
            logger.warning("flyai CLI not found. Run: npm install -g @fly-ai/flyai-cli")
            return None

        env = os.environ.copy()
        if self.api_key:
            env["FLYAI_API_KEY"] = self.api_key

        cmd = [self._flyai_bin] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
                encoding="utf-8",
            )
            if result.returncode != 0:
                self.last_error = f"flyai_cli_error: {result.stderr[:200]}"
                logger.warning("flyai CLI error: %s", result.stderr[:500])
                return None

            data = json.loads(result.stdout)
            if data.get("status") != 0:
                self.last_error = f"flyai_api_error: {data.get('message')}"
                logger.warning("flyai API error: %s", data.get("message"))
                return None
            self.last_error = ""
            return data
        except subprocess.TimeoutExpired:
            self.last_error = f"flyai_timeout_{self.timeout}s"
            logger.warning("flyai CLI timeout after %.1fs", self.timeout)
            return None
        except json.JSONDecodeError as e:
            self.last_error = f"flyai_invalid_json: {e}"
            logger.warning("flyai CLI invalid JSON: %s", e)
            return None
        except FileNotFoundError:
            self.last_error = "flyai_executable_not_found"
            logger.warning("flyai CLI executable not found at %s", self._flyai_bin)
            return None
        except Exception as e:
            self.last_error = f"flyai_exception: {e}"
            logger.warning("flyai CLI exception: %s", e)
            return None

    def search_hotels(
        self,
        city: str,
        max_price: Optional[int] = None,
        sort: str = "rate_desc",
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """搜索酒店，返回列表。"""
        args = [
            "search-hotel",
            "--dest-name", city,
            "--sort", sort,
        ]
        if max_price:
            args += ["--max-price", str(max_price)]

        data = self._run(args)
        if not data:
            return []

        payload = data.get("data") or {}
        items = payload.get("itemList", [])
        hotels = []
        for item in items[:max_results]:
            price_str = item.get("price", "")
            price = 0
            if price_str.startswith("¥"):
                try:
                    price = int(price_str.replace("¥", "").replace(",", "").split(".")[0])
                except ValueError:
                    pass

            hotels.append({
                "name": item.get("name", ""),
                "address": item.get("address", ""),
                "price_per_night": price,
                "rating": float(item.get("score", 0)) if item.get("score") else 4.0,
                "star": item.get("star", ""),
                "brand": item.get("brandName", ""),
                "nearby_poi": item.get("interestsPoi", ""),
                "detail_url": item.get("detailUrl", ""),
                "main_pic": item.get("mainPic", ""),
            })
        return hotels

    def search_flights(
        self,
        origin: str,
        destination: str,
        dep_date: str,
        back_date: Optional[str] = None,
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """搜索航班，返回列表。"""
        args = [
            "search-flight",
            "--origin", origin,
            "--destination", destination,
            "--dep-date", dep_date,
        ]
        if back_date:
            args += ["--back-date", back_date]

        data = self._run(args)
        if not data:
            return []

        payload = data.get("data") or {}
        items = payload.get("itemList", [])
        flights = []
        for item in items:  # 不过滤数量，先全部遍历
            journeys = item.get("journeys", [])
            if not journeys:
                continue
            seg = journeys[0].get("segments", [{}])[0]

            dep_city = seg.get("depCityName", "")
            arr_city = seg.get("arrCityName", "")

            # 过滤：出发/到达城市必须匹配用户请求
            if dep_city != origin or arr_city != destination:
                logger.warning("flyai 返回了不匹配航线: %s→%s (请求: %s→%s)", dep_city, arr_city, origin, destination)
                continue

            dep_dt = seg.get("depDateTime", "")
            arr_dt = seg.get("arrDateTime", "")
            dep_time = dep_dt.split(" ")[1][:5] if " " in dep_dt else ""
            arr_time = arr_dt.split(" ")[1][:5] if " " in arr_dt else ""

            duration_min = 0
            try:
                duration_min = int(seg.get("duration", 0))
            except (ValueError, TypeError):
                pass
            duration_str = f"{duration_min // 60}h{duration_min % 60:02d}m"

            price = 0
            try:
                price = int(float(item.get("ticketPrice", 0)))
            except (ValueError, TypeError):
                pass

            flights.append({
                "airline": seg.get("marketingTransportName", ""),
                "flight_number": seg.get("marketingTransportNo", ""),
                "departure_city": dep_city,
                "arrival_city": arr_city,
                "departure_airport": seg.get("depStationName", ""),
                "arrival_airport": seg.get("arrStationName", ""),
                "departure_time": dep_time,
                "arrival_time": arr_time,
                "departure": f"{dep_time} 从{dep_city}",
                "arrival": f"{arr_time} 到达{arr_city}",
                "price": price,
                "duration": duration_str,
                "layovers": 0 if journeys[0].get("journeyType") == "直达" else len(journeys[0].get("segments", [])) - 1,
                "layover_cities": [],
                "class_type": seg.get("seatClassName", "经济舱"),
                "booking_url": item.get("jumpUrl", ""),
                "is_return": False,
            })
            if len(flights) >= max_results:
                break
        return flights

    def search_trains(
        self,
        origin: str,
        destination: str,
        dep_date: str,
        back_date: Optional[str] = None,
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """搜索火车票（高铁/动车），返回列表。"""
        args = [
            "search-train",
            "--origin", origin,
            "--destination", destination,
            "--dep-date", dep_date,
            "--sort-type", "4",  # 时短优先
        ]
        if back_date:
            args += ["--back-date", back_date]

        data = self._run(args)
        if not data:
            return []

        payload = data.get("data") or {}
        items = payload.get("itemList", [])
        trains = []
        for item in items:
            journeys = item.get("journeys", [])
            if not journeys:
                continue
            seg = journeys[0].get("segments", [{}])[0]

            dep_city = seg.get("depCityName", "")
            arr_city = seg.get("arrCityName", "")

            # 过滤：出发/到达城市必须匹配用户请求
            if dep_city != origin or arr_city != destination:
                logger.warning("flyai 返回了不匹配车次: %s→%s (请求: %s→%s)", dep_city, arr_city, origin, destination)
                continue

            dep_dt = seg.get("depDateTime", "")
            arr_dt = seg.get("arrDateTime", "")
            dep_time = dep_dt.split(" ")[1][:5] if " " in dep_dt else ""
            arr_time = arr_dt.split(" ")[1][:5] if " " in arr_dt else ""

            duration_min = 0
            try:
                duration_min = int(journeys[0].get("totalDuration", 0))
            except (ValueError, TypeError):
                pass
            duration_str = f"{duration_min // 60}h{duration_min % 60:02d}m" if duration_min >= 60 else f"{duration_min}m"

            price_raw = item.get("price")
            try:
                price = int(float(price_raw)) if price_raw else 0
            except (ValueError, TypeError):
                price = 0  # 脱敏数据(如'1xx')或缺失

            is_direct = journeys[0].get("journeyType") == "直达"

            trains.append({
                "train_type": seg.get("marketingTransportName", "高铁"),
                "train_number": seg.get("marketingTransportNo", ""),
                "departure_city": dep_city,
                "arrival_city": arr_city,
                "departure_station": seg.get("depStationName", ""),
                "arrival_station": seg.get("arrStationName", ""),
                "departure_time": dep_time,
                "arrival_time": arr_time,
                "price": price,
                "duration": duration_str,
                "duration_min": duration_min,
                "seat_class": seg.get("seatClassName", "二等座"),
                "is_direct": is_direct,
                "booking_url": item.get("jumpUrl", ""),
            })
            if len(trains) >= max_results:
                break
        return trains

    def search_poi(
        self,
        city: str,
        keywords: str = "景点",
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """搜索景点/POI，返回列表。"""
        args = [
            "search-poi",
            "--city-name", city,
            "--keyword", keywords,
        ]

        data = self._run(args)
        if not data:
            return []

        payload = data.get("data") or {}
        items = payload.get("itemList", [])
        pois = []
        for item in items[:max_results]:
            if not isinstance(item, dict):
                continue
            ticket_info = item.get("ticketInfo") or {}
            price = item.get("price", 0)
            if not price and isinstance(ticket_info, dict):
                price = ticket_info.get("price", 0)
            pois.append({
                "name": item.get("name", ""),
                "address": item.get("address", ""),
                "price": price or 0,
                "rating": float(item.get("score", 0)) if item.get("score") else 4.0,
                "detail_url": item.get("detailUrl", item.get("jumpUrl", "")),
                "main_pic": item.get("mainPic", ""),
            })
        return pois


# 全局单例
_flyai_client: Optional[FlyAIClient] = None


def get_flyai_client() -> FlyAIClient:
    global _flyai_client
    if _flyai_client is None or _flyai_client._flyai_bin is None:
        _flyai_client = FlyAIClient()
    return _flyai_client
