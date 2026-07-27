"""PillClear FastAPI 应用工厂。

用法：
    uvicorn app.main:app --reload
    # 或编程式 create_app(settings=...) 用于测试注入。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import get_settings
from app.api.drug_routes import router as drug_router
from app.api.medbox_routes import router as medbox_router
from app.api.routes import router
from app.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建 FastAPI 应用实例。settings 为 None 时取全局缓存配置。"""
    if settings is None:
        settings = get_settings()
    app = FastAPI(
        title="PillClear",
        version="0.1.0",
        description="年轻人智能用药安全助手 —— C 端 OTC 用药安全助手",
    )

    if settings.cors_origins.strip():
        origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(router, prefix="/api/v1")
    app.include_router(medbox_router, prefix="/api/v1")
    app.include_router(drug_router, prefix="/api/v1")

    app.dependency_overrides[get_settings] = lambda: settings

    return app


# 模块级默认实例，供 uvicorn 直接引用
app = create_app()
