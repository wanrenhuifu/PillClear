# PillClear Web 前端 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 PillClear 构建响应式 Web 前端(React + Vite),让用户在浏览器里完成用药咨询对话与药箱叠加/冲突检查,并为后端补上药品列表接口与 CORS 支持。

**Architecture:** 前端是独立 SPA(`web/` 子目录),通过 `/api` 前缀消费现有 FastAPI 后端(开发期 Vite 代理到 127.0.0.1:8000)。两个视图(聊天 / 药箱)共享一个 typed API 层(`lib/api.ts`)与 TanStack Query 缓存;桌面端聊天与药箱同屏,移动端底部 tab 切换。后端仅新增只读 `GET /api/v1/drugs` 与 CORS 中间件,业务逻辑零改动。

**Tech Stack:** 后端 Python 3.12 / FastAPI / Pydantic v2 / pytest;前端 React 18 / TypeScript / Vite / Tailwind CSS v4 / TanStack Query v5 / React Router v7 / Vitest + React Testing Library。

## Global Constraints

- **铁律延续**:前端不产生任何药学结论——叠加/冲突判断全部展示后端返回的数据;`warning` 文案已由后端 `format_warning` 填充,前端**原样展示**,不改写、不截断。
- **后端禁区**:不改 `app/rules/`、`app/core/safety.py`、`app/prompts/`(golden 测试与 PostToolUse hook 敏感区)。全部 287+ 现有测试保持绿。
- **后端改动 TDD**:先写失败测试,再写实现。
- **前端测试纪律**:HTTP 一律在 `lib/api.ts` 边界 mock(`vi.mock` / `vi.stubGlobal("fetch", ...)`),不打真实网络。
- **文案语言**:界面文案全部简体中文(zh-CN)。
- **固定常量(不得更改)**:置信度 chip 阈值 `0.5`(对齐后端 `_LOW_CONFIDENCE_THRESHOLD`);剂量条阶梯 `<0.7` 绿 / `<1` 琥珀 / `≥1` 红;物质词表恰好 `["酒精", "避孕药"]`;快捷提问恰好 4 条(见 Task 7)。
- **Node 版本**:18+。commit 消息沿用仓库风格(`feat:` / `test:` / `docs:` 前缀 + 中文描述)。

---

## 文件结构总览

**后端(改):**
- `app/knowledge/repository.py` — `DrugReader` 增加 `list_drugs()`;InMemory 实现
- `app/knowledge/sqlite_repo.py` — SQLite 实现 `list_drugs()`
- `app/api/schemas.py` — 新增 `DrugSummary`
- `app/api/drug_routes.py`(新)— `GET /drugs` 路由
- `app/main.py` — include 新路由 + CORSMiddleware
- `app/config.py` — `cors_origins` 字段
- `tests/test_drug_listing.py`(新)、`tests/test_cors.py`(新)

**前端(全部新建于 `web/`):**
- 骨架:`package.json`、`vite.config.ts`、`tsconfig.json`、`index.html`、`.gitignore`
- `src/main.tsx`、`src/App.tsx`、`src/setupTests.ts`、`src/styles/index.css`
- `src/types/api.ts`;`src/lib/api.ts`、`device.ts`、`format.ts`
- `src/components/ui/`:Badge、Chip、CapsuleButton、SectionTitle、EmptyState、Logo、Header、TabBar
- `src/features/chat/`:ChatView、MessageBubble、CitationCard、Composer、QuickStart、AssistantLoading
- `src/features/medbox/`:MedboxPanel、DrugPicker、DoseMeter、CheckReport、RuleCard、SubstanceChips
- 测试:各 `__tests__/*.test.tsx`,API 边界 mock

---

## Task 1: 后端 — DrugReader.list_drugs() 及三种仓储实现

**Files:**
- Modify: `app/knowledge/repository.py`(DrugReader Protocol + InMemoryDrugRepository)
- Modify: `app/knowledge/sqlite_repo.py`(SQLiteDrugRepository)
- Modify: `app/knowledge/repository.py`(PostgresDrugRepository)
- Test: `tests/test_drug_listing.py`(新建)

**Interfaces:**
- Consumes: 现有 `upsert_drug(record) -> int`
- Produces: `list_drugs() -> list[dict]`,每个 dict 恰含键 `id` / `brand_name` / `generic_name`,按 `id` 升序

- [ ] **Step 1: 写失败测试**

新建 `tests/test_drug_listing.py`:

```python
"""药品列表能力测试:仓储 list_drugs() + GET /api/v1/drugs 路由。"""

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_drug_repository
from app.knowledge.repository import InMemoryDrugRepository
from app.knowledge.schemas import DrugRecord, Ingredient
from app.knowledge.sqlite_repo import SQLiteDrugRepository
from app.main import create_app


def _seed(repo):
    """种子两种药:泰诺(id=1,无通用名)/ 芬必得(id=2)。"""
    repo.upsert_drug(
        DrugRecord(
            brand_name="泰诺",
            ingredients=[Ingredient(name="对乙酰氨基酚", amount=325, unit="mg")],
        )
    )
    repo.upsert_drug(DrugRecord(brand_name="芬必得"))
    return repo


class TestListDrugsRepository:
    def test_inmemory_shape_and_order(self):
        repo = _seed(InMemoryDrugRepository())
        rows = repo.list_drugs()
        assert [(r["id"], r["brand_name"]) for r in rows] == [(1, "泰诺"), (2, "芬必得")]
        assert set(rows[0].keys()) == {"id", "brand_name", "generic_name"}
        assert rows[0]["generic_name"] is None

    def test_sqlite_shape_and_order(self):
        repo = _seed(SQLiteDrugRepository(":memory:"))
        rows = repo.list_drugs()
        assert [(r["id"], r["brand_name"]) for r in rows] == [(1, "泰诺"), (2, "芬必得")]
        assert set(rows[0].keys()) == {"id", "brand_name", "generic_name"}

    def test_empty_repo_returns_empty_list(self):
        assert InMemoryDrugRepository().list_drugs() == []
        assert SQLiteDrugRepository(":memory:").list_drugs() == []
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `python -m pytest tests/test_drug_listing.py -v`
Expected: FAIL — `AttributeError: 'InMemoryDrugRepository' object has no attribute 'list_drugs'`

- [ ] **Step 3: 实现 Protocol + InMemory + SQLite + Postgres**

`app/knowledge/repository.py` 的 `DrugReader` Protocol 追加方法:

```python
    def list_drugs(self) -> list[dict[str, Any]]:
        """列出全部药品(id/brand_name/generic_name),按 id 升序。药品选择器数据源。"""
        ...
```

`InMemoryDrugRepository` 追加:

```python
    def list_drugs(self) -> list[dict[str, Any]]:
        return [
            {
                "id": d["id"],
                "brand_name": d["brand_name"],
                "generic_name": d["generic_name"],
            }
            for d in sorted(self._drugs.values(), key=lambda d: d["id"])
        ]
```

`PostgresDrugRepository` 追加:

```python
    def list_drugs(self) -> list[dict[str, Any]]:
        with self._conn.cursor() as cur:
            cur.execute("select id, brand_name, generic_name from drugs order by id")
            return [
                dict(zip(("id", "brand_name", "generic_name"), row))
                for row in cur.fetchall()
            ]
```

`app/knowledge/sqlite_repo.py` 的 `SQLiteDrugRepository` 追加:

```python
    def list_drugs(self) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "select id, brand_name, generic_name from drugs order by id"
        )
        return [
            dict(zip(("id", "brand_name", "generic_name"), row))
            for row in cur.fetchall()
        ]
```

注:Postgres 实现与既有 `PostgresDrugRepository` 其他方法一样无 CI 单测(无 live 数据库,依赖延迟导入),SQL 与 SQLite 版逐字同构,靠 Step 4 的 InMemory/SQLite 测试 + Task 2 的路由测试覆盖语义。

- [ ] **Step 4: 运行测试,确认通过**

Run: `python -m pytest tests/test_drug_listing.py -v`
Expected: PASS(3 个)

- [ ] **Step 5: 全量回归**

Run: `python -m pytest tests/ -q`
Expected: 全绿(现有 287+ 无一失败)

- [ ] **Step 6: Commit**

```bash
git add app/knowledge/repository.py app/knowledge/sqlite_repo.py tests/test_drug_listing.py
git commit -m "feat(knowledge): 仓储增加 list_drugs(),供前端药品选择器使用"
```

---

## Task 2: 后端 — GET /api/v1/drugs 路由

**Files:**
- Modify: `app/api/schemas.py`(新增 DrugSummary)
- Create: `app/api/drug_routes.py`
- Modify: `app/main.py`(include 路由)
- Test: `tests/test_drug_listing.py`(追加路由测试类)

**Interfaces:**
- Consumes: Task 1 的 `list_drugs()`
- Produces: `GET /api/v1/drugs` → 200 `[{"drug_id": int, "brand_name": str, "generic_name": str | null}, ...]`

- [ ] **Step 1: 写失败测试**

在 `tests/test_drug_listing.py` 追加:

```python
@pytest.fixture
def client_inmemory() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_drug_repository] = lambda: _seed(
        InMemoryDrugRepository()
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client_sqlite() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_drug_repository] = lambda: _seed(
        SQLiteDrugRepository(":memory:")
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestDrugsRoute:
    def test_shape_inmemory(self, client_inmemory):
        resp = client_inmemory.get("/api/v1/drugs")
        assert resp.status_code == 200
        assert resp.json() == [
            {"drug_id": 1, "brand_name": "泰诺", "generic_name": None},
            {"drug_id": 2, "brand_name": "芬必得", "generic_name": None},
        ]

    def test_shape_sqlite(self, client_sqlite):
        resp = client_sqlite.get("/api/v1/drugs")
        assert resp.status_code == 200
        assert [d["brand_name"] for d in resp.json()] == ["泰诺", "芬必得"]
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `python -m pytest tests/test_drug_listing.py::TestDrugsRoute -v`
Expected: FAIL — 404(路由尚未注册)

- [ ] **Step 3: 新增 DrugSummary 响应模型**

在 `app/api/schemas.py` 的 `ChatResponse` 之后追加:

```python
class DrugSummary(BaseModel):
    """GET /api/v1/drugs 行:前端药品选择器只需 id / 商品名 / 通用名。"""

    drug_id: int
    brand_name: str
    generic_name: str | None = None
```

- [ ] **Step 4: 新建路由文件**

新建 `app/api/drug_routes.py`:

```python
"""药品列表路由:前端药品选择器的数据源(只读)。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from app.api.deps import get_drug_repository
from app.api.schemas import DrugSummary
from app.knowledge.repository import DrugReader

router = APIRouter()


@router.get("/drugs", response_model=list[DrugSummary])
async def list_drugs_endpoint(
    repo: DrugReader = Depends(get_drug_repository),
) -> list[DrugSummary]:
    """列出已入库药品(商品名 + 通用名),供前端药箱选择器检索。"""
    rows = await run_in_threadpool(repo.list_drugs)
    return [
        DrugSummary(
            drug_id=r["id"], brand_name=r["brand_name"], generic_name=r["generic_name"]
        )
        for r in rows
    ]
```

- [ ] **Step 5: 在 main.py 注册路由**

`app/main.py` 导入区追加:

```python
from app.api.drug_routes import router as drug_router
```

`create_app` 内现有两行 include 之后追加:

```python
    app.include_router(drug_router, prefix="/api/v1")
```

- [ ] **Step 6: 运行测试,确认通过**

Run: `python -m pytest tests/test_drug_listing.py -v`
Expected: PASS(5 个)

- [ ] **Step 7: Commit**

```bash
git add app/api/schemas.py app/api/drug_routes.py app/main.py tests/test_drug_listing.py
git commit -m "feat(api): GET /api/v1/drugs 药品列表端点(前端选择器数据源)"
```

---

## Task 3: 后端 — CORS 配置与中间件

**Files:**
- Modify: `app/config.py`(新增 `cors_origins` 字段)
- Modify: `app/main.py`(按配置挂 CORSMiddleware)
- Test: `tests/test_cors.py`(新建)

**Interfaces:**
- Consumes: `Settings`
- Produces: `cors_origins: str`(逗号分隔;空串 = 不挂中间件),默认包含 Vite 开发端口 5173

- [ ] **Step 1: 写失败测试**

新建 `tests/test_cors.py`:

```python
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
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `python -m pytest tests/test_cors.py -v`
Expected: FAIL — `TypeError: Settings ... unexpected keyword argument 'cors_origins'`

- [ ] **Step 3: 新增配置字段**

`app/config.py` 的 `Settings` 中 `data_dir` 字段之后追加:

```python
    # CORS 允许来源(逗号分隔)。空串 = 不挂 CORS 中间件。
    # 默认放行 Vite 开发服务器;部署时按实际域名覆盖。
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
```

- [ ] **Step 4: main.py 挂中间件**

`app/main.py` 导入区追加:

```python
from fastapi.middleware.cors import CORSMiddleware
```

将 `create_app` 开头改为先解析 settings,再按配置挂中间件(注意:原先 settings=None 时不覆盖依赖;现在统一解析后总是覆盖,行为更一致):

```python
def create_app(settings: Settings | None = None) -> FastAPI:
    """创建 FastAPI 应用实例。settings 为 None 时取全局缓存配置。"""
    if settings is None:
        settings = get_settings()
    app = FastAPI(
        title="PillClear",
        version="0.1.0",
        description="年轻人智能用药安全助手 —— C 端 OTC 用药安全助手",
    )

    if settings.cors_origins.strip():
        origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(router, prefix="/api/v1")
    app.include_router(medbox_router, prefix="/api/v1")
    app.include_router(drug_router, prefix="/api/v1")

    app.dependency_overrides[get_settings] = lambda: settings

    return app
```

- [ ] **Step 5: 运行测试,确认通过**

Run: `python -m pytest tests/test_cors.py -v`
Expected: PASS(4 个)

- [ ] **Step 6: 全量回归**

Run: `python -m pytest tests/ -q`
Expected: 全绿

- [ ] **Step 7: Commit**

```bash
git add app/config.py app/main.py tests/test_cors.py
git commit -m "feat(api): CORS 中间件 + cors_origins 配置(默认放行 Vite 开发端口)"
```

---

## Task 4: 前端脚手架 + 设计 token

**Files:**
- Create: `web/package.json`、`web/vite.config.ts`、`web/tsconfig.json`、`web/index.html`、`web/.gitignore`
- Create: `web/src/main.tsx`、`web/src/App.tsx`(最小壳,Task 12 整体重写)、`web/src/setupTests.ts`、`web/src/styles/index.css`
- Test: `web/src/App.test.tsx`

**Interfaces:**
- Produces: `npm run dev`(开发服务器,`/api` 代理到 127.0.0.1:8000)、`npx vitest run`(测试)、全套设计 token(CSS 变量 + 字体 + 背景 + 动画)

- [ ] **Step 1: package.json**

新建 `web/package.json`:

```json
{
  "name": "pillclear-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest"
  },
  "dependencies": {
    "@fontsource-variable/space-grotesk": "^5.0.0",
    "@fontsource/ibm-plex-mono": "^5.0.0",
    "@tanstack/react-query": "^5.0.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "react-router-dom": "^7.0.0"
  },
  "devDependencies": {
    "@tailwindcss/vite": "^4.0.0",
    "@testing-library/dom": "^10.0.0",
    "@testing-library/jest-dom": "^6.0.0",
    "@testing-library/react": "^16.0.0",
    "@testing-library/user-event": "^14.0.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.0.0",
    "jsdom": "^25.0.0",
    "tailwindcss": "^4.0.0",
    "typescript": "^5.6.0",
    "vite": "^6.0.0",
    "vitest": "^3.0.0"
  }
}
```

- [ ] **Step 2: 安装依赖**

Run: `cd web && npm install`
Expected: 生成 `package-lock.json` 与 `node_modules/`,无报错

- [ ] **Step 3: vite.config.ts**

新建 `web/vite.config.ts`:

```ts
/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    environmentOptions: { jsdom: { pretendToBeVisual: true } }, // 提供 requestAnimationFrame(DoseMeter 动画依赖)
    globals: true,
    setupFiles: ["./src/setupTests.ts"],
  },
});
```

- [ ] **Step 4: tsconfig.json**

新建 `web/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "verbatimModuleSyntax": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src", "vite.config.ts"]
}
```

- [ ] **Step 5: index.html + .gitignore + setupTests.ts**

新建 `web/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="description" content="PillClear — 年轻人用药安全助手:OTC 药冲突检查、重复成分筛查" />
    <title>PillClear · 用药安全助手</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

