import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Layers, FileText, Loader2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { listDrafts } from "../lib/api";
import { getSessionId } from "../lib/session";
import type { Draft } from "../lib/types";

const TYPE_LABELS: Record<string, string> = {
  blog_post: "Blog post",
  video_script: "Video script",
  x_thread: "X thread",
  linkedin_post: "LinkedIn post",
  newsletter: "Newsletter",
};

export default function DraftsView() {
  const { niche = "" } = useParams();
  const sessionId = useMemo(() => getSessionId(), []);
  const [drafts, setDrafts] = useState<Draft[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<Draft | null>(null);

  useEffect(() => {
    let cancelled = false;
    listDrafts(sessionId)
      .then((d) => {
        if (!cancelled) {
          setDrafts(d);
          if (d.length && !active) setActive(d[0]);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
    // active intentionally not in deps — only auto-select first on first load
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const backHref = niche ? `/feed/${niche}` : "/";

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Link to={backHref} className="text-slate-400 hover:text-slate-900">
              <ArrowLeft className="w-4 h-4" />
            </Link>
            <div className="w-8 h-8 bg-orange-500 rounded-xl flex items-center justify-center text-white">
              <Layers className="w-4 h-4" />
            </div>
            <span className="text-base font-bold tracking-tight text-slate-900">
              Compi<span className="text-orange-500">SMART</span>
            </span>
            <span className="text-sm text-slate-300">·</span>
            <span className="text-sm text-slate-600">Drafts</span>
          </div>
        </div>
      </header>

      <div className="flex-1 flex flex-col lg:flex-row min-h-0 max-w-7xl w-full mx-auto">
        {/* Sidebar: list of drafts */}
        <aside className="w-full lg:w-80 shrink-0 border-r border-slate-200 bg-white">
          <div className="p-4 border-b border-slate-200">
            <h2 className="font-bold text-slate-900">Your drafts</h2>
            <p className="text-xs text-slate-500 mt-1">
              Everything you generated this session.
            </p>
          </div>
          <div className="overflow-y-auto">
            {error && (
              <div className="px-4 py-3 text-xs text-red-600">{error}</div>
            )}
            {!drafts && !error && (
              <div className="flex items-center gap-2 p-4 text-xs text-slate-400">
                <Loader2 className="w-3.5 h-3.5 animate-spin" /> Loading…
              </div>
            )}
            {drafts && drafts.length === 0 && (
              <div className="p-4 text-xs text-slate-400">
                No drafts yet. Build something from the feed.
              </div>
            )}
            {drafts?.map((d) => (
              <button
                key={d.id}
                type="button"
                onClick={() => setActive(d)}
                className={`w-full text-left px-4 py-3 border-b border-slate-100 transition-colors ${
                  active?.id === d.id
                    ? "bg-orange-50"
                    : "hover:bg-slate-50"
                }`}
              >
                <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-slate-400 mb-1">
                  <FileText className="w-3 h-3" />
                  {TYPE_LABELS[d.output_type] || d.output_type}
                  <span className="text-slate-300">·</span>
                  <span>{d.tone}</span>
                </div>
                <div className="text-sm font-medium text-slate-800 line-clamp-2">
                  {d.title || "Untitled draft"}
                </div>
                {d.created_at && (
                  <div className="text-[10px] text-slate-400 mt-1">
                    {new Date(d.created_at).toLocaleString()}
                  </div>
                )}
              </button>
            ))}
          </div>
        </aside>

        {/* Main: rendered draft */}
        <main className="flex-1 min-w-0 overflow-y-auto p-6 lg:p-10">
          {active ? (
            <article className="prose prose-slate prose-headings:font-bold prose-headings:tracking-tight max-w-3xl">
              <ReactMarkdown>{active.content_md || "_(empty draft)_"}</ReactMarkdown>
            </article>
          ) : (
            <div className="text-center text-sm text-slate-400 py-16">
              Pick a draft on the left to view it.
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
