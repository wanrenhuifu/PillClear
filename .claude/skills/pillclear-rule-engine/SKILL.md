---
name: pillclear-rule-engine
description: YAML rule DSL for deterministic drug interaction/overlap checks. Use when adding or editing rules under app/rules/data/, implementing conflict detection, or running rule engine tests. Triggers: "新增药品规则", "药物冲突检查", "规则引擎", "YAML rule", "interaction rule", "overlap rule".
---

# PillClear 规则引擎

本 skill 确保所有药物冲突/重复成分判断严格走确定性规则引擎——**LLM 只翻译结论，不推断药学结论**。

## 一、铁律（不可违反）

1. **药学结论零 LLM**：任何药物相互作用、成分重复、剂量叠加的判断必须由 `app/rules/engine.py` 的 YAML 规则得出。LLM（`/chat` pipeline step 5）只能把 `CheckReport` / `ConflictReport` 翻译成大白话，禁止在 prompt 中让 LLM 自行推断。
2. **坏规则必响**：YAML 解析失败、模型校验失败、规则 id 重复、零条件规则、空规则目录 → 一律 `ValueError`，不得静默上线（见 `engine.py::load_rules`）。
3. **每条规则配测试**：新增 YAML 规则文件或修改既有规则条件，必须同步在 `tests/test_rules_engine.py` 中新增对应的命中/未命中用例。

## 二、YAML DSL 完整语法

规则文件位于 `app/rules/data/*.yaml`，顶层是一个 `rules:` 列表。

### 2.1 规则结构

```yaml
rules:
  - id: <kebab-case 唯一 ID，全局不得重复>
    severity: danger | warning | info
    confidence: high | medium | low
    title: "<中文标题，一句说清冲突>"
    description: "<对用户的解释，大白话>"
    conditions:
      ingredients:        # 可选——按药品成分匹配
        - name: "<成分中文名>"
          min_count: <int>  # 药箱中该成分出现 ≥ min_count 条时命中
          max_daily_mg: <int>  # 可选，mg 单位，超出时追加剂量警告
      substances:          # 可选——用户自报物质（酒精等）
        - name: "<物质中文名>"
      lifestyle:           # 可选——行为/饮食
        - name: "<行为中文名>"
    warning_template: "<模板字符串，可用 {count}、{total_mg} 占位>"
```

### 2.2 匹配语义

- **AND 语义**：`conditions` 下所有子条件（ingredients + substances + lifestyle）必须全部满足才命中。
- **ingredients 计数**：按「每药品每成分一条」的扁平列表计数。例：药箱含泰诺（对乙酰氨基酚 325mg）+ 白加黑（对乙酰氨基酚 325mg）→ 对乙酰氨基酚共 2 条 → `min_count: 2` 命中。
- **substances 匹配**：精确字符串匹配用户自报物质名。
- **max_daily_mg**：命中规则时额外用 `app/core/units.py::to_mg()` 归一化后计算总量，超出则追加剂量警告。

### 2.3 完整示例（来自 `overlap.yaml`）

```yaml
rules:
  - id: acetaminophen-overlap
    severity: warning
    confidence: high
    title: "对乙酰氨基酚重复用药风险"
    description: "你同时在吃{count}种含对乙酰氨基酚的药，一天总量是{total_mg}毫克。成人一天最多4000毫克，超了容易伤肝。"
    conditions:
      ingredients:
        - name: "对乙酰氨基酚"
          min_count: 2
          max_daily_mg: 4000
    warning_template: "检测到你同时在服用{count}种含对乙酰氨基酚的药品，每日总量{total_mg}mg。成人每日上限为4000mg，超量可能导致肝损伤。"
```

## 三、新增规则流程

1. 确认触发场景（成分重复 / 物质交互 / 生活方式交互）
2. 在对应的 `.yaml` 文件（或新建）中编写规则
3. 确保 `id` 全局唯一（`grep -r "id:" app/rules/data/` 查重）
4. 在 `tests/test_rules_engine.py` 中新增测试：
   - **命中用例**：构造满足条件的 medbox 和 substance 输入
   - **未命中用例**：仅差一个条件的情况（验证 AND 语义）
   - **剂量用例**（如有 `max_daily_mg`）：总量超阈值/不超阈值各一条
5. 运行 `pytest tests/test_rules_engine.py -k "<rule_id>"` 验证
6. 运行全量 `pytest` 确保无回归

## 四、测试模板

```python
def test_<rule_id>_matches(app: FastAPI):
    """规则 <rule_id> 命中——药箱含 <描述>"""
    # 构造 medbox items: [{"drug_id": "...", "dosage_per_day": N}]
    # 调用 check_medbox / process_chat
    # 断言 findings 中存在对应 title 的项

def test_<rule_id>_no_match_single_item(app: FastAPI):
    """仅一种药不触发 min_count: 2（AND 语义验证）"""
    # 只给一种含目标成分的药 → 不命中

def test_<rule_id>_dose_exceeds_limit(app: FastAPI):
    """剂量超 max_daily_mg 时追加警告"""
    # 两种含目标成分的药，总剂量超过阈值

def test_<rule_id>_dose_within_limit(app: FastAPI):
    """剂量不超 max_daily_mg 时仅成分重复警告"""
```

## 五、规则评审清单

新增或修改规则时逐项确认：

- [ ] 规则 `id` 全局唯一
- [ ] `severity` / `confidence` 与证据强度匹配（保健品交互 ≤ `medium` confidence）
- [ ] `conditions` 使用正确的匹配字段（成分→`ingredients`、自报物质→`substances`）
- [ ] `max_daily_mg` 与权威来源一致
- [ ] `warning_template` 无硬编码数值，用 `{count}` / `{total_mg}` 占位
- [ ] 命中 + 未命中测试均已添加
- [ ] 全量 `pytest` 通过
