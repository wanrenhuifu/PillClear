import type { ReactNode } from "react";

export function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h2 className="flex items-center gap-2 font-display text-[13px] font-bold tracking-[0.12em] text-ink/80">
      <span className="inline-block h-2.5 w-2.5 rounded-[3px] bg-pharma" aria-hidden />
      {children}
    </h2>
  );
}
