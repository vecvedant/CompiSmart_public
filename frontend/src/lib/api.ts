import type {
  Artifact,
  ArtifactKind,
  ArtifactStreamEvent,
  Asset,
  AssetType,
  BuildEvent,
  Draft,
  DraftLength,
  DraftTone,
  FeedResponse,
  IngestResponse,
  Niche,
  OutputType,
  SourcesPayload,
  Verdict,
  WebSource,
} from "./types";

// Same-origin: this SPA is served by the FastAPI backend at /. In Vite dev,
// the dev server proxies /api/* to localhost:8000.
const API_BASE = "";

export async function ingest(urlA: string, urlB: string): Promise<IngestResponse> {
  const res = await fetch(`${API_BASE}/api/ingest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url_a: urlA, url_b: urlB }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Ingest failed (${res.status}): ${text || res.statusText}`);
  }
  return (await res.json()) as IngestResponse;
}

export async function fetchSources(sessionId: string): Promise<SourcesPayload> {
  const res = await fetch(`${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}/sources`);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Sources fetch failed (${res.status}): ${text || res.statusText}`);
  }
  return (await res.json()) as SourcesPayload;
}

export async function fetchVerdict(
  sessionId: string,
  refresh: boolean = false,
): Promise<Verdict> {
  const url = `${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}/verdict${refresh ? "?refresh=1" : ""}`;
  const res = await fetch(url);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Verdict fetch failed (${res.status}): ${text || res.statusText}`);
  }
  return (await res.json()) as Verdict;
}

// Structured follow-up question the backend sends when an artifact intent
// is ambiguous (e.g., user has 5 videos and said "compare them").
export interface ClarificationFrame {
  kind: "clarification";
  question: string;
  questionKind: "mcq_single" | "mcq_multi" | "text";
  options: { id: string; label: string; description?: string }[];
  minPicks: number;
  maxPicks: number;
  intentHint: string;
}

// Server-Sent Events frame yielded by /api/chat. Includes artifact lifecycle.
export type ChatFrame =
  | { kind: "token"; text: string }
  | { kind: "sources"; sources: WebSource[] }
  | { kind: "done" }
  | { kind: "error"; message: string }
  | ClarificationFrame
  | ArtifactStreamEvent;

/**
 * Stream a chat response. Yields one ChatFrame per server-side event.
 * The backend emits one of three event shapes (see backend/app/routes/chat.py):
 *   data: {"token": "..."}
 *   event: done\ndata: {"done": true}
 *   event: error\ndata: {"error": "..."}
 *
 * We parse the wire format ourselves rather than using EventSource because
 * EventSource is GET-only and our endpoint is POST.
 */
export async function* chatStream(
  sessionId: string,
  message: string,
  signal?: AbortSignal,
): AsyncGenerator<ChatFrame> {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
    signal,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    yield { kind: "error", message: `Chat failed (${res.status}): ${text || res.statusText}` };
    return;
  }
  if (!res.body) {
    yield { kind: "error", message: "Chat response had no body" };
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line. Process any complete frames.
    let frameEnd: number;
    while ((frameEnd = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, frameEnd);
      buffer = buffer.slice(frameEnd + 2);
      const parsed = parseSseFrame(frame);
      if (parsed) yield parsed;
    }
  }

  // Drain any final unterminated frame.
  if (buffer.trim()) {
    const parsed = parseSseFrame(buffer);
    if (parsed) yield parsed;
  }
}

// ===========================================================================
// v2 endpoints
// ===========================================================================

export async function fetchNiches(): Promise<Niche[]> {
  const res = await fetch(`${API_BASE}/api/niches`);
  if (!res.ok) throw new Error(`Niches fetch failed (${res.status})`);
  const data = (await res.json()) as { niches: Niche[] };
  return data.niches;
}

export async function fetchFeed(niche: string, refresh = false): Promise<FeedResponse> {
  const url = refresh
    ? `${API_BASE}/api/feed/${encodeURIComponent(niche)}/refresh`
    : `${API_BASE}/api/feed/${encodeURIComponent(niche)}`;
  const res = await fetch(url, refresh ? { method: "POST" } : undefined);
  if (!res.ok) throw new Error(`Feed fetch failed (${res.status})`);
  return (await res.json()) as FeedResponse;
}

