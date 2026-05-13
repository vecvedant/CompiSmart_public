import { FileText, MessageSquare, Sparkles } from "lucide-react";
import type { Comment, SourcesInternal } from "../lib/types";

interface InternalSignalListProps {
  data: SourcesInternal;
}

function fmtTime(s?: number | null): string {
  if (s == null) return "?";
  const i = Math.round(s);
  const m = Math.floor(i / 60);
  const sec = i % 60;
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

function CommentRow({ c }: { c: Comment }) {
  return (
    <div className="px-3 py-2 rounded-lg border border-slate-100 bg-slate-50/40">
      <p className="text-xs text-slate-700 line-clamp-3">{c.text}</p>
      <div className="flex gap-3 mt-1 text-[10px] font-medium text-slate-400">
        {c.author && <span>@{c.author}</span>}
        <span>{c.likes.toLocaleString()} likes</span>
        {c.replies > 0 && <span>{c.replies} replies</span>}
      </div>
    </div>
  );
}

export function InternalSignalList({ data }: InternalSignalListProps) {
  const hasContent =
    data.hook || data.top_transcript.length > 0 || data.top_comments.length > 0;

  if (!hasContent) {
    return (
      <p className="text-xs text-slate-400 italic px-1">
        Transcript and comments load after ingest.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {data.hook && (
        <div>
          <div className="flex items-center gap-1.5 mb-1.5 text-[10px] font-bold uppercase tracking-widest text-amber-600">
            <Sparkles className="w-3 h-3" />
            Hook ({fmtTime(data.hook.start_sec)}{data.hook.end_sec != null ? ` - ${fmtTime(data.hook.end_sec)}` : ""})
          </div>
          <p className="text-xs text-slate-700 leading-relaxed border-l-2 border-amber-300 pl-3 italic">
            {data.hook.text}
          </p>
        </div>
      )}

      {data.top_transcript.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 mb-1.5 text-[10px] font-bold uppercase tracking-widest text-blue-600">
            <FileText className="w-3 h-3" />
            Transcript bits
          </div>
          <div className="space-y-1.5">
            {data.top_transcript.map((c, i) => (
              <div
                key={i}
                className="px-3 py-2 rounded-lg border border-slate-100 bg-white text-xs text-slate-700"
              >
                <div className="text-[10px] font-medium text-slate-400 mb-0.5">
                  {fmtTime(c.start_sec)}{c.end_sec != null ? ` - ${fmtTime(c.end_sec)}` : ""}
                </div>
                <p className="line-clamp-3">{c.text}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {data.top_comments.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 mb-1.5 text-[10px] font-bold uppercase tracking-widest text-orange-600">
            <MessageSquare className="w-3 h-3" />
            Top comments
          </div>
          <div className="space-y-1.5">
            {data.top_comments.map((c, i) => (
              <CommentRow key={i} c={c} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
