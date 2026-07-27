import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../../../lib/api";
import type { ChatResponse } from "../../../types/api";
import { ChatView } from "../ChatView";

// 保留真实 ApiError(kind 属性参与错误分类),仅 mock 网络函数
vi.mock("../../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api")>();
  return { ...actual, postChat: vi.fn() };
});

// jsdom 未实现 scrollIntoView;stub 掉以免 ChatView 的自动滚动 effect 报错
Element.prototype.scrollIntoView = vi.fn();

const okResp: ChatResponse = {
  blocked: false, category: null, boundary_message: null,
  answer: "不建议一起吃,两者都含对乙酰氨基酚。", confidence: 0.9,
  citations: [{ brand_name: "泰诺", section: "成份", excerpt: "每片含对乙酰氨基酚325毫克" }],
  sources_note: null, disclaimer: "仅供参考,不能替代医嘱。",
};

// resetAllMocks(而非 clearAllMocks):清掉上一测试的 mockResolvedValueOnce 队列,避免串味
beforeEach(() => vi.resetAllMocks());

describe("ChatView", () => {
  it("点快捷提问 → 渲染回答、引用与免责声明", async () => {
    vi.mocked(api.postChat).mockResolvedValue(okResp);
    render(<ChatView />);
    const user = userEvent.setup();

    await user.click(screen.getByText("泰诺和白加黑能一起吃吗?"));

    expect(screen.getByText("泰诺和白加黑能一起吃吗?")).toBeInTheDocument();
    expect(await screen.findByText(okResp.answer!)).toBeInTheDocument();
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
    expect(await screen.findByText(okResp.answer!)).toBeInTheDocument();
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
    await waitFor(() => expect(screen.getByText(okResp.answer!)).toBeInTheDocument());
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
