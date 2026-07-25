"""共享测试 fixtures。"""

import httpx
import pytest

from app.config import DEFAULT_MODEL, Settings
from app.llm.providers import PROVIDER_PRESETS

# respx 拦截的目标 URL——改造后 llm_base_url 默认值为空字符串（由 provider preset
# 解析），从 preset 推导以保持与默认厂牌一致，避免硬编码。
DEEPSEEK_BASE_URL = PROVIDER_PRESETS["deepseek"].default_base_url
DEEPSEEK_URL = f"{DEEPSEEK_BASE_URL}/chat/completions"

# _env_file=None：测试配置不得读取仓库 .env，保证套件与开发机环境无关。
TEST_SETTINGS_KWARGS: dict = {"deepseek_api_key": "test-key", "_env_file": None}
_TEST_SETTINGS = Settings(**TEST_SETTINGS_KWARGS)


@pytest.fixture
def settings() -> Settings:
    """默认测试配置（api_key 用占位值，不读 .env，避免真实网络）。"""
    return Settings(**TEST_SETTINGS_KWARGS)


def make_completion(content: str, usage: dict | None = None) -> httpx.Response:
    """构造一个 OpenAI 兼容的 chat.completion HTTP 响应。"""
    body = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1,
        "model": DEFAULT_MODEL,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": usage
        or {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }
    return httpx.Response(200, json=body)


# ── 样例说明书（国标章节格式），供 parser / ingest 测试复用 ──────────────

SAMPLE_INSERT_TAINUO = """【药品名称】
通用名称：酚麻美敏片
商品名称：泰诺
【成份】
本品为复方制剂，每片含对乙酰氨基酚325毫克，盐酸伪麻黄碱30毫克，氢溴酸右美沙芬15毫克，马来酸氯苯那敏2毫克。
【适应症】
用于缓解普通感冒及流行性感冒引起的发热、头痛、四肢酸痛、鼻塞、流涕、咳嗽等症状。
【规格】
复方
【用法用量】
口服。成人一次1-2片，一日3次。
【不良反应】
偶见困倦、口干、多汗、恶心等。
【禁忌】
严重肝肾功能不全者禁用。
【注意事项】
用药期间不得饮酒或含酒精饮料。
【药物相互作用】
与其他解热镇痛药同用可增加肾毒性。
【批准文号】
国药准字H10920001"""

SAMPLE_INSERT_FENBIDE = """【药品名称】
通用名称：布洛芬缓释胶囊
商品名称：芬必得
【成份】
本品每粒含布洛芬0.3克。
【适应症】
用于缓解轻至中度疼痛如头痛、关节痛、偏头痛、牙痛、肌肉痛、神经痛、痛经。
【用法用量】
口服。成人一次1粒，一日2次。
【不良反应】
可见恶心、胃烧灼感、消化不良等。
【禁忌】
对布洛芬过敏者禁用。
【注意事项】
服用期间不得饮酒。
【药物相互作用】
与阿司匹林同用可能降低其抗血小板作用。"""

