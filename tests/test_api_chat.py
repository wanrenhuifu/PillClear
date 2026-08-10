"""/api/v1/chat 端点的集成测试。

/chat 现为编排 RAG + 规则引擎 + LLM 的智能体，每次「放行」请求最多触发三次 LLM 调用：
    ① 能力边界分类（safety） → ② 意图分类（intent） → ③ 生成回答（answer）。
被关键词边界拦截的请求不触达任何 LLM。

本文件用 respx 为每一次 LLM 调用显式提供响应（side_effect 按调用顺序消费），
使测试确定、可读、不依赖「降级巧合」；所有调用均 mock，不打真实 API。
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_drug_repository, get_retriever
from app.config import Settings
from app.knowledge.repository import InMemoryDrugRepository
from app.knowledge.schemas import DrugRecord, Ingredient
from app.rag import NullRetriever
from tests.conftest import DEEPSEEK_URL, make_completion

# ── 三次 LLM 调用的响应构造器 ───────────────────────────────


def safety_completion(category: str = "none", confidence: float = 0.9):
    """① 能力边界分类响应。"""
    return make_completion(
        json.dumps({"category": category, "confidence": confidence})
    )


def intent_completion(
    intent: str = "drug_info",
    confidence: float = 0.9,
    drug_names: list[str] | None = None,
    lifestyle_substances: list[str] | None = None,
):
    """② 意图分类响应。"""
    return make_completion(
        json.dumps(
            {
                "intent": intent,
                "confidence": confidence,
                "drug_names": drug_names or [],
                "lifestyle_substances": lifestyle_substances or [],
            },
            ensure_ascii=False,
        )
    )


def answer_completion(
    answer: str,
    confidence: float = 0.85,
    citations_used: list[str] | None = None,
):
    """③ 生成回答响应。"""
    return make_completion(
        json.dumps(
            {
                "answer": answer,
                "confidence": confidence,
                "citations_used": citations_used or [],
            },
            ensure_ascii=False,
        )
    )


def last_request_body(respx_mock) -> dict:
    """取最后一次 LLM 调用的请求体（即「生成回答」阶段的 messages）。"""
    return json.loads(respx_mock.calls[-1].request.content)


def last_system_prompt(respx_mock) -> str:
    """取「生成回答」阶段 system prompt 文本。"""
    return last_request_body(respx_mock)["messages"][0]["content"]


# ── Fixtures ────────────────────────────────────────────────

@pytest.fixture
def app_with_test_settings(settings: Settings):
    """用测试 Settings 创建 app（覆盖 .env 的 API key）。"""
    from app.api.deps import get_settings
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    # 检索隔离：固定 NullRetriever，使套件与开发机是否已入库无关。
    # 否则 get_retriever 在本机会返回指向真实 %APPDATA% DB 的
    # KeywordRetriever；新增的确定性品牌扫描会把真实品牌名注入检索，
    # 让依赖「空引用」的用例（如 test_citations_empty_*）在本机变红。
    app.dependency_overrides[get_retriever] = lambda: NullRetriever()
    # 仓储隔离：同理——不覆盖时 get_drug_repository 在测试 Settings 下解析出
    # 指向真实 %APPDATA%/PillClear/pillclear.db 的 SQLiteDrugRepository，
    # pipeline 的 list_drugs 扫描会读到开发机已入库的真实品牌名（code review #8）。
    # 裸类作覆盖函数：每请求新建空仓储；client_seeded 会再覆盖为种子仓储。
    app.dependency_overrides[get_drug_repository] = InMemoryDrugRepository
    return app


@pytest.fixture
def client(app_with_test_settings) -> TestClient:
    return TestClient(app_with_test_settings)


def _seed_repo() -> InMemoryDrugRepository:
    """种子：泰诺 / 必理通 共享对乙酰氨基酚，芬必得含布洛芬。"""
    repo = InMemoryDrugRepository()
    repo.upsert_drug(
        DrugRecord(
            brand_name="泰诺",
            ingredients=[
                Ingredient(name="对乙酰氨基酚", amount=325, unit="mg"),
                Ingredient(name="马来酸氯苯那敏", amount=2, unit="mg"),
            ],
        )
    )
    repo.upsert_drug(
        DrugRecord(
            brand_name="必理通",
            ingredients=[Ingredient(name="对乙酰氨基酚", amount=500, unit="mg")],
        )
    )
    repo.upsert_drug(
        DrugRecord(
            brand_name="芬必得",
            ingredients=[Ingredient(name="布洛芬", amount=300, unit="mg")],
        )
    )
    return repo


@pytest.fixture
def client_seeded(app_with_test_settings) -> TestClient:
    """/chat 客户端 + 种子药箱仓储（药箱检查集成测试用）。"""
    app_with_test_settings.dependency_overrides[get_drug_repository] = _seed_repo
    return TestClient(app_with_test_settings)


# ── Health ──────────────────────────────────────────────────

class TestHealth:
    def test_health_ok(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ── 依赖隔离（套件不得触达开发机真实 DB）────────────────────

class TestDependencyIsolation:
    def test_chat_never_resolves_dev_machine_db_path(
        self, respx_mock, client, monkeypatch
    ):
        """/chat 全程不得触达开发机真实 DB 路径（code review #8）。

        client fixture 必须同时覆盖 get_retriever 与 get_drug_repository；
        否则测试 Settings 下 deps 会解析出指向 %APPDATA%/PillClear/pillclear.db
        的 SQLite 仓储，pipeline 的 list_drugs 扫描会读到开发机已入库的真实品牌，
        让依赖「空目录」的用例在本机变红、在干净 CI 上绿。
        """
        from app.api import deps

        def _boom(settings):
            raise AssertionError("触达开发机 DB 路径解析——依赖隔离失效")

        monkeypatch.setattr(deps, "_resolve_db_path", _boom)
        respx_mock.post(DEEPSEEK_URL).mock(
            side_effect=[
                safety_completion(),
                intent_completion("drug_info"),
                answer_completion("多喝水休息。", 0.9),
            ]
        )
        resp = client.post("/api/v1/chat", json={"query": "感冒了怎么办"})
        assert resp.status_code == 200
        assert resp.json()["blocked"] is False


# ── 安全边界拦截（关键词，不触达 LLM）─────────────────────────

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
        data = resp.json()
        assert data["blocked"] is True
        assert data["category"] == "special_population"
        assert data["answer"] is None

    def test_diagnosis_blocked(self, client):
        resp = client.post("/api/v1/chat", json={"query": "我是不是得了肺炎"})
        assert resp.json()["category"] == "diagnosis"

    def test_prescription_blocked(self, client):
        resp = client.post("/api/v1/chat", json={"query": "阿莫西林一次吃几粒"})
        assert resp.json()["category"] == "prescription"

    def test_keyword_block_makes_no_llm_call(self, respx_mock, client):
        """关键词命中即拦，不触达任何 LLM（0 次调用）。"""
        route = respx_mock.post(DEEPSEEK_URL).mock(
            return_value=safety_completion()
        )
        resp = client.post("/api/v1/chat", json={"query": "孕妇能吃布洛芬吗"})
        assert resp.json()["blocked"] is True
        assert route.call_count == 0


# ── 安全边界的 LLM 补漏（任务五）─────────────────────────────

class TestSafetyLLMLayer:

    def test_llm_flags_prescription_when_keyword_passes(self, respx_mock, client):
        """关键词放行、LLM 高置信度判为处方药 → 仍被拦截（仅 1 次 LLM 调用）。"""
        route = respx_mock.post(DEEPSEEK_URL).mock(
            return_value=safety_completion("prescription", 0.95)
        )
        resp = client.post(
            "/api/v1/chat", json={"query": "这个药能和那个药一起吃吗"}
        )
        data = resp.json()
        assert data["blocked"] is True
        assert data["category"] == "prescription"
        assert "处方药" in data["boundary_message"]
        # 被边界拦截后不再做意图分类 / 回答生成 → 只有 1 次调用
        assert route.call_count == 1

    def test_llm_low_confidence_does_not_block(self, respx_mock, client):
        """LLM 低置信度 → 以关键词结果（放行）为准，继续正常回答。"""
        respx_mock.post(DEEPSEEK_URL).mock(
            side_effect=[
                safety_completion("prescription", 0.3),  # 低置信度 → 放行
                intent_completion("drug_info"),
                answer_completion("布洛芬最好饭后吃。", 0.85),
            ]
        )
        resp = client.post("/api/v1/chat", json={"query": "布洛芬怎么吃"})
        data = resp.json()
        assert data["blocked"] is False
        assert "饭后" in data["answer"]

    def test_llm_says_none_proceeds(self, respx_mock, client):
        respx_mock.post(DEEPSEEK_URL).mock(
            side_effect=[
                safety_completion("none", 0.9),
                intent_completion("drug_info"),
                answer_completion("多喝水休息。", 0.9),
            ]
        )
        resp = client.post("/api/v1/chat", json={"query": "感冒了怎么办"})
        assert resp.json()["blocked"] is False


# ── 正常回答（放行 + 意图 + 回答）─────────────────────────────

class TestChatOk:

    def test_normal_otc_query(self, respx_mock, client):
        respx_mock.post(DEEPSEEK_URL).mock(
            side_effect=[
                safety_completion(),
                intent_completion("drug_info"),
                answer_completion("布洛芬最好饭后吃，能减少对胃的刺激。", 0.85),
            ]
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
            side_effect=[
                safety_completion(),
                intent_completion("general_health"),
                answer_completion("多喝水，注意休息。", 0.9),
            ]
        )
        resp = client.post("/api/v1/chat", json={"query": "感冒了怎么办"})
        data = resp.json()
        assert "不能替代医生或药师的建议" in data["answer"]
        assert data["disclaimer"] is not None
        assert "不能替代" in data["disclaimer"]

    def test_citations_empty_adds_no_citation_note(self, respx_mock, client):
        """无 RAG 引用、无检查结论、LLM 也没自报引用 → 代码追加查阅说明书提示。"""
        respx_mock.post(DEEPSEEK_URL).mock(
            side_effect=[
                safety_completion(),
                intent_completion("drug_info"),
                answer_completion("泰诺主要成分是对乙酰氨基酚。", 0.8, []),
            ]
        )
        resp = client.post("/api/v1/chat", json={"query": "泰诺有什么成分"})
        data = resp.json()
        assert data["citations"] == []
        assert data["sources_note"] is None
        assert "查阅原药品说明书" in data["answer"]

    def test_low_confidence_adds_uncertainty_note(self, respx_mock, client):
        """铁律 #4 代码兜底：低置信度必须显式提示"不确定 + 咨询药师"。"""
        respx_mock.post(DEEPSEEK_URL).mock(
            side_effect=[
                safety_completion(),
                intent_completion(
                    "lifestyle_interaction",
                    drug_names=["圣约翰草"],
                    lifestyle_substances=["避孕药"],
                ),
                answer_completion("也许可以一起吃吧。", 0.2),
            ]
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
            side_effect=[
                safety_completion(),
                intent_completion("drug_info"),
                answer_completion("最好饭后吃。", 0.9),
            ]
        )
        resp = client.post("/api/v1/chat", json={"query": "布洛芬能空腹吃吗"})
        data = resp.json()
        assert data["confidence"] == 0.9
        assert "把握不大" not in data["answer"]

    def test_negated_emergency_not_blocked(self, respx_mock, client):
        """否定语境不应触发安全边界（关键词 + LLM 均放行）。"""
        respx_mock.post(DEEPSEEK_URL).mock(
            side_effect=[
                safety_completion("none", 0.9),
                intent_completion("drug_info"),
                answer_completion("感冒药可以和布洛芬间隔4小时服用。", 0.7),
            ]
        )
        resp = client.post(
            "/api/v1/chat", json={"query": "我没有呼吸困难，就是想问问感冒药怎么吃"}
        )
        assert resp.json()["blocked"] is False


