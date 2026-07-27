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
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => jsonResponse([]));
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
