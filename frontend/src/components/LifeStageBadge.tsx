import type { LifeStage } from "../lib/types";

const STYLES: Record<
  LifeStage,
  { label: string; classes: string; emoji: string }
> = {
  fresh: {
    label: "FRESH",
    classes: "bg-emerald-50 text-emerald-700 border-emerald-200",
    emoji: "🟢",
  },
  early: {
    label: "EARLY",
    classes: "bg-emerald-50 text-emerald-700 border-emerald-200",
    emoji: "🟢",
  },
  mature: {
    label: "MATURE",
    classes: "bg-yellow-50 text-yellow-700 border-yellow-200",
    emoji: "🟡",
  },
  saturated: {
    label: "SATURATED",
    classes: "bg-slate-50 text-slate-600 border-slate-200",
    emoji: "⚪",
  },
};

export function LifeStageBadge({ stage }: { stage?: LifeStage | null }) {
  if (!stage) return null;
  const s = STYLES[stage];
  return (
    <span
      className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest border ${s.classes}`}
      title={`Heuristic life-stage from upload age (${stage}).`}
    >
      {s.emoji} {s.label}
    </span>
  );
}