新建 `web/.gitignore`:

```
node_modules/
dist/
```

新建 `web/src/setupTests.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 6: 设计 token — styles/index.css**

新建 `web/src/styles/index.css`。「数字说明书」视觉基座:药房绿主色、诊疗格纸背景、两款拉丁字体 + 中文系统栈、入场动画:

```css
@import "@fontsource-variable/space-grotesk";
@import "@fontsource/ibm-plex-mono/400.css";
@import "@fontsource/ibm-plex-mono/500.css";
@import "tailwindcss";

@theme {
  --color-ink: #1a2823;
  --color-mute: #5c6b64;
  --color-paper: #f4f7f5;
  --color-card: #ffffff;
  --color-line: #dce5e0;
  --color-pharma: #0e8a6a;
  --color-pharma-deep: #0a6b52;
  --color-pharma-soft: #e3f1ec;
  --color-danger: #c6362f;
  --color-danger-soft: #fbeae9;
  --color-warn: #b7791f;
  --color-warn-soft: #fbf3e4;
  --color-info: #2b6cb0;
  --color-info-soft: #e8f0f9;

  --font-display: "Space Grotesk Variable", "PingFang SC", "MiSans", "Microsoft YaHei", sans-serif;
  --font-body: "PingFang SC", "MiSans", "Microsoft YaHei", "Noto Sans CJK SC", system-ui, sans-serif;
  --font-mono-data: "IBM Plex Mono", "SFMono-Regular", Consolas, "Liberation Mono", monospace;

  --animate-bubble-in: bubble-in 0.35s cubic-bezier(0.22, 1, 0.36, 1) both;
  --animate-fade-up: fade-up 0.4s cubic-bezier(0.22, 1, 0.36, 1) both;
  --animate-dot: dot 1s ease-in-out infinite;

  @keyframes bubble-in {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: none; }
  }
  @keyframes fade-up {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: none; }
  }
  @keyframes dot {
    0%, 100% { transform: translateY(0); opacity: 0.45; }
    50% { transform: translateY(-4px); opacity: 1; }
  }
}

/* 诊疗格纸背景:顶部淡绿光晕 + 双向细网格(剂量记录纸质感) */
@utility bg-dosage-grid {
  background-image:
    radial-gradient(60rem 24rem at 50% -8rem, rgb(14 138 106 / 0.08), transparent),
    repeating-linear-gradient(0deg, rgb(26 40 35 / 0.028) 0 1px, transparent 1px 32px),
    repeating-linear-gradient(90deg, rgb(26 40 35 / 0.028) 0 1px, transparent 1px 32px);
}

