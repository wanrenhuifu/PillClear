import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { CapsuleButton } from "../../components/ui/CapsuleButton";
import { EmptyState } from "../../components/ui/EmptyState";
import { SectionTitle } from "../../components/ui/SectionTitle";
import {
  addMedboxItem,
  checkMedbox,
  getMedbox,
  listDrugs,
  removeMedboxItem,
} from "../../lib/api";
import { getDeviceId } from "../../lib/device";
import type { DrugSummary } from "../../types/api";
import { CheckReport } from "./CheckReport";
import { DrugPicker } from "./DrugPicker";
import { SubstanceChips } from "./SubstanceChips";

/** 药箱面板:full = /medbox 全页(含选择器);rail = 桌面右侧栏(紧凑)。 */
export function MedboxPanel({ variant }: { variant: "rail" | "full" }) {
  const deviceId = getDeviceId();
  const queryClient = useQueryClient();
  const [substances, setSubstances] = useState<string[]>([]);

  const drugsQ = useQuery({ queryKey: ["drugs"], queryFn: listDrugs, staleTime: Infinity });
  const medboxQ = useQuery({
    queryKey: ["medbox", deviceId],
    queryFn: () => getMedbox(deviceId),
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["medbox", deviceId] });

  const checkMut = useMutation({
    mutationFn: () => checkMedbox(medboxQ.data?.items ?? [], substances),
  });

  // 输入一变(加/减药、切换物质),旧报告立即作废——过期的「无风险」结论比没有结论更危险
  const discardReport = () => checkMut.reset();

  const addMut = useMutation({
    mutationFn: ({ drug, dosage }: { drug: DrugSummary; dosage: number | null }) =>
      addMedboxItem(deviceId, {
        drug_id: drug.drug_id,
        brand_name: drug.brand_name,
        dosage_per_day: dosage,
      }),
    onSuccess: () => {
      invalidate();
      discardReport();
    },
  });

  const removeMut = useMutation({
    mutationFn: (drugId: number) => removeMedboxItem(deviceId, drugId),
    onSuccess: () => {
      invalidate();
      discardReport();
    },
  });

  const items = medboxQ.data?.items ?? [];
  const toggle = (s: string) => {
    setSubstances((list) => (list.includes(s) ? list.filter((x) => x !== s) : [...list, s]));
    discardReport();
  };

  return (
    <div className="space-y-5">
      {variant === "full" && (
        <section>
          <SectionTitle>添加药品</SectionTitle>
          <div className="mt-3">
            {drugsQ.isLoading ? (
              <p className="text-sm text-mute">加载药品目录…</p>
            ) : drugsQ.isError ? (
              <p className="text-sm text-danger">药品目录加载失败,请刷新重试。</p>
            ) : (
              <DrugPicker
                drugs={drugsQ.data ?? []}
                inBoxIds={new Set(items.map((i) => i.drug_id))}
                onAdd={(drug, dosage) => addMut.mutate({ drug, dosage })}
              />
            )}
          </div>
        </section>
      )}

      <section>
        <div className="flex items-center justify-between">
          <SectionTitle>我的药箱</SectionTitle>
          {variant === "rail" && (
            <Link to="/medbox" className="text-xs text-pharma-deep underline-offset-2 hover:underline">
              管理药品
            </Link>
          )}
        </div>
        {medboxQ.isError ? (
          <p className="mt-3 text-sm text-danger">药箱加载失败,请刷新重试。</p>
        ) : items.length === 0 ? (
          <div className="mt-3">
            <EmptyState
              title="药箱是空的"
              hint={variant === "full" ? "先添加你正在吃的药,再开始检查" : "到「药箱」页添加你正在吃的药"}
            />
          </div>
        ) : (
          <ul className="mt-3 divide-y divide-line rounded-lg border border-line bg-card">
            {items.map((i) => (
              <li key={i.drug_id} className="flex items-center justify-between gap-2 px-3 py-2.5">
                <div>
                  <p className="font-display font-semibold leading-tight">{i.brand_name}</p>
                  <p className="font-mono-data text-xs text-mute">
                    {i.dosage_per_day != null ? `每日 ×${i.dosage_per_day}` : "频次未定"}
                  </p>
                </div>
                <button
                  type="button"
                  aria-label={`移除${i.brand_name}`}
                  disabled={removeMut.isPending}
                  onClick={() => removeMut.mutate(i.drug_id)}
                  className="rounded-full p-1.5 text-mute transition-colors hover:bg-danger-soft hover:text-danger disabled:opacity-40"
                >
                  <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                    <path d="M6 6l12 12M18 6L6 18" />
                  </svg>
                </button>
              </li>
            ))}
          </ul>
        )}
        {(addMut.isError || removeMut.isError) && (
          <p className="mt-2 text-sm text-danger">操作失败,请重试。</p>
        )}
      </section>

      <section className="space-y-3">
        <SubstanceChips selected={substances} onToggle={toggle} />
        <CapsuleButton
          className="w-full"
          disabled={items.length === 0 || checkMut.isPending}
          onClick={() => checkMut.mutate()}
        >
          {checkMut.isPending ? "检查中…" : "开始检查"}
        </CapsuleButton>
        {checkMut.isError && <p className="text-sm text-danger">检查失败,请重试。</p>}
      </section>

      {checkMut.data && <CheckReport report={checkMut.data} />}
    </div>
  );
}
