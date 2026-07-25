# app/prompts/chat.py 结构拆分实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `app/prompts/chat.py` 的模板文案 / 格式化函数 / 组装逻辑拆成三处，删除历史兼容层，prompt 渲染输出逐字不变。

**Architecture:** 新建 `app/prompts/templates/chat_system.py`（4 个文案常量）与 `app/prompts/formatters.py`（两个 format_* 函数），chat.py 只剩 `build_system_prompt` / `build_chat_messages` 组装逻辑；兼容层（intent 再导出 + 死常量 `SYSTEM_PROMPT_TEMPLATE`）删除，调用方改从规范位置导入。这是纯结构重构而非新功能——**不存在"先写失败测试"环节**：现有 14 个 golden 测试 + 320 条套件就是守门员，每个 Task 的门槛是"移动后依然全绿"，golden 变红 = 行为改变 = 回滚该 Task。

**Tech Stack:** Python 3.12，pytest + pytest-cov，git（每 Task 一个 commit）。

## Global Constraints

- 所有 prompt 渲染输出**逐字不变**；**严禁 `PILLCLEAR_REGEN_GOLDEN=1`** 重新生成 golden——变红即回滚
- pytest 通过数恒为 **320**（不增不减）；`app/prompts` 覆盖率保持 **100%**
- 不得改动任何 prompt 文案措辞——**一个标点都不行**；新增代码仅限：常量名、docstring、import 行、两个新文件
- `safety.py` 的 5 条锁定现状（发热正则窗口等）与本次零交集，不碰
- `tests/golden/` 内容文件不碰；除 `app/prompts/` 及其调用方（`app/chat/pipeline.py`、`tests/test_prompts.py`、`tests/test_prompts_golden.py`、`app/prompts/__init__.py`）外不改任何文件
- 每 Task 结尾跑全量 `python -m pytest -q`，确认 `320 passed` 后再 commit
- **原子性约束**：`app/prompts/__init__.py` 自身从 chat.py 导入符号——chat.py 删任一导出的 Task 必须与 `__init__.py` 联动同 commit

## 文件结构

| 文件 | 状态 | 职责 |
|---|---|---|
| `app/prompts/templates/__init__.py` | 新建 | 模板包，仅 docstring |
| `app/prompts/templates/chat_system.py` | 新建 | `/chat` 系统提示词静态骨架：4 个文案常量 |
| `app/prompts/formatters.py` | 新建 | 引用 / 检查报告 → prompt 文本块的格式化函数 |
| `app/prompts/chat.py` | 改 | 只剩 `build_system_prompt` / `build_chat_messages` 组装逻辑 |
| `app/prompts/__init__.py` | 改 | 包级 API 不变；`format_*` 换源；删 `SYSTEM_PROMPT_TEMPLATE` |
| `app/chat/pipeline.py` | 改 | `format_check_report_for_prompt` 换源（1 处 import） |
| `tests/test_prompts.py` | 改 | import 换源（format_* → formatters；intent 三符号 → intent） |
| `tests/test_prompts_golden.py` | 改 | 两个 format_* 换源 formatters |

---

### Task 0: 删除死常量 SYSTEM_PROMPT_TEMPLATE

**Files:**
- Modify: `app/prompts/chat.py`（尾部别名定义）
- Modify: `app/prompts/__init__.py`（导入 + `__all__`）

**Interfaces:**
- Consumes: 无
- Produces: chat.py 不再导出 `SYSTEM_PROMPT_TEMPLATE`（全仓零消费者，已核实）

- [ ] **Step 1: 删除 chat.py 尾部别名**

删除 `app/prompts/chat.py` 末尾这两行（文件最后两行）：

```python
# 兼容旧代码的常量：不带 RAG 上下文的基础 system prompt
SYSTEM_PROMPT_TEMPLATE = _SYSTEM_ROLE_AND_RULES
```

- [ ] **Step 2: 同步 __init__.py（原子性约束）**

`app/prompts/__init__.py` 中删除两处：

导入块改为（删掉 `SYSTEM_PROMPT_TEMPLATE,` 一行）：

```python
from app.prompts.chat import (
    build_chat_messages,
    build_system_prompt,
    format_citations_for_prompt,
    format_check_report_for_prompt,
)
```

`__all__` 改为（删掉 `"SYSTEM_PROMPT_TEMPLATE",` 一行）：

