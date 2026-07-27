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
