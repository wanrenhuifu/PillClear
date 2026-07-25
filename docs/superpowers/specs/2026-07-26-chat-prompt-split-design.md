# app/prompts/chat.py 结构拆分设计

> 2026-07-26 · 纯结构重构：行为逐字不变，golden 测试守门
> 验收依据：`docs/refactor-readiness.md` 周期 1 清单（随本文档同步修订两处）

## 目标

把 `app/prompts/chat.py` 混杂的三件事拆开：**prompt 模板文案** → `templates/`；**格式化函数** → `formatters.py`；**组装逻辑** → 留在 `chat.py`。同时移除历史兼容层（intent 再导出 + 死常量 `SYSTEM_PROMPT_TEMPLATE`）。

行为完全不变：所有 prompt 渲染输出逐字一致，`tests/golden/` 14 个黄金文件不许重新生成。本次不修任何文案（一个标点），不碰 `safety.py` 的 5 条锁定现状。

## 已确认决策

1. **模板载体 = Python 模板模块**：`app/prompts/templates/*.py` 字符串常量。无新 I/O、无打包风险（`app*` 匹配进 wheel）、diff 是纯代码搬迁。否决 `.txt + loader`（新行为面 + `.txt` 不进 wheel，修 `package_data` 又违反「不改其他文件」铁约束）。
2. **粒度 = 只移静态骨架**：`_SYSTEM_ROLE_AND_RULES` + `build_system_prompt` 的 3 段内联脚手架。formatters 的微型文案（未检索到降级句、无风险句、`- 【{severity}｜{title}】{warning}` 行格式）与转换逻辑绞合，留在 `formatters.py`。
3. **formatters = 干净移动**：`format_*` 只存在于 `app/prompts/formatters.py`；调用方一律从规范位置导入；`chat.py` 不留兼容再导出；包级 API（`app/prompts/__init__.py`）保持不变。
4. **`SYSTEM_PROMPT_TEMPLATE` = 删除**：全仓零消费者（仅 `__init__.py` 再导出）。

## 目标布局

```
app/prompts/
├── __init__.py          # 包级 API 不变；format_* 换源 formatters；删 SYSTEM_PROMPT_TEMPLATE
├── templates/
│   ├── __init__.py      # 新建，仅模块 docstring
│   └── chat_system.py   # 4 个常量（文案逐字搬，不改一字）
├── formatters.py        # format_citations_for_prompt + format_check_report_for_prompt
├── chat.py              # 只剩 build_system_prompt / build_chat_messages + 导入
├── intent.py            # 不动
├── safety.py            # 不动
└── ingest.py            # 不动
```

`pyproject.toml` 无需改动：`[tool.setuptools.packages.find] include = ["app*"]` 已覆盖 `app.prompts.templates`（这也是选 .py 模块而非 .txt 的原因之一）。

## 符号归属

| 符号 | 原位置 | 去向 |
|---|---|---|
| `_SYSTEM_ROLE_AND_RULES` | chat.py 常量 | `templates/chat_system.py`，**保持原名**（包内私有，chat.py 跨模块引用属包内协作） |
| `"\n\n## 参考说明书原文（回答必须基于以下内容）\n\n"` | build_system_prompt 内联 | `templates/chat_system.py: RAG_SECTION_HEADER` |
| `"\n\n## 检查结果（来自确定性规则引擎）\n\n"` | build_system_prompt 内联 | `templates/chat_system.py: CHECK_SECTION_HEADER` |
| 检查结论传达要求段（`"\n\n## 检查结论的传达要求（必须遵守）\n- 上面的检查结论……列出本次涉及的药品名。"`） | build_system_prompt 内联 | `templates/chat_system.py: CHECK_RELAY_REQUIREMENTS` |
| `format_citations_for_prompt` | chat.py | `formatters.py`，函数体逐字不动 |
| `format_check_report_for_prompt` | chat.py | `formatters.py`，函数体逐字不动 |
| `build_system_prompt` / `build_chat_messages` | chat.py | chat.py 保留 |
| `IntentCategory` / `IntentResult` / `build_intent_messages` 再导出块 | chat.py 顶部 | **删除** |
| `SYSTEM_PROMPT_TEMPLATE` 别名 | chat.py 尾部 | **删除** |

常量名是新代码；常量值（文案）逐字不变。

搬迁后 `build_system_prompt` 的组装形态（字符串拼接满足结合律，渲染结果逐字不变）：

```python
def build_system_prompt(citations=None, check_context=None):
    rag_context = format_citations_for_prompt(citations or [])
    prompt = _SYSTEM_ROLE_AND_RULES + RAG_SECTION_HEADER + rag_context
    if check_context:
        prompt += CHECK_SECTION_HEADER + check_context + CHECK_RELAY_REQUIREMENTS
    return prompt
```