```python
__all__ = [
    "IntentCategory",
    "IntentResult",
    "build_chat_messages",
    "build_intent_messages",
    "build_system_prompt",
    "format_citations_for_prompt",
    "format_check_report_for_prompt",
    "INGREDIENT_SYSTEM_PROMPT",
    "SAFETY_CLASSIFY_SYSTEM_PROMPT",
    "SafetyLLMResult",
    "build_safety_messages",
]
```

- [ ] **Step 3: 验证全绿**

Run: `python -m pytest -q`
Expected: `320 passed`

- [ ] **Step 4: Commit**

```bash
git add app/prompts/chat.py app/prompts/__init__.py
git commit -m "refactor(prompts): 删除零消费者的兼容常量 SYSTEM_PROMPT_TEMPLATE"
```

---

### Task 1: 模板骨架外置到 templates/chat_system.py

**Files:**
- Create: `app/prompts/templates/__init__.py`
- Create: `app/prompts/templates/chat_system.py`
- Modify: `app/prompts/chat.py`（删常量定义、改导入、改 build_system_prompt 内联拼接）

**Interfaces:**
- Consumes: 无
- Produces: `app.prompts.templates.chat_system` 导出 `_SYSTEM_ROLE_AND_RULES`、`RAG_SECTION_HEADER`、`CHECK_SECTION_HEADER`、`CHECK_RELAY_REQUIREMENTS`（字符串常量，值与现有渲染逐字一致）

- [ ] **Step 1: 创建 templates 包**

`app/prompts/templates/__init__.py`：

```python
"""Prompt 模板文案（静态骨架）。

纯文案集中于此；组装逻辑在 app/prompts/chat.py，格式化函数在 app/prompts/formatters.py。
"""
```

- [ ] **Step 2: 创建 chat_system.py（文案逐字搬运）**

`app/prompts/templates/chat_system.py`——常量值必须与现有 `chat.py` 渲染逐字一致（golden 守门）：

```python
"""/chat 系统提示词的静态骨架：角色规则 + 章节脚手架。

文案逐字即产品行为：tests/test_prompts_golden.py + tests/golden/ 逐字锁定渲染结果。
有意修改文案后，才可用 PILLCLEAR_REGEN_GOLDEN=1 重新生成 golden（需 commit 说明改动）。
"""

# 固定角色与规则（不带 RAG 上下文的基础 system prompt）
_SYSTEM_ROLE_AND_RULES = (
    "你是 PillClear，一个面向 18-30 岁年轻人的 OTC 用药安全助手。\n"
    "你的任务是把药品说明书「翻译」成大白话，帮用户看懂怎么吃药、有没有冲突。\n\n"
    "## 你的风格\n"
    "- 口语化、简短直接，像懂药学的好朋友在聊天，但该严肃的时候要严肃。\n"
    "- 用「你」不用「您」，不要官腔，不要长篇医学论述。\n"
    "- 安全提示（过量风险、禁忌、就医建议）必须醒目，用 ⚠️ 开头。\n\n"
    "## 能力边界（严格遵守）\n"
    "- 只聊 OTC 非处方药和保健品，涉及处方药请引导用户咨询医生/药师。\n"
    "- 不诊断疾病、不解读症状和检查报告——这是医生的事。\n"
    "- 如果用户描述紧急情况（严重过敏、呼吸困难、剧烈胸痛等），立刻提醒就医，不要只靠吃药。\n"
    "- 孕妇、哺乳期、儿童、慢病患者的问题，说明「我没法给个性化建议，请咨询医生」。\n\n"
    "## 引用规则（最重要的一条！）\n"
    "- 回答用药问题必须基于下方「参考说明书原文」的内容。\n"
    "- 引用原文时用「根据 XX 的说明书」「说明书【不良反应】部分提到」这样的表述。\n"
    "- 如果下方没有相关原文，你必须在回答中说明「根据我目前掌握的说明书资料，没有查到相关信息」，"
    "然后在 confidence 中体现不确定性。\n"
    "- 绝对不能编造说明书没有的内容。\n\n"
    "## 输出格式\n"
    "严格输出 JSON，不要任何额外文字：\n"
    '{"answer": "大白话回答", "confidence": 0.0~1.0 的置信度, '
    '"citations_used": ["引用了的药品名列表"]}'
)

# RAG 上下文章节标题（接在 _SYSTEM_ROLE_AND_RULES 与引用文本块之间）
RAG_SECTION_HEADER = "\n\n## 参考说明书原文（回答必须基于以下内容）\n\n"

# 检查结论槽位标题（接在引用文本块与 check_context 之间）
CHECK_SECTION_HEADER = "\n\n## 检查结果（来自确定性规则引擎）\n\n"

# 检查结论的传达要求（接在 check_context 之后，铁律 #1：LLM 只翻译不改写）
CHECK_RELAY_REQUIREMENTS = (
    "\n\n## 检查结论的传达要求（必须遵守）\n"
    "- 上面的检查结论由确定性规则引擎给出，你只能把它翻译成大白话，"
    "绝对不能自行判断、否定或改写这个结论。\n"
    "- 保留其中的安全提示（⚠️ 部分）与「咨询药师」建议，语气可以口语化，"
    "但严重性不打折。\n"
    "- 在 citations_used 中列出本次涉及的药品名。"
)
```

