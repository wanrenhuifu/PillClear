"""用药提醒数据模型。

提醒 = 某个药品 + 每日 1~4 个提醒时刻（HH:MM，24 小时制）。
MVP 阶段按 (device_id, drug_id) 唯一：重复设置同一药品即覆盖旧时刻表。

提醒是「调度数据」而非药学判断——不参与叠加 / 相互作用计算，
永不触碰 LLM（铁律 #1；tests/test_reminder.py 刻意不挂 respx 断言此事）。
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

# HH:MM 24 小时制：00:00 ~ 23:59。pattern 必须挂在元素类型上
# （pydantic v2 不支持把 pattern 直接加在 list 字段）。
TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
TimeOfDay = Annotated[str, Field(pattern=TIME_PATTERN)]


class Reminder(BaseModel):
    """一个药品的提醒设置（读取视图，附带下一次提醒时刻）。"""

    drug_id: int
    brand_name: str = Field(..., min_length=1)
    times: list[TimeOfDay] = Field(..., min_length=1, max_length=4)
    # 下一次提醒时刻（ISO 8601）；服务端按当前时间计算，前端直接展示。
    next_due_at: str | None = None


class ReminderAddRequest(BaseModel):
    """POST /api/v1/reminders/{device_id}/items 请求体。"""

    drug_id: int
    brand_name: str = Field(..., min_length=1)
    times: list[TimeOfDay] = Field(..., min_length=1, max_length=4)


class ReminderResponse(BaseModel):
    """提醒端点的统一响应：设备标识 + 当前全部提醒。"""

    device_id: str
    reminders: list[Reminder] = Field(default_factory=list)


__all__ = ["TIME_PATTERN", "Reminder", "ReminderAddRequest", "ReminderResponse", "TimeOfDay"]
