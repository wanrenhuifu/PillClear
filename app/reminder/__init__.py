"""用药提醒层：时刻表 CRUD + 下一次提醒计算。

提醒是调度数据，不做药学判断、不碰 LLM（铁律 #1）。
架构模式同药箱（app/medbox/）：Protocol 仓储三实现 + 服务层 + 薄路由。
"""

from app.reminder.repository import (
    InMemoryReminderRepository,
    PostgresReminderRepository,
    ReminderRepository,
)
from app.reminder.schemas import Reminder, ReminderAddRequest, ReminderResponse
from app.reminder.service import ReminderService, next_due
from app.reminder.sqlite_reminder_repo import SQLiteReminderRepository

__all__ = [
    "InMemoryReminderRepository",
    "PostgresReminderRepository",
    "Reminder",
    "ReminderAddRequest",
    "ReminderRepository",
    "ReminderResponse",
    "ReminderService",
    "SQLiteReminderRepository",
    "next_due",
]
