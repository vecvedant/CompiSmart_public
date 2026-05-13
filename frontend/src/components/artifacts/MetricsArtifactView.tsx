import type { Artifact } from "../../lib/types";

interface Row {
  idx: number;
  title: string;
  type: string;
  creator?: string;
  views?: number;
  likes?: number;
  comments?: number;
  engagement_rate?: number;
  view_velocity?: number;
  life_stage?: string;
  topic_trend_status?: string;
  discussion_depth?: number;
  sentiment?: {
    positive?: number;
    negative?: number;
    curious?: number;
    confused?: number;
    other?: number;
  };
  top_keywords?: string[];
}

export function MetricsArtifactView({ artifact }: { artifact: Artifact; isStreaming: boolean }) {
  const rows = ((artifact.payload_json as Record<string, unknown>).rows as Row[]) || [];

  if (rows.length === 0) {
    return <div className="text-sm text-slate-400 py-8 text-center">No metrics available.</div>;
  }

  return (
    <div className="space-y-4">
      {rows.map((r) => (
        <div key={r.idx} className="rounded-2xl border border-slate-200 bg-white p-4">
          <div className="flex items-start justify-between gap-3 mb-3">
            <div className="min-w-0">
              <div className="text-[10px] uppercase tracking-wide text-slate-400">
                Asset {r.idx} · {r.type}
              </div>
              <div className="text-sm font-bold text-slate-900 line-clamp-2 mt-0.5">
                {r.title}
              </div>
              {r.creator && (
                <div className="text-xs text-slate-500 mt-0.5">@{r.creator}</div>
              )}
            </div>
          </div>

          {/* Stat grid */}
          <div className="grid grid-cols-4 gap-2 mb-3">
            <Stat label="Views" value={fmt(r.views)} />
            <Stat label="Likes" value={fmt(r.likes)} />
            <Stat label="Comments" value={fmt(r.comments)} />
            <Stat
              label="Engagement"
              value={r.engagement_rate != null ? `${r.engagement_rate.toFixed(2)}%` : "—"}
            />
            <Stat label="Velocity/day" value={fmtFloat(r.view_velocity)} />
            <Stat label="Life stage" value={r.life_stage || "—"} />
            <Stat label="Trend" value={r.topic_trend_status || "—"} />
            <Stat label="Depth" value={fmtFloat(r.discussion_depth)} />
          </div>

          {/* Sentiment bar */}
          {r.sentiment && Object.keys(r.sentiment).length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-slate-400 mb-1.5">
                Comment sentiment
              </div>
              <SentimentBar s={r.sentiment} />
            </div>
          )}

          {/* Keywords */}
          {!!(r.top_keywords || []).length && (
            <div className="mt-3">
              <div className="text-[10px] uppercase tracking-wide text-slate-400 mb-1.5">
                Topic keywords
              </div>
              <div className="flex flex-wrap gap-1.5">
                {r.top_keywords!.map((k, i) => (
                  <span
                    key={i}
                    className="bg-slate-100 text-slate-700 text-[10px] px-2 py-0.5 rounded-full font-medium"
                  >
                    {k}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-slate-50 rounded-lg px-2.5 py-2">
      <div className="text-[9px] uppercase tracking-wide text-slate-400 mb-0.5">{label}</div>
      <div className="text-sm font-bold text-slate-900 truncate">{value}</div>
    </div>
  );
}

const SENTIMENT_COLORS: Record<string, string> = {
  positive: "bg-emerald-400",
  negative: "bg-red-400",
  curious: "bg-blue-400",
  confused: "bg-amber-400",
  other: "bg-slate-300",
};

function SentimentBar({ s }: { s: Row["sentiment"] }) {
  const entries = Object.entries(s || {});
  const total = entries.reduce((sum, [, v]) => sum + (v || 0), 0);
  if (!total) {
    return <div className="text-xs text-slate-400">No comment data.</div>;
  }
  return (
    <div>
      <div className="flex h-2 rounded-full overflow-hidden bg-slate-100">
        {entries.map(([k, v]) => {
          const pct = ((v || 0) / total) * 100;
          if (pct < 1) return null;
          return (
            <div
              key={k}
              className={`${SENTIMENT_COLORS[k] || "bg-slate-300"} h-full`}
              style={{ width: `${pct}%` }}
              title={`${k}: ${v}`}
            />
          );
        })}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-2 text-[10px]">
        {entries.map(([k, v]) => (
          <span key={k} className="flex items-center gap-1 text-slate-500">
            <span className={`w-2 h-2 rounded-full ${SENTIMENT_COLORS[k] || "bg-slate-300"}`} />
            <span className="font-medium">{k}</span>
            <span>{v || 0}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function fmt(n: number | undefined): string {
  if (n == null) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function fmtFloat(n: number | undefined): string {
  if (n == null) return "—";
  return n.toFixed(2);
}
