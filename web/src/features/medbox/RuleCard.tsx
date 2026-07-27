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
