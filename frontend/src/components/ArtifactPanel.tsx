import { useEffect, useState } from "react";
import {
  X,
  Sparkles,
  Loader2,
  AlertTriangle,
  FileText,
  GitCompare,
  ListChecks,
  BarChart3,
  Quote,
  History,
  Trash2,
  Bookmark,
  CheckCheck,
  ExternalLink,
} from "lucide-react";
import { Link } from "react-router-dom";
import { CompareArtifactView } from "./artifacts/CompareArtifactView";
import { DraftArtifactView } from "./artifacts/DraftArtifactView";
import { SummaryArtifactView } from "./artifacts/SummaryArtifactView";
import { MetricsArtifactView } from "./artifacts/MetricsArtifactView";
import { QuotesArtifactView } from "./artifacts/QuotesArtifactView";
import { deleteArtifact, listArtifacts, saveArtifactAsAsset } from "../lib/api";
import type { Artifact, ArtifactKind } from "../lib/types";

interface Props {
  sessionId: string;
  open: boolean;
  active: Artifact | null;
  history: Artifact[];
  isStreaming: boolean;
  onClose: () => void;
  onPickArtifact: (a: Artifact) => void;
  onHistoryChange: (list: Artifact[]) => void;
}

const KIND_ICON: Record<ArtifactKind, JSX.Element> = {
  compare: <GitCompare className="w-4 h-4" />,
  draft: <FileText className="w-4 h-4" />,
  summary: <ListChecks className="w-4 h-4" />,
  metrics: <BarChart3 className="w-4 h-4" />,
  quotes: <Quote className="w-4 h-4" />,
};

const KIND_LABEL: Record<ArtifactKind, string> = {
  compare: "Comparison",
  draft: "Draft",
  summary: "Summary",
  metrics: "Metrics",
  quotes: "Quotes",
};

