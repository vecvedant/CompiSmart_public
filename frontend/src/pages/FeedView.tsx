import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, RefreshCw, FileStack, Loader2 } from "lucide-react";
import { FeedCard } from "../components/FeedCard";
import { AssetsSidebar } from "../components/AssetsSidebar";
import { ArtifactPanel } from "../components/ArtifactPanel";
import { BuildModeUI } from "../components/BuildModeUI";
import { ChatPanel } from "../components/ChatPanel";
import {
  addAsset,
  createCompareSession,
  deleteAsset,
  fetchFeed,
  getArtifact,
  listArtifacts,
  listAssets,
} from "../lib/api";
import { getSessionId } from "../lib/session";
import type {
  Artifact,
  ArtifactKind,
  ArtifactStatus,
  ArtifactStreamEvent,
  Asset,
  FeedItem,
  FeedResponse,
} from "../lib/types";

type Mode = "plan" | "build";

export default function FeedView() {
  const { niche = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const sessionId = useMemo(() => getSessionId(), []);

  const mode: Mode = searchParams.get("mode") === "build" ? "build" : "plan";

  const [feed, setFeed] = useState<FeedResponse | null>(null);
  const [feedError, setFeedError] = useState<string | null>(null);
  const [feedLoading, setFeedLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const [assets, setAssets] = useState<Asset[]>([]);
  const [assetsLoading, setAssetsLoading] = useState(true);
  const [addingUrl, setAddingUrl] = useState<string | null>(null);
  const [savedUrls, setSavedUrls] = useState<Set<string>>(new Set());
  const [selectedAssetIds, setSelectedAssetIds] = useState<Set<string>>(new Set());

  // Two-step compare picker: first click stores the candidate video id;
  // second click on a different video fires the /api/compare call.
  const [compareFirst, setCompareFirst] = useState<FeedItem | null>(null);
  const [comparePreparing, setComparePreparing] = useState(false);

  // Focus mode — when true the chat panel takes the whole working area
  // and the feed grid collapses out of view. Esc / toolbar exits.
  const [chatFocused, setChatFocused] = useState(false);

  // Artifact state — Claude.ai-style overlay drawer + inline chat cards.
  // `artifactsById` is the single source of truth: ChatPanel reads it to
  // render fresh inline cards, the drawer reads it for the active artifact.
  const [artifactsById, setArtifactsById] = useState<Map<string, Artifact>>(new Map());
  const [activeArtifactId, setActiveArtifactId] = useState<string | null>(null);
  const [artifactStreaming, setArtifactStreaming] = useState(false);
  const [artifactPanelOpen, setArtifactPanelOpen] = useState(false);
  const [artifactHistory, setArtifactHistory] = useState<Artifact[]>([]);

  const activeArtifact = activeArtifactId ? artifactsById.get(activeArtifactId) ?? null : null;

  // Initial load: fetch any past artifacts in this session.
  useEffect(() => {
    listArtifacts(sessionId)
      .then((list) => {
        setArtifactHistory(list);
        setArtifactsById((prev) => {
          const next = new Map(prev);
          for (const a of list) next.set(a.id, a);
          return next;
        });
      })
      .catch((e) => console.warn("artifact list failed", e));
  }, [sessionId]);

  function patchArtifact(id: string, fn: (a: Artifact) => Artifact) {
    setArtifactsById((prev) => {
      const cur = prev.get(id);
      if (!cur) return prev;
      const next = new Map(prev);
      next.set(id, fn(cur));
      return next;
    });
  }

  function handleArtifactEvent(ev: ArtifactStreamEvent) {
    if (ev.kind === "artifact_create") {
      const newArtifact: Artifact = {
        id: ev.id,
        session_id: sessionId,
        kind: ev.artifactKind,
        title: ev.title,
        status: ev.status,
        asset_ids: [],
        prompt: "",
        payload_json: (ev.payload as Record<string, unknown>) || {},
      };
      setArtifactsById((prev) => {
        const next = new Map(prev);
        next.set(ev.id, newArtifact);
        return next;
      });
      setArtifactStreaming(ev.status === "pending");
      // Default behavior: don't auto-open the drawer — user clicks the
      // inline card to expand. Inline previews show progress in-context.
      setArtifactHistory((prev) => [newArtifact, ...prev.filter((h) => h.id !== ev.id)]);
    } else if (ev.kind === "artifact_update") {
      patchArtifact(ev.id, (a) => ({
        ...a,
        payload_json: { ...a.payload_json, ...ev.patch },
      }));
    } else if (ev.kind === "artifact_token") {
      patchArtifact(ev.id, (a) => {
        const cur = String(a.payload_json[ev.field] ?? "");
        return {
          ...a,
          payload_json: { ...a.payload_json, [ev.field]: cur + ev.text },
        };
      });
    } else if (ev.kind === "artifact_done") {
      patchArtifact(ev.id, (a) => ({
        ...a,
        status: "ready" as ArtifactStatus,
        title: ev.title || a.title,
        payload_json: ev.payload || a.payload_json,
      }));
      setArtifactHistory((h) => {
        const cur = artifactsById.get(ev.id);
        const merged: Artifact = cur
          ? { ...cur, status: "ready", title: ev.title || cur.title, payload_json: ev.payload || cur.payload_json }
          : ({} as Artifact);
        return [merged, ...h.filter((x) => x.id !== ev.id)];
      });
      setArtifactStreaming(false);
    } else if (ev.kind === "artifact_error") {
      patchArtifact(ev.id, (a) => ({
        ...a,
        status: "failed" as ArtifactStatus,
        payload_json: { ...a.payload_json, error: ev.message },
      }));
      setArtifactStreaming(false);
    }
  }

  function openArtifact(id: string) {
    setActiveArtifactId(id);
    setArtifactPanelOpen(true);
  }

  async function openHistoricalArtifact(a: Artifact) {
    try {
      const fresh = await getArtifact(a.id, sessionId);
      setArtifactsById((prev) => {
        const next = new Map(prev);
        next.set(fresh.id, fresh);
        return next;
      });
      setActiveArtifactId(fresh.id);
      setArtifactPanelOpen(true);
      setArtifactStreaming(false);
    } catch (e) {
      console.warn("get artifact failed", e);
      setActiveArtifactId(a.id);
      setArtifactPanelOpen(true);
      setArtifactStreaming(false);
    }
  }

  // ---- feed ----
  useEffect(() => {
    if (!niche) return;
    let cancelled = false;
    setFeedLoading(true);
    setFeedError(null);
    fetchFeed(niche)
      .then((f) => {
        if (!cancelled) setFeed(f);
      })
      .catch((e) => {
        if (!cancelled) setFeedError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setFeedLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [niche]);

  const refreshFeed = useCallback(async () => {
    if (!niche) return;
    setRefreshing(true);
    try {
      const f = await fetchFeed(niche, true);
      setFeed(f);
    } catch (e) {
      setFeedError(e instanceof Error ? e.message : String(e));
    } finally {
      setRefreshing(false);
    }
  }, [niche]);

  // ---- assets ----
  const loadAssets = useCallback(async () => {
    setAssetsLoading(true);
    try {
      const list = await listAssets(sessionId);
      setAssets(list);
      setSavedUrls(new Set(list.map((a) => a.source_url || "").filter(Boolean)));
    } catch (e) {
      console.warn("listAssets failed", e);
    } finally {
      setAssetsLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void loadAssets();
  }, [loadAssets]);

  // Light polling so pending → ready transitions show up without a refresh button.
  useEffect(() => {
    const hasPending = assets.some((a) => a.ingest_status === "pending");
    if (!hasPending) return;
    const t = setInterval(() => {
      void loadAssets();
    }, 5000);
    return () => clearInterval(t);
  }, [assets, loadAssets]);

  // ---- add to assets ----
  async function handleAdd(item: FeedItem) {
    if (savedUrls.has(item.url)) return;
    setAddingUrl(item.url);
    try {
      await addAsset({
        session_id: sessionId,
        type: item.type === "video" ? "video" : "article",
        source_url: item.url,
        title: item.title,
        summary: item.summary,
        niche_slug: niche || undefined,
        metadata: {},
      });
      setSavedUrls((prev) => new Set(prev).add(item.url));
      void loadAssets();
    } catch (e) {
      alert(`Add failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setAddingUrl(null);
    }
  }

  async function handleAddCustom(url: string) {
    if (savedUrls.has(url)) return;
    const isYoutube = /youtube\.com|youtu\.be/i.test(url);
    const isInstagram = /instagram\.com/i.test(url);
    try {
      await addAsset({
        session_id: sessionId,
        type: isYoutube || isInstagram ? "video" : "article",
        source_url: url,
        title: url,
        niche_slug: niche || undefined,
      });
      setSavedUrls((prev) => new Set(prev).add(url));
      void loadAssets();
    } catch (e) {
      alert(`Add failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  async function handleDelete(id: string) {
    const asset = assets.find((a) => a.id === id);
    setAssets((prev) => prev.filter((a) => a.id !== id));
    setSelectedAssetIds((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
    if (asset?.source_url) {
      setSavedUrls((prev) => {
        const next = new Set(prev);
        next.delete(asset.source_url!);
        return next;
      });
    }
    try {
      await deleteAsset(id, sessionId);
    } catch (e) {
      console.warn("delete failed", e);
      void loadAssets();
    }
  }

  // ---- compare flow ----
  async function handleCompareSelect(item: FeedItem) {
    if (!compareFirst) {
      setCompareFirst(item);
      return;
    }
    if (compareFirst.url === item.url) {
      setCompareFirst(null);
      return;
    }

    // Ensure both items are saved as assets first (compare needs ready assets).
    setComparePreparing(true);
    try {
      const firstAsset = await ensureAsset(compareFirst);
      const secondAsset = await ensureAsset(item);
      if (!firstAsset || !secondAsset) {
        alert("Could not save both videos as assets. Try again.");
        return;
      }

      // Poll until BOTH assets reach ingest_status=ready before navigating.
      // Without this, /api/compare 409s when the video is still being
      // transcribed (Apify pintostudio call takes 5-15s).
      const ok = await waitForAssetsReady([firstAsset.id, secondAsset.id], 90_000);
      if (!ok) {
        alert(
          "One of the videos is still being transcribed and we couldn't reach 'ready' " +
          "within 90 seconds. Open it from the sidebar and try again in a moment.",
        );
        return;
      }
      navigate(
        `/compare/${encodeURIComponent(firstAsset.id)}/${encodeURIComponent(secondAsset.id)}`,
      );
    } finally {
      setComparePreparing(false);
      setCompareFirst(null);
    }
  }

  /** Poll /api/assets until the given asset_ids are all `ready` (or `failed`),
   * or until timeout. Returns true iff all reached ready. */
  async function waitForAssetsReady(ids: string[], timeoutMs: number): Promise<boolean> {
    const want = new Set(ids);
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      try {
        const list = await listAssets(sessionId);
        const ready = new Set(
          list.filter((a) => want.has(a.id) && a.ingest_status === "ready").map((a) => a.id),
        );
        if (ready.size === want.size) return true;
        const failed = list.find((a) => want.has(a.id) && a.ingest_status === "failed");
        if (failed) return false;
      } catch {
        // ignore transient fetch errors, keep polling
      }
      await new Promise((r) => setTimeout(r, 2000));
    }
    return false;
  }

  async function ensureAsset(item: FeedItem): Promise<Asset | null> {
    const existing = assets.find((a) => a.source_url === item.url);
    if (existing) return existing;
    try {
      const created = await addAsset({
        session_id: sessionId,
        type: "video",
        source_url: item.url,
        title: item.title,
        summary: item.summary,
        niche_slug: niche || undefined,
      });
      setSavedUrls((prev) => new Set(prev).add(item.url));
      void loadAssets();
      return created;
    } catch (e) {
      console.warn("ensureAsset failed", e);
      return null;
    }
  }

  function toggleSelected(id: string) {
    setSelectedAssetIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // ---- render ----
  return (
    // h-screen + flex-col with overflow-hidden so the inner row's children
    // (feed grid, chat, assets sidebar) each manage their OWN scroll
    // instead of the whole document growing. Without this, the chat panel
    // stretches to document height and the feed becomes one giant page.
    <div className="h-screen bg-slate-50 flex flex-col overflow-hidden">
      <header className="border-b border-slate-200 bg-white shrink-0">
        <div className="max-w-7xl mx-auto px-5 py-2.5 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <Link
              to="/"
              className="text-slate-400 hover:text-slate-900 shrink-0"
              aria-label="Back to niches"
            >
              <ArrowLeft className="w-4 h-4" />
            </Link>
            <span className="text-sm font-semibold tracking-tight text-slate-900">
              CompiSMART
            </span>
            <span className="text-slate-200">/</span>
            <span className="text-sm text-slate-500 capitalize truncate">{niche}</span>
          </div>
          <div className="flex items-center gap-1">
            {/* Plan / Build toggle as a segmented control */}
            <div className="flex items-center bg-slate-100 rounded-lg p-0.5 mr-1">
              <button
                type="button"
                onClick={() => setSearchParams({})}
                className={`text-xs font-medium rounded-md px-2.5 py-1 transition-colors ${
                  mode === "plan" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-900"
                }`}
              >
                Plan
              </button>
              <button
                type="button"
                onClick={() => setSearchParams({ mode: "build" })}
                className={`text-xs font-medium rounded-md px-2.5 py-1 transition-colors ${
                  mode === "build" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-900"
                }`}
              >
                Build
              </button>
            </div>
            <Link
              to={`/feed/${niche}/drafts`}
              className="text-slate-400 hover:text-slate-900 p-1.5 rounded-md hover:bg-slate-100 transition-colors"
              title="Drafts"
              aria-label="Drafts"
            >
              <FileStack className="w-4 h-4" />
            </Link>
            <button
              type="button"
              onClick={refreshFeed}
              disabled={refreshing}
              className="text-slate-400 hover:text-slate-900 p-1.5 rounded-md hover:bg-slate-100 transition-colors disabled:opacity-50"
              title="Refresh feed"
              aria-label="Refresh feed"
            >
              <RefreshCw className={`w-4 h-4 ${refreshing ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>
      </header>

      <div className="flex-1 flex flex-col lg:flex-row min-h-0">
        {mode === "plan" ? (
          <PlanMode
            feed={feed}
            feedError={feedError}
            feedLoading={feedLoading}
            addingUrl={addingUrl}
            savedUrls={savedUrls}
            onAdd={handleAdd}
            onCompareSelect={handleCompareSelect}
            compareFirst={compareFirst}
            sessionId={sessionId}
            onArtifactEvent={handleArtifactEvent}
            artifactsById={artifactsById}
            onOpenArtifact={openArtifact}
            chatFocused={chatFocused}
            onToggleChatFocus={() => setChatFocused((v) => !v)}
          />
        ) : (
          <BuildModeUI
            sessionId={sessionId}
            assets={assets}
            selectedIds={selectedAssetIds}
          />
        )}

        {!chatFocused && (
          <AssetsSidebar
            assets={assets}
            loading={assetsLoading}
            selectable={mode === "build"}
            selectedIds={selectedAssetIds}
            onToggleSelect={toggleSelected}
            onDelete={handleDelete}
            onAddCustom={handleAddCustom}
          />
        )}
      </div>

      {/* Overlay drawer — fixed-position, slides in from right with backdrop. */}
      <ArtifactPanel
        sessionId={sessionId}
        open={artifactPanelOpen}
        active={activeArtifact}
        history={artifactHistory}
        isStreaming={artifactStreaming}
        onClose={() => setArtifactPanelOpen(false)}
        onPickArtifact={openHistoricalArtifact}
        onHistoryChange={setArtifactHistory}
      />

      {/* Compare-preparing toast — visible while waiting for both video
          assets to finish transcription before navigating to /compare. */}
      {comparePreparing && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-30 bg-slate-900 text-white text-sm px-4 py-2.5 rounded-full shadow-lg flex items-center gap-2">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          Preparing comparison… (transcribing videos)
        </div>
      )}
    </div>
  );
}

interface PlanProps {
  feed: FeedResponse | null;
  feedError: string | null;
  feedLoading: boolean;
  addingUrl: string | null;
  savedUrls: Set<string>;
  onAdd: (item: FeedItem) => void;
  onCompareSelect: (item: FeedItem) => void;
  compareFirst: FeedItem | null;
  sessionId: string;
  onArtifactEvent: (ev: ArtifactStreamEvent) => void;
  artifactsById: Map<string, Artifact>;
  onOpenArtifact: (id: string) => void;
  chatFocused: boolean;
  onToggleChatFocus: () => void;
}

function PlanMode(props: PlanProps) {
  const { feed, feedError, feedLoading, addingUrl, savedUrls, onAdd, onCompareSelect, compareFirst, sessionId, onArtifactEvent, artifactsById, onOpenArtifact, chatFocused, onToggleChatFocus } = props;
  return (
    <>
      {!chatFocused && (
        <main className="flex-1 min-w-0 overflow-y-auto p-6">
          {feedError && (
            <div className="rounded-xl border border-red-200 bg-red-50 text-red-700 px-4 py-3 mb-4">
              {feedError}
            </div>
          )}
          {feedLoading && (
            <div className="text-slate-400 text-sm">Loading feed…</div>
          )}
          {feed && (
            <div className="grid sm:grid-cols-2 xl:grid-cols-3 gap-4">
              {feed.items.map((item) => (
                <FeedCard
                  key={item.url}
                  item={item}
                  onAdd={onAdd}
                  onCompareSelect={onCompareSelect}
                  busy={addingUrl === item.url}
                  added={savedUrls.has(item.url)}
                  compareCandidate={compareFirst?.url === item.url}
                />
              ))}
            </div>
          )}
        </main>
      )}
      <div
        className={`shrink-0 border-l border-slate-200 bg-white flex flex-col min-h-0 transition-all duration-200 ${
          chatFocused ? "flex-1 w-full" : "w-full lg:w-96"
        }`}
      >
        <ChatPanel
          sessionId={sessionId}
          onSourcesUpdate={() => {}}
          onArtifactEvent={onArtifactEvent}
          artifactsById={artifactsById}
          onOpenArtifact={onOpenArtifact}
          focused={chatFocused}
          onToggleFocus={onToggleChatFocus}
        />
      </div>
    </>
  );
}