- [ ] **Step 3: 改造 chat.py**

3a. 删除 `chat.py` 中 `_SYSTEM_ROLE_AND_RULES = (...)` 整个定义及其上方两行注释（`# 系统提示词模板。{rag_context} 由 build_system_prompt() 注入。` / `# 分为两部分：固定角色/规则 + 动态 RAG 上下文。`）。

3b. 在 chat.py 导入区加入（位于 `if TYPE_CHECKING:` 块之前）：

```python
from app.prompts.templates.chat_system import (
    CHECK_RELAY_REQUIREMENTS,
    CHECK_SECTION_HEADER,
    RAG_SECTION_HEADER,
    _SYSTEM_ROLE_AND_RULES,
)
```

3c. `build_system_prompt` 函数体替换为（文案常量替代内联字符串，拼接结果逐字不变）：

```python
def build_system_prompt(
    citations: list[Citation] | None = None,
    check_context: str | None = None,
) -> str:
    """构造完整的 system prompt：角色 + 规则 + RAG 上下文 +（可选）检查结论。

    citations 为 None 或空列表时，提示中说明无原文可用。
    check_context 非 None 时（任务四：意图为药-药 / 药-物质相互作用），追加规则引擎结论槽位，
    并明确要求 LLM 只翻译、不改写确定性结论（铁律 #1）。
    """
    rag_context = format_citations_for_prompt(citations or [])
    prompt = _SYSTEM_ROLE_AND_RULES + RAG_SECTION_HEADER + rag_context
    if check_context:
        prompt += CHECK_SECTION_HEADER + check_context + CHECK_RELAY_REQUIREMENTS
    return prompt
```

（函数签名与 docstring 保持不变。）

- [ ] **Step 4: 验证全绿（golden 是本步主考）**

Run: `python -m pytest -q`
Expected: `320 passed`——尤其 `tests/test_prompts_golden.py` 的 `TestSystemPromptGolden` 4 条必须绿；变红说明常量搬运有字符漂移，`git checkout -- app/prompts/` 回滚重搬。

- [ ] **Step 5: Commit**

```bash
git add app/prompts/templates/ app/prompts/chat.py
git commit -m "refactor(prompts): 系统提示词静态骨架外置到 templates/chat_system.py"
```

---

### Task 2: format_* 迁移到 formatters.py（含调用方与 __init__ 换源）

**Files:**
- Create: `app/prompts/formatters.py`
- Modify: `app/prompts/chat.py`（删两个函数定义、加导入、删 TYPE_CHECKING 的 CheckReport）
- Modify: `app/prompts/__init__.py`（format_* 换源——原子性约束）
- Modify: `app/chat/pipeline.py:29-32`
- Modify: `tests/test_prompts.py:15-23`
- Modify: `tests/test_prompts_golden.py:20-24`

**Interfaces:**
- Consumes: 无（纯移动）
- Produces: `app.prompts.formatters` 导出 `format_citations_for_prompt(citations: list[Citation]) -> str` 与 `format_check_report_for_prompt(report: CheckReport) -> str`；`app.prompts.chat` 不再导出二者

- [ ] **Step 1: 创建 formatters.py（函数体逐字搬运）**

`app/prompts/formatters.py`：

