import { Chip } from "../../components/ui/Chip";

/** 物质词表严格对应规则 YAML(alcohol.yaml / interaction.yaml),不造新词。 */
export const SUBSTANCES = ["酒精", "避孕药"] as const;

export function SubstanceChips({
  selected,
  onToggle,
}: {
  selected: string[];
  onToggle: (s: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-mute">同时在摄入:</span>
      {SUBSTANCES.map((s) => (
        <Chip key={s} active={selected.includes(s)} onClick={() => onToggle(s)}>
          {s}
        </Chip>
      ))}
    </div>
  );
}