# ── 意图分类（任务三）────────────────────────────────────────

class TestIntentClassification:

    def test_intent_failure_degrades_to_drug_info(self, respx_mock, client):
        """意图分类三次全失败 → 降级 drug_info，/chat 仍 200（不 502）。"""
        respx_mock.post(DEEPSEEK_URL).mock(
            side_effect=[
                safety_completion(),
                make_completion("bad intent 1"),
                make_completion("bad intent 2"),
                make_completion("bad intent 3"),
                answer_completion("布洛芬饭后吃。", 0.85),
            ]
        )
        resp = client.post("/api/v1/chat", json={"query": "布洛芬怎么吃"})
        assert resp.status_code == 200
        assert resp.json()["blocked"] is False

    def test_drug_interaction_intent_retrieves_each_drug(self, respx_mock, client_seeded):
        """drug_interaction 意图：对每个药名分别检索（NullRetriever 下为空，不报错）。"""
        respx_mock.post(DEEPSEEK_URL).mock(
            side_effect=[
                safety_completion(),
                intent_completion(
                    "drug_interaction", drug_names=["泰诺", "必理通"]
                ),
                answer_completion("两种药都含对乙酰氨基酚，别一起吃。", 0.9),
            ]
        )
        resp = client_seeded.post(
            "/api/v1/chat", json={"query": "泰诺和必理通能一起吃吗"}
        )
        assert resp.status_code == 200
        assert resp.json()["blocked"] is False


