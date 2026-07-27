import { SectionTitle } from "../../components/ui/SectionTitle";

/** 恰好 4 条:覆盖正常回答、规则命中、边界拦截三条路径——空状态即产品演示。 */
export const QUICK_QUESTIONS = [
  "泰诺和白加黑能一起吃吗?",
  "吃布洛芬期间能喝酒吗?",
  "布洛芬和对乙酰氨基酚哪个退烧好?",
  "我最近总是头疼怎么办?",
];

export function QuickStart({ onAsk }: { onAsk: (q: string) => void }) {
  return (
    <div className="mx-auto mt-8 max-w-xl lg:mt-16">
      <SectionTitle>试试这些常见问题</SectionTitle>
      <div className="mt-4 grid grid-cols-1 gap-px overflow-hidden rounded-xl border border-line bg-line shadow-sm sm:grid-cols-2">
        {QUICK_QUESTIONS.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onAsk(q)}
            className="group bg-card px-4 py-4 text-left transition-colors duration-150 hover:bg-pharma-soft"
          >
            <span className="mb-2 inline-block h-2 w-4 origin-left rounded-full bg-pharma/70 transition-transform duration-200 group-hover:scale-x-125" aria-hidden />
            <span className="block text-sm leading-snug">{q}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
