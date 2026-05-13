import { ExternalLink, Globe } from "lucide-react";
import type { WebSource } from "../lib/types";

interface WebSourceCardProps {
  source: WebSource;
  // 1-indexed position in the list, used as the DOM id so a `[web:N]` chip
  // click can scroll-to-and-flash this card.
  index: number;
}

function deriveDomain(s: WebSource): string {
  // Gemini's grounding URLs are vertexaisearch.cloud.google.com redirects;
  // the human-readable domain lives in `title`. Fall back to the URL host
  // if that's missing (rare).
  if (s.title) return s.title;
  try {
    return new URL(s.url).hostname.replace(/^www\./, "");
  } catch {
    return s.url;
  }
}

export function WebSourceCard({ source, index }: WebSourceCardProps) {
  const domain = deriveDomain(source);
  const faviconUrl = (() => {
    try {
      const u = new URL(source.url);
      // Use Google's favicon service so we don't need to deal with CORS.
      return `https://www.google.com/s2/favicons?domain=${u.hostname}&sz=32`;
    } catch {
      return null;
    }
  })();

  return (
    <a
      id={`web-source-${index}`}
      href={source.url}
      target="_blank"
      rel="noopener noreferrer"
      className="group flex items-start gap-2.5 px-3 py-2 rounded-lg border border-slate-200 bg-white hover:border-emerald-300 hover:bg-emerald-50/30 transition-all"
    >
      <div className="flex-shrink-0 w-6 h-6 rounded bg-slate-100 flex items-center justify-center overflow-hidden">
        {faviconUrl ? (
          <img
            src={faviconUrl}
            alt=""
            className="w-4 h-4"
            onError={(e) => {
              (e.currentTarget as HTMLImageElement).style.display = "none";
            }}
          />
        ) : (
          <Globe className="w-3.5 h-3.5 text-slate-400" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-widest text-emerald-600">
          <span>Web {index}</span>
        </div>
        <div className="text-sm font-medium text-slate-900 truncate">{domain}</div>
        {source.snippet && (
          <p className="text-xs text-slate-500 line-clamp-2 mt-0.5">{source.snippet}</p>
        )}
      </div>
      <ExternalLink className="w-3.5 h-3.5 text-slate-300 group-hover:text-emerald-500 transition-colors flex-shrink-0 mt-0.5" />
    </a>
  );
}
