# 重构防护网与验收标准

> 2026-07-25 备战完成。本文件是各重构周期的验收依据；
> Superpowers 的 brainstorming / execute 阶段请把下方清单当作验收条件。

## 基线（2026-07-25）

| 项 | 值 |
|----|-----|
| 原始基线 | `378bd08`，287 passed（干净环境验证通过，见下） |
| 加防护网后 | **320 passed**（287 + 16 prompt golden + 17 safety 特征化） |
| 干净环境验证 | `git archive HEAD` 导出目录（无 `.env`、无未提交改动）跑通，exit 0——套件不依赖本机环境（conftest `_env_file=None` 有效） |
| 覆盖率 | `app.core.safety` + `app.prompts` 全包 **100%**（168 statements / 0 missing） |

**pytest 通过数低于基线 → 立即停工排查**（测试被误删或假绿）。

## 防护网组成

1. **prompt golden 逐字比对** — `tests/test_prompts_golden.py` + `tests/golden/`（16 个黄金文件）
   - 覆盖：`build_system_prompt`（无引用 / 有引用 / 带检查槽位 / 带近似匹配槽位 / 检查+近似匹配组合顺序）、intent / safety / ingest 三份分类器模板、citations 格式化两种形态、`format_check_report_for_prompt` 确定性五段渲染（无风险 / 未收录 / 触发规则 / 叠加警告 / 共享成分 / 组合报告顺序）；近似匹配披露走独立中立槽位（`AMBIGUITY_SECTION_HEADER`），不再混入「确定性规则引擎」检查结论（code review 修复：启发式披露不得伪装成确定性结论）
   - 重新生成（仅在确认文案变更为有意之后）：
     `PILLCLEAR_REGEN_GOLDEN=1 python -m pytest tests/test_prompts_golden.py`
     PowerShell：`$env:PILLCLEAR_REGEN_GOLDEN=1; python -m pytest tests/test_prompts_golden.py; Remove-Item env:PILLCLEAR_REGEN_GOLDEN`
2. **safety 特征化用例** — `tests/test_safety.py` 的 `*NearMiss` / `TestPriorityCharacterization` / `TestFixedMessagesGolden` 组
   - 四类固定话术逐字锁定、各类「命中 + 差一点不命中」边界、完整优先级链、否定语义
3. **PostToolUse hook**（`.claude/settings.json`，PowerShell）— Write/Edit 命中 `app/core/safety.py` 或 `app/rules/` → 自动跑 `python -m pytest tests/ -x --tb=short`
4. **pillclear-safety-review 临时自动触发** — 重构期已从 `skillOverrides` 移除（动 safety 逻辑时自动加载回归审查）。**重构结束后必须恢复** `"pillclear-safety-review": "user-invocable-only"`，恢复省 token 设置。

## 周期 1：prompts 拆分

> **✅ 已完成（2026-07-26，`fffa2cd..8e690a9`）**：320 passed（不增不减）；14 个 golden 全程绿、从未重新生成；包级 API 不变（`format_*` 规范位置 `app.prompts.formatters`，兼容层按批准删除）；`app.prompts` 覆盖率 100%。设计见 `docs/superpowers/specs/2026-07-26-chat-prompt-split-design.md`。

- [ ] pytest 通过数 ≥ 320
- [ ] golden 测试全绿（模板内容逐字不变；变红 = 文案变更，须审核后重新生成并在 commit 说明）
- [ ] 手动抽查：`build_system_prompt` 重构前后对同一输入输出 diff 为空（golden 已代劳，此项双保险）
- [ ] 包级 API（`app/prompts/__init__.py`）不变：`build_chat_messages` / `build_system_prompt` / `format_citations_for_prompt` / `format_check_report_for_prompt` / `build_intent_messages` / `build_safety_messages` / `SAFETY_CLASSIFY_SYSTEM_PROMPT` / `INGREDIENT_SYSTEM_PROMPT`（`format_*` 规范位置迁至 `app.prompts.formatters`，调用方从规范位置导入）；`SYSTEM_PROMPT_TEMPLATE` 与 `app.prompts.chat` 的 intent 三符号再导出经批准随本次重构删除（零消费者，见 `docs/superpowers/specs/2026-07-26-chat-prompt-split-design.md`）
- [ ] `app.prompts` 覆盖率保持 100%

## 周期 2：safety.py 重构

> **✅ 已完成（2026-08-13）**：结构重构（四类规则数据化为优先级表 `_RULES`、放行构造收敛为 `_allow()`）行为零变化，golden 与特征化用例零重新生成；同期修复盲区：「老人/老年人/老人家」纳入特殊人群关键词层，固定话术同步加入「老年人」（有意变更，`TestFixedMessagesGolden::test_special_population_message_exact` 与 `test_elderly_caught_by_keywords` 已显式更新）。基线 405 → **406**。

