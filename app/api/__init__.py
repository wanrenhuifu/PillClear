"""API 层：FastAPI 路由（用药咨询 / 药箱冲突检测 / 健康检查）。"""

from app.api.medbox_routes import router as medbox_router
from app.api.routes import router

__all__ = ["router", "medbox_router"]
