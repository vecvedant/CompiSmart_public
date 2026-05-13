import { useState } from "react";
import { Calendar, Clock, MessageCircle, Heart, Eye, PlayCircle, Users } from "lucide-react";
import type { VideoMeta } from "../lib/types";
import { LifeStageBadge } from "./LifeStageBadge";
import { TrendBadge } from "./TrendBadge";

const ACCENT: Record<"A" | "B", { ring: string; chipBg: string; chipText: string; gradient: string }> = {
  A: {
    ring: "ring-blue-200/60",
    chipBg: "bg-blue-50",
    chipText: "text-blue-700",
    gradient: "from-blue-500 to-blue-700",
  },
  B: {
    ring: "ring-orange-200/60",
    chipBg: "bg-orange-50",
    chipText: "text-orange-700",
    gradient: "from-orange-500 to-rose-600",
  },
};

/**
 * Pick the right URL for the <img> tag. Meta's CDN
 * (scontent-*.cdninstagram.com) blocks direct browser requests, so for IG
 * thumbnails we proxy through our own backend. YouTube's i.ytimg.com loads
 * fine directly.
 */
function thumbnailSrc(meta: VideoMeta): string | null {
  if (!meta.thumbnail_url) return null;
  if (meta.platform === "instagram") {
    return `/api/proxy-image?url=${encodeURIComponent(meta.thumbnail_url)}`;
  }
  return meta.thumbnail_url;
}

function creatorInitials(creator: string): string {
  const cleaned = creator.replace(/^@/, "").replace(/[^a-zA-Z0-9]/g, "");
  if (cleaned.length === 0) return "?";
  const parts = cleaned.split(/(?=[A-Z_])|_/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return cleaned.slice(0, 2).toUpperCase();
}

export function VideoCard({ meta }: { meta: VideoMeta }) {
  const accent = ACCENT[meta.slot];
  const [imgFailed, setImgFailed] = useState(false);
  const src = thumbnailSrc(meta);

  return (
    <div
      className={`bg-white rounded-3xl border border-slate-200 overflow-hidden shadow-sm hover:shadow-md transition-shadow ring-2 ${accent.ring}`}
    >
      <div className="relative aspect-video bg-slate-900 overflow-hidden group">
        {src && !imgFailed ? (
          <img
            src={src}
            alt={meta.title ?? meta.creator}
            className="w-full h-full object-cover opacity-90 group-hover:scale-105 transition-transform duration-500"
            loading="lazy"
            referrerPolicy="no-referrer"
            onError={() => setImgFailed(true)}
          />
        ) : (
          // Graceful fallback: gradient + initials. Looks intentional rather
          // than broken when Meta refuses to serve the image.
          <div
            className={`w-full h-full flex items-center justify-center bg-gradient-to-br ${accent.gradient}`}
          >
            <div className="text-white text-5xl font-extrabold tracking-tight opacity-90">
              {creatorInitials(meta.creator)}
            </div>
          </div>
        )}
        <a
          href={meta.url}
          target="_blank"
          rel="noopener noreferrer"
          className="absolute inset-0 flex items-center justify-center"
          title="Open original video"
        >
          <div className="w-16 h-16 bg-white/30 border border-white/40 rounded-full flex items-center justify-center text-white text-3xl hover:bg-orange-500 hover:border-orange-500 transition-all shadow-xl">
            <PlayCircle className="w-8 h-8" />
          </div>
        </a>
        <div className="absolute top-3 left-3">
          <span
            className={`inline-flex items-center px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest ${accent.chipBg} ${accent.chipText}`}
          >
            Video {meta.slot}
          </span>
        </div>
      </div>

      <div className="p-6 md:p-7 space-y-5">
        {/* Creator + engagement headline */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-lg font-bold text-slate-900 tracking-tight">
              @{meta.creator}
            </h3>
            <p className="text-slate-500 text-sm flex items-center gap-1 mt-1">
              <Users className="w-4 h-4" />
              {meta.follower_count != null
                ? `${formatCompact(meta.follower_count)} followers`
                : "follower count unavailable"}
            </p>
          </div>
          <div className="text-right shrink-0">
            <div className="text-2xl font-black text-orange-500 tracking-tight">
              {meta.engagement_rate.toFixed(2)}%
            </div>
            <div className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">
              Engagement
            </div>
          </div>
        </div>

        {/* Metric row */}
        <div className="grid grid-cols-3 gap-3 bg-slate-50 p-4 rounded-2xl border border-slate-100">
          <Stat icon={<Eye className="w-3.5 h-3.5" />} label="Views" value={formatCompact(meta.views)} />
          <Stat icon={<Heart className="w-3.5 h-3.5" />} label="Likes" value={formatCompact(meta.likes)} />
          <Stat icon={<MessageCircle className="w-3.5 h-3.5" />} label="Comments" value={formatCompact(meta.comments)} />
        </div>

        {/* Date / duration / velocity */}
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
          {meta.upload_date && (
            <span className="inline-flex items-center gap-1">
              <Calendar className="w-3.5 h-3.5" />
              {formatDate(meta.upload_date)}
            </span>
          )}
          {meta.duration_sec != null && (
            <span className="inline-flex items-center gap-1">
              <Clock className="w-3.5 h-3.5" />
              {Math.round(meta.duration_sec)}s
            </span>
          )}
          {meta.view_velocity != null && meta.age_days != null && (
            <span className="inline-flex items-center gap-1">
              📊 {Math.round(meta.view_velocity).toLocaleString()} views/day
            </span>
          )}
        </div>

        {/* Stage + trend badges */}
        <div className="flex flex-wrap gap-2">
          <LifeStageBadge stage={meta.life_stage} />
          <TrendBadge status={meta.topic_trend_status} />
        </div>

        {/* Hashtags */}
        {meta.hashtags.length > 0 && (
          <div className="text-sm text-slate-500 truncate">
            {meta.hashtags.slice(0, 8).map((h) => `#${h}`).join("  ")}
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="text-center">
      <div className="text-slate-900 font-bold text-lg tracking-tight">
        {value}
      </div>
      <div className="flex items-center justify-center gap-1 text-slate-400 text-[10px] font-bold uppercase tracking-widest">
        {icon}
        {label}
      </div>
    </div>
  );
}

function formatCompact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n >= 10_000 ? 0 : 1)}K`;
  return String(n);
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}
