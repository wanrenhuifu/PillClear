import { useEffect, useState } from "react";
import { formatMg } from "../../lib/format";
import type { IngredientTotal } from "../../types/api";

/** 成分日总量 vs 安全上限的动画剂量条。
 *  阶梯:<70% 绿 / 70%~100% 琥珀 / ≥100% 红(封顶 + 溢出刻线)。
 *  max 未知时渲染中性条 + 未知提示(铁律 #4:不确定必须明说)。 */
export function DoseMeter({ item }: { item: IngredientTotal }) {
  const ratio =
    item.max_daily_mg && item.max_daily_mg > 0
      ? item.total_amount_mg / item.max_daily_mg
      : null;
  const pct = ratio === null ? 100 : Math.min(ratio, 1) * 100;
  const over = ratio !== null && ratio > 1;

  const [width, setWidth] = useState(0);
  useEffect(() => {
    const raf = requestAnimationFrame(() => setWidth(pct));
    return () => cancelAnimationFrame(raf);
  }, [pct]);

  const barTone =
    ratio === null ? "bg-mute/40" : ratio < 0.7 ? "bg-pharma" : ratio < 1 ? "bg-warn" : "bg-danger";

  return (
    <div className="rounded-lg border border-line bg-card p-3 transition-shadow duration-200 hover:shadow-md">
      <div className="flex items-baseline justify-between gap-3">
        <div className="min-w-0">
          <p className="font-display font-semibold">{item.name}</p>
          <p className="truncate text-xs text-mute">来自:{item.sources.join("、")}</p>
        </div>
        <p className="shrink-0 font-mono-data text-lg font-medium leading-none">
          {formatMg(item.total_amount_mg)}
          <span className="ml-0.5 text-xs text-mute">mg</span>
          {item.max_daily_mg != null && (
            <span className="ml-2 text-xs font-normal text-mute">上限 {formatMg(item.max_daily_mg)}</span>
          )}
        </p>
      </div>
      <div className="relative mt-2.5 h-2.5 overflow-hidden rounded-full bg-paper ring-1 ring-line">
        <div
          className={`h-full rounded-full ${barTone} transition-[width] duration-700`}
          style={{ width: `${width}%`, transitionTimingFunction: "cubic-bezier(0.22, 1, 0.36, 1)" }}
        />
        {over && <div className="absolute inset-y-0 right-0 w-1 bg-danger" aria-hidden />}
      </div>
      <p className={`mt-1.5 text-xs ${over ? "font-semibold text-danger" : "text-mute"}`}>
        {ratio === null
          ? "安全上限未知——无法判断是否超量,请咨询药师"
          : over
            ? `已超安全上限(约 ${Math.round(ratio * 100)}%)`
            : `占安全上限 ${Math.round(ratio * 100)}%`}
      </p>
    </div>
  );
}
