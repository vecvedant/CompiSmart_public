import { useState } from "react";
import { Loader2, X, FileText, Youtube as YoutubeIcon, AlertTriangle, CheckCircle2, Plus } from "lucide-react";
import type { Asset } from "../lib/types";

interface Props {
  assets: Asset[];
  loading: boolean;
  selectable?: boolean;
  selectedIds?: Set<string>;
  onToggleSelect?: (id: string) => void;
  onDelete: (assetId: string) => void;
  onAddCustom?: (url: string) => void;
}

export function AssetsSidebar({
  assets,
  loading,
  selectable,
  selectedIds,
  onToggleSelect,
  onDelete,
  onAddCustom,
}: Props) {
  const [url, setUrl] = useState("");

  return (
    <aside className="w-full lg:w-72 shrink-0 bg-white border-l border-slate-100 flex flex-col">
      <div className="px-4 py-3 border-b border-slate-100">
        <h2 className="text-sm font-semibold text-slate-900">Assets</h2>
        <p className="text-xs text-slate-400 mt-0.5">
          {selectable ? "Pick what to build from" : `${assets.length} saved this session`}
        </p>
      </div>

      {onAddCustom && (
        <form
          className="px-4 py-2.5 border-b border-slate-100"
          onSubmit={(e) => {
            e.preventDefault();
            const v = url.trim();
            if (v) {
              onAddCustom(v);
              setUrl("");
            }
          }}
        >
          <div className="flex items-center gap-1.5">
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="Paste a URL…"
              className="flex-1 text-xs px-2.5 py-1.5 rounded-md bg-slate-50 border border-slate-100 focus:bg-white focus:border-slate-300 outline-none transition-colors"
            />
            <button
              type="submit"
              disabled={!url.trim()}
              className="text-xs bg-slate-900 text-white rounded-md px-2 py-1.5 hover:bg-slate-700 transition-colors disabled:opacity-30"
              title="Add"
              aria-label="Add custom URL"
            >
              <Plus className="w-3 h-3" />
            </button>
          </div>
        </form>
      )}

      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1">
        {loading && (
          <div className="flex items-center gap-2 text-xs text-slate-400 py-4 justify-center">
            <Loader2 className="w-3 h-3 animate-spin" /> loading…
          </div>
        )}
        {!loading && assets.length === 0 && (
          <div className="text-xs text-slate-400 text-center py-10 leading-relaxed">
            Nothing saved yet.<br />Add items from the feed.
          </div>
        )}
        {assets.map((a) => {
          const isSelected = selectedIds?.has(a.id) ?? false;
          return (
            <div
              key={a.id}
              className={`group rounded-lg border px-2.5 py-2 transition-colors ${
                isSelected
                  ? "bg-slate-50 border-slate-300"
                  : "bg-white border-transparent hover:bg-slate-50"
              }`}
            >
              <div className="flex items-start gap-2">
                {selectable && onToggleSelect && (
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => onToggleSelect(a.id)}
                    className="mt-0.5 accent-slate-900"
                  />
                )}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1 text-[10px] text-slate-400 mb-0.5">
                    {a.type === "video" ? (
                      <YoutubeIcon className="w-2.5 h-2.5" />
                    ) : (
                      <FileText className="w-2.5 h-2.5" />
                    )}
                    <span className="uppercase tracking-wide">{a.type}</span>
                    <StatusIcon status={a.ingest_status} />
                  </div>
                  <div className="text-xs text-slate-800 line-clamp-2 leading-snug">
                    {a.title}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => onDelete(a.id)}
                  className="text-slate-300 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                  aria-label="Remove asset"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </aside>
  );
}

function StatusIcon({ status }: { status: string }) {
  if (status === "ready") {
    return <CheckCircle2 className="w-3 h-3 text-emerald-500" />;
  }
  if (status === "failed") {
    return <AlertTriangle className="w-3 h-3 text-red-500" />;
  }
  return <Loader2 className="w-3 h-3 animate-spin text-amber-500" />;
}
