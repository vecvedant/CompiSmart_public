import { FileText, Globe, MessageSquare, Bookmark } from "lucide-react";
import type { CitationRef } from "../lib/types";

// The prop is named `citation` (NOT `ref`) because React reserves `ref` as
// the component-ref forwarding mechanism.
interface CitationChipProps {
  citation: CitationRef;
  raw: string;
}

const VIDEO_STYLES = {
  A: "bg-blue-50 text-blue-700 border-blue-200 hover:bg-blue-100",
  B: "bg-orange-50 text-orange-700 border-orange-200 hover:bg-orange-100",
} as const;

const WEB_STYLES =
  "bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100";

export function CitationChip({ citation, raw }: CitationChipProps) {
  // Web chip: clicking scrolls the SourcesPanel to the matching source row.
  // We use a CSS id (web-source-N) on each panel item; a tiny window event
  // triggers the scroll-and-flash.
  if (citation.kind === "web") {
    const handleClick = () => {
      const id = `web-source-${citation.idx}`;
      const el = document.getElementById(id);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.classList.add("ring-2", "ring-emerald-400");
        setTimeout(() => el.classList.remove("ring-2", "ring-emerald-400"), 1400);
      }
    };
    return (
      <button
        type="button"
        onClick={handleClick}
        title={`Web source ${citation.idx} -- click to view`}
        className={`inline-flex items-center gap-1 mx-0.5 px-2 py-0.5 rounded-full text-[11px] font-medium border align-middle cursor-pointer transition-colors ${WEB_STYLES}`}
      >
        <Globe className="w-3 h-3" />
        Web source {citation.idx}
        <span className="sr-only">{raw}</span>
      </button>
    );
  }

  // Asset chip: v2 chat over arbitrary saved assets.
  if (citation.slot === "asset") {
    const isAssetComment = citation.kind === "comment";
    const label = isAssetComment
      ? `Comment on asset ${citation.idx}`
      : `Asset ${citation.idx}`;
    const handleClick = () => {
      const id = `asset-${citation.idx}`;
      const el = document.getElementById(id);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.classList.add("ring-2", "ring-amber-400");
        setTimeout(() => el.classList.remove("ring-2", "ring-amber-400"), 1400);
      }
    };
    const Icon = isAssetComment ? MessageSquare : Bookmark;
    return (
      <button
        type="button"
        onClick={handleClick}
        title={`Asset ${citation.idx}${isAssetComment ? ` · comment ${citation.commentIdx}` : ""}`}
        className="inline-flex items-center gap-1 mx-0.5 px-2 py-0.5 rounded-full text-[11px] font-medium border align-middle cursor-pointer transition-colors bg-amber-50 text-amber-800 border-amber-200 hover:bg-amber-100"
      >
        <Icon className="w-3 h-3" />
        {label}
        <span className="sr-only">{raw}</span>
      </button>
    );
  }

  // Transcript / comment chip: friendly label, no chunk number.
  const isComment = citation.kind === "comment";
  const slotKey = citation.slot === "A" ? "A" : "B";
  const label = isComment
    ? `A comment from Video ${slotKey}`
    : `Video ${slotKey}`;
  const Icon = isComment ? MessageSquare : FileText;
  return (
    <span
      title={`From Video ${slotKey} -- ${citation.kind} chunk ${citation.idx}`}
      className={`inline-flex items-center gap-1 mx-0.5 px-2 py-0.5 rounded-full text-[11px] font-medium border align-middle ${VIDEO_STYLES[slotKey]}`}
    >
      <Icon className="w-3 h-3" />
      {label}
      <span className="sr-only">{raw}</span>
    </span>
  );
}
