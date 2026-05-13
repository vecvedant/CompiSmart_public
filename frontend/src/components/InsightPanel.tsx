import { Globe, RefreshCw, Sparkles, Trophy } from "lucide-react";
import type { Verdict } from "../lib/types";
import { WebSourceCard } from "./WebSourceCard";

interface InsightPanelProps {
  verdict: Verdict | null;
  loading: boolean;
  error?: string | null;
  onRefresh?: () => void;
}

function TopicRow({ slot, topic }: { slot: "A" | "B"; topic: string }) {
  // Side label is the slot letter in the same color as VideoCard's accent
  // border so the eye links the topic chip to the right card above.
  const slotStyles =
    slot === "A"
      ? "bg-blue-100 text-blue-700 border-blue-200"
      : "bg-orange-100 text-orange-700 border-orange-200";
  return (
    <div className="flex items-center gap-2">
      <span
        className={`flex-shrink-0 w-6 h-6 rounded-md flex items-center justify-center text-xs font-extrabold border ${slotStyles}`}
      >
        {slot}
      </span>
      <span className="text-sm font-semibold text-slate-900 leading-snug">
        {topic || (
          <span className="text-slate-400 italic font-normal">
            (topic not detected)
          </span>
        )}
      </span>
    </div>
  );
}

function WinnerBadge({ slot }: { slot: "A" | "B" | null }) {
  if (slot === null) {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-bold uppercase tracking-widest bg-slate-100 text-slate-600 border border-slate-200">
        <Trophy className="w-3 h-3" />
        Too close to call
      </span>
    );
  }
  const styles =
    slot === "A"
      ? "bg-blue-50 text-blue-700 border-blue-200"
      : "bg-orange-50 text-orange-700 border-orange-200";
  return (
    <span
      className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-bold uppercase tracking-widest border ${styles}`}
    >
      <Trophy className="w-3 h-3" />
      Video {slot} wins
    </span>
  );
}

export function InsightPanel({
  verdict,
  loading,
  error,
  onRefresh,
}: InsightPanelProps) {
  return (
    <section className="bg-white border border-slate-200 rounded-3xl shadow-sm overflow-hidden">
      <header className="px-6 py-4 border-b border-slate-100 flex items-center gap-2">
        <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-orange-400 to-orange-600 flex items-center justify-center text-white">
          <Sparkles className="w-4 h-4" />
        </div>
        <h2 className="font-bold text-slate-900">At a glance</h2>
        {verdict && (
          <span className="ml-auto flex items-center gap-2">
            {verdict.used_search && (
              <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-widest text-emerald-600">
                <Globe className="w-3 h-3" />
                Grounded with Search
              </span>
            )}
            {onRefresh && (
              <button
                type="button"
                onClick={onRefresh}
                disabled={loading}
                className="text-slate-400 hover:text-slate-700 transition-colors disabled:opacity-50"
                title="Regenerate the verdict"
                aria-label="Refresh verdict"
              >
                <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
              </button>
            )}
          </span>
        )}
      </header>

      <div className="p-6">
        {loading && !verdict && <Skeleton />}
        {error && !verdict && (
          <p className="text-sm text-red-600">
            Could not generate a verdict: {error}. The chat below still works.
          </p>
        )}
        {verdict && <Body verdict={verdict} />}
      </div>
    </section>
  );
}

function Skeleton() {
  return (
    <div className="space-y-3 animate-pulse">
      <div className="h-3 w-32 bg-slate-200 rounded" />
      <div className="h-4 w-3/4 bg-slate-200 rounded" />
      <div className="h-4 w-2/3 bg-slate-200 rounded" />
      <div className="space-y-2 pt-2">
        <div className="h-3 w-1/2 bg-slate-100 rounded" />
        <div className="h-3 w-2/5 bg-slate-100 rounded" />
      </div>
    </div>
  );
}

function Body({ verdict }: { verdict: Verdict }) {
  // Per-video topic chips: each video gets its OWN one-line topic, since
  // a comparison can pit two completely different domains against each
  // other (e.g. engineering vs B-school internships). The legacy single
  // `domain` field is shown only as a fallback when both topics are
  // empty (older cached verdicts).
  const showTopics = verdict.topic_a || verdict.topic_b;
  return (
    <div className="space-y-5">
      {/* Header line: per-video topics + winner badge */}
      <div className="flex items-start gap-3 flex-wrap">
        <div className="flex-1 min-w-0 space-y-2">
          {showTopics ? (
            <>
              <TopicRow slot="A" topic={verdict.topic_a} />
              <TopicRow slot="B" topic={verdict.topic_b} />
            </>
          ) : (
            <div>
              <div className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-1">
                Topic
              </div>
              <div className="text-base font-bold text-slate-900 leading-snug">
                {verdict.domain || "Unknown"}
              </div>
            </div>
          )}
        </div>
        <WinnerBadge slot={verdict.winning_video} />
      </div>

      {/* Opinion */}
      {verdict.opinion && (
        <div>
          <div className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-1">
            Why
          </div>
          <p className="text-sm text-slate-700 leading-relaxed">
            {verdict.opinion}
          </p>
        </div>
      )}

      {/* Reasons */}
      {verdict.reasons.length > 0 && (
        <div>
          <div className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">
            Reasons
          </div>
          <ul className="space-y-1.5">
            {verdict.reasons.map((r, i) => (
              <li
                key={i}
                className="text-sm text-slate-700 leading-relaxed flex gap-2"
              >
                <span className="text-orange-500 flex-shrink-0">•</span>
                <span>{r}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Web sources */}
      {verdict.web_sources.length > 0 && (
        <div>
          <div className="text-[10px] font-bold uppercase tracking-widest text-emerald-600 mb-2 flex items-center gap-1">
            <Globe className="w-3 h-3" />
            From the web
            <span className="text-slate-400">{verdict.web_sources.length}</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {verdict.web_sources.map((s, i) => (
              <WebSourceCard key={s.url} source={s} index={i + 1} />
            ))}
          </div>
        </div>
      )}

      {!verdict.used_search && (
        <p className="text-xs text-slate-400 italic">
          The AI did not search the web for this verdict — the topic looked
          evergreen, so the comparison sticks to what's inside the videos.
        </p>
      )}
    </div>
  );
}