export async function listAssets(sessionId: string): Promise<Asset[]> {
  const res = await fetch(
    `${API_BASE}/api/assets?session_id=${encodeURIComponent(sessionId)}`,
  );
  if (!res.ok) throw new Error(`Assets fetch failed (${res.status})`);
  const data = (await res.json()) as { assets: Asset[] };
  return data.assets;
}

export async function addAsset(input: {
  session_id: string;
  type: AssetType;
  source_url?: string;
  title?: string;
  summary?: string;
  niche_slug?: string;
  metadata?: Record<string, unknown>;
}): Promise<Asset> {
  const res = await fetch(`${API_BASE}/api/assets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Add asset failed (${res.status}): ${text || res.statusText}`);
  }
  return (await res.json()) as Asset;
}

export async function deleteAsset(assetId: string, sessionId: string): Promise<void> {
  const res = await fetch(
    `${API_BASE}/api/assets/${encodeURIComponent(assetId)}?session_id=${encodeURIComponent(sessionId)}`,
    { method: "DELETE" },
  );
  if (!res.ok) throw new Error(`Delete asset failed (${res.status})`);
}

export async function createCompareSession(
  sessionId: string,
  assetAId: string,
  assetBId: string,
): Promise<{ compare_session_id: string }> {
  const res = await fetch(`${API_BASE}/api/compare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      asset_a_id: assetAId,
      asset_b_id: assetBId,
    }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Compare failed (${res.status}): ${text || res.statusText}`);
  }
  return (await res.json()) as { compare_session_id: string };
}

export async function listDrafts(sessionId: string): Promise<Draft[]> {
  const res = await fetch(
    `${API_BASE}/api/drafts?session_id=${encodeURIComponent(sessionId)}`,
  );
  if (!res.ok) throw new Error(`Drafts fetch failed (${res.status})`);
  const data = (await res.json()) as { drafts: Draft[] };
  return data.drafts;
}

