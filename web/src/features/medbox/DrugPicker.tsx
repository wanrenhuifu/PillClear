import { useState } from "react";
import { CapsuleButton } from "../../components/ui/CapsuleButton";
import type { DrugSummary } from "../../types/api";

function Stepper({
  value,
  onChange,
  disabled,
}: {
  value: number;
  onChange: (v: number) => void;
  disabled: boolean;
}) {
  return (
    <div className={`flex items-center overflow-hidden rounded-full border border-line bg-card ${disabled ? "opacity-40" : ""}`}>
      <button
        type="button"
        aria-label="减少频次"
        disabled={disabled || value <= 1}
        onClick={() => onChange(Math.max(1, value - 1))}
        className="px-2.5 py-1 text-sm transition-colors hover:text-pharma-deep disabled:opacity-30"
      >
        −
      </button>
      <span className="min-w-8 text-center font-mono-data text-sm">{value}</span>
      <button
        type="button"
        aria-label="增加频次"
        disabled={disabled || value >= 10}
        onClick={() => onChange(Math.min(10, value + 1))}
        className="px-2.5 py-1 text-sm transition-colors hover:text-pharma-deep disabled:opacity-30"
      >
        +
      </button>
    </div>
  );
}

export function DrugPicker({
  drugs,
  inBoxIds,
  onAdd,
}: {
  drugs: DrugSummary[];
  inBoxIds: Set<number>;
  onAdd: (drug: DrugSummary, dosagePerDay: number | null) => void;
}) {
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState<number | null>(null);
  const [dosage, setDosage] = useState(1);
  const [unspecified, setUnspecified] = useState(false);

  const filtered = drugs.filter(
    (d) => q === "" || d.brand_name.includes(q) || (d.generic_name ?? "").includes(q),
  );

  const startAdd = (id: number) => {
    setAdding(id);
    setDosage(1);
    setUnspecified(false);
  };

  const confirm = (drug: DrugSummary) => {
    onAdd(drug, unspecified ? null : dosage);
    setAdding(null);
  };

  return (
    <div>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="搜索药品(商品名/通用名)"
        className="w-full rounded-lg border border-line bg-card px-3 py-2 text-sm outline-none transition-colors focus:border-pharma"
      />
      <ul className="mt-2 divide-y divide-line rounded-lg border border-line bg-card">
        {filtered.map((d) => {
          const inBox = inBoxIds.has(d.drug_id);
          return (
            <li key={d.drug_id} className="px-3 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="font-display font-semibold leading-tight">{d.brand_name}</p>
                  {d.generic_name && <p className="truncate text-xs text-mute">{d.generic_name}</p>}
                </div>
                <CapsuleButton
                  size="sm"
                  variant={inBox ? "ghost" : "primary"}
                  disabled={inBox}
                  onClick={() => startAdd(d.drug_id)}
                >
                  {inBox ? "已在药箱" : "加入"}
                </CapsuleButton>
              </div>
              {adding === d.drug_id && (
                <div className="mt-2.5 flex flex-wrap items-center gap-3 rounded-lg bg-paper p-2.5 animate-fade-up">
                  <label className="flex cursor-pointer items-center gap-1.5 text-xs text-mute">
                    <input
                      type="checkbox"
                      checked={unspecified}
                      onChange={(e) => setUnspecified(e.target.checked)}
                      className="accent-pharma"
                    />
                    不确定频次
                  </label>
                  <div className="flex items-center gap-1">
                    <Stepper value={dosage} onChange={setDosage} disabled={unspecified} />
                    <span className="text-xs text-mute">次/日</span>
                  </div>
                  <div className="ml-auto flex gap-2">
                    <CapsuleButton size="sm" variant="ghost" onClick={() => setAdding(null)}>
                      取消
                    </CapsuleButton>
                    <CapsuleButton size="sm" onClick={() => confirm(d)}>
                      确认加入
                    </CapsuleButton>
                  </div>
                </div>
              )}
            </li>
          );
        })}
        {filtered.length === 0 && (
          <li className="px-3 py-6 text-center text-sm text-mute">没有匹配的药——试试商品名,如"泰诺"</li>
        )}
      </ul>
    </div>
  );
}
