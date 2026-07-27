import { Link } from "react-router-dom";
import { Logo } from "./Logo";

export function Header() {
  return (
    <header className="border-b border-line/70 bg-card/80">
      <div className="mx-auto flex w-full max-w-6xl items-center gap-2.5 px-4 py-3.5">
        <Logo className="h-7 w-7" />
        <Link to="/chat" className="font-display text-lg font-bold tracking-tight">
          PillClear
        </Link>
        <span className="mt-0.5 hidden text-xs text-mute sm:block">
          用药安全助手 · OTC + 保健品
        </span>
      </div>
    </header>
  );
}
