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
