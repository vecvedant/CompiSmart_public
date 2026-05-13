import { useState } from "react";
import { Copy, CheckCheck, Eye, Code2, Loader2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import type { Artifact } from "../../lib/types";

interface Payload {
  output_type?: string;
  tone?: string;
  length?: string;
  bullets?: string[];
  content_md?: string;
  asset_titles?: string[];
  sections_drafted?: number;
}

export function DraftArtifactView({
  artifact,
  isStreaming,
}: { artifact: Artifact; isStreaming: boolean }) {
  const p = artifact.payload_json as Payload;
  const [view, setView] = useState<"preview" | "raw">("preview");
  const [copied, setCopied] = useState(false);

  const md = p.content_md || "";

  function copy() {
    navigator.clipboard.writeText(md).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2 text-xs">
          <Badge label={(p.output_type || "draft").replace("_", " ")} />
          <Badge label={p.tone || ""} />
          <Badge label={p.length || ""} />
          <span className="text-slate-400">·</span>
          <span className="text-slate-500">
            {p.asset_titles?.length ?? 0} asset{(p.asset_titles?.length ?? 0) === 1 ? "" : "s"}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 bg-slate-100 rounded-md p-0.5">
            <button
              type="button"
              onClick={() => setView("preview")}
              className={`text-[11px] px-2 py-1 rounded flex items-center gap-1 transition-colors ${
                view === "preview" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"
              }`}
            >
              <Eye className="w-3 h-3" /> Preview
            </button>
            <button
              type="button"
              onClick={() => setView("raw")}
              className={`text-[11px] px-2 py-1 rounded flex items-center gap-1 transition-colors ${
                view === "raw" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500"
              }`}
            >
              <Code2 className="w-3 h-3" /> MD
            </button>
          </div>
          <button
            type="button"
            onClick={copy}
            className="text-xs text-slate-500 hover:text-slate-900 flex items-center gap-1"
          >
            {copied ? (
              <>
                <CheckCheck className="w-3.5 h-3.5 text-emerald-500" /> Copied
              </>
            ) : (
              <>
                <Copy className="w-3.5 h-3.5" /> Copy
              </>
            )}
          </button>
        </div>
      </div>

      {p.bullets?.length ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2">
          <div className="text-[10px] uppercase tracking-wide font-bold text-amber-700 mb-1">
            Outline
          </div>
          <ul className="text-xs text-amber-900 space-y-0.5 list-disc list-inside">
            {p.bullets.map((b, i) => (
              <li key={i}>{b}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="rounded-xl border border-slate-200 bg-white">
        {view === "preview" ? (
          <article className="prose prose-slate max-w-none p-5 prose-headings:font-bold prose-h1:text-xl prose-h2:text-base prose-p:text-sm prose-p:leading-relaxed prose-li:text-sm min-h-[40vh]">
            {md ? (
              <ReactMarkdown>{md}</ReactMarkdown>
            ) : (
              <p className="text-slate-400 text-sm">Waiting for the model to start writing…</p>
            )}
            {isStreaming && md && (
              <div className="text-[11px] text-slate-400 mt-3 flex items-center gap-1.5">
                <Loader2 className="w-3 h-3 animate-spin" />
                still writing…
              </div>
            )}
          </article>
        ) : (
          <pre className="text-xs font-mono leading-relaxed p-5 whitespace-pre-wrap text-slate-800 min-h-[40vh]">
            {md || "(empty)"}
          </pre>
        )}
      </div>
    </div>
  );
}

function Badge({ label }: { label: string }) {
  if (!label) return null;
  return (
    <span className="bg-slate-100 text-slate-700 px-2 py-0.5 rounded-full text-[10px] uppercase tracking-wide font-bold">
      {label}
    </span>
  );
}