# ── 药箱检查集成（任务四）────────────────────────────────────

class TestCheckIntegration:

    def test_overlap_rule_conclusion_injected_into_prompt(
        self, respx_mock, client_seeded
    ):
        """泰诺 + 必理通 → 规则引擎判定对乙酰氨基酚重复，结论注入回答 prompt。"""
        respx_mock.post(DEEPSEEK_URL).mock(
            side_effect=[
                safety_completion(),
                intent_completion(
                    "drug_interaction", drug_names=["泰诺", "必理通"]
                ),
                answer_completion(
                    "泰诺和必理通都含对乙酰氨基酚，一起吃容易超量伤肝，建议只留一种。",
                    0.9,
                    ["泰诺", "必理通"],
                ),
            ]
        )
        resp = client_seeded.post(
            "/api/v1/chat", json={"query": "泰诺和必理通能一起吃吗"}
        )
        assert resp.status_code == 200

        # 规则引擎的确定性结论（标题 + 代码填充的剂量）必须出现在发给 LLM 的 prompt 里
        prompt = last_system_prompt(respx_mock)
        assert "对乙酰氨基酚重复过量" in prompt
        assert "825" in prompt  # 325 + 500（dosage_per_day 缺省按 1 计）
        # prompt 明确要求 LLM 只翻译、不改写结论（铁律 #1）
        assert "不能" in prompt and "改写" in prompt

    def test_no_findings_reported_clean(self, respx_mock, client_seeded):
        """泰诺 + 芬必得 无共享成分 → prompt 明示未检测到风险。"""
        respx_mock.post(DEEPSEEK_URL).mock(
            side_effect=[
                safety_completion(),
                intent_completion(
                    "drug_interaction", drug_names=["泰诺", "芬必得"]
                ),
                answer_completion("这两种药成分不同，按说明书用量一般可同用。", 0.8),
            ]
        )
        resp = client_seeded.post(
            "/api/v1/chat", json={"query": "泰诺和芬必得能一起吃吗"}
        )
        assert resp.status_code == 200
        prompt = last_system_prompt(respx_mock)
        assert "未检测到" in prompt

    def test_unresolved_drug_made_explicit_in_prompt(
        self, respx_mock, client_seeded
    ):
        """未入库药品 → prompt 明示「暂未收录、无法检测」（铁律 #4）。"""
        respx_mock.post(DEEPSEEK_URL).mock(
            side_effect=[
                safety_completion(),
                intent_completion(
                    "drug_interaction", drug_names=["泰诺", "某神秘药"]
                ),
                answer_completion("泰诺可查，某神秘药暂未收录。", 0.7),
            ]
        )
        resp = client_seeded.post(
            "/api/v1/chat", json={"query": "泰诺和某神秘药能一起吃吗"}
        )
        assert resp.status_code == 200
        prompt = last_system_prompt(respx_mock)
        assert "暂未收录" in prompt
        assert "某神秘药" in prompt

    def test_findings_suppress_no_citation_note(
        self, respx_mock, client_seeded
    ):
        """有规则引擎检查结论时，即使 LLM 没自报引用，也不追加「查阅说明书」提示。"""
        respx_mock.post(DEEPSEEK_URL).mock(
            side_effect=[
                safety_completion(),
                intent_completion(
                    "drug_interaction", drug_names=["泰诺", "必理通"]
                ),
                # citations_used 为空，但有检查结论
                answer_completion("别一起吃，对乙酰氨基酚会超量。", 0.9, []),
            ]
        )
        resp = client_seeded.post(
            "/api/v1/chat", json={"query": "泰诺和必理通能一起吃吗"}
        )
        data = resp.json()
        assert "查阅原药品说明书" not in data["answer"]

    def test_lifestyle_substance_rule_injected(self, respx_mock, client_seeded):
        """lifestyle_interaction：芬必得 + 酒精 → 布洛芬酒精规则注入 prompt。"""
        respx_mock.post(DEEPSEEK_URL).mock(
            side_effect=[
                safety_completion(),
                intent_completion(
                    "lifestyle_interaction",
                    drug_names=["芬必得"],
                    lifestyle_substances=["酒精"],
                ),
                answer_completion("吃芬必得别喝酒，会伤胃。", 0.9, ["芬必得"]),
            ]
        )
        resp = client_seeded.post(
            "/api/v1/chat", json={"query": "吃芬必得能喝酒吗"}
        )
        assert resp.status_code == 200
        prompt = last_system_prompt(respx_mock)
        assert "布洛芬" in prompt and "酒精" in prompt