**类型导入随函数迁移**：`formatters.py` 带走 `TYPE_CHECKING` 下的 `Citation`（`app.knowledge.schemas`）与 `CheckReport`（`app.medbox.schemas`）；chat.py 的 `TYPE_CHECKING` 仅保留 `Citation`（`build_*` 签名仍在用），删除 `CheckReport`。

## 调用方迁移清单

| 文件 | 改动 | 所在步骤 |
|---|---|---|
| `app/prompts/__init__.py` | 删 `SYSTEM_PROMPT_TEMPLATE` 导入 + `__all__` 条目 | 步骤 0（与 chat.py 删别名原子） |
| `app/prompts/__init__.py` | `format_*` 换源 `app.prompts.formatters` | 步骤 2（与 chat.py 删定义原子） |
| `app/chat/pipeline.py:29-32` | `format_check_report_for_prompt` 换源 `app.prompts.formatters`；`build_chat_messages` 留原处 | 步骤 2 |
| `tests/test_prompts.py:15-23` | 两个 `format_*` 换源 formatters | 步骤 2 |
| `tests/test_prompts.py:16-19` | `IntentCategory` / `IntentResult` / `build_intent_messages` 换源 `app.prompts.intent` | 步骤 3 |
| `tests/test_prompts_golden.py:20-24` | 两个 `format_*` 换源 formatters；`build_system_prompt` 留原处 | 步骤 2 |
| `app/chat/pipeline.py` 的 intent 导入 | 无改动（本就直连 `app.prompts.intent`） | — |

**原子性约束（排期依据）**：`__init__.py` 自身就是 chat.py 导出的调用方——chat.py 删除任一导出的那一步，`__init__.py` 必须在同一 commit 联动，否则中间态 ImportError。

## 实施序列（一步一 commit，步步绿）

| 步 | 动作 | 门槛 |
|---|---|---|
| **0** | chat.py 删 `SYSTEM_PROMPT_TEMPLATE` 别名；`__init__.py` 同步删导入与 `__all__` 条目 | 全量 pytest 320 绿 |
| **1** | 新建 `templates/__init__.py` + `templates/chat_system.py`（4 常量逐字搬）；chat.py 删定义、改为从 templates 导入 | 全量 pytest 320 绿 |
| **2** | 新建 `formatters.py`（两函数体连同类型导入逐字搬）；chat.py 删定义、改为从 formatters 导入；`pipeline.py` / `test_prompts.py` / `test_prompts_golden.py` 换源；`__init__.py` 的 `format_*` 换源 | 全量 pytest 320 绿 |
| **3** | chat.py 删顶部 intent 再导出块 + 改写头部过时 docstring（说明新结构）；删 `TYPE_CHECKING` 的 `CheckReport`；`test_prompts.py` 三个 intent 符号换源 | 全量 pytest 320 绿 |

不需要新测试：14 个 golden 测试 + 现有 `test_prompts.py` 已覆盖全部搬迁符号；测试文件改动仅限上表的导入行。

## 守门规则

- 每步收尾跑全量 `python -m pytest`，必须 ≥ 320 绿；**golden 变红 → `git checkout` 回滚该步排查，严禁 `PILLCLEAR_REGEN_GOLDEN=1`**
- 每步 `git diff` 自查：除 import 行、新建文件、过时 docstring 外，函数体与常量文本 diff 为空
- 末步后跑 `pytest --cov=app.prompts --cov-report=term-missing`：`app.prompts` 保持 100%（`templates/chat_system.py` 与 `formatters.py` 由 golden 测试天然覆盖）
- 文案零改动（一个标点）；`safety.py` 5 条锁定现状与本次零交集，不碰
- `tests/golden/` 内容文件不碰；`app/prompts/` 及其调用方（`pipeline.py`、两份测试、`__init__.py`）以外不改任何文件

## 验收文档同步

`docs/refactor-readiness.md` 周期 1 清单随本 spec 同一 commit 修订两处：
1. `format_*` 条目 → 「包级 API 不变，规范位置迁至 `app.prompts.formatters`」
2. 注明 `SYSTEM_PROMPT_TEMPLATE` 与 chat.py 的 intent 再导出经批准删除（零消费者）

## 范围外

- 任何 prompt 文案措辞变更
- `safety.py` 5 条已知盲区/保守行为（发热正则窗口、缺「老人」、「月经期」、保守子串命中、否定前置）——一律不修
- `intent.py` / `safety.py` / `ingest.py` 的内部结构
- `app/prompts/` 之外的任何 app 模块
