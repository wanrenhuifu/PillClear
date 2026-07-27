# PillClear Web 前端设计 Spec

- 日期：2026-07-28
- 状态：已评审通过，待实施
- 上游：后端 API 已就绪（chat + medbox，均非流式）；仓库此前无任何前端

## 1. 背景与目标

PillClear 后端提供两组能力：用药咨询（`POST /api/v1/chat`）与药箱检查/持久化（`/api/v1/medbox/*`）。目前只能通过 Swagger 或 curl 使用。本 spec 定义一个**响应式 Web 前端**，让产品成为可演示的完整形态：年轻人（18-30 岁，C 端）在浏览器里完成"问一句"和"查一箱"两件事。

成功标准：`web/` 目录下 `npm run dev` 起页面，后端 `uvicorn app.main:app --reload` 起 API，浏览器里可完整走通：提问 → 带引用的回答 → 选药入箱 → 检查出叠加/冲突报告。

## 2. 范围与非目标

**范围内：**
- 聊天视图、药箱视图（响应式，桌面 + 移动）
- 后端两处小改动：`GET /api/v1/drugs` 只读列表接口；CORS 中间件 + `cors_origins` 配置

**非目标（YAGNI，明确不做）：**
- 用户登录（沿用 `device_id` 方案）
- 聊天记录持久化（刷新即清空，纯前端内存）
- 后端流式改造（维持一次性返回，前端做等待体验）
- 国际化、暗色模式、用药提醒（`app/reminder/` 仍为空占位）
- 小程序 / H5 封装

## 3. 技术栈

| 项 | 选择 | 理由 |
|---|---|---|
| 框架 | React 18 + TypeScript + Vite | 用户指定的 `npm run dev` 路线；TS 镜像后端 Pydantic 契约 |
| 样式 | Tailwind CSS v4 | CSS-first 配置（`@theme` token），细节打磨快 |
| 服务端状态 | TanStack Query v5 | 药品列表缓存、药箱增删后自动 refetch、loading/error 统一 |
| 路由 | React Router v7 | `/chat`、`/medbox` 两个真实路由，为后续提醒页预留 |
| 测试 | Vitest + React Testing Library | 与后端 TDD 纪律一致；API 在 `lib/api.ts` 边界 mock |
| 位置 | 仓库 `web/` 子目录 | 与 Python 后端互不干扰 |

不引入：UI 组件库（自绘组件以保持设计独特性）、markdown 解析器（回答按纯文本 + 保留换行渲染）、状态管理库（两个视图，TanStack Query + useState 足够）。

## 4. 仓库布局

```
web/
  package.json
  vite.config.ts          # /api 代理 → http://127.0.0.1:8000
  tsconfig.json
  index.html
  src/
    main.tsx
    App.tsx               # 路由 + 布局壳（桌面侧栏 / 移动底栏）
    types/api.ts          # 后端 schema 的 TS 镜像（ChatResponse/CheckReport/...）
    lib/
      api.ts              # 唯一 fetch 出口，typed，统一错误类型
      device.ts           # device_id：crypto.randomUUID() 一次，存 localStorage["pillclear_device_id"]
      format.ts           # 剂量数字格式化（mg，一位小数按需）
    features/
      chat/
        ChatView.tsx      # 消息列表 + 输入器
        MessageBubble.tsx # 用户/助手气泡，助手气泡内嵌引用与免责声明
        CitationCard.tsx  # 可折叠「说明书原文」卡（商品名/章节/摘录）
        Composer.tsx      # 输入框 + 字数计数（上限 2000）+ 发送
        QuickStart.tsx    # 空状态「泡罩板」快捷提问
        AssistantLoading.tsx  # 三点跳动 + 轮播状态文案
      medbox/
        MedboxPanel.tsx   # 药箱列表 + 物质选择 + 触发检查
        DrugPicker.tsx    # 搜索 + 添加（日频次 stepper，可为空）
        DoseMeter.tsx     # 成分日总量 vs 安全上限的动画进度条
        CheckReport.tsx   # 三段式报告：叠加 / 规则卡 / 未入库提示
        RuleCard.tsx      # 按 severity 着色的规则卡 + 证据强度徽章
    components/ui/
      Badge.tsx, Chip.tsx, CapsuleButton.tsx, SectionTitle.tsx, EmptyState.tsx
    styles/
      index.css           # Tailwind v4 + @theme token + 背景层 + 关键帧
```

