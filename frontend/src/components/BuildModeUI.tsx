import { useRef, useState } from "react";
import { Loader2, Wand2, Copy, CheckCheck, Eye, Code2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { buildStream } from "../lib/api";
import type { Asset, DraftLength, DraftTone, OutputType } from "../lib/types";

const OUTPUT_TYPES: { value: OutputType; label: string }[] = [
  { value: "blog_post",     label: "Blog post" },
  { value: "video_script",  label: "Video script" },
  { value: "x_thread",      label: "X / Twitter thread" },
  { value: "linkedin_post", label: "LinkedIn post" },
  { value: "newsletter",    label: "Newsletter" },
];

const TONES: { value: DraftTone; label: string }[] = [
  { value: "confident",  label: "Confident" },
  { value: "analytical", label: "Analytical" },
  { value: "casual",     label: "Casual" },
  { value: "irreverent", label: "Irreverent" },
];

const LENGTHS: { value: DraftLength; label: string }[] = [
  { value: "short",  label: "Short" },
  { value: "medium", label: "Medium" },
  { value: "long",   label: "Long" },
];

interface Props {
  sessionId: string;
  assets: Asset[];
  selectedIds: Set<string>;
}

export function BuildModeUI({ sessionId, assets, selectedIds }: Props) {
  const [outputType, setOutputType] = useState<OutputType>("blog_post");
  const [tone, setTone] = useState<DraftTone>("confident");
  const [length, setLength] = useState<DraftLength>("medium");
  const [instruction, setInstruction] = useState("");
  const [bullets, setBullets] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [stage, setStage] = useState<"idle" | "outline" | "expand" | "polish" | "done" | "error">("idle");
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [viewMode, setViewMode] = useState<"preview" | "raw">("preview");
  const abortRef = useRef<AbortController | null>(null);

  const readyAssets = assets.filter((a) => a.ingest_status === "ready");
  const selectedAssets = readyAssets.filter((a) => selectedIds.has(a.id));

  async function generate() {
    if (selectedAssets.length === 0) {
      setError("Pick at least one ready asset to build from.");
      return;
    }
    setError(null);
    setBullets([]);
    setDraft("");
    setStage("outline");
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      for await (const ev of buildStream(
        {
          session_id: sessionId,
          asset_ids: selectedAssets.map((a) => a.id),
          output_type: outputType,
          tone,
          length,
          instruction: instruction.trim() || undefined,
        },
        ctrl.signal,
      )) {
        if (ev.kind === "outline") {
          setBullets(ev.bullets);
        } else if (ev.kind === "expand") {
          setStage("polish");
        } else if (ev.kind === "token") {
          setDraft((prev) => prev + ev.text);
        } else if (ev.kind === "done") {
          setStage("done");
        } else if (ev.kind === "error") {
          setError(ev.message);
          setStage("error");
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStage("error");
    }
  }

  function copy() {
    navigator.clipboard.writeText(draft).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      },
      () => {},
    );
  }

  return (
    <div className="flex-1 min-w-0 flex flex-col bg-slate-50">
      <div className="p-4 bg-white border-b border-slate-200">
        <div className="grid md:grid-cols-3 gap-3 mb-3">
          <Field label="Output">
            <select
              value={outputType}
              onChange={(e) => setOutputType(e.target.value as OutputType)}
              className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:border-orange-400 outline-none"
            >
              {OUTPUT_TYPES.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </Field>
          <Field label="Tone">
            <select
              value={tone}
              onChange={(e) => setTone(e.target.value as DraftTone)}
              className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:border-orange-400 outline-none"
            >
              {TONES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </Field>
          <Field label="Length">
            <select
              value={length}
              onChange={(e) => setLength(e.target.value as DraftLength)}
              className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:border-orange-400 outline-none"
            >
              {LENGTHS.map((l) => (
                <option key={l.value} value={l.value}>{l.label}</option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Steering (optional)">
          <input
            type="text"
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            placeholder="e.g. focus on the policy angle, target devs, end with a sharp opinion…"
            className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm focus:border-orange-400 outline-none"
          />
        </Field>
        <div className="flex items-center justify-between mt-3">
          <div className="text-xs text-slate-500">
            Using <b>{selectedAssets.length}</b> asset{selectedAssets.length === 1 ? "" : "s"}
            {selectedAssets.length === 0 && (
              <span className="text-amber-600 ml-2">— tick assets on the right.</span>
            )}
          </div>
          <button
            type="button"
            onClick={generate}
            disabled={stage === "outline" || stage === "polish" || selectedAssets.length === 0}
            className="bg-slate-900 text-white text-sm font-medium rounded-lg px-4 py-2 hover:bg-slate-700 disabled:opacity-50 inline-flex items-center gap-2"
          >
            {stage === "outline" || stage === "polish" ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                {stage === "outline" ? "Outlining…" : "Writing…"}
              </>
            ) : (
              <>
                <Wand2 className="w-4 h-4" />
                Generate
              </>
            )}
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 text-red-700 px-4 py-3 mb-4">
            {error}
          </div>
        )}
        {bullets.length > 0 && (
          <div className="mb-6 bg-amber-50 border border-amber-200 rounded-xl p-4">
            <div className="text-xs font-bold text-amber-800 uppercase tracking-wide mb-2">
              Outline
            </div>
            <ul className="text-sm text-amber-900 space-y-1 list-disc list-inside">
              {bullets.map((b, i) => (
                <li key={i}>{b}</li>
              ))}
            </ul>
          </div>
        )}
        {draft && (
          <div className="bg-white border border-slate-200 rounded-2xl shadow-sm">
            <div className="flex items-center justify-between px-4 py-2 border-b border-slate-100">
              <div className="text-xs uppercase tracking-wide text-slate-500">
                Draft {stage === "done" && <span className="text-emerald-600 ml-1">· saved</span>}
              </div>
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1 bg-slate-100 rounded-md p-0.5">
                  <button
                    type="button"
                    onClick={() => setViewMode("preview")}
                    className={`text-xs px-2 py-1 rounded flex items-center gap-1 transition-colors ${
                      viewMode === "preview"
                        ? "bg-white text-slate-900 shadow-sm"
                        : "text-slate-500 hover:text-slate-900"
                    }`}
                  >
                    <Eye className="w-3 h-3" /> Preview
                  </button>
                  <button
                    type="button"
                    onClick={() => setViewMode("raw")}
                    className={`text-xs px-2 py-1 rounded flex items-center gap-1 transition-colors ${
                      viewMode === "raw"
                        ? "bg-white text-slate-900 shadow-sm"
                        : "text-slate-500 hover:text-slate-900"
                    }`}
                  >
                    <Code2 className="w-3 h-3" /> Markdown
                  </button>
                </div>
                <button
                  type="button"
                  onClick={copy}
                  className="text-xs text-slate-500 hover:text-slate-900 flex items-center gap-1"
                >
                  {copied ? (
                    <>
                      <CheckCheck className="w-3.5 h-3.5 text-emerald-500" /> Copied
                    </>
                  ) : (
                    <>
                      <Copy className="w-3.5 h-3.5" /> Copy
                    </>
                  )}
                </button>
              </div>
            </div>
            {viewMode === "preview" ? (
              <article className="prose prose-slate max-w-none p-6 min-h-[60vh] prose-headings:font-bold prose-headings:tracking-tight prose-h1:text-2xl prose-h2:text-lg prose-p:text-sm prose-p:leading-relaxed prose-li:text-sm">
                <ReactMarkdown>{draft}</ReactMarkdown>
                {(stage === "outline" || stage === "polish") && (
                  <div className="text-xs text-slate-400 mt-4 flex items-center gap-2">
                    <Loader2 className="w-3 h-3 animate-spin" /> still writing…
                  </div>
                )}
              </article>
            ) : (
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                spellCheck={false}
                className="w-full min-h-[60vh] p-4 text-sm font-mono leading-relaxed text-slate-800 focus:outline-none resize-none whitespace-pre-wrap"
              />
            )}
          </div>
        )}
        {!draft && !error && stage === "idle" && (
          <div className="text-center text-sm text-slate-400 py-16">
            Pick an output type, tick assets on the right, hit <b>Generate</b>.
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[10px] uppercase tracking-wide text-slate-400 font-bold">
        {label}
      </span>
      <div className="mt-1">{children}</div>
    </label>
  );
}