# ── 错误处理 ────────────────────────────────────────────────

class TestChatErrors:

    def test_empty_query(self, client):
        resp = client.post("/api/v1/chat", json={"query": ""})
        assert resp.status_code == 422

    def test_query_too_long(self, client):
        resp = client.post("/api/v1/chat", json={"query": "x" * 2001})
        assert resp.status_code == 422

    def test_llm_retry_exhausted_on_answer(self, respx_mock, client):
        """safety / intent 正常，回答阶段三次全坏 JSON → 502。"""
        respx_mock.post(DEEPSEEK_URL).mock(
            side_effect=[
                safety_completion(),
                intent_completion("drug_info"),
                make_completion("bad json 1"),
                make_completion("bad json 2"),
                make_completion("bad json 3"),
            ]
        )
        resp = client.post("/api/v1/chat", json={"query": "布洛芬用法"})
        assert resp.status_code == 502
        assert "不可用" in resp.json()["detail"]

    def test_llm_validation_error_retry_succeeds(self, respx_mock, client):
        """回答阶段首次缺字段 → retry → 成功。"""
        respx_mock.post(DEEPSEEK_URL).mock(
            side_effect=[
                safety_completion(),
                intent_completion("drug_info"),
                make_completion('{"foo": 1}'),
                make_completion('{"answer": "没问题", "confidence": 0.6}'),
            ]
        )
        resp = client.post("/api/v1/chat", json={"query": "布洛芬怎么吃"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["blocked"] is False
        assert "没问题" in data["answer"]

    def test_safety_llm_failure_degrades_not_502(self, respx_mock, client):
        """safety LLM 三次全失败 → 降级放行，后续正常回答，不 502。"""
        respx_mock.post(DEEPSEEK_URL).mock(
            side_effect=[
                make_completion("bad safety 1"),
                make_completion("bad safety 2"),
                make_completion("bad safety 3"),
                intent_completion("drug_info"),
                answer_completion("布洛芬饭后吃。", 0.85),
            ]
        )
        resp = client.post("/api/v1/chat", json={"query": "布洛芬怎么吃"})
        assert resp.status_code == 200
        assert resp.json()["blocked"] is False