export function ArtifactPanel({
  sessionId,
  open,
  active,
  history,
  isStreaming,
  onClose,
  onPickArtifact,
  onHistoryChange,
}: Props) {
  const [showHistory, setShowHistory] = useState(false);
  const [savedAsAsset, setSavedAsAsset] = useState<Set<string>>(new Set());
  const [savingId, setSavingId] = useState<string | null>(null);

  async function handleSaveAsAsset() {
    if (!active || active.status !== "ready") return;
    setSavingId(active.id);
    try {
      await saveArtifactAsAsset(active.id, sessionId);
      setSavedAsAsset((prev) => new Set(prev).add(active.id));
    } catch (e) {
      alert(`Save as asset failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSavingId(null);
    }
  }

  // Hide history menu when active changes (we just opened something new).
  useEffect(() => setShowHistory(false), [active?.id]);

  async function refreshHistory() {
    try {
      const list = await listArtifacts(sessionId);
      onHistoryChange(list);
    } catch (e) {
      console.warn("artifact list failed", e);
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteArtifact(id, sessionId);
      onHistoryChange(history.filter((h) => h.id !== id));
      if (active?.id === id) onClose();
    } catch (e) {
      console.warn("artifact delete failed", e);
    }
  }

  // Overlay drawer — slides in from the right, doesn't reflow the layout.
  // Uses translate-x for the slide animation so transitions are GPU-cheap.
  return (
    <>
      {/* Backdrop */}
      <div
        className={`fixed inset-0 bg-slate-900/30 z-40 transition-opacity ${
          open ? "opacity-100" : "opacity-0 pointer-events-none"
        }`}
        onClick={onClose}
        aria-hidden="true"
      />
      {/* Drawer */}
      <aside
        className={`fixed inset-y-0 right-0 z-50 w-full sm:w-[34rem] lg:w-[42rem] bg-white border-l border-slate-200 flex flex-col min-h-0 shadow-2xl transition-transform duration-200 ease-out ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
      <header className="border-b border-slate-200 px-4 py-3 flex items-center gap-3 bg-gradient-to-r from-amber-50 to-white">
        <div className="w-7 h-7 bg-amber-500 rounded-lg flex items-center justify-center text-white">
          <Sparkles className="w-3.5 h-3.5" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[10px] uppercase tracking-wide text-amber-700 flex items-center gap-1.5">
            {active ? KIND_ICON[active.kind] : <Sparkles className="w-3 h-3" />}
            {active ? KIND_LABEL[active.kind] : "Artifact"}
            {isStreaming && (
              <span className="inline-flex items-center gap-1 text-slate-500 ml-1">
                <Loader2 className="w-3 h-3 animate-spin" /> live
              </span>
            )}
          </div>
          <div className="text-sm font-bold text-slate-900 truncate">
            {active?.title || "Artifact panel"}
          </div>
        </div>
        {active && active.status === "ready" && (
          <button
            type="button"
            onClick={handleSaveAsAsset}
            disabled={savingId === active.id || savedAsAsset.has(active.id)}
            className={`inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-lg transition-colors ${
              savedAsAsset.has(active.id)
                ? "bg-emerald-50 text-emerald-700"
                : "bg-amber-100 text-amber-800 hover:bg-amber-200"
            } disabled:opacity-50 disabled:cursor-not-allowed`}
            title={savedAsAsset.has(active.id) ? "Already saved" : "Save as an asset (chat-queryable)"}
          >
            {savedAsAsset.has(active.id) ? (
              <>
                <CheckCheck className="w-3 h-3" /> Saved
              </>
            ) : savingId === active.id ? (
              <>
                <Loader2 className="w-3 h-3 animate-spin" /> Saving…
              </>
            ) : (
              <>
                <Bookmark className="w-3 h-3" /> Save as asset
              </>
            )}
          </button>
        )}
        {active && active.kind === "draft" && active.status === "ready" && (
          <Link
            to="/drafts"
            className="text-slate-400 hover:text-slate-900 inline-flex items-center gap-1 text-xs"
            title="See in Drafts library"
          >
            <ExternalLink className="w-3.5 h-3.5" />
          </Link>
        )}
        <button
          type="button"
          onClick={() => {
            setShowHistory((v) => !v);
            if (!showHistory) void refreshHistory();
          }}
          className="text-slate-400 hover:text-slate-900"
          title="Artifact history"
        >
          <History className="w-4 h-4" />
        </button>
        <button
          type="button"
          onClick={onClose}
          className="text-slate-400 hover:text-slate-900"
          aria-label="Close panel"
        >
          <X className="w-4 h-4" />
        </button>
      </header>

      {showHistory && (
        <div className="border-b border-slate-200 max-h-72 overflow-y-auto bg-slate-50">
          {history.length === 0 && (
            <div className="text-xs text-slate-400 p-4 text-center">No artifacts yet this session.</div>
          )}
          {history.map((h) => (
            <div
              key={h.id}
              className={`flex items-center gap-2 px-4 py-2 text-sm border-b border-slate-100 last:border-b-0 ${
                active?.id === h.id ? "bg-amber-50" : "hover:bg-white"
              }`}
            >
              <button
                type="button"
                onClick={() => onPickArtifact(h)}
                className="flex-1 min-w-0 flex items-center gap-2 text-left"
              >
                <span className="text-amber-600">{KIND_ICON[h.kind]}</span>
                <span className="truncate text-slate-700">{h.title || `(${h.kind})`}</span>
                {h.status === "failed" && (
                  <AlertTriangle className="w-3 h-3 text-red-500 shrink-0" />
                )}
              </button>
              <button
                type="button"
                onClick={() => handleDelete(h.id)}
                className="text-slate-300 hover:text-red-500"
                title="Delete artifact"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-5">
        {!active && (
          <div className="text-center text-sm text-slate-400 py-12">
            Ask the chat to compare, summarize, or draft — the artifact lands here.
          </div>
        )}
        {active && active.status === "failed" && (
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            <div className="font-semibold mb-1 flex items-center gap-1.5">
              <AlertTriangle className="w-4 h-4" /> This artifact failed
            </div>
            <div className="text-xs">
              {(active.payload_json as Record<string, unknown>)?.error?.toString() ||
                "Unknown error."}
            </div>
          </div>
        )}
        {active && active.status !== "failed" && active.kind === "compare" && (
          <CompareArtifactView artifact={active} isStreaming={isStreaming} />
        )}
        {active && active.status !== "failed" && active.kind === "draft" && (
          <DraftArtifactView artifact={active} isStreaming={isStreaming} />
        )}
        {active && active.status !== "failed" && active.kind === "summary" && (
          <SummaryArtifactView artifact={active} isStreaming={isStreaming} />
        )}
        {active && active.status !== "failed" && active.kind === "metrics" && (
          <MetricsArtifactView artifact={active} isStreaming={isStreaming} />
        )}
        {active && active.status !== "failed" && active.kind === "quotes" && (
          <QuotesArtifactView artifact={active} isStreaming={isStreaming} />
        )}
      </div>
      </aside>
    </>
  );
}