```python
"""Prompt 格式化函数：把引用 / 检查报告渲染成 prompt 文本块。

铁律 #1：检查结论由规则引擎产出，LLM 只负责翻译成大白话，不得改写结论。
铁律 #4：unresolved_drugs 非空时必须明示「暂未收录、无法检测」，不得静默忽略。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.knowledge.schemas import Citation
    from app.medbox.schemas import CheckReport


def format_citations_for_prompt(citations: list[Citation]) -> str:
    """将检索到的引用格式化为 prompt 可用的文本块。

    每个引用包含药品名、章节名、原文摘录，按药品分组。
    空引用返回提示性文本。
    """
    if not citations:
        return "（未检索到相关说明书原文，请基于你的知识回答，但必须在 confidence 中反映不确定性——最高不超过 0.5）"

    lines: list[str] = []
    # 按商品名分组
    by_brand: dict[str, list[Citation]] = {}
    for c in citations:
        by_brand.setdefault(c.brand_name, []).append(c)

    for brand_name, refs in by_brand.items():
        lines.append(f"### {brand_name}")
        for r in refs:
            lines.append(f"- 【{r.section}】{r.excerpt}")
        lines.append("")

    return "\n".join(lines)


def format_check_report_for_prompt(report: CheckReport) -> str:
    """将确定性规则引擎的 CheckReport 格式化为 prompt 上下文。

    铁律 #1：检查结论由规则引擎产出，LLM 只负责翻译成大白话，不得改写结论。
    铁律 #4：unresolved_drugs 非空时必须明示「暂未收录、无法检测」，不得静默忽略。

    返回文本供 build_system_prompt(check_context=...) 注入检查槽位；
    即使「无风险」也返回说明性文本，让 LLM 能如实转达「未检测到风险」。
    """
    lines: list[str] = []

    # 未收录药品：最高优先明示（铁律 #4）
    if report.unresolved_drugs:
        lines.append(
            "以下药品暂未收录，无法检测其成分与相互作用："
            + "、".join(report.unresolved_drugs)
            + "。请在回答中明确告知用户这些药暂时查不到，建议咨询药师。"
        )

    # 规则引擎触发的冲突规则（确定性结论，必须原样传达）
    if report.triggered_rules:
        lines.append("规则引擎检测到以下风险（确定性结论，必须原样传达，不得否定或改写）：")
        for rule in report.triggered_rules:
            lines.append(f"- 【{rule.severity}｜{rule.title}】{rule.warning}")

    # 成分叠加超限警告（纯代码计算结果，铁律 #1）
    if report.overlap.warnings:
        lines.append("成分叠加超限警告（代码计算，必须传达）：")
        for warning in report.overlap.warnings:
            lines.append(f"- {warning}")

    # 共享成分信息（帮助 LLM 说明「哪几种药共享什么成分」）
    shared = [
        t
        for t in report.overlap.overlapping
        if len(t.sources) >= 2
    ]
    if shared:
        lines.append("被多种药品共享的成分（叠加来源）：")
        for t in shared:
            lines.append(
                f"- {t.name}：来自 {'、'.join(t.sources)}，"
                f"每日合计约 {t.total_amount_mg}mg"
            )

    if not lines:
        return "规则引擎未检测到成分叠加或已知相互作用。请如实告知用户目前未检测到风险，但仍提醒按说明书用量服用。"

    return "\n".join(lines)
```

- [ ] **Step 2: 改造 chat.py**

2a. 删除 `format_citations_for_prompt` 与 `format_check_report_for_prompt` 两个函数定义，连同各自的装饰性 banner 注释块（`# ═══...` 三行 × 2）。

2b. 导入区加入（与 Task 1 的 templates 导入并列）：

```python
from app.prompts.formatters import format_citations_for_prompt
```

2c. `TYPE_CHECKING` 块只保留 `Citation`（`CheckReport` 已随函数迁走）：

```python
if TYPE_CHECKING:
    from app.knowledge.schemas import Citation
```

- [ ] **Step 3: __init__.py 换源（原子性约束，同 commit）**

`app/prompts/__init__.py` 导入区改为：

```python
from app.prompts.chat import (
    build_chat_messages,
    build_system_prompt,
)
from app.prompts.formatters import (
    format_citations_for_prompt,
    format_check_report_for_prompt,
)
```

（`__all__` 不动；intent / safety / ingest 的导入不动。）

- [ ] **Step 4: 调用方换源**

`app/chat/pipeline.py` 导入改为：

```python
from app.prompts.chat import build_chat_messages
from app.prompts.formatters import format_check_report_for_prompt
```

`tests/test_prompts.py` 导入改为（intent 三符号暂留 chat，Task 3 处理）：