## 5. 设计语言：「数字说明书」

概念：药品印刷物的精确质感 × 现代健康应用。面向年轻人但不低幼；所有视觉决定服务于「这是严肃的用药安全工具」。

**色彩 token（@theme）：**

| token | 值 | 用途 |
|---|---|---|
| `--color-ink` | `#1A2823` | 正文文字（深绿灰墨色） |
| `--color-paper` | `#F4F7F5` | 页面基底（临床 off-white） |
| `--color-card` | `#FFFFFF` | 卡片面 |
| `--color-pharma` | `#0E8A6A` | 主色（药房绿）：品牌、主按钮、链接 |
| `--color-pharma-deep` | `#0A6B52` | 主色 hover / 强调 |
| `--color-danger` | `#C6362F` | severity=danger、超限剂量条、错误 |
| `--color-warn` | `#B7791F` | severity=warning、未入库提示 |
| `--color-info` | `#2B6CB0` | severity=info |
| `--color-mute` | `#5C6B64` | 次级文字 |

severity 三色**仅**用于规则严重级别与剂量条状态，不做装饰。无渐变标题、无玻璃拟态、无极光光斑。

**字体：**
- 数字 / 拉丁展示：Space Grotesk（几何、技术感）——标题、大数字
- 剂量 / mg / 报告数据：IBM Plex Mono——化验单式的精确感
- 中文：系统栈 `PingFang SC, MiSans, Microsoft YaHei, Noto Sans CJK SC`（不携带中文 webfont）
- 通过 fontsource 引入两款拉丁字体

**背景（分层）：** 基底 `paper` 色 + 细网格纸纹理（1px 线，~4% 不透明度，CSS repeating-linear-gradient，像剂量记录格）+ 顶部大面积淡绿径向微光。克制、有层次、不花。

**动效原则：** 每个交互有可感知反馈——hover 抬升（translateY -1px + 阴影）、按压缩小（scale 0.98）、消息气泡滑入（12px + fade）、引用卡展开用 grid-template-rows 过渡、规则卡错峰浮现（stagger 60ms）、剂量条 cubic-bezier(0.22, 1, 0.36, 1) 宽度动画。全部 CSS 实现，prefers-reduced-motion 下降级为瞬时。

**品牌：** 内联 SVG 双色胶囊 logo 标记 + Space Grotesk 字标「PillClear」。

## 6. 信息架构与布局

- **桌面（≥1024px）**：左侧主区 = 聊天；右侧固定 320px 栏 = 药箱紧凑摘要（列表 + 物质 chip + 「开始检查」），检查报告在右栏内展开。核心叙事：「我在吃什么」与「问药师」同屏。
- **`/medbox` 全页**：选药器（DrugPicker）+ 完整报告，桌面端从右栏「管理药箱」进入，移动端即 tab 本体。两视图共享同一份 TanStack Query 缓存，任一侧增删药品，另一侧自动同步。
- **移动（<1024px）**：底部 tab 栏切换「问诊」「药箱」两个视图；聊天页内不再显示药箱。
- **聊天空状态（第一屏）**：不做通用欢迎页。做「泡罩板」快捷提问区——预置 4 个真实可答的问题，点击直接发送：
  1. 「泰诺和白加黑能一起吃吗？」（命中 overlap.yaml 对乙酰氨基酚重复）
  2. 「吃布洛芬期间能喝酒吗？」（命中 alcohol.yaml）
  3. 「布洛芬和对乙酰氨基酚哪个退烧好？」（正常咨询路径）
  4. 「我最近总是头疼怎么办？」（命中诊断边界 → 展示拦截卡）

  快捷提问刻意覆盖三条路径：正常回答、规则命中、安全拦截——空状态即产品演示。

## 7. 功能规格

### 7.1 聊天视图

**消息模型（纯前端内存）：** `{ id, role: 'user' | 'assistant', ...ChatResponse 字段 | null, status: 'pending' | 'ok' | 'error', errorKind?: 'llm' | 'network' }`

**ChatResponse 各字段渲染规则：**

