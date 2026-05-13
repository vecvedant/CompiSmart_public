import { useEffect, useRef, useState } from "react";
import { Send, Square, Maximize2, Minimize2 } from "lucide-react";
import { chatStream } from "../lib/api";
import type { Artifact, ArtifactStreamEvent, ChatTurn, WebSource } from "../lib/types";
import { UserMessage } from "./UserMessage";
import { AIMessage } from "./AIMessage";
import { ArtifactInlineCard } from "./ArtifactInlineCard";
import { ClarificationCard } from "./ClarificationCard";

const SUGGESTIONS = [
  "Compare the top two videos",
  "Write me a blog post from these",
  "Summarize what these are all saying",
  "Pull the best quotes from the comments",
];

interface ChatPanelProps {
  sessionId: string;
  // Fires after each AI turn finishes, with the new web sources Gemini cited
  // during that turn (empty array if it didn't search). The parent uses this
  // to grow the Sources panel without re-fetching the whole sources payload.
  onSourcesUpdate?: (sources: WebSource[]) => void;
  // Fires for artifact lifecycle events spawned by chat intent. Parent uses
  // these to open / update / close the artifact side panel.
  onArtifactEvent?: (ev: ArtifactStreamEvent) => void;
  // Live map of artifacts by id, updated by the parent. ChatPanel reads this
  // when rendering inline artifact cards so they stay current as the stream
  // arrives.
  artifactsById?: Map<string, Artifact>;
  // Click-to-open: opens the artifact in the side overlay drawer.
  onOpenArtifact?: (artifactId: string) => void;
  // Focus-mode controls — the parent decides how to enlarge the panel.
  focused?: boolean;
  onToggleFocus?: () => void;
}

// localStorage cache for chat turns. Survives reload + focus-mode unmounts
// for 15 minutes of idle. Keyed by session_id so each session has its own
// history.
const CHAT_CACHE_KEY = (sid: string) => `compismart_chat_${sid}`;
const CHAT_CACHE_TTL_MS = 15 * 60 * 1000;

interface ChatCache {
  ts: number;
  turns: ChatTurn[];
}

function loadCachedTurns(sessionId: string): ChatTurn[] {
  if (!sessionId) return [];
  try {
    const raw = localStorage.getItem(CHAT_CACHE_KEY(sessionId));
    if (!raw) return [];
    const cache = JSON.parse(raw) as ChatCache;
    if (!cache || !cache.ts) return [];
    if (Date.now() - cache.ts > CHAT_CACHE_TTL_MS) {
      localStorage.removeItem(CHAT_CACHE_KEY(sessionId));
      return [];
    }
    // Streaming flags should be FALSE on restore — the AI/artifact wasn't
    // actually mid-stream when the page reloaded.
    return (cache.turns || []).map((t) => ({ ...t, done: true }));
  } catch {
    return [];
  }
}

function saveCachedTurns(sessionId: string, turns: ChatTurn[]) {
  if (!sessionId) return;
  try {
    const cache: ChatCache = { ts: Date.now(), turns };
    localStorage.setItem(CHAT_CACHE_KEY(sessionId), JSON.stringify(cache));
  } catch {
    // Quota / disabled — silently skip.
  }
}

