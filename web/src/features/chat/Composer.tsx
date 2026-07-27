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
