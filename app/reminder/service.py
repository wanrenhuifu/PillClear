"""用药提醒服务层：CRUD + 下一次提醒时刻计算（不依赖 Web 框架）。

提醒是调度数据：本层不做任何药学判断（铁律 #1），也不碰 LLM。
next_due 是纯函数（显式注入 now），保证「下一次提醒」逻辑可离线逐字测试。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.reminder.repository import ReminderRepository
from app.reminder.schemas import Reminder, ReminderAddRequest, ReminderResponse


def next_due(times: list[str], now: datetime) -> datetime | None:
    """给定每日提醒时刻表（HH:MM），返回严格晚于 now 的下一次提醒时刻。

    今天还有未到的时刻 → 取今天最早的一个；全部已过 → 明天最早的一个。
    空时刻表返回 None。纯函数：同一输入恒同一输出，跨月/跨年由 timedelta 兜底。
    """
    if not times:
        return None
    todays = sorted(
        now.replace(hour=int(t[:2]), minute=int(t[3:]), second=0, microsecond=0)
        for t in times
    )
    for candidate in todays:
        if candidate > now:
            return candidate
    return todays[0] + timedelta(days=1)


class ReminderService:
    """提醒 CRUD 服务。每个实例绑定一个 ReminderRepository。"""

    def __init__(self, repo: ReminderRepository) -> None:
        self._repo = repo

    def get_reminders(
        self, device_id: str, now: datetime | None = None
    ) -> ReminderResponse:
        """获取用户全部提醒（附 next_due_at）；无记录返回空列表。"""
        now = now or datetime.now()
        user_id = self._repo.get_or_create_user(device_id)
        return ReminderResponse(
            device_id=device_id,
            reminders=[
                Reminder(
                    drug_id=row["drug_id"],
                    brand_name=row["brand_name"],
                    times=row["times"],
                    next_due_at=_iso(next_due(row["times"], now)),
                )
                for row in self._repo.get_reminders(user_id)
            ],
        )

    def set_reminder(
        self, device_id: str, request: ReminderAddRequest
    ) -> ReminderResponse:
        """覆盖式设置某药品的提醒时刻表（去重 + 升序归一化），返回全部提醒。"""
        user_id = self._repo.get_or_create_user(device_id)
        self._repo.set_reminder(user_id, request.drug_id, request.times)
        return self.get_reminders(device_id)

    def remove_reminder(self, device_id: str, drug_id: int) -> ReminderResponse:
        """移除某药品的提醒，返回剩余提醒。"""
        user_id = self._repo.get_or_create_user(device_id)
        self._repo.remove_reminder(user_id, drug_id)
        return self.get_reminders(device_id)


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment is not None else None


__all__ = ["ReminderService", "next_due"]
