import { Sparkles } from "lucide-react";
import { splitCitations } from "../lib/parseCitations";
import type { Segment } from "../lib/parseCitations";
import { CitationChip } from "./CitationChip";

interface AIMessageProps {
  text: string;
  streaming: boolean;
}

export function AIMessage({ text, streaming }: AIMessageProps) {
  return (
    <div className="flex justify-start">
      <div className="max-w-3xl bg-white border border-slate-100 px-6 py-5 rounded-2xl rounded-tl-none shadow-sm text-slate-700 leading-relaxed text-sm">
        <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-orange-500 mb-3">
          <Sparkles className="w-3 h-3" />
          AI
        </div>
        <div className="space-y-3">
          {renderParagraphs(text)}
          {streaming && <span className="streaming-cursor" aria-hidden />}
        </div>
      </div>
    </div>
  );
}

/** Split on blank lines to make real paragraphs, then render each with
 *  bold + citation chips inline. */
function renderParagraphs(text: string) {
  const paragraphs = text.split(/\n\s*\n/).filter((p) => p.trim().length > 0);
  if (paragraphs.length === 0) {
    // Streaming hasn't produced a paragraph break yet -- render as one.
    return <p>{renderInline(splitCitations(text))}</p>;
  }
  return paragraphs.map((p, i) => (
    <p key={i} className="whitespace-pre-wrap">
      {renderInline(splitCitations(p))}
    </p>
  ));
}

function renderInline(segments: Segment[]) {
  return segments.map((seg, i) => {
    if (seg.kind === "text") return <span key={i}>{seg.text}</span>;
    if (seg.kind === "bold")
      return (
        <strong key={i} className="font-bold text-slate-900">
          {seg.text}
        </strong>
      );
    return <CitationChip key={i} citation={seg.citation} raw={seg.raw} />;
  });
}
