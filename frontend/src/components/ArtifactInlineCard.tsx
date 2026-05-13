import {
  Sparkles,
  GitCompare,
  FileText,
  ListChecks,
  BarChart3,
  Quote,
  Loader2,
  AlertTriangle,
  ChevronRight,
  CheckCircle2,
} from "lucide-react";
import type { Artifact, ArtifactKind } from "../lib/types";
import { ArtifactSkeleton } from "./ArtifactSkeleton";

const KIND_ICON: Record<ArtifactKind, JSX.Element> = {
  compare: <GitCompare className="w-3.5 h-3.5" />,
  draft: <FileText className="w-3.5 h-3.5" />,
  summary: <ListChecks className="w-3.5 h-3.5" />,
  metrics: <BarChart3 className="w-3.5 h-3.5" />,
  quotes: <Quote className="w-3.5 h-3.5" />,
};

const KIND_LABEL: Record<ArtifactKind, string> = {
  compare: "Comparison",
  draft: "Draft",
  summary: "Summary",
  metrics: "Metrics",
  quotes: "Quotes",
};

interface Props {
  artifact: Artifact;
  streaming: boolean;
  onOpen: () => void;
}

export function ArtifactInlineCard({ artifact, streaming, onOpen }: Props) {
  const status = artifact.status;
  const failed = status === "failed";
  const pending = status === "pending";
  const ready = status === "ready";

  return (
    <button
      type="button"
      onClick={onOpen}
      className={`w-full text-left rounded-2xl border transition-all overflow-hidden group ${
        failed
          ? "border-red-200 bg-red-50 hover:bg-red-100"
          : pending
            ? "border-amber-200 bg-gradient-to-br from-amber-50 to-white"
            : "border-slate-200 bg-white hover:border-amber-300 hover:shadow-md"
      }`}
    >
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-slate-100">
        <div
          className={`w-6 h-6 rounded-md flex items-center justify-center ${
            failed
              ? "bg-red-100 text-red-600"
              : "bg-amber-100 text-amber-700"
          }`}
        >
          {failed ? <AlertTriangle className="w-3 h-3" /> : <Sparkles className="w-3 h-3" />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-amber-700 font-bold">
            {KIND_ICON[artifact.kind]}
            <span>{KIND_LABEL[artifact.kind]}</span>
            {pending && streaming && (
              <span className="inline-flex items-center gap-1 text-slate-500 font-normal normal-case tracking-normal ml-1">
                <Loader2 className="w-3 h-3 animate-spin" /> building…
              </span>
            )}
            {ready && (
              <span className="inline-flex items-center gap-1 text-emerald-600 font-normal normal-case tracking-normal ml-1">
                <CheckCircle2 className="w-3 h-3" /> ready
              </span>
            )}
          </div>
          <div className="text-sm font-semibold text-slate-900 truncate">
            {artifact.title || "Untitled artifact"}
          </div>
        </div>
        <ChevronRight className="w-4 h-4 text-slate-300 group-hover:text-amber-500 transition-colors" />
      </div>
      <div className="px-4 py-3">
        {pending && <PendingPreview artifact={artifact} />}
        {ready && <ReadyPreview artifact={artifact} />}
        {failed && (
          <div className="text-xs text-red-700">
            {(artifact.payload_json?.error as string) || "Generation failed."}
          </div>
        )}
      </div>
    </button>
  );
}

function PendingPreview({ artifact }: { artifact: Artifact }) {
  const p = artifact.payload_json as Record<string, unknown>;
  const streamingPreview = (p.streaming_preview as string | undefined) ?? "";
  const draftContent = (p.content_md as string | undefined) ?? "";
  const liveText = draftContent || streamingPreview;
  if (liveText) {
    return (
      <div className="text-xs text-slate-700 leading-relaxed bg-amber-50/50 rounded-lg p-2 border border-amber-100 max-h-32 overflow-hidden">
        <div className="line-clamp-5 whitespace-pre-wrap">
          {liveText}
          <span className="inline-block w-1 h-2.5 bg-amber-500 ml-0.5 animate-blink align-middle" />
        </div>
      </div>
    );
  }
  return <ArtifactSkeleton kind={artifact.kind} payload={artifact.payload_json} />;
}


function ReadyPreview({ artifact }: { artifact: Artifact }) {
  const p = artifact.payload_json as Record<string, unknown>;
  if (artifact.kind === "compare") {
    const v = (p.verdict as { opinion?: string; winning_video?: string } | undefined) ?? {};
    return (
      <div className="text-xs text-slate-600 line-clamp-3 leading-relaxed">
        {v.opinion || "Comparison ready — open to see verdict + side-by-side cards."}
      </div>
    );
  }
  if (artifact.kind === "draft") {
    const md = String(p.content_md ?? "");
    const preview = md.replace(/^#+\s*/gm, "").replace(/\n+/g, " ").trim().slice(0, 200);
    return (
      <div className="text-xs text-slate-600 line-clamp-3 leading-relaxed">
        {preview || "Draft ready — click to read or edit."}
      </div>
    );
  }
  if (artifact.kind === "summary") {
    const head = String(p.headline ?? "");
    return (
      <div className="text-xs text-slate-600 line-clamp-2 leading-relaxed">
        {head || "Summary ready."}
      </div>
    );
  }
  if (artifact.kind === "metrics") {
    const rows = (p.rows as unknown[]) || [];
    return (
      <div className="text-xs text-slate-600">
        Metrics across {rows.length} asset{rows.length === 1 ? "" : "s"}.
      </div>
    );
  }
  if (artifact.kind === "quotes") {
    const quotes = (p.quotes as { text: string }[]) || [];
    const first = quotes[0]?.text;
    return (
      <div className="text-xs text-slate-600 italic line-clamp-2">
        {first ? `"${first}"` : `${quotes.length} quotes picked.`}
      </div>
    );
  }
  return null;
}
