import type { ReactNode } from "react";

export function Chip({
  active = false,
  onClick,
  children,
}: {
  active?: boolean;
  onClick?: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`rounded-full border px-3 py-1 text-xs font-medium transition-all duration-150 active:scale-95 ${
        active
          ? "border-pharma bg-pharma text-white shadow-sm"
          : "border-line bg-card text-mute hover:border-pharma/50 hover:text-pharma-deep"
      }`}
    >
      {children}
    </button>
  );
}