- [x] pytest 通过数 ≥ 基线（406 passed，+1 新增紧邻否定近失用例）
- [x] `test_safety.py` 全绿（关键词命中 / 近失边界 / 固定话术 / 优先级链逐字不变；仅老人相关两处有意更新）
- [x] hook 自动跑 `pytest tests/ -x` 通过（pre-commit 钩子提交时实跑验证）
- [x] 回归审查无新增越界漏放（全量特征化套件 + 新增近失用例）
- [x] 公开接口不变：`check(text, llm=None) → BoundaryResult`，`__all__ = ["BoundaryCategory", "BoundaryResult", "check"]`
- [x] 优先级链不变：急症 > 特殊人群 > 诊断 > 处方药 > 放行（即 `_RULES` 声明顺序）
- [x] `app.core.safety` 覆盖率保持 100%（80 statements / 0 missing）

## 已知保守行为与盲区（特征化测试锁定在案）

以下均为**当前有意或已知接受**的行为，对应测试变红即行为变更，必须单独决策
（修行为 or 接受新行为并有意识改测试），**严禁悄悄改测试凑绿**：

1. **发热组合正则窗口 `{0,10}`**：「发热/高烧/发烧/高热」与「不退/退不下/退不了」间隔超 10 字当前放行（`TestEmergencyNearMiss::test_fever_gap_beyond_window_not_emergency`）——已知漏判窗口，收紧需单独决策
2. ~~**关键词层不含「老人/老年人」**~~：✅ 已修复（2026-08-13，周期 2）——「老人/老年人/老人家」已纳入关键词层（`test_elderly_caught_by_keywords`）；年龄正则仍只覆盖 0-17 岁，高龄数字表述继续由 LLM 补漏层兜底
3. **「月经期」不在特殊人群列表**（`test_menstrual_period_not_special_population`）
4. **子串保守命中**（铁律 #3：漏判比误判危险，宁可拦了引导咨询）：
   - 「治什么病」命中 diagnosis（`TestDiagnosisNearMiss::test_what_disease_treats_still_diagnosis`）
   - 「是不是抗生素」命中 prescription（`TestPrescriptionNearMiss::test_asking_if_antibiotic_blocked`）
   - 「下周要哺乳期」命中 special_population（`TestSpecialPopulationNearMiss::test_future_breastfeeding_still_blocked`）
5. **否定只认紧邻关键词之前**：「发热没有不退的情况」仍触发急症（`TestEmergencyNearMiss::test_negation_only_checked_before_keyword`）——远距否定放行是铁律 #3 下的有意取舍
6. **品牌名扫描语义（T4/T5/T6 定型）**：
   - **扫描无条件运行 + LLM∪扫描并集**（`_effective_drug_names`）：确定性扫描与 LLM 抽取取并集去重，补回 LLM 半解析漏掉的药；LLM 裸名经近似匹配规范映射收敛到存储名（扶他林 → 扶他林_外用），同一药不以「用户原文 + 存储名」两种形态进检查。近似匹配强制披露（独立中立槽位，见上第 1 条）。
   - **裸名歧义降级**（`_brand_patterns`）：核名指向多个存储品、或裸名与注解兄弟并存（扶他林 与 扶他林_外用）时，裸名/核名不作匹配模式——宁走整句检索也不静默命中某个剂型（召回不得依赖入库顺序）。
   - **紧邻式否定/停药过滤**（`_is_past_or_negated`，`_NEGATED_PRE/POST_MARKERS`）：只认药名前 3 字窗口内的动词否定（不吃/停用…）与药名后 4 字窗口内的停药标记（停了/戒了…）；时态词（昨天/上周/以前…）与健康状态词（康复/痊愈…）不作标记，保守保留进检查（铁律 #1 安全优先，宁可多警告也不漏正在吃的药）。
   - **已知盲区（无分词器不可消除）**：
     - 「泰诺林里的泰诺」子串误命中：未收录长名内嵌已收录短名时，扫描仍把内嵌短名检出为药名。T5 后扫描无条件并集，此误命中在 LLM 成功抽出长名时也会经并集进入名单（缓解：长名已收录时由最左最长匹配掩蔽），无分词器不可消除。
     - 紧邻式否定固有盲区：「不想停用泰诺 / 别停用泰诺」前置窗口仍误杀仍在吃的药——「停用」紧邻药名被当作否定信号，实际「不想/别」否定的是「停用」本身。保守方向的已知取舍：宁可多警告也不漏正在吃的药。
   - 在案语义由 `tests/test_chat_pipeline.py::TestScanHardening` / `TestBrandScan` 锁定
