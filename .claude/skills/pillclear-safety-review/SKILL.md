---
name: pillclear-safety-review
description: Safety boundary and citation compliance checklist for changes to app/core/safety.py, app/api/routes.py, or the /chat pipeline. Use before committing any change that touches the safety layer or API response path. Triggers: "安全边界", "safety review", "处方药", "特殊人群", "引用检查", and can be auto-triggered via pre-commit hook.
---

# PillClear 安全审查

本 skill 确保对 `app/core/safety.py` 和 API 层的任何改动不会引入安全边界回归。

## 一、触发条件

当变更涉及以下文件时，必须执行本审查：

- `app/core/safety.py` — 能力边界关键词/分类逻辑
- `app/api/routes.py` — `/chat` 端点的安全步骤和免责声明
- `app/chat/pipeline.py` — 编排管线中的 safety step
- `app/prompts/safety.py` — LLM 安全分类 prompt
- `app/core/units.py` — 剂量归一化（错误可导致误报/漏报）

## 二、安全边界回归检查

### 2.1 五大分类优先级

检测优先级（`safety.py`）：**急症 > 特殊人群 > 诊断 > 处方药 > 放行**

每项必须验证：

| 类别 | 触发词示例 | 预期行为 | 验证方式 |
|------|-----------|----------|----------|
| **急症** | "高热不退"、"呼吸困难"、"严重过敏" | 立即提示就医，不继续分析 | `tests/test_safety.py::TestEmergency` |
| **特殊人群** | "孕妇"、"哺乳期"、"儿童"、"3岁宝宝" | 拒绝个性化建议，引导咨询医生 | `tests/test_safety.py::TestSpecialPopulation` |
| **诊断** | "我得了XX病"、"这是什么病" | 不提供诊断，引导就医 | `tests/test_safety.py::TestDiagnosis` |
| **处方药** | "头孢"、"阿莫西林"、"降压药" | 不提供处方药建议，引导就医/药师 | `tests/test_safety.py::TestPrescription` |
| **放行** | "感冒药怎么吃"、"布洛芬间隔多久" | 放行进入后续管线 | `tests/test_safety.py::TestPassThrough` |

### 2.2 关键词表更新约束

修改 `safety.py` 中的关键词表时确认：

- [ ] 新增关键词不会错误拦截 OTC 正常咨询（误报）
- [ ] 新增关键词的同类表达也已覆盖（如"怀孕"+"孕妇"+"备孕"）
- [ ] 否定检测仍然有效：`"我没有呼吸困难"` → 不触发急症（`_has_negation`）
- [ ] 子类关键词（如"宝宝发烧"）仍能正确分类为特殊人群
- [ ] 关键字匹配和 LLM 补漏的结论一致（防止两套逻辑互相矛盾）

### 2.3 LLM 补漏层约束

`_classify_boundary_with_llm()` 仅在关键词检查通过后调用（作为第二道防线）。约束：
- [ ] LLM 分类失败 → 降级为 NONE（放行），不能误杀
- [ ] LLM 返回的固定话术必须与 `_BOUNDARY_RESPONSES` 一致（不能自由发挥）
- [ ] `SafetyLLMResult` 模型字段（category / confidence）未被移除或改名

## 三、引用强制检查

**铁律：所有用药相关回答必须携带说明书原文引用。**

- [ ] `/chat` 管线 step 7：无引用时代码级追加"未找到相关说明书引用"提示
- [ ] `LLMAnswer.citations_used` 字段未被移除
- [ ] 低置信度（<0.5）+ 无引用 → 两条提示都追加，不互相覆盖
- [ ] 检索失败（KeywordRetriever 降级空引用）→ 不抛异常，不中断 /chat

## 四、免责声明检查

- [ ] `routes.py::_DISCLAIMER` 文案未被移除或截断
- [ ] 免责声明由代码追加（`_append_disclaimer`），不依赖 LLM prompt
- [ ] 安全阻断（急症/特殊人群/诊断/处方药）的固定话术中不含免责声明（阻断消息和免责声明是两回事）

## 五、API 端点回退检查

- [ ] `LLMRetryExhausted` → HTTP 502，"AI service temporarily unavailable"
- [ ] 意图分类失败 → 降级 `drug_info`，不中断用户请求
- [ ] RAG 检索异常 → 降级空引用，不中断用户请求
- [ ] Safety LLM 异常 → 降级关键词结果，不中断用户请求

## 六、审查执行

```bash
# 全量安全相关测试
pytest tests/test_safety.py tests/test_api_chat.py -v

# 仅跑安全边界回归
pytest tests/test_safety.py -v

# 仅跑 /chat 端到端（含引用和免责声明验证）
pytest tests/test_api_chat.py -v -k "safety or disclaimer or citation"
```

## 七、自动化

项目的 `.claude/settings.json` 已配置 PostToolUse hook：修改 `app/core/safety.py` 或 `app/rules/` 下任一文件 → 自动执行 `pytest tests/ -x`。安全相关改动会自动触发测试，无需额外配置。
