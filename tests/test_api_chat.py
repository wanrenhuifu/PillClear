"""/api/v1/chat 端点的集成测试。

覆盖：安全边界拦截 / LLM 正常回答 / 错误处理 / 健康检查。
所有 LLM 调用通过 respx mock，不产生真实网络请求。
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from tests.conftest import DEEPSEEK_URL, make_completion


# ── Fixtures ────────────────────────────────────────────────

@pytest.fixture
def app_with_test_settings(settings: Settings):
    """用测试 Settings 创建 app（覆盖 .env 的 API key）。"""
    from app.main import create_app
    from app.api.deps import get_settings

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return app


@pytest.fixture
def client(app_with_test_settings) -> TestClient:
    return TestClient(app_with_test_settings)


# ── Health ──────────────────────────────────────────────────

class TestHealth:
    def test_health_ok(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ── 安全边界拦截 ────────────────────────────────────────────

class TestSafetyBlock:

    def test_emergency_blocked(self, client):
        resp = client.post("/api/v1/chat", json={"query": "我吃完药呼吸困难怎么办"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["blocked"] is True
        assert data["category"] == "emergency"
        assert "120" in data["boundary_message"]
        assert data["answer"] is None

    def test_special_population_blocked(self, client):
        resp = client.post("/api/v1/chat", json={"query": "孕妇能吃布洛芬吗"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["blocked"] is True
        assert data["category"] == "special_population"
        assert data["answer"] is None

    def test_diagnosis_blocked(self, client):
        resp = client.post("/api/v1/chat", json={"query": "我是不是得了肺炎"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["blocked"] is True
        assert data["category"] == "diagnosis"

    def test_prescription_blocked(self, client):
        resp = client.post("/api/v1/chat", json={"query": "阿莫西林一次吃几粒"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["blocked"] is True
        assert data["category"] == "prescription"


# ── 正常回答（通过安全边界 + LLM）───────────────────────────

class TestChatOk:

    def test_normal_otc_query(self, respx_mock, client):
        respx_mock.post(DEEPSEEK_URL).mock(
            return_value=make_completion(
                '{"answer": "布洛芬最好饭后吃，能减少对胃的刺激。", "confidence": 0.85}'
            )
        )
        resp = client.post("/api/v1/chat", json={"query": "布洛芬能空腹吃吗"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["blocked"] is False
        assert "饭后" in data["answer"]
        assert data["category"] is None
        assert data["boundary_message"] is None

    def test_disclaimer_appended(self, respx_mock, client):
        respx_mock.post(DEEPSEEK_URL).mock(
            return_value=make_completion(
                '{"answer": "多喝水，注意休息。", "confidence": 0.9}'
            )
        )
        resp = client.post("/api/v1/chat", json={"query": "感冒了怎么办"})
        data = resp.json()
        assert "不能替代医生或药师的建议" in data["answer"]
        assert data["disclaimer"] is not None
        assert "不能替代" in data["disclaimer"]

    def test_citations_empty_rag_pending(self, respx_mock, client):
        respx_mock.post(DEEPSEEK_URL).mock(
            return_value=make_completion(
                '{"answer": "泰诺主要成分是对乙酰氨基酚。", "confidence": 0.8}'
            )
        )
        resp = client.post("/api/v1/chat", json={"query": "泰诺有什么成分"})
        data = resp.json()
        assert data["citations"] == []
        assert "开发中" in data["sources_note"]

    def test_low_confidence_adds_uncertainty_note(self, respx_mock, client):
        """铁律 #4 代码兜底：低置信度回答必须显式提示"不确定 + 咨询药师"。"""
        respx_mock.post(DEEPSEEK_URL).mock(
            return_value=make_completion(
                '{"answer": "也许可以一起吃吧。", "confidence": 0.2}'
            )
        )
        resp = client.post(
            "/api/v1/chat", json={"query": "圣约翰草和避孕药能一起吃吗"}
        )
        data = resp.json()
        assert data["confidence"] == 0.2
        assert "把握不大" in data["answer"]
        assert "咨询药师" in data["answer"]

    def test_high_confidence_no_uncertainty_note(self, respx_mock, client):
        respx_mock.post(DEEPSEEK_URL).mock(
            return_value=make_completion(
                '{"answer": "最好饭后吃。", "confidence": 0.9}'
            )
        )
        resp = client.post("/api/v1/chat", json={"query": "布洛芬能空腹吃吗"})
        data = resp.json()
        assert data["confidence"] == 0.9
        assert "把握不大" not in data["answer"]

    def test_negated_emergency_not_blocked(self, respx_mock, client):
        """否定语境不应触发安全边界。"""
        respx_mock.post(DEEPSEEK_URL).mock(
            return_value=make_completion(
                '{"answer": "感冒药可以和布洛芬间隔4小时服用。", "confidence": 0.7}'
            )
        )
        resp = client.post(
            "/api/v1/chat", json={"query": "我没有呼吸困难，就是想问问感冒药怎么吃"}
        )
        data = resp.json()
        assert data["blocked"] is False


# ── 错误处理 ────────────────────────────────────────────────

class TestChatErrors:

    def test_empty_query(self, client):
        resp = client.post("/api/v1/chat", json={"query": ""})
        assert resp.status_code == 422

    def test_query_too_long(self, client):
        resp = client.post("/api/v1/chat", json={"query": "x" * 2001})
        assert resp.status_code == 422

    def test_llm_retry_exhausted(self, respx_mock, client):
        # 三次全部返回非法 JSON → retries 耗尽
        respx_mock.post(DEEPSEEK_URL).mock(
            side_effect=[
                make_completion("bad json 1"),
                make_completion("bad json 2"),
                make_completion("bad json 3"),
            ]
        )
        resp = client.post("/api/v1/chat", json={"query": "布洛芬用法"})
        assert resp.status_code == 502
        assert "不可用" in resp.json()["detail"]

    def test_llm_validation_error_retry_succeeds(self, respx_mock, client):
        # 首次缺必填字段 → retry → 成功
        respx_mock.post(DEEPSEEK_URL).mock(
            side_effect=[
                make_completion('{"foo": 1}'),
                make_completion('{"answer": "没问题", "confidence": 0.6}'),
            ]
        )
        resp = client.post("/api/v1/chat", json={"query": "布洛芬怎么吃"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["blocked"] is False
        assert "没问题" in data["answer"]
