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