| 字段 | 渲染 |
|---|---|
| `blocked=true` | 边界卡：类别图标（急症/特殊人群/诊断/处方药四图标 + 通用）+ `boundary_message` 固定话术，米白底 + 左侧绿色竖线样式；不显示引用与免责声明 |
| `answer` | 纯文本渲染，`\n` 保留换行；助手气泡内 |
| `citations[]` | 回答下方折叠卡列表，标题「说明书原文 · {brand_name} · {section}」，展开显示 `excerpt` |
| `confidence < 0.5` | 回答头部加琥珀色 chip「不太确定，请咨询药师」——阈值与后端 `_LOW_CONFIDENCE_THRESHOLD` 一致（0.5），后端已在正文追加同义提示，chip 做视觉强调 |
| `disclaimer` | 每条助手消息最底部灰色小字，永远展示 |

**等待体验（非流式，关键）：** 发送后用户气泡立即上屏，助手侧显示 `AssistantLoading`：胶囊色三点跳动 + 按时间轮播状态文案（0s「正在理解你的问题…」→3s「翻阅说明书…」→8s「比对安全规则…」→15s「组织回答，马上好…」）。输入框期间禁用。

**错误处理：**

| 情况 | 表现 |
|---|---|
| HTTP 502（`LLMRetryExhausted`） | 失败卡：「AI 服务暂时不可用，请稍后重试」+「重试」按钮（重发同一条 query） |
| 网络错误 / 超时（60s AbortController） | 失败卡：「网络好像断了，检查一下再试」+ 重试 |
| 输入为空或 >2000 字 | 前端拦截：发送按钮禁用 + 字数计数变红 |

### 7.2 药箱视图

**选药（DrugPicker）：** 搜索框对 `GET /drugs` 全量列表（TanStack Query 缓存，29 条量级）做本地 includes 过滤（商品名 + 通用名）；每条结果右侧「加入药箱」。已在箱中的药置灰禁点——v1 不做频次编辑，改频次 = 删除后重新添加（后端 POST items 本身是 upsert，此限制仅为前端交互取舍）。

**添加：** 展开内联行：日频次 stepper（1-10）+ 「不确定频次」开关（置 `dosage_per_day=null`，后端按 1 次/日保守计）→ 确认调 `POST /medbox/{device_id}/items` → 成功后 invalidate `["medbox", deviceId]`。

**药箱列表：** 每项 = 商品名（Space Grotesk）+ 频次小字（`每日 ×3` 或 `频次未定`）+ 删除按钮（调 DELETE，invalidate 同 key）。

**物质自报：** 两个预置 chip 多选切换：**酒精**、**避孕药**（严格对应 `alcohol.yaml` / `interaction.yaml` 现有 substance 词表，不造新词）。

**检查（CheckReport，三段式）：** 点「开始检查」→ `POST /medbox/check`（items 来自当前药箱，lifestyle_substances 来自 chip）→ 报告滑入：

1. **成分叠加**：`overlap.overlapping[]` 每项一个 `DoseMeter`——
   - 左：成分名 + 「来自：{sources.join('、')}」
   - 中：动画进度条，宽度 = `total_amount_mg / max_daily_mg`（封顶 100%）；`max_daily_mg=null` 时渲染中性灰条 + 「安全上限未知」标签（铁律 #4）
   - 右：IBM Plex Mono 大字 `{total} mg` / 小字 `上限 {max} mg`
   - 颜色阶梯：比率 <70% 绿 / 70-100% 琥珀 / >100% 红（条满 + 溢出刻线）
   - `overlap.warnings[]`（超上限警告）在叠加区顶部渲染为红色横幅，逐条列出
2. **相互作用**：`triggered_rules[]` 每条一个 `RuleCard`——severity 决定卡色（danger 红边 / warning 琥珀边 / info 蓝边）、标题、`warning` 文案（已由后端 `format_warning` 填充完毕，前端**原样展示**）、`description` 次级文字、右上角证据强度徽章（high/medium/low → 「证据充分/中等/有限」，low/medium 徽章附 tooltip「证据有限，保守提示」）、`source` 小字
3. **未入库药品**：`unresolved_drugs[]` 非空时渲染琥珀提示条：「以下药品暂未收录，本次无法纳入检测：X、Y」

**空态与边界：** 空药箱 → EmptyState 引导「先添加你在吃的药」；有药但未检查 → 只显示列表 + 醒目检查按钮；检查中 → 报告区骨架屏。

## 8. API 契约

**现有端点（前端消费方）：**

