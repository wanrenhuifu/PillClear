import { SectionTitle } from "../../components/ui/SectionTitle";
import type { CheckReport as CheckReportData } from "../../types/api";
import { DoseMeter } from "./DoseMeter";
import { RuleCard } from "./RuleCard";

export function CheckReport({ report }: { report: CheckReportData }) {
  const { overlap, triggered_rules, unresolved_drugs } = report;
  const empty =
    overlap.overlapping.length === 0 &&
    overlap.warnings.length === 0 &&
    triggered_rules.length === 0 &&
    unresolved_drugs.length === 0;

  if (empty) {
    return (
      <p className="rounded-lg border border-pharma/30 bg-pharma-soft px-4 py-3 text-sm">
        未发现叠加或相互作用风险。继续保持,有疑问随时问。
      </p>
    );
  }

  return (
    <div className="space-y-6">
      {unresolved_drugs.length > 0 && (
        <p className="rounded-lg border border-warn/40 bg-warn-soft px-3.5 py-2.5 text-[13px] leading-relaxed">
          <strong className="font-semibold">以下药品暂未收录,本次无法纳入检测:</strong>
          {unresolved_drugs.join("、")}
        </p>
      )}

      <section>
        <SectionTitle>成分叠加</SectionTitle>
        {overlap.warnings.length > 0 && (
          <ul className="mt-3 space-y-1.5">
            {overlap.warnings.map((w) => (
              <li key={w} className="rounded-lg border border-danger/40 bg-danger-soft px-3.5 py-2.5 text-sm font-medium text-danger">
                {w}
              </li>
            ))}
          </ul>
        )}
        {overlap.overlapping.length > 0 ? (
          <div className="mt-3 space-y-2.5">
            {overlap.overlapping.map((t) => (
              <DoseMeter key={t.name} item={t} />
            ))}
          </div>
        ) : (
          overlap.warnings.length === 0 && <p className="mt-3 text-sm text-mute">未发现重复成分。</p>
        )}
      </section>

      <section>
        <SectionTitle>相互作用警示</SectionTitle>
        {triggered_rules.length > 0 ? (
          <div className="mt-3 space-y-2.5">
            {triggered_rules.map((r, i) => (
              <RuleCard key={r.id} rule={r} index={i} />
            ))}
          </div>
        ) : (
          <p className="mt-3 text-sm text-mute">未触发相互作用警示。</p>
        )}
      </section>
    </div>
  );
}
