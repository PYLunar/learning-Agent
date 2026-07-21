"""
火车票搜索工具 - 基于实际高铁用时动态判断是否推荐高铁出行。
通过飞猪 FlyAI search-train 获取真实高铁/动车数据。
规则：高铁直达用时 <=4h 仅推荐高铁，否则同时展示高铁和飞机。
"""

import logging
from typing import Any, Dict, Optional

from app.tools.flyai_cli import get_flyai_client

logger = logging.getLogger(__name__)

# 高铁推荐阈值（分钟）：4小时 = 240分钟
_TRAIN_RECOMMEND_THRESHOLD_MIN = 240


class TrainSearchTool:
    """火车票搜索工具。基于实际高铁用时动态判断推荐。"""

    def __init__(self):
        self.flyai = get_flyai_client()

    async def search(
        self,
        origin: str,
        destination: str,
        departure_date: Optional[str] = None,
        return_date: Optional[str] = None,
        max_results: int = 3,
    ) -> Dict[str, Any]:
        """
        搜索高铁票。先搜索再判断是否推荐。
        规则：有直达车次且最短用时 <= 4h → train_only=True，否则 train_only=False。
        """
        result: Dict[str, Any] = {
            "trains": [],
            "recommended": False,
            "train_only": False,
            "show_flights": True,
            "min_duration_min": None,
            "recommend_reason": "",
        }

        if not departure_date:
            return result

        try:
            # 去程高铁
            trains = self.flyai.search_trains(
                origin, destination, departure_date,
                max_results=max_results * 2,  # 多取一些用于筛选
            )
            # 只保留直达车次
            direct_trains = [t for t in trains if t.get("is_direct")]

            if direct_trains:
                # 找最短用时
                min_duration = min(t.get("duration_min", 999) for t in direct_trains)
                result["trains"] = direct_trains[:max_results]
                result["min_duration_min"] = min_duration
                if min_duration <= _TRAIN_RECOMMEND_THRESHOLD_MIN:
                    result["recommended"] = True
                    result["train_only"] = True
                    result["show_flights"] = False
                    result["recommend_reason"] = (
                        f"{origin}→{destination} 高铁最短 {min_duration} 分钟，"
                        f"小于等于 4 小时，仅展示高铁方案"
                    )
                    logger.info("TrainSearch: %s→%s 仅展示高铁（最短%dm <= 4h），%d 个直达车次",
                                origin, destination, min_duration, len(direct_trains))
                else:
                    result["recommend_reason"] = (
                        f"{origin}→{destination} 高铁最短 {min_duration} 分钟，"
                        f"大于 4 小时，同时展示高铁和飞机方案"
                    )
                    logger.info("TrainSearch: %s→%s 同时展示高铁和飞机（最短%dm > 4h）",
                                origin, destination, min_duration)

            # 返程高铁（只要去程搜到直达高铁就补充返程，便于报告展示）
            if return_date and result["trains"]:
                return_trains = self.flyai.search_trains(
                    destination, origin, return_date,
                    max_results=max_results * 2,
                )
                direct_return = [t for t in return_trains if t.get("is_direct")]
                if direct_return:
                    ret_min = min(t.get("duration_min", 999) for t in direct_return)
                    for t in direct_return[:max_results]:
                        t["is_return"] = True
                    result["return_trains"] = direct_return[:max_results]
                    result["return_min_duration_min"] = ret_min
                    logger.info("TrainSearch: %s→%s 返程高铁（最短%dm），%d 个直达车次",
                                destination, origin, ret_min, len(direct_return))

        except Exception as e:
            logger.warning("TrainSearch: 搜索失败: %s", e)

        return result