@layer base {
  body {
    @apply bg-paper font-body text-ink antialiased;
  }
  ::selection {
    background: var(--color-pharma-soft);
  }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 7: main.tsx + 最小 App 壳**

新建 `web/src/main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles/index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

新建 `web/src/App.tsx`(最小壳;Task 12 整体重写为完整路由布局):

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <div className="min-h-dvh bg-paper bg-dosage-grid font-body text-ink">
          <header className="border-b border-line bg-card px-4 py-3.5 font-display text-lg font-bold">
            PillClear
          </header>
          <main className="p-4 text-sm text-mute">脚手架就绪。</main>
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
```

- [ ] **Step 8: 冒烟测试**

新建 `web/src/App.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import App from "./App";

it("渲染应用外壳", () => {
  render(<App />);
  expect(screen.getByText("PillClear")).toBeInTheDocument();
});
```

Run: `cd web && npx vitest run`
Expected: PASS(1 个)

- [ ] **Step 9: 类型检查**

Run: `cd web && npx tsc -b`
Expected: 无输出(无类型错误)

- [ ] **Step 10: Commit**

```bash
git add web/
git commit -m "feat(web): Vite + Tailwind v4 脚手架与设计 token(数字说明书视觉基座)"
```

---

## Task 5: 前端 lib 层 — types / api / device / format

**Files:**
- Create: `web/src/types/api.ts`、`web/src/lib/api.ts`、`web/src/lib/device.ts`、`web/src/lib/format.ts`
- Test: `web/src/lib/__tests__/api.test.ts`、`web/src/lib/__tests__/device.test.ts`、`web/src/lib/__tests__/format.test.ts`

**Interfaces:**
- Produces(后续所有 Task 依赖):
  - `types/api.ts`:`ChatResponse`、`Citation`、`MedboxItem`、`MedboxResponse`、`DrugSummary`、`IngredientTotal`、`CheckReport`、`TriggeredRule`
  - `api.ts`:`ApiError`(kind: `"llm" | "http" | "network"`)、`postChat(query)`、`getHealth()`、`listDrugs()`、`getMedbox(deviceId)`、`addMedboxItem(deviceId, item)`、`removeMedboxItem(deviceId, drugId)`、`checkMedbox(items, substances)`
  - `device.ts`:`getDeviceId(): string`
  - `format.ts`:`formatMg(mg: number): string`

- [ ] **Step 1: 写失败测试 — api**

新建 `web/src/lib/__tests__/api.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  addMedboxItem,
  checkMedbox,
  getMedbox,
  listDrugs,
  postChat,
  removeMedboxItem,
} from "../api";

const jsonResponse = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });

afterEach(() => vi.unstubAllGlobals());

describe("postChat", () => {
  it("POST query 到 /api/v1/chat 并解析响应", async () => {
    const body = {
      blocked: false, category: null, boundary_message: null,
      answer: "不建议同服。", confidence: 0.9, citations: [],
      sources_note: null, disclaimer: "仅供参考。",
    };
    const fetchMock = vi.fn(async () => jsonResponse(body));
    vi.stubGlobal("fetch", fetchMock);

    const res = await postChat("泰诺能吃吗");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/chat",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ query: "泰诺能吃吗" }),
      }),
    );
    expect(res.answer).toBe("不建议同服。");
  });

  it("502 映射为 kind=llm", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ detail: "AI 服务暂时不可用" }, 502)));
    await expect(postChat("x")).rejects.toMatchObject({ kind: "llm", status: 502 });
  });

  it("其他 HTTP 错误映射为 kind=http", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({}, 500)));
    await expect(postChat("x")).rejects.toMatchObject({ kind: "http", status: 500 });
  });

  it("网络异常映射为 kind=network", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("fetch failed"); }));
    await expect(postChat("x")).rejects.toMatchObject({ kind: "network" });
  });
});

describe("medbox 端点映射", () => {
  it("listDrugs 走 GET /api/v1/drugs", async () => {
    const fetchMock = vi.fn(async () => jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);
    await listDrugs();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/drugs",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method ?? "GET").toBe("GET");
  });

  it("getMedbox 路径含 device_id", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ device_id: "d1", items: [] }));
    vi.stubGlobal("fetch", fetchMock);
    await getMedbox("d1");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/medbox/d1",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("addMedboxItem POST 完整条目", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ device_id: "d1", items: [] }));
    vi.stubGlobal("fetch", fetchMock);
    await addMedboxItem("d1", { drug_id: 3, brand_name: "芬必得", dosage_per_day: null });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/medbox/d1/items",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ drug_id: 3, brand_name: "芬必得", dosage_per_day: null }),
      }),
    );
  });

  it("removeMedboxItem 走 DELETE", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ device_id: "d1", items: [] }));
    vi.stubGlobal("fetch", fetchMock);
    await removeMedboxItem("d1", 3);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/medbox/d1/items/3",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("checkMedbox 上送 items 与 lifestyle_substances", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({ overlap: { overlapping: [], warnings: [] }, triggered_rules: [], unresolved_drugs: [] }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await checkMedbox([{ drug_id: 1, brand_name: "泰诺", dosage_per_day: 3 }], ["酒精"]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/medbox/check",
      expect.objectContaining({
        body: JSON.stringify({
          items: [{ drug_id: 1, brand_name: "泰诺", dosage_per_day: 3 }],
          lifestyle_substances: ["酒精"],
        }),
      }),
    );
  });
});
```

注意:`listDrugs`/`getMedbox` 不传 init,`request()` 只补 `signal`,因此断言 GET 时用 `init.method ?? "GET"`。

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd web && npx vitest run src/lib/__tests__/api.test.ts`
Expected: FAIL — `Cannot find module '../api'`

- [ ] **Step 3: 实现 types/api.ts**

新建 `web/src/types/api.ts`(后端 Pydantic schema 的 TS 镜像):

```ts
/** GET /api/v1/drugs 行。 */
export interface DrugSummary {
  drug_id: number;
  brand_name: string;
  generic_name: string | null;
}

export interface Citation {
  brand_name: string;
  section: string;
  excerpt: string;
}

export interface ChatResponse {
  blocked: boolean;
  category: "emergency" | "special_population" | "diagnosis" | "prescription" | null;
  boundary_message: string | null;
  answer: string | null;
  confidence: number | null;
  citations: Citation[];
  sources_note: string | null;
  disclaimer: string | null;
}

export interface MedboxItem {
  drug_id: number;
  brand_name: string;
  dosage_per_day: number | null;
}

export interface MedboxResponse {
  device_id: string;
  items: MedboxItem[];
}

export interface IngredientTotal {
  name: string;
  total_amount_mg: number;
  sources: string[];
  max_daily_mg: number | null;
}

export interface OverlapResult {
  overlapping: IngredientTotal[];
  warnings: string[];
}

export interface TriggeredRule {
  id: string;
  title: string;
  severity: "danger" | "warning" | "info";
  description: string;
  warning: string;
  confidence: "high" | "medium" | "low";
  source: string | null;
}

export interface CheckReport {
  overlap: OverlapResult;
  triggered_rules: TriggeredRule[];
  unresolved_drugs: string[];
}
```

- [ ] **Step 4: 实现 lib/api.ts**

新建 `web/src/lib/api.ts`:

```ts
import type {
  ChatResponse,
  CheckReport,
  DrugSummary,
  MedboxItem,
  MedboxResponse,
} from "../types/api";

export type ApiErrorKind = "llm" | "http" | "network";

export class ApiError extends Error {
  kind: ApiErrorKind;
  status?: number;

  constructor(kind: ApiErrorKind, message: string, status?: number) {
    super(message);
    this.kind = kind;
    this.status = status;
  }
}

const TIMEOUT_MS = 60_000;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(path, { ...init, signal: controller.signal });
  } catch (err) {
    const message =
      err instanceof DOMException && err.name === "AbortError"
        ? "请求超时"
        : "网络异常";
    throw new ApiError("network", message);
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    if (res.status === 502) {
      throw new ApiError("llm", "AI 服务暂时不可用", 502);
    }
    throw new ApiError("http", `服务异常(${res.status})`, res.status);
  }
  return (await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const getHealth = () => request<{ status: string }>("/api/v1/health");

export const postChat = (query: string) =>
  request<ChatResponse>("/api/v1/chat", json({ query }));

export const listDrugs = () => request<DrugSummary[]>("/api/v1/drugs");

export const getMedbox = (deviceId: string) =>
  request<MedboxResponse>(`/api/v1/medbox/${deviceId}`);

export const addMedboxItem = (
  deviceId: string,
  item: { drug_id: number; brand_name: string; dosage_per_day: number | null },
) => request<MedboxResponse>(`/api/v1/medbox/${deviceId}/items`, json(item));

export const removeMedboxItem = (deviceId: string, drugId: number) =>
  request<MedboxResponse>(`/api/v1/medbox/${deviceId}/items/${drugId}`, {
    method: "DELETE",
  });

export const checkMedbox = (items: MedboxItem[], lifestyleSubstances: string[]) =>
  request<CheckReport>("/api/v1/medbox/check", json({
    items,
    lifestyle_substances: lifestyleSubstances,
  }));
```

- [ ] **Step 5: 运行 api 测试,确认通过**

Run: `cd web && npx vitest run src/lib/__tests__/api.test.ts`
Expected: PASS(9 个)

- [ ] **Step 6: device.ts + 测试**

新建 `web/src/lib/device.ts`:

```ts
const KEY = "pillclear_device_id";

/** MVP 用户标识:首次访问生成 UUID 并持久化,后续读取同一值。 */
export function getDeviceId(): string {
  const existing = localStorage.getItem(KEY);
  if (existing) return existing;
  const id = crypto.randomUUID();
  localStorage.setItem(KEY, id);
  return id;
}
```

新建 `web/src/lib/__tests__/device.test.ts`:

```ts
import { beforeEach, expect, it, vi } from "vitest";
import { getDeviceId } from "../device";

beforeEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

it("首次调用生成并持久化", () => {
  vi.stubGlobal("crypto", { randomUUID: () => "uuid-1234" });
  expect(getDeviceId()).toBe("uuid-1234");
  expect(localStorage.getItem("pillclear_device_id")).toBe("uuid-1234");
});

it("二次调用读取已有值,不重新生成", () => {
  const gen = vi.fn(() => "new-uuid");
  vi.stubGlobal("crypto", { randomUUID: gen });
  localStorage.setItem("pillclear_device_id", "existing");
  expect(getDeviceId()).toBe("existing");
  expect(gen).not.toHaveBeenCalled();
});
```

- [ ] **Step 7: format.ts + 测试**

新建 `web/src/lib/format.ts`:

```ts
/** 剂量数字格式化:整数不带小数点(1975.0 → "1975"),否则保留一位。 */
export function formatMg(mg: number): string {
  return Number.isInteger(mg) ? String(mg) : mg.toFixed(1);
}
```

新建 `web/src/lib/__tests__/format.test.ts`:

```ts
import { expect, it } from "vitest";
import { formatMg } from "../format";

it("整数省略小数", () => {
  expect(formatMg(1975)).toBe("1975");
  expect(formatMg(4000)).toBe("4000");
});

it("非整数保留一位", () => {
  expect(formatMg(325.5)).toBe("325.5");
});
```

- [ ] **Step 8: 全部 lib 测试通过**

Run: `cd web && npx vitest run src/lib/`
Expected: PASS(12 个)

- [ ] **Step 9: Commit**

```bash
git add web/src/types/ web/src/lib/
git commit -m "feat(web): typed API 层 + device_id + 剂量格式化(错误三分类 llm/http/network)"
```

---

## Task 6: UI 原语组件

**Files:**
- Create: `web/src/components/ui/` 下 `Badge.tsx`、`Chip.tsx`、`CapsuleButton.tsx`、`SectionTitle.tsx`、`EmptyState.tsx`、`Logo.tsx`
- Test: `web/src/components/ui/__tests__/primitives.test.tsx`

**Interfaces:**
- Produces:`Badge({tone?, children})`(tone: pharma/danger/warn/info/mute)、`Chip({active?, onClick?, children})`(带 aria-pressed)、`CapsuleButton({variant?, size?, ...button 属性})`、`SectionTitle({children})`、`EmptyState({title, hint?})`、`Logo({className?})`

- [ ] **Step 1: 写失败测试**

新建 `web/src/components/ui/__tests__/primitives.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { Badge } from "../Badge";
import { CapsuleButton } from "../CapsuleButton";
import { Chip } from "../Chip";
import { EmptyState } from "../EmptyState";
import { Logo } from "../Logo";
import { SectionTitle } from "../SectionTitle";

it("Chip 反映 pressed 状态并响应点击", async () => {
  const onClick = vi.fn();
  render(<Chip active onClick={onClick}>酒精</Chip>);
  const chip = screen.getByRole("button", { name: "酒精" });
  expect(chip).toHaveAttribute("aria-pressed", "true");
  await userEvent.setup().click(chip);
  expect(onClick).toHaveBeenCalledTimes(1);
});

it("CapsuleButton disabled 时不触发点击", async () => {
  const onClick = vi.fn();
  render(<CapsuleButton disabled onClick={onClick}>发送</CapsuleButton>);
  await userEvent.setup().click(screen.getByRole("button", { name: "发送" }));
  expect(onClick).not.toHaveBeenCalled();
});

it("Badge 渲染子内容", () => {
  render(<Badge tone="danger">危险</Badge>);
  expect(screen.getByText("危险")).toBeInTheDocument();
});

it("SectionTitle 渲染 h2", () => {
  render(<SectionTitle>成分叠加</SectionTitle>);
  expect(screen.getByRole("heading", { level: 2, name: "成分叠加" })).toBeInTheDocument();
});

it("EmptyState 渲染标题与提示", () => {
  render(<EmptyState title="药箱是空的" hint="先添加你正在吃的药" />);
  expect(screen.getByText("药箱是空的")).toBeInTheDocument();
  expect(screen.getByText("先添加你正在吃的药")).toBeInTheDocument();
});

it("Logo 带无障碍标签", () => {
  render(<Logo />);
  expect(screen.getByLabelText("PillClear")).toBeInTheDocument();
});
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd web && npx vitest run src/components/`
Expected: FAIL — 模块不存在

- [ ] **Step 3: 实现六个组件**

`web/src/components/ui/Badge.tsx`:

```tsx
import type { ReactNode } from "react";

const TONES = {
  pharma: "border-pharma/30 bg-pharma-soft text-pharma-deep",
  danger: "border-danger/30 bg-danger-soft text-danger",
  warn: "border-warn/30 bg-warn-soft text-warn",
  info: "border-info/30 bg-info-soft text-info",
  mute: "border-line bg-paper text-mute",
} as const;

export type BadgeTone = keyof typeof TONES;

export function Badge({ tone = "mute", children }: { tone?: BadgeTone; children: ReactNode }) {
  return (
    <span className={`inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${TONES[tone]}`}>
      {children}
    </span>
  );
}
```

`web/src/components/ui/Chip.tsx`:

```tsx
import type { ReactNode } from "react";

export function Chip({
  active = false,
  onClick,
  children,
}: {
  active?: boolean;
  onClick?: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`rounded-full border px-3 py-1 text-xs font-medium transition-all duration-150 active:scale-95 ${
        active
          ? "border-pharma bg-pharma text-white shadow-sm"
          : "border-line bg-card text-mute hover:border-pharma/50 hover:text-pharma-deep"
      }`}
    >
      {children}
    </button>
  );
}
```

`web/src/components/ui/CapsuleButton.tsx`:

```tsx
import type { ButtonHTMLAttributes } from "react";

const VARIANTS = {
  primary: "bg-pharma text-white shadow-sm hover:bg-pharma-deep disabled:bg-mute/40",
  ghost: "border border-line bg-card text-ink hover:border-pharma/50 hover:text-pharma-deep disabled:opacity-40",
  danger: "bg-danger text-white hover:bg-danger/90 disabled:opacity-40",
} as const;

const SIZES = {
  md: "px-4 py-2 text-sm",
  sm: "px-3 py-1.5 text-xs",
} as const;

