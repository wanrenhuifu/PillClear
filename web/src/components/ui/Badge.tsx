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
