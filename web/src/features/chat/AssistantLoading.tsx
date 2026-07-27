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
