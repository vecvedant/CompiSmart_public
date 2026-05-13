import { Newspaper, Youtube, Plus, GitCompare } from "lucide-react";
import type { FeedItem } from "../lib/types";

interface Props {
  item: FeedItem;
  onAdd: (item: FeedItem) => void;
  onCompareSelect?: (item: FeedItem) => void;
  busy?: boolean;
  added?: boolean;
  compareCandidate?: boolean;  // is this the first-clicked compare candidate
}

export function FeedCard({ item, onAdd, onCompareSelect, busy, added, compareCandidate }: Props) {
  const isVideo = item.type === "video";
  return (
    <div className="bg-white border border-slate-100 rounded-xl overflow-hidden hover:border-slate-300 transition-all flex flex-col">
      {item.thumbnail && (
        <a href={item.url} target="_blank" rel="noopener noreferrer" className="block aspect-video bg-slate-50 overflow-hidden">
          <img
            src={item.thumbnail}
            alt=""
            loading="lazy"
            className="w-full h-full object-cover"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = "none";
            }}
          />
        </a>
      )}
      <div className="p-3.5 flex-1 flex flex-col">
        <div className="flex items-center gap-1.5 text-[11px] text-slate-400 mb-1.5">
          {isVideo ? <Youtube className="w-3 h-3" /> : <Newspaper className="w-3 h-3" />}
          <span className="truncate">{item.source}</span>
          {item.view_count != null && (
            <span className="text-slate-300">·</span>
          )}
          {item.view_count != null && (
            <span>{fmt(item.view_count)}{isVideo ? " views" : ""}</span>
          )}
        </div>
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm font-semibold text-slate-900 leading-snug line-clamp-3 hover:underline mb-1.5"
        >
          {item.title}
        </a>
        {item.summary && (
          <p className="text-xs text-slate-500 line-clamp-2 mb-3 leading-relaxed">{item.summary}</p>
        )}
        <div className="mt-auto flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => onAdd(item)}
            disabled={busy || added}
            className={`text-xs font-medium rounded-md px-2.5 py-1.5 flex items-center gap-1 transition-colors ${
              added
                ? "bg-emerald-50 text-emerald-700 cursor-default"
                : "bg-slate-900 text-white hover:bg-slate-700 disabled:opacity-50"
            }`}
          >
            <Plus className="w-3 h-3" />
            {added ? "Saved" : busy ? "Adding…" : "Add"}
          </button>
          {isVideo && onCompareSelect && (
            <button
              type="button"
              onClick={() => onCompareSelect(item)}
              className={`text-xs font-medium rounded-md px-2.5 py-1.5 flex items-center gap-1 transition-colors ${
                compareCandidate
                  ? "bg-amber-100 text-amber-800 ring-1 ring-amber-300"
                  : "bg-slate-100 text-slate-700 hover:bg-slate-200"
              }`}
              title={compareCandidate ? "Selected for compare. Click another video" : "Pick this video to compare"}
            >
              <GitCompare className="w-3 h-3" />
              {compareCandidate ? "Pick 2nd" : "Compare"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}
