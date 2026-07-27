import { useState } from "react";
import type { Citation } from "../../types/api";

export function CitationCard({ citation }: { citation: Citation }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-line bg-paper">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition-colors hover:bg-pharma-soft/50"
      >
        <svg viewBox="0 0 24 24" className={`h-3 w-3 shrink-0 text-mute transition-transform duration-200 ${open ? "rotate-90" : ""}`} fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden>
          <path d="M9 5l7 7-7 7" />
        </svg>
        <span className="font-semibold text-pharma-deep">说明书原文</span>
        <span className="truncate text-mute">{citation.brand_name} · {citation.section}</span>
      </button>
      <div className="grid transition-[grid-template-rows] duration-300 ease-out" style={{ gridTemplateRows: open ? "1fr" : "0fr" }}>
        <div className="overflow-hidden">
          <blockquote className="mx-3 mb-3 border-l-2 border-pharma px-3 py-1.5 text-[13px] leading-relaxed text-ink/80">
            {citation.excerpt}
          </blockquote>
        </div>
      </div>
    </div>
  );
}