export async function updateDraft(
  draftId: string,
  sessionId: string,
  patch: { title?: string; content_md?: string },
): Promise<Draft> {
  const res = await fetch(`${API_BASE}/api/drafts/${encodeURIComponent(draftId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, ...patch }),
  });
  if (!res.ok) throw new Error(`Draft update failed (${res.status})`);
  return (await res.json()) as Draft;
}

/** Stream Build mode events. Yields outline → expand → token… → done. */
export async function* buildStream(
  input: {
    session_id: string;
    asset_ids: string[];
    output_type: OutputType;
    tone?: DraftTone;
    length?: DraftLength;
    instruction?: string;
    chat_context_turns?: number;
  },
  signal?: AbortSignal,
): AsyncGenerator<BuildEvent> {
  const res = await fetch(`${API_BASE}/api/build`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
    signal,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    yield { kind: "error", message: `Build failed (${res.status}): ${text || res.statusText}` };
    return;
  }
  if (!res.body) {
    yield { kind: "error", message: "Build response had no body" };
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let frameEnd: number;
    while ((frameEnd = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, frameEnd);
      buffer = buffer.slice(frameEnd + 2);
      const ev = parseBuildFrame(frame);
      if (ev) yield ev;
    }
  }
  if (buffer.trim()) {
    const ev = parseBuildFrame(buffer);
    if (ev) yield ev;
  }
}

function parseBuildFrame(raw: string): BuildEvent | null {
  let event: string | null = null;
  const dataLines: string[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return null;
  try {
    const data = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
    if (event === "outline" && Array.isArray(data.bullets)) {
      return { kind: "outline", bullets: data.bullets as string[] };
    }
    if (event === "expand" && typeof data.section_count === "number") {
      return { kind: "expand", section_count: data.section_count };
    }
    if (event === "done") {
      return { kind: "done", draft_id: String(data.draft_id ?? "") };
    }
    if (event === "error" || typeof data.error === "string") {
      return { kind: "error", message: String(data.error ?? "unknown error") };
    }
    if (typeof data.token === "string") {
      return { kind: "token", text: data.token };
    }
  } catch {
    // ignore
  }
  return null;
}

function parseSseFrame(raw: string): ChatFrame | null {
  let event: string | null = null;
  let dataLines: string[] = [];
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }
  if (dataLines.length === 0) return null;
  const dataStr = dataLines.join("\n");
  try {
    const data = JSON.parse(dataStr) as Record<string, unknown>;
    // Artifact lifecycle events (backend emits `event: artifact_*`).
    if (event === "artifact_create") {
      return {
        kind: "artifact_create",
        id: String(data.id),
        artifactKind: String(data.kind) as ArtifactKind,
        title: String(data.title ?? ""),
        status: (data.status as "pending" | "ready" | "failed") ?? "pending",
        payload: (data.payload as Record<string, unknown>) ?? undefined,
      };
    }
    if (event === "artifact_update") {
      return {
        kind: "artifact_update",
        id: String(data.id),
        patch: (data.patch as Record<string, unknown>) ?? {},
      };
    }
    if (event === "artifact_token") {
      return {
        kind: "artifact_token",
        id: String(data.id),
        field: String(data.field ?? "content_md"),
        text: String(data.text ?? ""),
      };
    }
    if (event === "artifact_done") {
      return {
        kind: "artifact_done",
        id: String(data.id),
        title: String(data.title ?? ""),
        payload: (data.payload as Record<string, unknown>) ?? {},
      };
    }
    if (event === "artifact_error") {
      return {
        kind: "artifact_error",
        id: String(data.id),
        message: String(data.message ?? "unknown error"),
      };
    }
    if (event === "clarification") {
      return {
        kind: "clarification",
        question: String(data.question ?? ""),
        questionKind: (data.kind as "mcq_single" | "mcq_multi" | "text") ?? "mcq_single",
        options: ((data.options as Array<Record<string, unknown>>) ?? []).map((o) => ({
          id: String(o.id),
          label: String(o.label ?? ""),
          description: o.description ? String(o.description) : undefined,
        })),
        minPicks: Number(data.min_picks ?? 1),
        maxPicks: Number(data.max_picks ?? 1),
        intentHint: String(data.intent_hint ?? ""),
      };
    }
    if (event === "error" || typeof data.error === "string") {
      return { kind: "error", message: String(data.error ?? "unknown error") };
    }
    if (event === "done" || data.done === true) {
      return { kind: "done" };
    }
    if (event === "sources" && Array.isArray(data.sources)) {
      return { kind: "sources", sources: data.sources as WebSource[] };
    }
    if (typeof data.token === "string") {
      return { kind: "token", text: data.token };
    }
  } catch {
    // ignore unparseable frames
  }
  return null;
}

// ---------------------------------------------------------------------------
// Artifacts CRUD
// ---------------------------------------------------------------------------

export async function listArtifacts(sessionId: string): Promise<Artifact[]> {
  const res = await fetch(
    `${API_BASE}/api/artifacts?session_id=${encodeURIComponent(sessionId)}`,
  );
  if (!res.ok) throw new Error(`Artifacts fetch failed (${res.status})`);
  const data = (await res.json()) as { artifacts: Artifact[] };
  return data.artifacts;
}

export async function getArtifact(artifactId: string, sessionId: string): Promise<Artifact> {
  const res = await fetch(
    `${API_BASE}/api/artifacts/${encodeURIComponent(artifactId)}?session_id=${encodeURIComponent(sessionId)}`,
  );
  if (!res.ok) throw new Error(`Artifact fetch failed (${res.status})`);
  return (await res.json()) as Artifact;
}

export async function deleteArtifact(artifactId: string, sessionId: string): Promise<void> {
  const res = await fetch(
    `${API_BASE}/api/artifacts/${encodeURIComponent(artifactId)}?session_id=${encodeURIComponent(sessionId)}`,
    { method: "DELETE" },
  );
  if (!res.ok) throw new Error(`Artifact delete failed (${res.status})`);
}

/** Convert an artifact into a note-type asset (saved in the AssetsSidebar). */
export async function saveArtifactAsAsset(
  artifactId: string,
  sessionId: string,
): Promise<Asset> {
  const res = await fetch(
    `${API_BASE}/api/artifacts/${encodeURIComponent(artifactId)}/save-as-asset`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    },
  );
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Save as asset failed (${res.status}): ${text || res.statusText}`);
  }
  return (await res.json()) as Asset;
}
