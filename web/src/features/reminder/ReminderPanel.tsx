import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CapsuleButton } from "../../components/ui/CapsuleButton";
import { EmptyState } from "../../components/ui/EmptyState";
import { SectionTitle } from "../../components/ui/SectionTitle";
import { getReminders, listDrugs, removeReminder, setReminder } from "../../lib/api";
import { getDeviceId } from "../../lib/device";
import { formatDueLabel } from "../../lib/format";
import type { DrugSummary } from "../../types/api";

const MAX_TIMES = 4;

/** 时刻编辑器:选药后展开,1~4 个 HH:MM 输入(增/删/改)。 */
function TimeEditor({
  onConfirm,
  onCancel,
  disabled,
}: {
  onConfirm: (times: string[]) => void;
  onCancel: () => void;
  disabled: boolean;
}) {
  const [times, setTimes] = useState<string[]>(["08:00"]);

  const update = (i: number, v: string) =>
    setTimes((list) => list.map((t, idx) => (idx === i ? v : t)));
  const add = () => setTimes((list) => (list.length < MAX_TIMES ? [...list, "12:00"] : list));
  const remove = (i: number) => setTimes((list) => list.filter((_, idx) => idx !== i));

  // 空串/非法时刻不允许提交(后端也会 422 兜底)
  const valid = times.length > 0 && times.every((t) => /^([01]\d|2[0-3]):[0-5]\d$/.test(t));

  return (
    <div className="mt-2.5 space-y-2 rounded-lg bg-paper p-2.5 animate-fade-up">
      {times.map((t, i) => (
        <div key={i} className="flex items-center gap-2">
          <input
            type="time"
            value={t}
            aria-label={`提醒时刻${i + 1}`}
            disabled={disabled}
            onChange={(e) => update(i, e.target.value)}
            className="rounded-lg border border-line bg-card px-3 py-1.5 font-mono-data text-sm outline-none transition-colors focus:border-pharma"
          />
          {times.length > 1 && (
            <button
              type="button"
              aria-label={`删除时刻${i + 1}`}
              disabled={disabled}
              onClick={() => remove(i)}
              className="rounded-full p-1 text-mute transition-colors hover:bg-danger-soft hover:text-danger"
            >
              <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          )}
        </div>
      ))}
      <div className="flex items-center gap-2">
        {times.length < MAX_TIMES && (
          <CapsuleButton size="sm" variant="ghost" disabled={disabled} onClick={add}>
            + 加一个时刻
          </CapsuleButton>
        )}
        <div className="ml-auto flex gap-2">
          <CapsuleButton size="sm" variant="ghost" disabled={disabled} onClick={onCancel}>
            取消
          </CapsuleButton>
          <CapsuleButton size="sm" disabled={disabled || !valid} onClick={() => onConfirm(times)}>
            确认设置
          </CapsuleButton>
        </div>
      </div>
    </div>
  );
}