| 方法 | 路径 | 关键字段 |
|---|---|---|
| GET | `/api/v1/health` | `{status}` |
| POST | `/api/v1/chat` | req `{query}` / resp `ChatResponse`（见 §7.1） |
| GET | `/api/v1/medbox/{device_id}` | resp `{device_id, items[]}` |
| POST | `/api/v1/medbox/{device_id}/items` | req `{drug_id, brand_name, dosage_per_day?}` / resp 完整药箱 |
| DELETE | `/api/v1/medbox/{device_id}/items/{drug_id}` | resp 完整药箱 |
| POST | `/api/v1/medbox/check` | req `{items[], lifestyle_substances?}` / resp `CheckReport`（见 §7.2） |

**新增端点：**

```
GET /api/v1/drugs → 200 [{ "drug_id": 1, "brand_name": "泰诺", "generic_name": "酚麻美敏片" }, ...]
```

**CORS：** `create_app()` 加 `CORSMiddleware`，允许来源取新配置 `cors_origins: str`（逗号分隔，默认 `"http://localhost:5173,http://127.0.0.1:5173"`，空串 = 不加中间件）。开发期前端仍走 Vite 代理（`/api → 127.0.0.1:8000`），CORS 为部署与第三方客户端准备。

## 9. 后端改动明细（TDD，先测后码）

1. `app/knowledge/repository.py`：`DrugReader` Protocol 增加 `list_drugs() -> list[dict]`（返回 id/brand_name/generic_name）；`InMemoryDrugRepository`、`PostgresDrugRepository` 实现之；`app/knowledge/sqlite_repo.py` 的 SQLite 实现同样实现。三处各加单测。
2. 新增 `app/api/drug_routes.py`：`GET /drugs` 路由（`run_in_threadpool` 包同步仓储调用，与现有路由同构）；`main.py` include。加 TestClient 路由测试。
3. `app/config.py`：`cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"`；`main.py` 按配置挂 `CORSMiddleware`。加配置测试（空串不挂 / 默认值正确）。

约束：不动 `app/rules/`、`app/core/safety.py`、`app/prompts/`（golden 测试与 PostToolUse hook 的敏感区一律不碰）；全部现有测试保持绿。

## 10. 状态与数据流

- `device_id`：首次访问 `crypto.randomUUID()` 生成，存 `localStorage["pillclear_device_id"]`，全站唯一用户标识。
- TanStack Query keys：`["drugs"]`（staleTime 无限，入库才会变）、`["medbox", deviceId]`（增删后 invalidate）。
- 聊天消息：`useState` 数组，无持久化。
- 检查报告：检查请求的响应，存视图本地 state。

## 11. 测试策略

- **后端**：新增改动全部 TDD；收尾 `pytest` 全绿（287 个现有 + 新增）。
- **前端（Vitest + RTL，fetch 在 api.ts 边界 mock）：**
  - `lib/api.ts`：请求路径/方法/body 映射、错误分类（502 vs 网络错误）
  - `lib/device.ts`：首次生成、二次读取同一 id
  - `DoseMeter`：比率三档颜色、`max=null` 的未知上限分支、超 100% 封顶
  - `CheckReport`：三段按 fixture 渲染（叠加/规则/未入库各一），severity → 徽章文案映射
  - `ChatView`：发送 → pending → ok 状态机；blocked 渲染边界卡；502 渲染重试卡且重试按钮重发
  - `DrugPicker`：本地搜索过滤、已入箱禁点

## 12. 验收标准（冒烟脚本）

1. `pytest` 全绿；
2. 后端 `uvicorn app.main:app --reload` + `web/` 下 `npm run dev`；
3. 浏览器走通：点快捷提问「泰诺和白加黑能一起吃吗」→ 回答带引用卡与免责声明 → 药箱加入泰诺、白加黑 → 开始检查 → 对乙酰氨基酚剂量条出现（红色超上限）+ 规则卡 → 点「吃布洛芬期间能喝酒吗」前勾选「酒精」→ 报告出现酒精规则卡 → 删除药品后报告变化。

## 13. 风险

- **非流式长等待**是最大体验风险——轮播状态文案是缓解手段，根治需后端流式改造（明确不在本期）。
- 药品列表 29 条全量下发 + 本地搜索，量级无虞；药品上千时需后端搜索接口（不在本期）。
