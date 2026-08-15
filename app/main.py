"""PillClear FastAPI 应用工厂。

用法：
    uvicorn app.main:app --reload
    # 或编程式 create_app(settings=...) 用于测试注入。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.deps import get_settings
from app.api.drug_routes import router as drug_router
from app.api.medbox_routes import router as medbox_router
from app.api.reminder_routes import router as reminder_router
from app.api.routes import router
from app.config import Settings


def _mount_spa(app: FastAPI, static_dir: Path) -> None:
    """同源服务前端构建产物：静态文件 + SPA history 回退（部署路径用）。

    必须在全部 API 路由之后调用——路由按注册顺序匹配，catch-all 垫底，
    /api/v1 与 /docs 等优先命中。目录穿越以 resolve + is_relative_to 拦截。
    """
    static_dir = static_dir.resolve()
    index_file = static_dir / "index.html"
    if not index_file.is_file():
        raise RuntimeError(
            f"STATIC_DIR {static_dir} 缺少 index.html——前端未构建或路径配错，"
            "拒绝静默启动（参见 Dockerfile 构建阶段）"
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        candidate = (static_dir / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(static_dir):
            return FileResponse(candidate)
        return FileResponse(index_file)


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
    app.include_router(reminder_router, prefix="/api/v1")

    if settings.static_dir:
        _mount_spa(app, Path(settings.static_dir))

    app.dependency_overrides[get_settings] = lambda: settings

    return app


# 模块级默认实例，供 uvicorn 直接引用
app = create_app()
