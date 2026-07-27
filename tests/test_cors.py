"""CORS 配置与中间件测试。"""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

VITE_ORIGIN = "http://localhost:5173"


def _client(cors_origins: str) -> TestClient:
    settings = Settings(
        deepseek_api_key="k", cors_origins=cors_origins, _env_file=None
    )
    return TestClient(create_app(settings))


def test_allowed_origin_gets_header():
    resp = _client(VITE_ORIGIN).get(
        "/api/v1/health", headers={"Origin": VITE_ORIGIN}
    )
    assert resp.headers["access-control-allow-origin"] == VITE_ORIGIN


def test_multiple_origins_comma_separated():
    resp = _client(f"{VITE_ORIGIN}, http://127.0.0.1:5173").get(
        "/api/v1/health", headers={"Origin": "http://127.0.0.1:5173"}
    )
    assert resp.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_blank_cors_origins_disables_middleware():
    resp = _client("").get("/api/v1/health", headers={"Origin": VITE_ORIGIN})
    assert "access-control-allow-origin" not in resp.headers


def test_default_settings_include_vite_origin():
    s = Settings(deepseek_api_key="k", _env_file=None)
    assert VITE_ORIGIN in s.cors_origins
