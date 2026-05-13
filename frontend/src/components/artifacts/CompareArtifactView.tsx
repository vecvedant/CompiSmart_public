import { Loader2, Trophy } from "lucide-react";
import type { Artifact } from "../../lib/types";

interface VideoSide {
  id: string;
  title: string;
  metadata?: Record<string, unknown> | null;
}

interface Verdict {
  topic_a?: string;
  topic_b?: string;
  winning_video?: "A" | "B" | null;
  opinion?: string;
  reasons?: string[];
  used_search?: boolean;
  web_sources?: { url: string; title: string }[];
}

export function CompareArtifactView({
  artifact,
  isStreaming,
}: { artifact: Artifact; isStreaming: boolean }) {
  const p = artifact.payload_json as Record<string, unknown>;
  const a = (p.video_a as VideoSide | undefined) ?? null;
  const b = (p.video_b as VideoSide | undefined) ?? null;
  const verdict = (p.verdict as Verdict | undefined) ?? null;
  const stage = p.stage as string | undefined;
  const streamingPreview = (p.streaming_preview as string | undefined) ?? "";

  return (
    <div className="space-y-5">
      {/* Side-by-side cards */}
      <div className="grid grid-cols-2 gap-3">
        <SideCard side="A" video={a} winning={verdict?.winning_video === "A"} topic={verdict?.topic_a} />
        <SideCard side="B" video={b} winning={verdict?.winning_video === "B"} topic={verdict?.topic_b} />
      </div>

      {/* Verdict — live streaming preview while generating */}
      {!verdict && isStreaming && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/50 px-4 py-3 text-sm text-slate-700">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-amber-700 font-bold mb-1.5">
            <Loader2 className="w-3 h-3 animate-spin" />
            {stage === "verdict" ? "writing verdict…" : "setting up comparison…"}
          </div>
          {streamingPreview ? (
            <pre className="whitespace-pre-wrap text-xs leading-relaxed font-sans text-slate-600">
              {streamingPreview}
              <span className="inline-block w-1.5 h-3 bg-amber-500 ml-0.5 animate-blink align-middle" />
            </pre>
          ) : (
            <div className="text-slate-400 text-xs italic">Thinking…</div>
          )}
        </div>
      )}

      {verdict && (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-amber-700 mb-2">
            <Trophy className="w-3.5 h-3.5" /> Verdict
          </div>
          {verdict.winning_video && (
            <div className="text-sm font-semibold text-slate-900 mb-2">
              Winner: Video {verdict.winning_video}
            </div>
          )}
          {verdict.opinion && (
            <p className="text-sm text-slate-700 leading-relaxed mb-3">
              {verdict.opinion}
            </p>
          )}
          {!!(verdict.reasons || []).length && (
            <ul className="text-sm text-slate-700 space-y-1.5 list-disc list-inside">
              {verdict.reasons!.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}
          {verdict.used_search && !!(verdict.web_sources || []).length && (
            <div className="mt-3 border-t border-amber-200 pt-3">
              <div className="text-[10px] uppercase tracking-wide text-amber-700 mb-1.5">
                From the web
              </div>
              <ul className="space-y-1 text-xs">
                {verdict.web_sources!.map((s, i) => (
                  <li key={i}>
                    <a
                      href={s.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-amber-700 hover:underline truncate block"
                    >
                      {s.title || s.url}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SideCard({
  side,
  video,
  winning,
  topic,
}: {
  side: "A" | "B";
  video: VideoSide | null;
  winning: boolean;
  topic?: string;
}) {
  const meta = (video?.metadata as Record<string, unknown> | undefined) ?? {};
  const views = meta.views as number | undefined;
  const likes = meta.likes as number | undefined;
  const engagement = meta.engagement_rate as number | undefined;
  const creator = meta.creator as string | undefined;
  const thumb = meta.thumbnail_url as string | undefined;

  return (
    <div
      className={`rounded-2xl border p-3 ${
        winning
          ? "border-amber-400 bg-amber-50 shadow-md"
          : "border-slate-200 bg-white"
      }`}
    >
      <div className={`text-[10px] uppercase tracking-wide font-bold mb-1.5 ${
        winning ? "text-amber-700" : "text-slate-400"
      }`}>
        Video {side}
        {winning && " · winner"}
      </div>
      {thumb && (
        <div className="aspect-video bg-slate-100 rounded-lg overflow-hidden mb-2">
          <img
            src={thumb}
            alt=""
            className="w-full h-full object-cover"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = "none";
            }}
          />
        </div>
      )}
      <div className="text-sm font-semibold text-slate-900 line-clamp-2 leading-snug mb-2">
        {video?.title || "Untitled"}
      </div>
      {topic && (
        <div className="text-xs text-slate-500 italic mb-2 line-clamp-1">{topic}</div>
      )}
      {creator && (
        <div className="text-xs text-slate-500 mb-1">@{creator}</div>
      )}
      <div className="grid grid-cols-3 gap-1 text-[11px] mt-2 pt-2 border-t border-slate-100">
        <Stat label="Views" value={views ? fmt(views) : "—"} />
        <Stat label="Likes" value={likes ? fmt(likes) : "—"} />
        <Stat label="Eng." value={engagement ? `${engagement.toFixed(1)}%` : "—"} />
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-slate-400 text-[9px] uppercase tracking-wide">{label}</div>
      <div className="text-slate-900 font-semibold text-xs">{value}</div>
    </div>
  );
}

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}