export function CapsuleButton({
  variant = "primary",
  size = "md",
  className = "",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof VARIANTS;
  size?: keyof typeof SIZES;
}) {
  return (
    <button
      type="button"
      {...rest}
      className={`rounded-full font-medium transition-all duration-150 active:scale-[0.97] disabled:cursor-not-allowed disabled:active:scale-100 ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
    />
  );
}
```

`web/src/components/ui/SectionTitle.tsx`:

```tsx
import type { ReactNode } from "react";

export function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h2 className="flex items-center gap-2 font-display text-[13px] font-bold tracking-[0.12em] text-ink/80">
      <span className="inline-block h-2.5 w-2.5 rounded-[3px] bg-pharma" aria-hidden />
      {children}
    </h2>
  );
}
```

`web/src/components/ui/Logo.tsx`(双色胶囊,旋转 -30°):

```tsx
export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} role="img" aria-label="PillClear">
      <g transform="rotate(-30 16 16)">
        <rect x="3" y="10.5" width="26" height="11" rx="5.5" fill="#0e8a6a" />
        <path d="M16 10.5h7.5a5.5 5.5 0 0 1 0 11H16v-11z" fill="#e3f1ec" />
        <rect x="15" y="10.5" width="2" height="11" fill="#ffffff" />
      </g>
    </svg>
  );
}
```

`web/src/components/ui/EmptyState.tsx`:

```tsx
import { Logo } from "./Logo";

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-dashed border-line bg-paper/60 px-4 py-6 text-center">
      <Logo className="mx-auto h-8 w-8 opacity-40" />
      <p className="mt-2 text-sm font-medium">{title}</p>
      {hint && <p className="mt-1 text-xs text-mute">{hint}</p>}
    </div>
  );
}
```

- [ ] **Step 4: 运行测试,确认通过**

Run: `cd web && npx vitest run src/components/`
Expected: PASS(6 个)

- [ ] **Step 5: Commit**

```bash
git add web/src/components/
git commit -m "feat(web): UI 原语(Badge/Chip/CapsuleButton/SectionTitle/EmptyState/Logo)"
```

---

## Task 7: 聊天展示组件

**Files:**
- Create: `web/src/features/chat/` 下 `MessageBubble.tsx`、`CitationCard.tsx`、`AssistantLoading.tsx`、`QuickStart.tsx`
- Test: `web/src/features/chat/__tests__/presentation.test.tsx`

**Interfaces:**
- Consumes: Task 5 的 `types/api.ts`(`ChatResponse`、`Citation`);Task 6 的 `Badge`
- Produces:
  - `ChatMsg`(消息模型,Task 8 复用):`{ id: number; role: "user" | "assistant"; query: string; resp?: ChatResponse; status: "pending" | "ok" | "error"; errorKind?: "llm" | "network" }`
  - `MessageBubble({ msg, onRetry })`、`CitationCard({ citation })`、`AssistantLoading()`、`QuickStart({ onAsk })`、`QUICK_QUESTIONS: string[]`(恰好 4 条)

- [ ] **Step 1: 写失败测试**

新建 `web/src/features/chat/__tests__/presentation.test.tsx`:

```tsx
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatResponse } from "../../../types/api";
import { AssistantLoading } from "../AssistantLoading";
import { CitationCard } from "../CitationCard";
import { MessageBubble, type ChatMsg } from "../MessageBubble";
import { QUICK_QUESTIONS, QuickStart } from "../QuickStart";

const citation = { brand_name: "泰诺", section: "用法用量", excerpt: "成人一次1-2片,一日3次。" };

function okMsg(resp: Partial<ChatResponse>): ChatMsg {
  return {
    id: 1, role: "assistant", query: "q", status: "ok",
    resp: {
      blocked: false, category: null, boundary_message: null,
      answer: "不建议同服。", confidence: 0.9, citations: [citation],
      sources_note: null, disclaimer: "仅供参考,不能替代医嘱。", ...resp,
    },
  };
}

describe("CitationCard", () => {
  it("默认收起(aria-expanded=false),点击后展开", async () => {
    render(<CitationCard citation={citation} />);
    const btn = screen.getByRole("button");
    expect(btn).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText(citation.excerpt)).toBeInTheDocument();
    await userEvent.setup().click(btn);
    expect(btn).toHaveAttribute("aria-expanded", "true");
  });

  it("展示商品名与章节", () => {
    render(<CitationCard citation={citation} />);
    expect(screen.getByText("泰诺 · 用法用量")).toBeInTheDocument();
  });
});

describe("MessageBubble", () => {
  it("渲染回答、引用卡与免责声明", () => {
    render(<MessageBubble msg={okMsg({})} onRetry={() => {}} />);
    expect(screen.getByText("不建议同服。")).toBeInTheDocument();
    expect(screen.getByText("泰诺 · 用法用量")).toBeInTheDocument();
    expect(screen.getByText("仅供参考,不能替代医嘱。")).toBeInTheDocument();
  });

  it("低置信度(<0.5)显示不确定 chip", () => {
    render(<MessageBubble msg={okMsg({ confidence: 0.3 })} onRetry={() => {}} />);
    expect(screen.getByText("不太确定,请咨询药师")).toBeInTheDocument();
  });

  it("置信度 ≥0.5 不显示 chip", () => {
    render(<MessageBubble msg={okMsg({ confidence: 0.5 })} onRetry={() => {}} />);
    expect(screen.queryByText("不太确定,请咨询药师")).not.toBeInTheDocument();
  });

  it("blocked 时渲染边界话术而非回答", () => {
    render(
      <MessageBubble
        msg={okMsg({ blocked: true, category: "diagnosis", boundary_message: "这属于诊断范畴,请咨询医生。", answer: null, citations: [], disclaimer: null })}
        onRetry={() => {}}
      />,
    );
    expect(screen.getByText("这属于诊断范畴,请咨询医生。")).toBeInTheDocument();
    expect(screen.queryByText("不建议同服。")).not.toBeInTheDocument();
  });

  it("llm 错误渲染重试卡,点击触发 onRetry", async () => {
    const onRetry = vi.fn();
    render(<MessageBubble msg={{ id: 2, role: "assistant", query: "q", status: "error", errorKind: "llm" }} onRetry={onRetry} />);
    expect(screen.getByText("AI 服务暂时不可用,请稍后重试")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "重试" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("network 错误使用网络文案", () => {
    render(<MessageBubble msg={{ id: 2, role: "assistant", query: "q", status: "error", errorKind: "network" }} onRetry={() => {}} />);
    expect(screen.getByText("网络好像断了,检查一下再试")).toBeInTheDocument();
  });
});

describe("QuickStart", () => {
  it("恰好 4 条预置问题,点击触发 onAsk", async () => {
    const onAsk = vi.fn();
    render(<QuickStart onAsk={onAsk} />);
    expect(QUICK_QUESTIONS).toHaveLength(4);
    await userEvent.setup().click(screen.getByText(QUICK_QUESTIONS[0]));
    expect(onAsk).toHaveBeenCalledWith(QUICK_QUESTIONS[0]);
  });
});

describe("AssistantLoading", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("按时间轮播状态文案", () => {
    render(<AssistantLoading />);
    expect(screen.getByText("正在理解你的问题…")).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(3100); });
    expect(screen.getByText("翻阅说明书…")).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(5000); });
    expect(screen.getByText("比对安全规则…")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd web && npx vitest run src/features/chat/`
Expected: FAIL — 模块不存在

- [ ] **Step 3: CitationCard**

新建 `web/src/features/chat/CitationCard.tsx`:

```tsx
import { useState } from "react";
import type { Citation } from "../../types/api";

export function CitationCard({ citation }: { citation: Citation }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-line bg-paper">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition-colors hover:bg-pharma-soft/50"
      >
        <svg viewBox="0 0 24 24" className={`h-3 w-3 shrink-0 text-mute transition-transform duration-200 ${open ? "rotate-90" : ""}`} fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden>
          <path d="M9 5l7 7-7 7" />
        </svg>
        <span className="font-semibold text-pharma-deep">说明书原文</span>
        <span className="truncate text-mute">{citation.brand_name} · {citation.section}</span>
      </button>
      <div className="grid transition-[grid-template-rows] duration-300 ease-out" style={{ gridTemplateRows: open ? "1fr" : "0fr" }}>
        <div className="overflow-hidden">
          <blockquote className="mx-3 mb-3 border-l-2 border-pharma px-3 py-1.5 text-[13px] leading-relaxed text-ink/80">
            {citation.excerpt}
          </blockquote>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: AssistantLoading**

新建 `web/src/features/chat/AssistantLoading.tsx`(胶囊形跳点 + 轮播文案,缓解非流式长等待):

```tsx
import { useEffect, useState } from "react";

const STAGES: Array<[delayMs: number, text: string]> = [
  [0, "正在理解你的问题…"],
  [3000, "翻阅说明书…"],
  [8000, "比对安全规则…"],
  [15000, "组织回答,马上好…"],
];

export function AssistantLoading() {
  const [stage, setStage] = useState(0);

  useEffect(() => {
    const timers = STAGES.map(([delay], i) => setTimeout(() => setStage(i), delay));
    return () => timers.forEach(clearTimeout);
  }, []);

  return (
    <div className="flex items-center gap-3" role="status" aria-live="polite">
      <span className="flex gap-1">
        {[0, 1, 2].map((i) => (
          <span key={i} className="h-2 w-3.5 animate-dot rounded-full bg-pharma" style={{ animationDelay: `${i * 160}ms` }} />
        ))}
      </span>
      <span className="text-sm text-mute">{STAGES[stage][1]}</span>
    </div>
  );
}
```

- [ ] **Step 5: MessageBubble(含 ChatMsg 模型与边界图标)**

新建 `web/src/features/chat/MessageBubble.tsx`:

```tsx
import { Badge } from "../../components/ui/Badge";
import { CapsuleButton } from "../../components/ui/CapsuleButton";
import type { ChatResponse } from "../../types/api";
import { AssistantLoading } from "./AssistantLoading";
import { CitationCard } from "./CitationCard";

/** 聊天消息模型(纯前端内存,不持久化)。query 在助手消息上保留,供失败重试。 */
export interface ChatMsg {
  id: number;
  role: "user" | "assistant";
  query: string;
  resp?: ChatResponse;
  status: "pending" | "ok" | "error";
  errorKind?: "llm" | "network";
}

const LOW_CONFIDENCE = 0.5; // 与后端 _LOW_CONFIDENCE_THRESHOLD 一致

const ERROR_COPY: Record<"llm" | "network", { title: string; hint: string }> = {
  llm: { title: "AI 服务暂时不可用,请稍后重试", hint: "服务繁忙,通常几分钟后恢复。" },
  network: { title: "网络好像断了,检查一下再试", hint: "确认后端服务(uvicorn)仍在运行。" },
};

const CATEGORY_LABEL: Record<NonNullable<ChatResponse["category"]>, string> = {
  emergency: "急症信号",
  special_population: "特殊人群",
  diagnosis: "症状解读",
  prescription: "处方药",
};

function BoundaryIcon({ category }: { category: ChatResponse["category"] }) {
  const cls = "h-5 w-5 shrink-0";
  const common = { className: cls, fill: "none", stroke: "currentColor", strokeWidth: 2, "aria-hidden": true } as const;
  switch (category) {
    case "emergency":
      return <svg viewBox="0 0 24 24" {...common}><circle cx="12" cy="12" r="9" /><path d="M12 7v6M12 16.5h.01" /></svg>;
    case "special_population":
      return <svg viewBox="0 0 24 24" {...common}><circle cx="12" cy="8" r="3.5" /><path d="M5 20c1.2-3.5 4-5 7-5s5.8 1.5 7 5" /></svg>;
    case "diagnosis":
      return <svg viewBox="0 0 24 24" {...common}><circle cx="10.5" cy="10.5" r="6" /><path d="M15.5 15.5L21 21" /></svg>;
    case "prescription":
      return <svg viewBox="0 0 24 24" {...common}><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M9 8h6M9 12h6M9 16h3" /></svg>;
    default:
      return <svg viewBox="0 0 24 24" {...common}><path d="M12 3L2.5 20h19L12 3z" /><path d="M12 10v4M12 17h.01" /></svg>;
  }
}

export function MessageBubble({ msg, onRetry }: { msg: ChatMsg; onRetry: (msg: ChatMsg) => void }) {
  if (msg.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] animate-bubble-in whitespace-pre-wrap rounded-2xl rounded-br-md bg-pharma-soft px-4 py-2.5 text-[15px] leading-relaxed">
          {msg.query}
        </div>
      </div>
    );
  }

  if (msg.status === "pending") {
    return <div className="animate-bubble-in rounded-xl border border-line bg-card p-4"><AssistantLoading /></div>;
  }

  if (msg.status === "error") {
    const copy = ERROR_COPY[msg.errorKind ?? "network"];
    return (
      <div className="animate-bubble-in rounded-xl border border-danger/30 bg-danger-soft p-4">
        <p className="text-sm font-semibold text-danger">{copy.title}</p>
        <p className="mt-1 text-xs text-ink/70">{copy.hint}</p>
        <CapsuleButton size="sm" className="mt-3" onClick={() => onRetry(msg)}>重试</CapsuleButton>
      </div>
    );
  }

  const resp = msg.resp;
  if (!resp) return null;

  if (resp.blocked) {
    return (
      <div className="animate-bubble-in border-l-4 border-pharma rounded-r-xl bg-paper p-4">
        <div className="flex items-center gap-2 text-pharma-deep">
          <BoundaryIcon category={resp.category} />
          {resp.category && <Badge tone="pharma">{CATEGORY_LABEL[resp.category]}</Badge>}
        </div>
        <p className="mt-2 whitespace-pre-wrap text-[15px] leading-relaxed">{resp.boundary_message}</p>
      </div>
    );
  }

  const uncertain = resp.confidence !== null && resp.confidence < LOW_CONFIDENCE;
  return (
    <div className="animate-bubble-in space-y-3 rounded-xl border border-line bg-card p-4">
      {uncertain && <Badge tone="warn">不太确定,请咨询药师</Badge>}
      <p className="whitespace-pre-wrap text-[15px] leading-relaxed">{resp.answer}</p>
      {resp.citations.length > 0 && (
        <div className="space-y-1.5">
          {resp.citations.map((c, i) => <CitationCard key={`${c.brand_name}-${i}`} citation={c} />)}
        </div>
      )}
      {resp.disclaimer && (
        <p className="border-t border-line pt-2.5 text-xs leading-relaxed text-mute">{resp.disclaimer}</p>
      )}
    </div>
  );
}
```

- [ ] **Step 6: QuickStart(泡罩板式快捷提问)**

新建 `web/src/features/chat/QuickStart.tsx`:

```tsx
import { SectionTitle } from "../../components/ui/SectionTitle";

/** 恰好 4 条:覆盖正常回答、规则命中、边界拦截三条路径——空状态即产品演示。 */
export const QUICK_QUESTIONS = [
  "泰诺和白加黑能一起吃吗?",
  "吃布洛芬期间能喝酒吗?",
  "布洛芬和对乙酰氨基酚哪个退烧好?",
  "我最近总是头疼怎么办?",
];

export function QuickStart({ onAsk }: { onAsk: (q: string) => void }) {
  return (
    <div className="mx-auto mt-8 max-w-xl lg:mt-16">
      <SectionTitle>试试这些常见问题</SectionTitle>
      <div className="mt-4 grid grid-cols-1 gap-px overflow-hidden rounded-xl border border-line bg-line shadow-sm sm:grid-cols-2">
        {QUICK_QUESTIONS.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onAsk(q)}
            className="group bg-card px-4 py-4 text-left transition-colors duration-150 hover:bg-pharma-soft"
          >
            <span className="mb-2 inline-block h-2 w-4 origin-left rounded-full bg-pharma/70 transition-transform duration-200 group-hover:scale-x-125" aria-hidden />
            <span className="block text-sm leading-snug">{q}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 7: 运行测试,确认通过**

Run: `cd web && npx vitest run src/features/chat/`
Expected: PASS(10 个)

- [ ] **Step 8: Commit**

```bash
git add web/src/features/chat/
git commit -m "feat(web): 聊天展示组件(消息气泡/引用折叠卡/边界卡/等待轮播/快捷提问)"
```

---

## Task 8: Composer + ChatView 状态机

**Files:**
- Create: `web/src/features/chat/Composer.tsx`、`web/src/features/chat/ChatView.tsx`
- Test: `web/src/features/chat/__tests__/ChatView.test.tsx`

**Interfaces:**
- Consumes: Task 5 的 `postChat` / `ApiError`;Task 7 的 `MessageBubble` / `QuickStart` / `ChatMsg`
- Produces: `Composer({ onSend, busy })`、`ChatView()`(自包含视图)

- [ ] **Step 1: 写失败测试**

新建 `web/src/features/chat/__tests__/ChatView.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../../../lib/api";
import type { ChatResponse } from "../../../types/api";
import { ChatView } from "../ChatView";

vi.mock("../../../lib/api");

const okResp: ChatResponse = {
  blocked: false, category: null, boundary_message: null,
  answer: "不建议一起吃,两者都含对乙酰氨基酚。", confidence: 0.9,
  citations: [{ brand_name: "泰诺", section: "成份", excerpt: "每片含对乙酰氨基酚325毫克" }],
  sources_note: null, disclaimer: "仅供参考,不能替代医嘱。",
};

beforeEach(() => vi.clearAllMocks());

describe("ChatView", () => {
  it("点快捷提问 → 渲染回答、引用与免责声明", async () => {
    vi.mocked(api.postChat).mockResolvedValue(okResp);
    render(<ChatView />);
    const user = userEvent.setup();

    await user.click(screen.getByText("泰诺和白加黑能一起吃吗?"));

    expect(screen.getByText("泰诺和白加黑能一起吃吗?")).toBeInTheDocument();
    expect(await screen.findByText(okResp.answer)).toBeInTheDocument();
    expect(screen.getByText("泰诺 · 成份")).toBeInTheDocument();
    expect(screen.getByText("仅供参考,不能替代医嘱。")).toBeInTheDocument();
  });

  it("手动输入并发送", async () => {
    vi.mocked(api.postChat).mockResolvedValue(okResp);
    render(<ChatView />);
    const user = userEvent.setup();

    await user.type(screen.getByRole("textbox"), "布洛芬怎么吃?");
    await user.click(screen.getByRole("button", { name: "发送" }));

    expect(api.postChat).toHaveBeenCalledWith("布洛芬怎么吃?");
    expect(await screen.findByText(okResp.answer)).toBeInTheDocument();
  });

  it("blocked 响应渲染边界话术", async () => {
    vi.mocked(api.postChat).mockResolvedValue({
      ...okResp, blocked: true, category: "emergency",
      boundary_message: "这可能危及生命,请立即拨打 120。", answer: null, citations: [], disclaimer: null,
    });
    render(<ChatView />);
    await userEvent.setup().click(screen.getByText("我最近总是头疼怎么办?"));
    expect(await screen.findByText("这可能危及生命,请立即拨打 120。")).toBeInTheDocument();
  });

  it("502 错误渲染重试卡,重试后恢复", async () => {
    vi.mocked(api.postChat)
      .mockRejectedValueOnce(new api.ApiError("llm", "AI 服务暂时不可用", 502))
      .mockResolvedValueOnce(okResp);
    render(<ChatView />);
    const user = userEvent.setup();

    await user.click(screen.getByText("吃布洛芬期间能喝酒吗?"));
    expect(await screen.findByText("AI 服务暂时不可用,请稍后重试")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(screen.getByText(okResp.answer)).toBeInTheDocument());
    expect(api.postChat).toHaveBeenCalledTimes(2);
  });

  it("网络错误使用网络文案", async () => {
    vi.mocked(api.postChat).mockRejectedValue(new api.ApiError("network", "网络异常"));
    render(<ChatView />);
    await userEvent.setup().click(screen.getByText("泰诺和白加黑能一起吃吗?"));
    expect(await screen.findByText("网络好像断了,检查一下再试")).toBeInTheDocument();
  });
});

describe("Composer", () => {
  it("空输入禁用发送", () => {
    render(<ChatView />);
    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
  });

  it("字数计数随输入更新", async () => {
    render(<ChatView />);
    await userEvent.setup().type(screen.getByRole("textbox"), "abc");
    expect(screen.getByText("3/2000")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd web && npx vitest run src/features/chat/__tests__/ChatView.test.tsx`
Expected: FAIL — 模块不存在

- [ ] **Step 3: Composer**

新建 `web/src/features/chat/Composer.tsx`:

```tsx
import { useState } from "react";
import { CapsuleButton } from "../../components/ui/CapsuleButton";

const MAX_LEN = 2000; // 对齐后端 ChatRequest.query max_length

export function Composer({ onSend, busy }: { onSend: (query: string) => void; busy: boolean }) {
  const [text, setText] = useState("");
  const over = text.length > MAX_LEN;
  const disabled = busy || text.trim() === "" || over;

  const submit = () => {
    if (disabled) return;
    onSend(text.trim());
    setText("");
  };

  return (
    <div className="rounded-xl border border-line bg-card p-3 shadow-sm transition-colors focus-within:border-pharma">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            submit();
          }
        }}
        rows={2}
        disabled={busy}
        placeholder="问问用药安全,比如:泰诺和白加黑能一起吃吗?(Enter 发送,Shift+Enter 换行)"
        className="w-full resize-none bg-transparent text-[15px] leading-relaxed outline-none placeholder:text-mute/60 disabled:opacity-60"
      />
      <div className="mt-1 flex items-center justify-between">
        <span className={`font-mono-data text-xs ${over ? "font-semibold text-danger" : "text-mute"}`}>
          {text.length}/{MAX_LEN}
        </span>
        <CapsuleButton onClick={submit} disabled={disabled}>
          {busy ? "思考中…" : "发送"}
        </CapsuleButton>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: ChatView**

新建 `web/src/features/chat/ChatView.tsx`:

```tsx
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, postChat } from "../../lib/api";
import type { ChatMsg } from "./MessageBubble";
import { MessageBubble } from "./MessageBubble";
import { Composer } from "./Composer";
import { QuickStart } from "./QuickStart";

export function ChatView() {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const idRef = useRef(1);
  const endRef = useRef<HTMLDivElement>(null);
  const busy = messages.some((m) => m.status === "pending");

  const send = useCallback(async (query: string) => {
    const userMsg: ChatMsg = { id: idRef.current++, role: "user", query, status: "ok" };
    const pendingId = idRef.current++;
    setMessages((ms) => [
      ...ms,
      userMsg,
      { id: pendingId, role: "assistant", query, status: "pending" },
    ]);
    try {
      const resp = await postChat(query);
      setMessages((ms) => ms.map((m) => (m.id === pendingId ? { ...m, resp, status: "ok" } : m)));
    } catch (err) {
      const errorKind: "llm" | "network" =
        err instanceof ApiError && err.kind === "llm" ? "llm" : "network";
      setMessages((ms) => ms.map((m) => (m.id === pendingId ? { ...m, status: "error", errorKind } : m)));
    }
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  return (
    <div className="flex flex-col gap-5">
      {messages.length === 0 ? (
        <QuickStart onAsk={send} />
      ) : (
        <div className="space-y-4">
          {messages.map((m) => (
            <MessageBubble key={m.id} msg={m} onRetry={(target) => send(target.query)} />
          ))}
          <div ref={endRef} />
        </div>
      )}
      <div className="sticky bottom-20 z-10 lg:bottom-4">
        <Composer onSend={send} busy={busy} />
      </div>
    </div>
  );
}
```

- [ ] **Step 5: 运行测试,确认通过**

Run: `cd web && npx vitest run src/features/chat/`
Expected: PASS(17 个:Task 7 的 10 + 本 Task 的 7)

- [ ] **Step 6: Commit**

```bash
git add web/src/features/chat/
git commit -m "feat(web): ChatView 状态机(发送/等待/边界/错误重试)与 Composer"
```

---

## Task 9: DoseMeter + RuleCard

**Files:**
- Create: `web/src/features/medbox/DoseMeter.tsx`、`web/src/features/medbox/RuleCard.tsx`
- Test: `web/src/features/medbox/__tests__/DoseMeter.test.tsx`、`web/src/features/medbox/__tests__/RuleCard.test.tsx`

**Interfaces:**
- Consumes: Task 5 的 `IngredientTotal` / `TriggeredRule` / `formatMg`;Task 6 的 `Badge`
- Produces: `DoseMeter({ item })`(动画剂量条)、`RuleCard({ rule, index? })`(severity 三色卡 + 证据徽章)

- [ ] **Step 1: 写失败测试 — DoseMeter**

新建 `web/src/features/medbox/__tests__/DoseMeter.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { DoseMeter } from "../DoseMeter";

const base = { name: "对乙酰氨基酚", total_amount_mg: 2000, sources: ["泰诺", "白加黑"], max_daily_mg: 4000 };

it("低于 70% 渲染绿色档与占比文案", () => {
  const { container } = render(<DoseMeter item={base} />);
  expect(screen.getByText("占安全上限 50%")).toBeInTheDocument();
  expect(container.querySelector(".bg-pharma")).not.toBeNull();
});

it("70%~100% 渲染琥珀档", () => {
  const { container } = render(<DoseMeter item={{ ...base, total_amount_mg: 3200 }} />);
  expect(screen.getByText("占安全上限 80%")).toBeInTheDocument();
  expect(container.querySelector(".bg-warn")).not.toBeNull();
});

it("超过上限渲染红色档与超限文案", () => {
  const { container } = render(<DoseMeter item={{ ...base, total_amount_mg: 4800 }} />);
  expect(screen.getByText("已超安全上限(约 120%)")).toBeInTheDocument();
  expect(container.querySelector(".bg-danger")).not.toBeNull();
});

it("上限未知渲染中性条与未知提示", () => {
  const { container } = render(<DoseMeter item={{ ...base, max_daily_mg: null }} />);
  expect(screen.getByText(/安全上限未知/)).toBeInTheDocument();
  expect(container.querySelector(".bg-pharma")).toBeNull();
  expect(container.querySelector(".bg-danger")).toBeNull();
});

it("展示来源药品与毫克数", () => {
  render(<DoseMeter item={base} />);
  expect(screen.getByText("来自:泰诺、白加黑")).toBeInTheDocument();
  expect(screen.getByText("2000")).toBeInTheDocument();
});
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd web && npx vitest run src/features/medbox/__tests__/DoseMeter.test.tsx`
Expected: FAIL — 模块不存在

- [ ] **Step 3: 实现 DoseMeter**

新建 `web/src/features/medbox/DoseMeter.tsx`:

```tsx
import { useEffect, useState } from "react";
import { formatMg } from "../../lib/format";
import type { IngredientTotal } from "../../types/api";

/** 成分日总量 vs 安全上限的动画剂量条。
 *  阶梯:<70% 绿 / 70%~100% 琥珀 / ≥100% 红(封顶 + 溢出刻线)。
 *  max 未知时渲染中性条 + 未知提示(铁律 #4:不确定必须明说)。 */
export function DoseMeter({ item }: { item: IngredientTotal }) {
  const ratio =
    item.max_daily_mg && item.max_daily_mg > 0
      ? item.total_amount_mg / item.max_daily_mg
      : null;
  const pct = ratio === null ? 100 : Math.min(ratio, 1) * 100;
  const over = ratio !== null && ratio > 1;

  const [width, setWidth] = useState(0);
  useEffect(() => {
    const raf = requestAnimationFrame(() => setWidth(pct));
    return () => cancelAnimationFrame(raf);
  }, [pct]);

  const barTone =
    ratio === null ? "bg-mute/40" : ratio < 0.7 ? "bg-pharma" : ratio < 1 ? "bg-warn" : "bg-danger";

  return (
    <div className="rounded-lg border border-line bg-card p-3 transition-shadow duration-200 hover:shadow-md">
      <div className="flex items-baseline justify-between gap-3">
        <div className="min-w-0">
          <p className="font-display font-semibold">{item.name}</p>
          <p className="truncate text-xs text-mute">来自:{item.sources.join("、")}</p>
        </div>
        <p className="shrink-0 font-mono-data text-lg font-medium leading-none">
          {formatMg(item.total_amount_mg)}
          <span className="ml-0.5 text-xs text-mute">mg</span>
          {item.max_daily_mg != null && (
            <span className="ml-2 text-xs font-normal text-mute">上限 {formatMg(item.max_daily_mg)}</span>
          )}
        </p>
      </div>
      <div className="relative mt-2.5 h-2.5 overflow-hidden rounded-full bg-paper ring-1 ring-line">
        <div
          className={`h-full rounded-full ${barTone} transition-[width] duration-700`}
          style={{ width: `${width}%`, transitionTimingFunction: "cubic-bezier(0.22, 1, 0.36, 1)" }}
        />
        {over && <div className="absolute inset-y-0 right-0 w-1 bg-danger" aria-hidden />}
      </div>
      <p className={`mt-1.5 text-xs ${over ? "font-semibold text-danger" : "text-mute"}`}>
        {ratio === null
          ? "安全上限未知——无法判断是否超量,请咨询药师"
          : over
            ? `已超安全上限(约 ${Math.round(ratio * 100)}%)`
            : `占安全上限 ${Math.round(ratio * 100)}%`}
      </p>
    </div>
  );
}
```

- [ ] **Step 4: 写失败测试 — RuleCard**

新建 `web/src/features/medbox/__tests__/RuleCard.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import type { TriggeredRule } from "../../../types/api";
import { RuleCard } from "../RuleCard";

const base: TriggeredRule = {
  id: "ibuprofen-alcohol",
  title: "布洛芬 + 酒精:伤胃又伤肝",
  severity: "danger",
  description: "两者同用显著增加消化道出血风险。",
  warning: "服用布洛芬期间饮酒会加重胃黏膜损伤,请避免饮酒。",
  confidence: "high",
  source: "药品说明书【注意事项】",
};

it("danger 渲染危险徽章并原样展示 warning 文案", () => {
  render(<RuleCard rule={base} />);
  expect(screen.getByText("危险")).toBeInTheDocument();
  expect(screen.getByText(base.warning)).toBeInTheDocument();
  expect(screen.getByText(base.source)).toBeInTheDocument();
});

it("warning / info 渲染对应徽章", () => {
  render(<RuleCard rule={{ ...base, id: "w", severity: "warning" }} />);
  expect(screen.getByText("注意")).toBeInTheDocument();
});

it("证据强度映射为中文徽章,medium/low 带保守提示", () => {
  render(<RuleCard rule={{ ...base, id: "m", confidence: "medium" }} />);
  const badge = screen.getByText("证据中等");
  expect(badge).toHaveAttribute("title", "证据有限,保守提示");
});

it("high 证据不带保守提示 tooltip", () => {
  render(<RuleCard rule={base} />);
  expect(screen.getByText("证据充分")).not.toHaveAttribute("title");
});
```

- [ ] **Step 5: 运行,确认失败**

Run: `cd web && npx vitest run src/features/medbox/__tests__/RuleCard.test.tsx`
Expected: FAIL — 模块不存在

- [ ] **Step 6: 实现 RuleCard**

新建 `web/src/features/medbox/RuleCard.tsx`:

```tsx
import type { TriggeredRule } from "../../types/api";
import { Badge } from "../../components/ui/Badge";

const SEVERITY_STYLES = {
  danger: "border-danger/50 bg-danger-soft",
  warning: "border-warn/50 bg-warn-soft",
  info: "border-info/50 bg-info-soft",
} as const;

const SEVERITY_LABEL = { danger: "危险", warning: "注意", info: "提示" } as const;
const SEVERITY_TONE = { danger: "danger", warning: "warn", info: "info" } as const;
const EVIDENCE_LABEL = { high: "证据充分", medium: "证据中等", low: "证据有限" } as const;

/** 规则卡:warning 文案由后端 format_warning 填充,前端原样展示,不改写。 */
export function RuleCard({ rule, index = 0 }: { rule: TriggeredRule; index?: number }) {
  const soft = rule.confidence !== "high";
  return (
    <article
      className={`animate-fade-up rounded-lg border-l-4 p-3.5 shadow-sm ${SEVERITY_STYLES[rule.severity]}`}
      style={{ animationDelay: `${index * 60}ms` }}
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-display text-[15px] font-semibold leading-snug">{rule.title}</h3>
        <Badge tone={SEVERITY_TONE[rule.severity]}>{SEVERITY_LABEL[rule.severity]}</Badge>
      </div>
      <p className="mt-1.5 text-sm leading-relaxed">{rule.warning}</p>
      <p className="mt-1 text-xs leading-relaxed text-ink/70">{rule.description}</p>
      <div className="mt-2 flex items-center gap-2 text-[11px] text-mute">
        <span
          title={soft ? "证据有限,保守提示" : undefined}
          className={`rounded-full border px-2 py-0.5 ${
            soft ? "border-warn/50 text-warn" : "border-pharma/40 text-pharma-deep"
          }`}
        >
          {EVIDENCE_LABEL[rule.confidence]}
        </span>
        {rule.source && <span className="truncate">{rule.source}</span>}
      </div>
    </article>
  );
}
```

- [ ] **Step 7: 两个测试文件全部通过**

Run: `cd web && npx vitest run src/features/medbox/`
Expected: PASS(9 个)

- [ ] **Step 8: Commit**

```bash
git add web/src/features/medbox/DoseMeter.tsx web/src/features/medbox/RuleCard.tsx web/src/features/medbox/__tests__/DoseMeter.test.tsx web/src/features/medbox/__tests__/RuleCard.test.tsx
git commit -m "feat(web): 剂量条(三档颜色/超限刻线/未知上限)与规则卡(severity 三色/证据徽章)"
```

---

## Task 10: DrugPicker + SubstanceChips

**Files:**
- Create: `web/src/features/medbox/DrugPicker.tsx`、`web/src/features/medbox/SubstanceChips.tsx`
- Test: `web/src/features/medbox/__tests__/DrugPicker.test.tsx`

**Interfaces:**
- Consumes: Task 5 的 `DrugSummary`;Task 6 的 `CapsuleButton` / `Chip`
- Produces:
  - `DrugPicker({ drugs, inBoxIds, onAdd })`,`onAdd(drug: DrugSummary, dosagePerDay: number | null)`
  - `SubstanceChips({ selected, onToggle })`、`SUBSTANCES: readonly ["酒精", "避孕药"]`

- [ ] **Step 1: 写失败测试**

新建 `web/src/features/medbox/__tests__/DrugPicker.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { DrugPicker } from "../DrugPicker";
import { SUBSTANCES, SubstanceChips } from "../SubstanceChips";

const drugs = [
  { drug_id: 1, brand_name: "泰诺", generic_name: "酚麻美敏片" },
  { drug_id: 2, brand_name: "芬必得", generic_name: "布洛芬缓释胶囊" },
];

it("按商品名与通用名过滤", async () => {
  render(<DrugPicker drugs={drugs} inBoxIds={new Set()} onAdd={() => {}} />);
  const user = userEvent.setup();

  await user.type(screen.getByPlaceholderText(/搜索药品/), "芬");
  expect(screen.getByText("芬必得")).toBeInTheDocument();
  expect(screen.queryByText("泰诺")).not.toBeInTheDocument();

  await user.clear(screen.getByPlaceholderText(/搜索药品/));
  await user.type(screen.getByPlaceholderText(/搜索药品/), "酚麻");
  expect(screen.getByText("泰诺")).toBeInTheDocument();
});

it("已在药箱的药显示为禁用状态", () => {
  render(<DrugPicker drugs={drugs} inBoxIds={new Set([1])} onAdd={() => {}} />);
  expect(screen.getByRole("button", { name: "已在药箱" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "加入" })).toBeEnabled();
});

it("默认日频次 1,确认后回调", async () => {
  const onAdd = vi.fn();
  render(<DrugPicker drugs={drugs} inBoxIds={new Set()} onAdd={onAdd} />);
  const user = userEvent.setup();

  await user.click(screen.getByRole("button", { name: "加入" }));
  await user.click(screen.getByRole("button", { name: "确认加入" }));

  expect(onAdd).toHaveBeenCalledWith(drugs[0], 1);
});

it("stepper 可加减且有上下界", async () => {
  const onAdd = vi.fn();
  render(<DrugPicker drugs={drugs} inBoxIds={new Set()} onAdd={onAdd} />);
  const user = userEvent.setup();

  await user.click(screen.getByRole("button", { name: "加入" }));
  await user.click(screen.getByRole("button", { name: "增加频次" }));
  await user.click(screen.getByRole("button", { name: "增加频次" }));
  await user.click(screen.getByRole("button", { name: "确认加入" }));

  expect(onAdd).toHaveBeenCalledWith(drugs[0], 3);
});

it("勾选不确定频次后 dosage 传 null", async () => {
  const onAdd = vi.fn();
  render(<DrugPicker drugs={drugs} inBoxIds={new Set()} onAdd={onAdd} />);
  const user = userEvent.setup();

  await user.click(screen.getByRole("button", { name: "加入" }));
  await user.click(screen.getByRole("checkbox", { name: "不确定频次" }));
  await user.click(screen.getByRole("button", { name: "确认加入" }));

  expect(onAdd).toHaveBeenCalledWith(drugs[0], null);
});

it("物质 chip 恰好两个且可切换", async () => {
  const onToggle = vi.fn();
  render(<SubstanceChips selected={["酒精"]} onToggle={onToggle} />);
  expect(SUBSTANCES).toEqual(["酒精", "避孕药"]);
  expect(screen.getByRole("button", { name: "酒精" })).toHaveAttribute("aria-pressed", "true");
  await userEvent.setup().click(screen.getByRole("button", { name: "避孕药" }));
  expect(onToggle).toHaveBeenCalledWith("避孕药");
});
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd web && npx vitest run src/features/medbox/__tests__/DrugPicker.test.tsx`
Expected: FAIL — 模块不存在

- [ ] **Step 3: SubstanceChips**

新建 `web/src/features/medbox/SubstanceChips.tsx`:

```tsx
import { Chip } from "../../components/ui/Chip";

/** 物质词表严格对应规则 YAML(alcohol.yaml / interaction.yaml),不造新词。 */
export const SUBSTANCES = ["酒精", "避孕药"] as const;

export function SubstanceChips({
  selected,
  onToggle,
}: {
  selected: string[];
  onToggle: (s: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-mute">同时在摄入:</span>
      {SUBSTANCES.map((s) => (
        <Chip key={s} active={selected.includes(s)} onClick={() => onToggle(s)}>
          {s}
        </Chip>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: DrugPicker**

新建 `web/src/features/medbox/DrugPicker.tsx`:

```tsx
import { useState } from "react";
import { CapsuleButton } from "../../components/ui/CapsuleButton";
import type { DrugSummary } from "../../types/api";

function Stepper({
  value,
  onChange,
  disabled,
}: {
  value: number;
  onChange: (v: number) => void;
  disabled: boolean;
}) {
  return (
    <div className={`flex items-center overflow-hidden rounded-full border border-line bg-card ${disabled ? "opacity-40" : ""}`}>
      <button
        type="button"
        aria-label="减少频次"
        disabled={disabled || value <= 1}
        onClick={() => onChange(Math.max(1, value - 1))}
        className="px-2.5 py-1 text-sm transition-colors hover:text-pharma-deep disabled:opacity-30"
      >
        −
      </button>
      <span className="min-w-8 text-center font-mono-data text-sm">{value}</span>
      <button
        type="button"
        aria-label="增加频次"
        disabled={disabled || value >= 10}
        onClick={() => onChange(Math.min(10, value + 1))}
        className="px-2.5 py-1 text-sm transition-colors hover:text-pharma-deep disabled:opacity-30"
      >
        +
      </button>
    </div>
  );
}

export function DrugPicker({
  drugs,
  inBoxIds,
  onAdd,
}: {
  drugs: DrugSummary[];
  inBoxIds: Set<number>;
  onAdd: (drug: DrugSummary, dosagePerDay: number | null) => void;
}) {
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState<number | null>(null);
  const [dosage, setDosage] = useState(1);
  const [unspecified, setUnspecified] = useState(false);

  const filtered = drugs.filter(
    (d) => q === "" || d.brand_name.includes(q) || (d.generic_name ?? "").includes(q),
  );

  const startAdd = (id: number) => {
    setAdding(id);
    setDosage(1);
    setUnspecified(false);
  };

  const confirm = (drug: DrugSummary) => {
    onAdd(drug, unspecified ? null : dosage);
    setAdding(null);
  };

  return (
    <div>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="搜索药品(商品名/通用名)"
        className="w-full rounded-lg border border-line bg-card px-3 py-2 text-sm outline-none transition-colors focus:border-pharma"
      />
      <ul className="mt-2 divide-y divide-line rounded-lg border border-line bg-card">
        {filtered.map((d) => {
          const inBox = inBoxIds.has(d.drug_id);
          return (
            <li key={d.drug_id} className="px-3 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="font-display font-semibold leading-tight">{d.brand_name}</p>
                  {d.generic_name && <p className="truncate text-xs text-mute">{d.generic_name}</p>}
                </div>
                <CapsuleButton
                  size="sm"
                  variant={inBox ? "ghost" : "primary"}
                  disabled={inBox}
                  onClick={() => startAdd(d.drug_id)}
                >
                  {inBox ? "已在药箱" : "加入"}
                </CapsuleButton>
              </div>
              {adding === d.drug_id && (
                <div className="mt-2.5 flex flex-wrap items-center gap-3 rounded-lg bg-paper p-2.5 animate-fade-up">
                  <label className="flex cursor-pointer items-center gap-1.5 text-xs text-mute">
                    <input
                      type="checkbox"
                      checked={unspecified}
                      onChange={(e) => setUnspecified(e.target.checked)}
                      className="accent-pharma"
                    />
                    不确定频次
                  </label>
                  <div className="flex items-center gap-1">
                    <Stepper value={dosage} onChange={setDosage} disabled={unspecified} />
                    <span className="text-xs text-mute">次/日</span>
                  </div>
                  <div className="ml-auto flex gap-2">
                    <CapsuleButton size="sm" variant="ghost" onClick={() => setAdding(null)}>
                      取消
                    </CapsuleButton>
                    <CapsuleButton size="sm" onClick={() => confirm(d)}>
                      确认加入
                    </CapsuleButton>
                  </div>
                </div>
              )}
            </li>
          );
        })}
        {filtered.length === 0 && (
          <li className="px-3 py-6 text-center text-sm text-mute">没有匹配的药——试试商品名,如"泰诺"</li>
        )}
      </ul>
    </div>
  );
}
```

- [ ] **Step 5: 运行,确认通过**

Run: `cd web && npx vitest run src/features/medbox/__tests__/DrugPicker.test.tsx`
Expected: PASS(6 个)

- [ ] **Step 6: Commit**

```bash
git add web/src/features/medbox/DrugPicker.tsx web/src/features/medbox/SubstanceChips.tsx web/src/features/medbox/__tests__/DrugPicker.test.tsx
git commit -m "feat(web): 药品选择器(本地搜索/频次 stepper/不确定频次)与物质 chip"
```

---

## Task 11: CheckReport + MedboxPanel(Query 集成)

**Files:**
- Create: `web/src/features/medbox/CheckReport.tsx`、`web/src/features/medbox/MedboxPanel.tsx`
- Test: `web/src/features/medbox/__tests__/CheckReport.test.tsx`、`web/src/features/medbox/__tests__/MedboxPanel.test.tsx`

**Interfaces:**
- Consumes: Task 5 全部 api 函数与 `getDeviceId`;Task 9 的 `DoseMeter` / `RuleCard`;Task 10 的 `DrugPicker` / `SubstanceChips`;Task 6 的 `CapsuleButton` / `EmptyState` / `SectionTitle`
- Produces:`CheckReport({ report })`(三段式报告)、`MedboxPanel({ variant: "rail" | "full" })`(药箱页/侧栏共用)

- [ ] **Step 1: 写失败测试 — CheckReport**

新建 `web/src/features/medbox/__tests__/CheckReport.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import type { CheckReport as CheckReportData } from "../../../types/api";
import { CheckReport } from "../CheckReport";

const full: CheckReportData = {
  overlap: {
    overlapping: [
      { name: "对乙酰氨基酚", total_amount_mg: 1975, sources: ["泰诺", "白加黑"], max_daily_mg: 4000 },
    ],
    warnings: ["对乙酰氨基酚日总量已超过安全上限"],
  },
  triggered_rules: [
    {
      id: "ibuprofen-alcohol", title: "布洛芬 + 酒精", severity: "danger",
      description: "描述。", warning: "警告文案。", confidence: "high", source: "来源",
    },
  ],
  unresolved_drugs: ["某特效药"],
};

it("三段齐全:警告横幅 / 剂量条 / 规则卡 / 未入库提示", () => {
  render(<CheckReport report={full} />);
  expect(screen.getByText("对乙酰氨基酚日总量已超过安全上限")).toBeInTheDocument();
  expect(screen.getByText("占安全上限 49%")).toBeInTheDocument();
  expect(screen.getByText("警告文案。")).toBeInTheDocument();
  expect(screen.getByText(/某特效药/)).toBeInTheDocument();
});

it("全部为空时渲染安心文案", () => {
  render(
    <CheckReport report={{ overlap: { overlapping: [], warnings: [] }, triggered_rules: [], unresolved_drugs: [] }} />,
  );
  expect(screen.getByText(/未发现叠加或相互作用风险/)).toBeInTheDocument();
});

it("无叠加时显示未发现重复成分", () => {
  render(
    <CheckReport
      report={{ overlap: { overlapping: [], warnings: [] }, triggered_rules: full.triggered_rules, unresolved_drugs: [] }}
    />,
  );
  expect(screen.getByText("未发现重复成分。")).toBeInTheDocument();
});
```

- [ ] **Step 2: 实现 CheckReport**

新建 `web/src/features/medbox/CheckReport.tsx`:

```tsx
import { SectionTitle } from "../../components/ui/SectionTitle";
import type { CheckReport as CheckReportData } from "../../types/api";
import { DoseMeter } from "./DoseMeter";
import { RuleCard } from "./RuleCard";

export function CheckReport({ report }: { report: CheckReportData }) {
  const { overlap, triggered_rules, unresolved_drugs } = report;
  const empty =
    overlap.overlapping.length === 0 &&
    overlap.warnings.length === 0 &&
    triggered_rules.length === 0 &&
    unresolved_drugs.length === 0;

  if (empty) {
    return (
      <p className="rounded-lg border border-pharma/30 bg-pharma-soft px-4 py-3 text-sm">
        未发现叠加或相互作用风险。继续保持,有疑问随时问。
      </p>
    );
  }

  return (
    <div className="space-y-6">
      {unresolved_drugs.length > 0 && (
        <p className="rounded-lg border border-warn/40 bg-warn-soft px-3.5 py-2.5 text-[13px] leading-relaxed">
          <strong className="font-semibold">以下药品暂未收录,本次无法纳入检测:</strong>
          {unresolved_drugs.join("、")}
        </p>
      )}

      <section>
        <SectionTitle>成分叠加</SectionTitle>
        {overlap.warnings.length > 0 && (
          <ul className="mt-3 space-y-1.5">
            {overlap.warnings.map((w) => (
              <li key={w} className="rounded-lg border border-danger/40 bg-danger-soft px-3.5 py-2.5 text-sm font-medium text-danger">
                {w}
              </li>
            ))}
          </ul>
        )}
        {overlap.overlapping.length > 0 ? (
          <div className="mt-3 space-y-2.5">
            {overlap.overlapping.map((t) => (
              <DoseMeter key={t.name} item={t} />
            ))}
          </div>
        ) : (
          overlap.warnings.length === 0 && <p className="mt-3 text-sm text-mute">未发现重复成分。</p>
        )}
      </section>

      <section>
        <SectionTitle>相互作用警示</SectionTitle>
        {triggered_rules.length > 0 ? (
          <div className="mt-3 space-y-2.5">
            {triggered_rules.map((r, i) => (
              <RuleCard key={r.id} rule={r} index={i} />
            ))}
          </div>
        ) : (
          <p className="mt-3 text-sm text-mute">未触发相互作用警示。</p>
        )}
      </section>
    </div>
  );
}
```

- [ ] **Step 3: 运行,确认通过**

Run: `cd web && npx vitest run src/features/medbox/__tests__/CheckReport.test.tsx`
Expected: PASS(3 个)

- [ ] **Step 4: 写失败测试 — MedboxPanel**

新建 `web/src/features/medbox/__tests__/MedboxPanel.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import * as api from "../../../lib/api";
import { MedboxPanel } from "../MedboxPanel";

vi.mock("../../../lib/api");
vi.mock("../../../lib/device", () => ({ getDeviceId: () => "dev-1" }));

const drugs = [
  { drug_id: 1, brand_name: "泰诺", generic_name: "酚麻美敏片" },
  { drug_id: 2, brand_name: "芬必得", generic_name: "布洛芬缓释胶囊" },
];

const report = {
  overlap: { overlapping: [], warnings: [] },
  triggered_rules: [],
  unresolved_drugs: [],
};

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listDrugs).mockResolvedValue(drugs);
  vi.mocked(api.getMedbox).mockResolvedValue({ device_id: "dev-1", items: [] });
  vi.mocked(api.addMedboxItem).mockResolvedValue({
    device_id: "dev-1",
    items: [{ drug_id: 1, brand_name: "泰诺", dosage_per_day: 3 }],
  });
  vi.mocked(api.removeMedboxItem).mockResolvedValue({ device_id: "dev-1", items: [] });
  vi.mocked(api.checkMedbox).mockResolvedValue(report);
});

it("full 变体渲染选择器,加入药品后上送并刷新列表", async () => {
  render(<MedboxPanel variant="full" />, { wrapper });
  const user = userEvent.setup();

  expect(await screen.findByText("芬必得")).toBeInTheDocument();
  // 两个药各有一个「加入」按钮,取第一个(泰诺)
  await user.click(screen.getAllByRole("button", { name: "加入" })[0]);
  await user.click(screen.getByRole("button", { name: "确认加入" }));

  expect(api.addMedboxItem).toHaveBeenCalledWith("dev-1", {
    drug_id: 1, brand_name: "泰诺", dosage_per_day: 1,
  });
  // invalidate 触发药箱重取
  await waitFor(() => expect(api.getMedbox).toHaveBeenCalledTimes(2));
});

it("检查按钮上送当前药箱与所选物质,渲染报告", async () => {
  vi.mocked(api.getMedbox).mockResolvedValue({
    device_id: "dev-1",
    items: [{ drug_id: 1, brand_name: "泰诺", dosage_per_day: 3 }],
  });
  render(<MedboxPanel variant="rail" />, { wrapper });
  const user = userEvent.setup();

  await screen.findByText("泰诺");
  await user.click(screen.getByRole("button", { name: "酒精" }));
  await user.click(screen.getByRole("button", { name: "开始检查" }));

  await waitFor(() =>
    expect(api.checkMedbox).toHaveBeenCalledWith(
      [{ drug_id: 1, brand_name: "泰诺", dosage_per_day: 3 }],
      ["酒精"],
    ),
  );
  expect(await screen.findByText(/未发现叠加或相互作用风险/)).toBeInTheDocument();
});

it("移除药品调用 DELETE 并刷新", async () => {
  vi.mocked(api.getMedbox).mockResolvedValue({
    device_id: "dev-1",
    items: [{ drug_id: 1, brand_name: "泰诺", dosage_per_day: null }],
  });
  render(<MedboxPanel variant="rail" />, { wrapper });
  const user = userEvent.setup();

  expect(await screen.findByText("频次未定")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "移除泰诺" }));

  expect(api.removeMedboxItem).toHaveBeenCalledWith("dev-1", 1);
  await waitFor(() => expect(api.getMedbox).toHaveBeenCalledTimes(2));
});

it("空药箱禁用检查按钮并显示空态", async () => {
  render(<MedboxPanel variant="full" />, { wrapper });
  await screen.findByText("芬必得");
  expect(screen.getByText("药箱是空的")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "开始检查" })).toBeDisabled();
});
```

- [ ] **Step 5: 实现 MedboxPanel**

新建 `web/src/features/medbox/MedboxPanel.tsx`:

```tsx
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { CapsuleButton } from "../../components/ui/CapsuleButton";
import { EmptyState } from "../../components/ui/EmptyState";
import { SectionTitle } from "../../components/ui/SectionTitle";
import {
  addMedboxItem,
  checkMedbox,
  getMedbox,
  listDrugs,
  removeMedboxItem,
} from "../../lib/api";
import { getDeviceId } from "../../lib/device";
import type { DrugSummary } from "../../types/api";
import { CheckReport } from "./CheckReport";
import { DrugPicker } from "./DrugPicker";
import { SubstanceChips } from "./SubstanceChips";

/** 药箱面板:full = /medbox 全页(含选择器);rail = 桌面右侧栏(紧凑)。 */
export function MedboxPanel({ variant }: { variant: "rail" | "full" }) {
  const deviceId = getDeviceId();
  const queryClient = useQueryClient();
  const [substances, setSubstances] = useState<string[]>([]);

  const drugsQ = useQuery({ queryKey: ["drugs"], queryFn: listDrugs, staleTime: Infinity });
  const medboxQ = useQuery({
    queryKey: ["medbox", deviceId],
    queryFn: () => getMedbox(deviceId),
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["medbox", deviceId] });

  const addMut = useMutation({
    mutationFn: ({ drug, dosage }: { drug: DrugSummary; dosage: number | null }) =>
      addMedboxItem(deviceId, {
        drug_id: drug.drug_id,
        brand_name: drug.brand_name,
        dosage_per_day: dosage,
      }),
    onSuccess: invalidate,
  });

  const removeMut = useMutation({
    mutationFn: (drugId: number) => removeMedboxItem(deviceId, drugId),
    onSuccess: invalidate,
  });

  const checkMut = useMutation({
    mutationFn: () => checkMedbox(medboxQ.data?.items ?? [], substances),
  });

  const items = medboxQ.data?.items ?? [];
  const toggle = (s: string) =>
    setSubstances((list) => (list.includes(s) ? list.filter((x) => x !== s) : [...list, s]));

  return (
    <div className="space-y-5">
      {variant === "full" && (
        <section>
          <SectionTitle>添加药品</SectionTitle>
          <div className="mt-3">
            {drugsQ.isLoading ? (
              <p className="text-sm text-mute">加载药品目录…</p>
            ) : (
              <DrugPicker
                drugs={drugsQ.data ?? []}
                inBoxIds={new Set(items.map((i) => i.drug_id))}
                onAdd={(drug, dosage) => addMut.mutate({ drug, dosage })}
              />
            )}
          </div>
        </section>
      )}

      <section>
        <div className="flex items-center justify-between">
          <SectionTitle>我的药箱</SectionTitle>
          {variant === "rail" && (
            <Link to="/medbox" className="text-xs text-pharma-deep underline-offset-2 hover:underline">
              管理药品
            </Link>
          )}
        </div>
        {items.length === 0 ? (
          <div className="mt-3">
            <EmptyState
              title="药箱是空的"
              hint={variant === "full" ? "先添加你正在吃的药,再开始检查" : "到「药箱」页添加你正在吃的药"}
            />
          </div>
        ) : (
          <ul className="mt-3 divide-y divide-line rounded-lg border border-line bg-card">
            {items.map((i) => (
              <li key={i.drug_id} className="flex items-center justify-between gap-2 px-3 py-2.5">
                <div>
                  <p className="font-display font-semibold leading-tight">{i.brand_name}</p>
                  <p className="font-mono-data text-xs text-mute">
                    {i.dosage_per_day != null ? `每日 ×${i.dosage_per_day}` : "频次未定"}
                  </p>
                </div>
                <button
                  type="button"
                  aria-label={`移除${i.brand_name}`}
                  disabled={removeMut.isPending}
                  onClick={() => removeMut.mutate(i.drug_id)}
                  className="rounded-full p-1.5 text-mute transition-colors hover:bg-danger-soft hover:text-danger disabled:opacity-40"
                >
                  <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                    <path d="M6 6l12 12M18 6L6 18" />
                  </svg>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-3">
        <SubstanceChips selected={substances} onToggle={toggle} />
        <CapsuleButton
          className="w-full"
          disabled={items.length === 0 || checkMut.isPending}
          onClick={() => checkMut.mutate()}
        >
          {checkMut.isPending ? "检查中…" : "开始检查"}
        </CapsuleButton>
        {checkMut.isError && <p className="text-sm text-danger">检查失败,请重试。</p>}
      </section>

      {checkMut.data && <CheckReport report={checkMut.data} />}
    </div>
  );
}
```

- [ ] **Step 6: 运行,确认通过**

Run: `cd web && npx vitest run src/features/medbox/`
Expected: PASS(22 个:Task 9 的 9 + Task 10 的 6 + 本 Task 的 7)

- [ ] **Step 7: Commit**

```bash
git add web/src/features/medbox/CheckReport.tsx web/src/features/medbox/MedboxPanel.tsx web/src/features/medbox/__tests__/CheckReport.test.tsx web/src/features/medbox/__tests__/MedboxPanel.test.tsx
git commit -m "feat(web): 三段式检查报告 + MedboxPanel(TanStack Query 增删与 invalidate)"
```

---

## Task 12: 应用外壳 — 路由 / Header / TabBar / 桌面侧栏

**Files:**
- Create: `web/src/components/ui/Header.tsx`、`web/src/components/ui/TabBar.tsx`
- Modify: `web/src/App.tsx`(整体重写)
- Test: `web/src/App.test.tsx`(整体重写)

**Interfaces:**
- Consumes: Task 8 `ChatView`、Task 11 `MedboxPanel`、Task 6 `Logo`
- Produces: 完整应用布局——桌面 `/chat` 主区 + 320px 药箱侧栏;移动端底部 tab;`/` 重定向 `/chat`

- [ ] **Step 1: 写失败测试**

整体重写 `web/src/App.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import * as api from "./lib/api";
import { AppRoutes } from "./App";

vi.mock("./lib/api");
vi.mock("./lib/device", () => ({ getDeviceId: () => "dev-test" }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listDrugs).mockResolvedValue([]);
  vi.mocked(api.getMedbox).mockResolvedValue({ device_id: "dev-test", items: [] });
});

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("/chat 渲染聊天视图与药箱侧栏入口", async () => {
  renderAt("/chat");
  expect(screen.getByText("PillClear")).toBeInTheDocument();
  expect(await screen.findByText("试试这些常见问题")).toBeInTheDocument();
  expect(screen.getAllByText("我的药箱").length).toBeGreaterThan(0);
});

it("/medbox 渲染全页药箱(含选择器)", async () => {
  renderAt("/medbox");
  expect(await screen.findByText("添加药品")).toBeInTheDocument();
});

it("底部 tab 可在两个视图间切换", async () => {
  renderAt("/chat");
  const user = userEvent.setup();
  await user.click(screen.getByRole("link", { name: "药箱" }));
  expect(await screen.findByText("添加药品")).toBeInTheDocument();
});
```

- [ ] **Step 2: 运行,确认失败**

Run: `cd web && npx vitest run src/App.test.tsx`
Expected: FAIL — `AppRoutes` 未从 App 导出

- [ ] **Step 3: Header**

新建 `web/src/components/ui/Header.tsx`:

```tsx
import { Link } from "react-router-dom";
import { Logo } from "./Logo";

export function Header() {
  return (
    <header className="border-b border-line/70 bg-card/80">
      <div className="mx-auto flex w-full max-w-6xl items-center gap-2.5 px-4 py-3.5">
        <Logo className="h-7 w-7" />
        <Link to="/chat" className="font-display text-lg font-bold tracking-tight">
          PillClear
        </Link>
        <span className="mt-0.5 hidden text-xs text-mute sm:block">
          用药安全助手 · OTC + 保健品
        </span>
      </div>
    </header>
  );
}
```

- [ ] **Step 4: TabBar(移动端底部导航)**

新建 `web/src/components/ui/TabBar.tsx`:

```tsx
import { NavLink } from "react-router-dom";

const TABS = [
  { to: "/chat", label: "问诊", icon: <path d="M4 5h16v11H8l-4 4V5z" /> },
  {
    to: "/medbox",
    label: "药箱",
    icon: (
      <>
        <rect x="4" y="7" width="16" height="13" rx="2" />
        <path d="M9 7V5h6v2M4 12h16" />
      </>
    ),
  },
];

export function TabBar() {
  return (
    <nav className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-card lg:hidden">
      <div className="mx-auto flex max-w-md">
        {TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            className={({ isActive }) =>
              `flex flex-1 flex-col items-center gap-0.5 py-2.5 text-[11px] transition-colors ${
                isActive ? "font-semibold text-pharma-deep" : "text-mute"
              }`
            }
          >
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" aria-hidden>
              {t.icon}
            </svg>
            {t.label}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
```

- [ ] **Step 5: 整体重写 App.tsx**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Header } from "./components/ui/Header";
import { TabBar } from "./components/ui/TabBar";
import { ChatView } from "./features/chat/ChatView";
import { MedboxPanel } from "./features/medbox/MedboxPanel";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1 } },
});

/** 路由与布局(导出供测试以 MemoryRouter 包裹)。 */
export function AppRoutes() {
  return (
    <div className="min-h-dvh bg-paper bg-dosage-grid font-body text-ink">
      <Header />
      <div className="mx-auto flex w-full max-w-6xl gap-8 px-4 pb-28 pt-6 lg:pb-12">
        <main className="min-w-0 flex-1">
          <Routes>
            <Route path="/" element={<Navigate to="/chat" replace />} />
            <Route path="/chat" element={<ChatView />} />
            <Route path="/medbox" element={<MedboxPanel variant="full" />} />
          </Routes>
        </main>
        <aside className="hidden w-80 shrink-0 lg:block">
          <div className="sticky top-6 rounded-xl border border-line bg-card p-4 shadow-sm">
            <MedboxPanel variant="rail" />
          </div>
        </aside>
      </div>
      <TabBar />
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
```

- [ ] **Step 6: 运行测试,确认通过**

Run: `cd web && npx vitest run`
Expected: 前端全部测试 PASS(App 3 + chat 17 + medbox 22 + lib 12 + components 6 = 60)

- [ ] **Step 7: 类型检查**

Run: `cd web && npx tsc -b`
Expected: 无错误

- [ ] **Step 8: Commit**

```bash
git add web/src/App.tsx web/src/App.test.tsx web/src/components/ui/Header.tsx web/src/components/ui/TabBar.tsx
git commit -m "feat(web): 应用外壳(路由/桌面侧栏/移动底 tab),前后端视图接线完成"
```

---

## Task 13: README + 全量验收

**Files:**
- Modify: `README.md`(新增「前端」小节)
- Modify: `.env.example`(补充 `CORS_ORIGINS` 说明,若该文件存在)

**Interfaces:**
- Consumes: 全部前序 Task
- Produces: 可复现的启动文档 + 全绿测试 + 冒烟验收

- [ ] **Step 1: README 增加前端小节**

在 `README.md` 的「快速开始」之后追加:

````markdown
## 前端(Web)

响应式 Web 应用位于 `web/`(React + Vite,独立子项目):

```bash
# 1. 先起后端(默认 8000 端口)
uvicorn app.main:app --reload

# 2. 再起前端(默认 5173 端口,/api 自动代理到后端)
cd web
npm install
npm run dev

# 前端测试
cd web && npx vitest run
```

打开 http://localhost:5173 即可使用:聊天问诊 + 药箱检查。
跨域部署时通过 `CORS_ORIGINS` 环境变量配置允许来源(逗号分隔,默认已含 Vite 开发端口)。
````

- [ ] **Step 2: .env.example 补充 CORS 说明**

若 `.env.example` 存在,在末尾追加:

```bash
# CORS 允许来源(逗号分隔;空串 = 关闭 CORS 中间件)
# CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

- [ ] **Step 3: 后端全量测试**

Run: `python -m pytest tests/ -q`
Expected: 全绿(现有 287+ 加新增约 12,无一失败)

- [ ] **Step 4: 前端全量测试 + 构建**

Run: `cd web && npx vitest run && npx tsc -b && npm run build`
Expected: 测试全绿、类型无错误、`dist/` 构建成功

- [ ] **Step 5: 手动冒烟(需 DEEPSEEK_API_KEY 与已入库数据)**

前置:已执行 `python -m app.knowledge.ingest data/package_inserts`(药名入库),`.env` 配有 `DEEPSEEK_API_KEY`。

1. 起后端:`uvicorn app.main:app --reload`
2. 起前端:`cd web && npm run dev`,打开 http://localhost:5173
3. 聊天页点快捷提问「泰诺和白加黑能一起吃吗?」→ 等待态轮播文案出现 → 回答带引用折叠卡与免责声明
4. 点「我最近总是头疼怎么办?」→ 出现绿色竖线边界卡(诊断类话术)
5. 桌面右栏(或移动端「药箱」tab)加入泰诺、白加黑(各选频次)→ 「开始检查」→ 对乙酰氨基酚剂量条出现、占比正确;若超上限则红色超限文案 + 警告横幅
6. 勾选「酒精」,药箱留芬必得 → 检查 → 出现布洛芬+酒精规则卡(danger 红边 + 证据徽章)
7. 删除药品后再次检查 → 报告相应变化

- [ ] **Step 6: Commit**

```bash
git add README.md .env.example
git commit -m "docs: README 增加前端启动说明与 CORS_ORIGINS"
```

---

## 验收标准汇总

1. `python -m pytest tests/ -q` 全绿;
2. `cd web && npx vitest run` 全绿、`npx tsc -b` 无错误、`npm run build` 成功;
3. 冒烟脚本(Task 13 Step 5)全部走通;
4. `app/rules/`、`app/core/safety.py`、`app/prompts/` 零改动(git diff 确认);
5. 新增端点仅 `GET /api/v1/drugs`(只读),其余后端行为不变。
