import { Loader2 } from "lucide-react";
import type { Artifact } from "../../lib/types";
import { splitCitations } from "../../lib/parseCitations";

interface Payload {
  headline?: string;
  bullets?: string[];
  takeaway?: string;
  asset_titles?: string[];
}

export function SummaryArtifactView({
  artifact,
  isStreaming,
}: { artifact: Artifact; isStreaming: boolean }) {
  const p = artifact.payload_json as Payload;

  const streamingPreview = (artifact.payload_json as Record<string, unknown>).streaming_preview as string | undefined;

  if (isStreaming && !p.headline) {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-amber-700 font-bold">
          <Loader2 className="w-3 h-3 animate-spin" /> writing brief…
        </div>
        {streamingPreview ? (
          <pre className="whitespace-pre-wrap text-xs leading-relaxed font-sans text-slate-600 bg-amber-50/40 border border-amber-100 rounded-xl p-3">
            {streamingPreview}
            <span className="inline-block w-1.5 h-3 bg-amber-500 ml-0.5 animate-blink align-middle" />
          </pre>
        ) : (
          <div className="text-slate-400 text-sm italic">Reading your assets…</div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {p.headline && (
        <h3 className="text-lg font-bold tracking-tight text-slate-900 leading-snug">
          {p.headline}
        </h3>
      )}
      <ul className="space-y-2">
        {(p.bullets || []).map((b, i) => (
          <li key={i} className="text-sm text-slate-700 flex gap-2 leading-relaxed">
            <span className="text-amber-500 mt-1">●</span>
            <span>{renderWithCitations(b)}</span>
          </li>
        ))}
      </ul>
      {p.takeaway && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
          <div className="text-[10px] uppercase tracking-wide font-bold text-amber-700 mb-1">
            Takeaway
          </div>
          <div className="text-sm text-slate-800 leading-relaxed">
            {renderWithCitations(p.takeaway)}
          </div>
        </div>
      )}
      {(p.asset_titles || []).length > 0 && (
        <div className="border-t border-slate-100 pt-3 mt-4">
          <div className="text-[10px] uppercase tracking-wide text-slate-400 mb-1">
            From these assets
          </div>
          <ul className="text-xs text-slate-500 space-y-0.5">
            {p.asset_titles!.map((t, i) => (
              <li key={i} className="truncate">{i + 1}. {t}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function renderWithCitations(text: string) {
  const segments = splitCitations(text);
  return segments.map((s, i) => {
    if (s.kind === "text") return <span key={i}>{s.text}</span>;
    if (s.kind === "bold") return <strong key={i}>{s.text}</strong>;
    // citation chip — lightweight inline rendering
    const c = s.citation;
    const label =
      c.slot === "asset"
        ? c.kind === "comment"
          ? `Comment ${c.commentIdx} · Asset ${c.idx}`
          : `Asset ${c.idx}`
        : c.kind === "web"
          ? `Web ${c.idx}`
          : `Video ${c.slot}`;
    return (
      <span
        key={i}
        className="inline-block mx-0.5 px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-800 text-[10px] font-bold align-middle"
      >
        {label}
      </span>
    );
  });
}
