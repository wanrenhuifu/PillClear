import { Logo } from "./Logo";

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-dashed border-line bg-paper/60 px-4 py-6 text-center">
      <Logo className="mx-auto h-8 w-8 opacity-40" />
      <p className="mt-2 text-sm font-medium">{title}</p>
      {hint && <p className="mt-1 text-xs text-mute">{hint}</p>}
    </div>
  );
}