```python
from app.prompts.chat import (
    IntentCategory,
    IntentResult,
    build_chat_messages,
    build_intent_messages,
    build_system_prompt,
)
from app.prompts.formatters import (
    format_citations_for_prompt,
    format_check_report_for_prompt,
)
```

`tests/test_prompts_golden.py` 导入改为：

```python
from app.prompts.chat import build_system_prompt
from app.prompts.formatters import (
    format_check_report_for_prompt,
    format_citations_for_prompt,
)
```

- [ ] **Step 5: 验证全绿**

Run: `python -m pytest -q`
Expected: `320 passed`——golden 的 `TestCitationsFormatGolden` / `TestCheckReportFormatGolden` 与 `test_prompts.py` 的 `TestFormatCitations` / `TestFormatCheckReport` 必须绿。变红 = 函数体搬运有漂移，回滚本 Task 全部改动重搬。

- [ ] **Step 6: Commit**

```bash
git add app/prompts/formatters.py app/prompts/chat.py app/prompts/__init__.py app/chat/pipeline.py tests/test_prompts.py tests/test_prompts_golden.py
git commit -m "refactor(prompts): format_* 迁移到 formatters.py，调用方换源"
```

---

### Task 3: 删除 intent 再导出 + 覆盖率终检

**Files:**
- Modify: `app/prompts/chat.py`（删再导出块、更新 docstring）
- Modify: `tests/test_prompts.py`（intent 三符号换源）

**Interfaces:**
- Consumes: Task 2 完成态
- Produces: `app.prompts.chat` 的最终导出面 = `build_system_prompt` / `build_chat_messages`（+ 从 templates/formatters 的导入）；`app.prompts.chat` 不再导出任何 intent 符号

- [ ] **Step 1: 删除 chat.py 的 intent 再导出块**

删除 chat.py 顶部这两段：

```python
# 向后兼容再导出：意图分类定义已迁入 app/prompts/intent.py
from app.prompts.intent import (  # noqa: F401
    IntentCategory,
    IntentResult,
    build_intent_messages,
)
```

- [ ] **Step 2: 更新 chat.py 模块 docstring**

chat.py 头部 docstring 改为（原末段描述的再导出已不存在）：

```python
"""聊天提示词组装：系统角色 + RAG 上下文注入 + 检查结论槽位。

铁律 #2：所有用药相关回答必须携带说明书原文引用（citations_used 非空）。
铁律 #3/#4：能力边界与不确定原则写进 prompt，代码层再做兜底。

静态模板文案在 app/prompts/templates/chat_system.py；
格式化函数在 app/prompts/formatters.py；意图分类在 app/prompts/intent.py。
"""
```

- [ ] **Step 3: test_prompts.py intent 符号换源**

`tests/test_prompts.py` 导入区最终形态：

```python
from app.prompts.chat import (
    build_chat_messages,
    build_system_prompt,
)
from app.prompts.formatters import (
    format_citations_for_prompt,
    format_check_report_for_prompt,
)
from app.prompts.intent import (
    IntentCategory,
    IntentResult,
    build_intent_messages,
)
```

- [ ] **Step 4: 验证全绿**

Run: `python -m pytest -q`
Expected: `320 passed`

- [ ] **Step 5: 覆盖率终检**

Run: `python -m pytest --cov=app.prompts --cov-report=term-missing -q`
Expected: `app.prompts` 全部模块（含新增 `templates/chat_system.py`、`formatters.py`）100%，`TOTAL ... 0` missing；`320 passed`。

- [ ] **Step 6: diff 终检**

Run: `git diff fe266e3..HEAD --stat` 确认改动文件恰为计划内 8 个（templates/ 2 个新建 + chat.py + __init__.py + pipeline.py + 2 个测试 + formatters.py），无其他文件。抽查 `git diff fe266e3..HEAD -- app/prompts/formatters.py` 与原 chat.py 对应函数逐字一致（除 docstring 位置）。

- [ ] **Step 7: Commit**

```bash
git add app/prompts/chat.py tests/test_prompts.py
git commit -m "refactor(prompts): 删除 chat.py 的 intent 兼容再导出，调用方直连 intent 模块"
```

---

## 收尾

- 对照 `docs/refactor-readiness.md` 周期 1 清单逐项打勾（通过数 ≥320 / golden 全绿 / 包级 API 不变 / 覆盖率 100%）
- 若后续会话要恢复省 token 设置：`skillOverrides` 加回 `"pillclear-safety-review": "user-invocable-only"`（与本次重构无关，但属同期临时改动）
