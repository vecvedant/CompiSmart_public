import type { ArtifactKind } from "../lib/types";

interface Props {
  kind: ArtifactKind;
  payload?: Record<string, unknown>;
}

/** Skeleton previews shown inline in the chat while the artifact streams in.
 * Mirrors the shape of the final renderer so the transition feels smooth. */
export function ArtifactSkeleton({ kind, payload }: Props) {
  if (kind === "compare") return <CompareSkeleton payload={payload} />;
  if (kind === "draft") return <DraftSkeleton payload={payload} />;
  if (kind === "summary") return <SummarySkeleton />;
  if (kind === "metrics") return <MetricsSkeleton />;
  if (kind === "quotes") return <QuotesSkeleton />;
  return <DefaultSkeleton />;
}

// Shared shimmer utility: pulse + soft gradient.
const SHIMMER = "bg-gradient-to-r from-slate-100 via-slate-200 to-slate-100 bg-[length:200%_100%] animate-shimmer rounded";

function CompareSkeleton({ payload }: { payload?: Record<string, unknown> }) {
  const a = payload?.video_a as { title?: string; metadata?: Record<string, unknown> } | undefined;
  const b = payload?.video_b as { title?: string; metadata?: Record<string, unknown> } | undefined;
  return (
    <div className="space-y-2.5">
      <div className="grid grid-cols-2 gap-2">
        <MiniVideoCard side="A" title={a?.title} />
        <MiniVideoCard side="B" title={b?.title} />
      </div>
      <div className="h-2 w-3/4 bg-slate-200 rounded animate-pulse" />
      <div className="h-2 w-full bg-slate-200 rounded animate-pulse" />
      <div className="h-2 w-2/3 bg-slate-200 rounded animate-pulse" />
    </div>
  );
}

function MiniVideoCard({ side, title }: { side: "A" | "B"; title?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-2">
      <div className="text-[9px] uppercase tracking-wide font-bold text-slate-400 mb-1">
        Video {side}
      </div>
      <div className={`h-12 ${SHIMMER} mb-1.5`} />
      {title ? (
        <div className="text-[10px] text-slate-700 font-semibold line-clamp-2 leading-tight">
          {title}
        </div>
      ) : (
        <div className={`h-2 w-3/4 ${SHIMMER}`} />
      )}
    </div>
  );
}

function DraftSkeleton({ payload }: { payload?: Record<string, unknown> }) {
  const bullets = (payload?.bullets as string[] | undefined) || [];
  const content = String(payload?.content_md ?? "");
  return (
    <div className="space-y-2">
      {bullets.length > 0 && (
        <div className="space-y-1">
          <div className="text-[9px] uppercase tracking-wide font-bold text-amber-700">
            Outline ✓
          </div>
          {bullets.slice(0, 3).map((b, i) => (
            <div key={i} className="text-[11px] text-slate-600 line-clamp-1">
              · {b}
            </div>
          ))}
        </div>
      )}
      {content ? (
        <div className="text-[11px] text-slate-600 line-clamp-3 italic">
          {content.slice(0, 220).replace(/^#+\s*/gm, "")}…
        </div>
      ) : (
        <div className="space-y-1">
          <div className={`h-2 w-full ${SHIMMER}`} />
          <div className={`h-2 w-11/12 ${SHIMMER}`} />
          <div className={`h-2 w-5/6 ${SHIMMER}`} />
        </div>
      )}
    </div>
  );
}

function SummarySkeleton() {
  return (
    <div className="space-y-1.5">
      <div className={`h-3 w-2/3 ${SHIMMER}`} />
      <div className="space-y-1 pl-2">
        <div className={`h-2 w-full ${SHIMMER}`} />
        <div className={`h-2 w-5/6 ${SHIMMER}`} />
        <div className={`h-2 w-4/6 ${SHIMMER}`} />
      </div>
    </div>
  );
}

function MetricsSkeleton() {
  return (
    <div className="grid grid-cols-4 gap-1.5">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="rounded-md border border-slate-100 bg-slate-50 p-1.5">
          <div className={`h-1.5 w-1/2 ${SHIMMER} mb-1`} />
          <div className={`h-2 w-3/4 ${SHIMMER}`} />
        </div>
      ))}
    </div>
  );
}

function QuotesSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 2 }).map((_, i) => (
        <div key={i} className="border-l-2 border-amber-200 pl-2.5 space-y-1">
          <div className={`h-2 w-full ${SHIMMER}`} />
          <div className={`h-2 w-4/5 ${SHIMMER}`} />
        </div>
      ))}
    </div>
  );
}

function DefaultSkeleton() {
  return (
    <div className="space-y-1.5">
      <div className={`h-2 w-full ${SHIMMER}`} />
      <div className={`h-2 w-2/3 ${SHIMMER}`} />
    </div>
  );
}
