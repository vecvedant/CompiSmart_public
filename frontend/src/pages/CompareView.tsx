import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Layers } from "lucide-react";
import { VideoCard } from "../components/VideoCard";
import { ChatPanel } from "../components/ChatPanel";
import { InsightPanel } from "../components/InsightPanel";
import { SourcesPanel } from "../components/SourcesPanel";
import {
  createCompareSession,
  fetchSources,
  fetchVerdict,
} from "../lib/api";
import { getSessionId } from "../lib/session";
import type {
  IngestResponse,
  SourcesPayload,
  Verdict,
  WebSource,
} from "../lib/types";

export default function CompareView() {
  const { assetA = "", assetB = "" } = useParams();
  const sessionId = getSessionId();

  const [data, setData] = useState<IngestResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sources, setSources] = useState<SourcesPayload | null>(null);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [verdictLoading, setVerdictLoading] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // 1) Create the compare session from the two asset IDs.
  useEffect(() => {
    let cancelled = false;
    if (!assetA || !assetB) return;
    setError(null);
    createCompareSession(sessionId, assetA, assetB)
      .then((res) => {
        if (cancelled) return;
        // Hydrate IngestResponse from compare-mode response.
        const r = res as unknown as {
          compare_session_id: string;
          video_a: IngestResponse["video_a"];
          video_b: IngestResponse["video_b"];
        };
        setData({
          session_id: r.compare_session_id,
          video_a: r.video_a,
          video_b: r.video_b,
        });
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [assetA, assetB, sessionId]);

  // 2) Fetch sources + verdict for the compare session.
  useEffect(() => {
    if (!data) return;
    let cancelled = false;
    fetchSources(data.session_id)
      .then((p) => {
        if (!cancelled) setSources(p);
      })
      .catch(() => {});
    setVerdictLoading(true);
    fetchVerdict(data.session_id)
      .then((v) => {
        if (!cancelled) setVerdict(v);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setVerdictLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [data]);

  const mergeWebSources = useCallback((fresh: WebSource[]) => {
    if (!fresh.length) return;
    setVerdict((prev) => {
      if (!prev) return prev;
      const seen = new Set(prev.web_sources.map((s) => s.url));
      const next = [...prev.web_sources];
      for (const s of fresh) {
        if (!seen.has(s.url)) {
          next.push(s);
          seen.add(s.url);
        }
      }
      return { ...prev, web_sources: next, used_search: true };
    });
  }, []);

  if (error) {
    return (
      <div className="min-h-screen bg-slate-50 p-8">
        <div className="max-w-xl mx-auto rounded-xl border border-red-200 bg-red-50 text-red-700 px-4 py-3">
          {error}
        </div>
        <div className="text-center mt-6">
          <Link to="/" className="text-orange-600 hover:underline">
            ← Back to niches
          </Link>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center text-slate-400">
        Setting up the compare session…
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 flex">
      <SourcesPanel
        data={sources}
        loading={!sources}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
      <div className="flex-1 min-w-0 flex flex-col">
        <header className="border-b border-slate-200 bg-white">
          <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <div className="w-9 h-9 bg-orange-500 rounded-xl flex items-center justify-center text-white">
                <Layers className="w-4 h-4" />
              </div>
              <span className="text-lg font-bold tracking-tight text-slate-900">
                Compi<span className="text-orange-500">SMART</span>
              </span>
              <span className="text-xs text-slate-400 ml-2">· compare</span>
            </div>
            <Link
              to="/"
              className="inline-flex items-center gap-1.5 text-sm font-medium text-slate-500 hover:text-slate-900"
            >
              <ArrowLeft className="w-4 h-4" />
              Back to niches
            </Link>
          </div>
        </header>
        <main className="flex-1 max-w-6xl w-full mx-auto px-6 py-8 pb-12 space-y-6">
          <div className="grid md:grid-cols-2 gap-6">
            <VideoCard meta={data.video_a} />
            <VideoCard meta={data.video_b} />
          </div>
          <InsightPanel
            verdict={verdict}
            loading={verdictLoading}
            error={null}
            onRefresh={() => {
              setVerdictLoading(true);
              fetchVerdict(data.session_id, true)
                .then((v) => setVerdict(v))
                .finally(() => setVerdictLoading(false));
            }}
          />
          <ChatPanel
            sessionId={data.session_id}
            onSourcesUpdate={mergeWebSources}
          />
        </main>
      </div>
      {drawerOpen && (
        <div
          className="fixed inset-0 bg-slate-900/30 z-30 lg:hidden"
          onClick={() => setDrawerOpen(false)}
        />
      )}
    </div>
  );
}
