import { Quote, Loader2 } from "lucide-react";
import type { Artifact } from "../../lib/types";

interface Q {
  text: string;
  source: string;
  why: string;
}

export function QuotesArtifactView({
  artifact,
  isStreaming,
}: { artifact: Artifact; isStreaming: boolean }) {
  const quotes = ((artifact.payload_json as Record<string, unknown>).quotes as Q[]) || [];

  const streamingPreview = (artifact.payload_json as Record<string, unknown>).streaming_preview as string | undefined;

  if (isStreaming && !quotes.length) {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-amber-700 font-bold">
          <Loader2 className="w-3 h-3 animate-spin" /> picking quotes…
        </div>
        {streamingPreview ? (
          <pre className="whitespace-pre-wrap text-xs leading-relaxed font-sans text-slate-600 bg-amber-50/40 border border-amber-100 rounded-xl p-3">
            {streamingPreview}
            <span className="inline-block w-1.5 h-3 bg-amber-500 ml-0.5 animate-blink align-middle" />
          </pre>
        ) : (
          <div className="text-slate-400 text-sm italic">Scanning chunks…</div>
        )}
      </div>
    );
  }

  if (!quotes.length) {
    return <div className="text-sm text-slate-400 py-8 text-center">No quotes available.</div>;
  }

  return (
    <div className="space-y-3">
      {quotes.map((q, i) => (
        <div key={i} className="rounded-2xl border border-slate-200 bg-white p-4 hover:border-amber-300 transition-colors">
          <Quote className="w-4 h-4 text-amber-500 mb-2" />
          <div className="text-[15px] text-slate-900 leading-relaxed font-medium mb-2">
            "{q.text}"
          </div>
          <div className="flex items-center justify-between gap-3 text-[11px]">
            <span className="text-slate-400">{q.source}</span>
            {q.why && (
              <span className="text-slate-500 italic text-right truncate">{q.why}</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
