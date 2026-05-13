import type { TrendStatus } from "../lib/types";

const STYLES: Record<
  TrendStatus,
  { label: string; emoji: string; classes: string }
> = {
  rising: {
    label: "Rising",
    emoji: "📈",
    classes: "bg-orange-50 text-orange-700 border-orange-200",
  },
  steady: {
    label: "Steady",
    emoji: "➡",
    classes: "bg-slate-50 text-slate-600 border-slate-200",
  },
  declining: {
    label: "Declining",
    emoji: "📉",
    classes: "bg-red-50 text-red-700 border-red-200",
  },
  niche: {
    label: "Niche",
    emoji: "⚪",
    classes: "bg-slate-50 text-slate-500 border-slate-200",
  },
  unavailable: {
    label: "No trend data",
    emoji: "—",
    classes: "bg-slate-50 text-slate-400 border-slate-200",
  },
};

export function TrendBadge({ status }: { status: TrendStatus }) {
  const s = STYLES[status];
  return (
    <span
      className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest border ${s.classes}`}
      title="Topic search-interest trend (Google Trends, last 90 days)"
    >
      {s.emoji} {s.label}
    </span>
  );
}
