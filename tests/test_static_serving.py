"""STATIC_DIR 可选静态服务测试（部署路径：单镜像同源服务前端构建产物）。

语义（见 docs/superpowers/specs/2026-08-15-docker-deployment-design.md）：
- static_dir 为空 = 完全不挂静态服务（默认行为零变化，守护现状）；
- 非空 = catch-all 路由服务静态文件 + SPA history 回退，且不得吞 /api/v1；
- 目录穿越不得逃逸出静态目录；缺 index.html → fail fast。
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _make_static_dir(tmp_path: Path) -> Path:
    """造一个最小前端构建产物目录。"""
    static = tmp_path / "dist"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>pillclear-spa</html>", encoding="utf-8")
    (static / "assets" / "app.js").write_text("console.log('spa');", encoding="utf-8")
    return static


def _client(static_dir: str) -> TestClient:
    settings = Settings(deepseek_api_key="k", static_dir=static_dir, _env_file=None)
    return TestClient(create_app(settings))


def test_default_app_does_not_serve_static(settings: Settings) -> None:
    """守护现状：未设 STATIC_DIR 时根路径仍 404（开发与测试行为零变化）。"""
    assert settings.static_dir == ""
    resp = TestClient(create_app(settings)).get("/")
    assert resp.status_code == 404


def test_root_serves_index(tmp_path: Path) -> None:
    resp = _client(str(_make_static_dir(tmp_path))).get("/")
    assert resp.status_code == 200
    assert "pillclear-spa" in resp.text
    assert resp.headers["content-type"].startswith("text/html")


def test_spa_history_fallback(tmp_path: Path) -> None:
    """/chat 等前端路由直开/刷新不得 404，回退 index.html 交给前端路由。"""
    resp = _client(str(_make_static_dir(tmp_path))).get("/chat")
    assert resp.status_code == 200
    assert "pillclear-spa" in resp.text


def test_static_asset_served(tmp_path: Path) -> None:
    resp = _client(str(_make_static_dir(tmp_path))).get("/assets/app.js")
    assert resp.status_code == 200
    assert "console.log('spa');" in resp.text


def test_api_not_shadowed(tmp_path: Path) -> None:
    """catch-all 注册在全部路由之后，/api/v1/* 必须优先命中。"""
    resp = _client(str(_make_static_dir(tmp_path))).get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_path_traversal_blocked(tmp_path: Path) -> None:
    """编码的 ../ 不得逃逸出静态目录（不得返回仓库源码）。"""
    client = _client(str(_make_static_dir(tmp_path)))
    for path in ("/%2e%2e/%2e%2e/app/config.py", "/assets/%2e%2e/%2e%2e/app/config.py"):
        resp = client.get(path)
        assert "pydantic" not in resp.text, f"源码泄漏: {path}"


def test_missing_index_fails_fast(tmp_path: Path) -> None:
    """配置非空但目录缺 index.html = 坏部署，必须显式失败而非静默 404。"""
    empty = tmp_path / "empty"
    empty.mkdir()
    settings = Settings(deepseek_api_key="k", static_dir=str(empty), _env_file=None)
    with pytest.raises(RuntimeError, match=r"index\.html"):
        create_app(settings)