export function ChatPanel({
  sessionId,
  onSourcesUpdate,
  onArtifactEvent,
  artifactsById,
  onOpenArtifact,
  focused,
  onToggleFocus,
}: ChatPanelProps) {
  const [turns, setTurns] = useState<ChatTurn[]>(() => loadCachedTurns(sessionId));
  const [draft, setDraft] = useState("");
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Persist turns to localStorage whenever they change. Only persists when
  // not actively streaming so we don't write on every token (cheap, but
  // would write 100x per turn). On stream-finish, the final state lands.
  useEffect(() => {
    if (streaming) return;
    saveCachedTurns(sessionId, turns);
  }, [turns, streaming, sessionId]);

  // Auto-scroll on new tokens.
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [turns]);

  // Cancel stream on unmount.
  useEffect(() => () => abortRef.current?.abort(), []);

  // Esc shortcut: stop active stream, else exit focus mode.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      if (streaming) {
        abortRef.current?.abort();
      } else if (focused && onToggleFocus) {
        onToggleFocus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [streaming, focused, onToggleFocus]);

  async function send(message: string) {
    if (streaming) return;
    const trimmed = message.trim();
    if (!trimmed) return;

    setDraft("");
    setStreaming(true);

    const userTurn: ChatTurn = {
      id: `u-${Date.now()}`,
      role: "user",
      text: trimmed,
      done: true,
    };
    const aiTurn: ChatTurn = {
      id: `a-${Date.now()}`,
      role: "ai",
      text: "",
      done: false,
    };
    setTurns((prev) => [...prev, userTurn, aiTurn]);

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    try {
      for await (const frame of chatStream(sessionId, trimmed, ctrl.signal)) {
        if (frame.kind === "token") {
          setTurns((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last && last.role === "ai") {
              next[next.length - 1] = { ...last, text: last.text + frame.text };
            }
            return next;
          });
        } else if (frame.kind === "sources") {
          onSourcesUpdate?.(frame.sources);
        } else if (frame.kind === "artifact_create") {
          // Drop an inline artifact card into the chat stream right after
          // the current AI turn. Parent's onArtifactEvent updates the
          // shared artifacts map; we just stamp a marker turn so the card
          // renders in the right place.
          onArtifactEvent?.(frame);
          setTurns((prev) => [
            ...prev,
            {
              id: `art-${frame.id}`,
              role: "artifact",
              text: "",
              done: false,
              artifactId: frame.id,
            },
          ]);
        } else if (
          frame.kind === "artifact_update" ||
          frame.kind === "artifact_token"
        ) {
          // Pass through to parent; the inline card reads fresh state
          // from artifactsById and re-renders.
          onArtifactEvent?.(frame);
        } else if (frame.kind === "artifact_done") {
          onArtifactEvent?.(frame);
          // Mark the inline card turn as done so the "building…" indicator clears.
          setTurns((prev) =>
            prev.map((t) =>
              t.artifactId === frame.id ? { ...t, done: true } : t,
            ),
          );
        } else if (frame.kind === "artifact_error") {
          onArtifactEvent?.(frame);
          setTurns((prev) =>
            prev.map((t) =>
              t.artifactId === frame.id ? { ...t, done: true } : t,
            ),
          );
        } else if (frame.kind === "clarification") {
          // Backend asked us a follow-up before generating the artifact.
          // Render an interactive card in the chat stream.
          setTurns((prev) => [
            ...prev,
            {
              id: `clar-${Date.now()}`,
              role: "clarification",
              text: "",
              done: false,
              clarification: {
                question: frame.question,
                kind: frame.questionKind,
                options: frame.options,
                minPicks: frame.minPicks,
                maxPicks: frame.maxPicks,
                intentHint: frame.intentHint,
                answered: false,
              },
            },
          ]);
        } else if (frame.kind === "error") {
          setTurns((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last && last.role === "ai") {
              next[next.length - 1] = {
                ...last,
                text: (last.text ? last.text + "\n\n" : "") + `Error: ${frame.message}`,
                done: true,
              };
            }
            return next;
          });
          break;
        } else if (frame.kind === "done") {
          break;
        }
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setTurns((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last && last.role === "ai") {
          next[next.length - 1] = {
            ...last,
            text: (last.text ? last.text + "\n\n" : "") + `Error: ${msg}`,
            done: true,
          };
        }
        return next;
      });
    } finally {
      // Mark ALL not-yet-done turns from this turn-pair (AI + any artifact
      // turns inserted during the stream) as done. The previous logic only
      // touched `next[last]` which was the artifact turn, leaving the AI
      // bubble blinking forever.
      setTurns((prev) =>
        prev.map((t) =>
          !t.done && (t.role === "ai" || t.role === "artifact")
            ? { ...t, done: true }
            : t,
        ),
      );
      setStreaming(false);
      abortRef.current = null;
    }
  }

  return (
    <div className="bg-white flex flex-col h-full min-h-0">
      {/* Header */}
      <div className="px-5 py-3 border-b border-slate-100 flex items-center gap-2">
        <h2 className="text-sm font-semibold text-slate-900">Chat</h2>
        {onToggleFocus && (
          <button
            type="button"
            onClick={onToggleFocus}
            className="ml-auto text-slate-400 hover:text-slate-900 transition-colors"
            title={focused ? "Exit focus mode (Esc)" : "Focus mode"}
            aria-label={focused ? "Exit focus mode" : "Enter focus mode"}
          >
            {focused ? (
              <Minimize2 className="w-4 h-4" />
            ) : (
              <Maximize2 className="w-4 h-4" />
            )}
          </button>
        )}
      </div>

      {/* Scrollable history */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
        {turns.length === 0 && (
          <div className="space-y-3 pt-4">
            <p className="text-xs text-slate-400">Try one of these</p>
            <div className="flex flex-col gap-1.5">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="text-left px-3 py-2 bg-slate-50 hover:bg-slate-100 border border-slate-100 hover:border-slate-200 rounded-xl text-sm text-slate-700 transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((t) => {
          if (t.role === "user") {
            return <UserMessage key={t.id} text={t.text} />;
          }
          if (t.role === "artifact" && t.artifactId) {
            const art = artifactsById?.get(t.artifactId);
            if (!art) return null;
            return (
              <ArtifactInlineCard
                key={t.id}
                artifact={art}
                streaming={!t.done}
                onOpen={() => onOpenArtifact?.(t.artifactId!)}
              />
            );
          }
          if (t.role === "clarification" && t.clarification) {
            return (
              <ClarificationCard
                key={t.id}
                turn={t}
                disabled={streaming}
                onAnswer={(turnId, phrase) => {
                  // Mark this clarification answered (it collapses into a pill).
                  setTurns((prev) =>
                    prev.map((x) =>
                      x.id === turnId && x.clarification
                        ? { ...x, clarification: { ...x.clarification, answered: true } }
                        : x,
                    ),
                  );
                  // Fire a fresh chat with the disambiguated phrasing. The
                  // dispatcher will now have everything it needs.
                  void send(phrase);
                }}
              />
            );
          }
          return <AIMessage key={t.id} text={t.text} streaming={!t.done} />;
        })}
      </div>

      {/* Input */}
      <form
        className="px-4 py-3 border-t border-slate-100 flex gap-2 bg-white"
        onSubmit={(e) => {
          e.preventDefault();
          if (streaming) {
            abortRef.current?.abort();
            return;
          }
          send(draft);
        }}
      >
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={streaming ? "AI is replying…" : "Ask anything, or 'compare', 'summarize', 'write a…'"}
          disabled={streaming}
          className="flex-1 px-3 py-2 bg-slate-50 border border-slate-100 rounded-lg outline-none focus:bg-white focus:border-slate-300 focus:ring-1 focus:ring-slate-300 transition-all text-sm placeholder:text-slate-400 disabled:opacity-60"
        />
        {streaming ? (
          <button
            type="button"
            onClick={() => abortRef.current?.abort()}
            className="px-3 py-2 bg-slate-900 text-white rounded-lg text-sm hover:bg-slate-700 transition-colors inline-flex items-center gap-1.5"
            title="Stop (Esc)"
            aria-label="Stop generating"
          >
            <Square className="w-3 h-3 fill-current" />
          </button>
        ) : (
          <button
            type="submit"
            disabled={!draft.trim()}
            className="px-3 py-2 bg-slate-900 text-white rounded-lg text-sm hover:bg-slate-700 transition-colors disabled:opacity-30 disabled:cursor-not-allowed inline-flex items-center gap-1.5"
            aria-label="Send"
          >
            <Send className="w-3.5 h-3.5" />
          </button>
        )}
      </form>
    </div>
  );
}