/** 用药提醒面板:选药 → 设每日时刻表;列表展示下次提醒。 */
export function ReminderPanel() {
  const deviceId = getDeviceId();
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);

  const drugsQ = useQuery({ queryKey: ["drugs"], queryFn: listDrugs, staleTime: Infinity });
  const remindersQ = useQuery({
    queryKey: ["reminders", deviceId],
    queryFn: () => getReminders(deviceId),
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["reminders", deviceId] });

  const setMut = useMutation({
    mutationFn: ({ drug, times }: { drug: DrugSummary; times: string[] }) =>
      setReminder(deviceId, {
        drug_id: drug.drug_id,
        brand_name: drug.brand_name,
        times,
      }),
    onSuccess: () => {
      invalidate();
      setEditingId(null);
    },
  });

  const removeMut = useMutation({
    mutationFn: (drugId: number) => removeReminder(deviceId, drugId),
    onSuccess: () => invalidate(),
  });

  const reminders = remindersQ.data?.reminders ?? [];
  const remindedIds = new Set(reminders.map((r) => r.drug_id));
  const filtered = (drugsQ.data ?? []).filter(
    (d) => q === "" || d.brand_name.includes(q) || (d.generic_name ?? "").includes(q),
  );

  return (
    <div className="space-y-5">
      <section>
        <SectionTitle>添加提醒</SectionTitle>
        <div className="mt-3">
          {drugsQ.isLoading ? (
            <p className="text-sm text-mute">加载药品目录…</p>
          ) : drugsQ.isError ? (
            <p className="text-sm text-danger">药品目录加载失败,请刷新重试。</p>
          ) : (
            <div>
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="搜索药品(商品名/通用名)"
                className="w-full rounded-lg border border-line bg-card px-3 py-2 text-sm outline-none transition-colors focus:border-pharma"
              />
              <ul className="mt-2 divide-y divide-line rounded-lg border border-line bg-card">
                {filtered.map((d) => {
                  const editing = editingId === d.drug_id;
                  return (
                    <li key={d.drug_id} className="px-3 py-2.5">
                      <div className="flex items-center justify-between gap-2">
                        <div className="min-w-0">
                          <p className="font-display font-semibold leading-tight">{d.brand_name}</p>
                          {d.generic_name && (
                            <p className="truncate text-xs text-mute">{d.generic_name}</p>
                          )}
                        </div>
                        <CapsuleButton
                          size="sm"
                          variant={remindedIds.has(d.drug_id) && !editing ? "ghost" : "primary"}
                          onClick={() => setEditingId(editing ? null : d.drug_id)}
                        >
                          {editing ? "收起" : remindedIds.has(d.drug_id) ? "改时间" : "设提醒"}
                        </CapsuleButton>
                      </div>
                      {editing && (
                        <TimeEditor
                          disabled={setMut.isPending}
                          onConfirm={(times) => setMut.mutate({ drug: d, times })}
                          onCancel={() => setEditingId(null)}
                        />
                      )}
                    </li>
                  );
                })}
                {filtered.length === 0 && (
                  <li className="px-3 py-6 text-center text-sm text-mute">
                    没有匹配的药——试试商品名,如"泰诺"
                  </li>
                )}
              </ul>
            </div>
          )}
          {setMut.isError && <p className="mt-2 text-sm text-danger">设置失败,请重试。</p>}
        </div>
      </section>

      <section>
        <SectionTitle>我的提醒</SectionTitle>
        {remindersQ.isError ? (
          <p className="mt-3 text-sm text-danger">提醒加载失败,请刷新重试。</p>
        ) : reminders.length === 0 ? (
          <div className="mt-3">
            <EmptyState title="还没有提醒" hint="选一个药,设好每天吃药的时间" />
          </div>
        ) : (
          <ul className="mt-3 divide-y divide-line rounded-lg border border-line bg-card">
            {reminders.map((r) => (
              <li key={r.drug_id} className="flex items-center justify-between gap-2 px-3 py-2.5">
                <div>
                  <p className="font-display font-semibold leading-tight">{r.brand_name}</p>
                  <p className="mt-0.5 flex flex-wrap gap-1.5">
                    {r.times.map((t) => (
                      <span
                        key={t}
                        className="rounded-full bg-pharma-soft px-2 py-0.5 font-mono-data text-xs text-pharma-deep"
                      >
                        {t}
                      </span>
                    ))}
                  </p>
                  {r.next_due_at && (
                    <p className="mt-1 text-xs text-mute">下次:{formatDueLabel(r.next_due_at)}</p>
                  )}
                </div>
                <button
                  type="button"
                  aria-label={`删除${r.brand_name}的提醒`}
                  disabled={removeMut.isPending}
                  onClick={() => removeMut.mutate(r.drug_id)}
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
        {removeMut.isError && <p className="mt-2 text-sm text-danger">删除失败,请重试。</p>}
      </section>
    </div>
  );
}
