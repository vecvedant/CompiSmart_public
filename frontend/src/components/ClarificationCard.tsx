import { useState } from "react";
import { Check, HelpCircle, Send } from "lucide-react";
import type { ChatTurn } from "../lib/types";

interface Props {
  turn: ChatTurn;
  disabled?: boolean;
  onAnswer: (turnId: string, answer: string) => void;
}

/** Claude.ai-style interactive follow-up card.
 *
 * Renders MCQ buttons or a text input depending on the question kind.
 * Once answered, the card collapses to a compact "answer: X" pill and the
 * parent fires onAnswer with a phrasing the chat backend can re-dispatch.
 */
export function ClarificationCard({ turn, disabled, onAnswer }: Props) {
  const c = turn.clarification;
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [textValue, setTextValue] = useState("");

  if (!c) return null;

  const isMulti = c.kind === "mcq_multi";
  const isSingle = c.kind === "mcq_single";
  const isText = c.kind === "text";

  function togglePick(id: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        if (isSingle) next.clear();
        next.add(id);
      }
      return next;
    });
  }

  function canSubmit(): boolean {
    if (disabled || c?.answered) return false;
    if (isText) return textValue.trim().length > 0;
    if (!c) return false;
    const n = picked.size;
    return n >= (c.minPicks ?? 1) && n <= (c.maxPicks ?? n);
  }

  function submit() {
    if (!c || !canSubmit()) return;
    let phrase: string;
    if (isText) {
      phrase = textValue.trim();
    } else {
      const labels = (c.options || [])
        .filter((o) => picked.has(o.id))
        .map((o) => o.label);
      // Compose a natural-language follow-up that re-fires the dispatcher
      // confidently. For compare, name the videos. For draft, name the type.
      if (c.intentHint === "compare") {
        phrase = `compare "${labels[0] ?? ""}" and "${labels[1] ?? ""}"`;
      } else if (c.intentHint === "draft") {
        phrase = `write a ${labels[0]}`;
      } else {
        phrase = labels.join(", ");
      }
    }
    onAnswer(turn.id, phrase);
  }

  // Compact rendering when already answered — just show the picked label.
  if (c.answered) {
    return (
      <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-3 py-2 flex items-center gap-2 text-sm text-emerald-800">
        <Check className="w-3.5 h-3.5" />
        <span className="font-medium">{c.question}</span>
        <span className="text-emerald-600">— answered</span>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-amber-200 bg-gradient-to-br from-amber-50 to-white p-4 space-y-3">
      <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-amber-700 font-bold">
        <HelpCircle className="w-3.5 h-3.5" />
        Quick clarification
      </div>
      <div className="text-sm font-semibold text-slate-900 leading-snug">
        {c.question}
      </div>

      {(isSingle || isMulti) && (
        <div className="space-y-1.5">
          {(c.options || []).map((o) => {
            const isPicked = picked.has(o.id);
            return (
              <button
                key={o.id}
                type="button"
                disabled={disabled || c.answered}
                onClick={() => togglePick(o.id)}
                className={`w-full text-left rounded-xl border px-3 py-2 transition-all flex items-start gap-2 ${
                  isPicked
                    ? "border-amber-400 bg-amber-100"
                    : "border-slate-200 bg-white hover:border-amber-300"
                } ${disabled || c.answered ? "opacity-60 cursor-not-allowed" : ""}`}
              >
                <div
                  className={`mt-0.5 w-4 h-4 shrink-0 rounded ${isMulti ? "rounded-md" : "rounded-full"} border-2 flex items-center justify-center transition-all ${
                    isPicked
                      ? "border-amber-500 bg-amber-500 text-white"
                      : "border-slate-300 bg-white"
                  }`}
                >
                  {isPicked && <Check className="w-2.5 h-2.5" />}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-slate-900 line-clamp-1">
                    {o.label}
                  </div>
                  {o.description && (
                    <div className="text-[11px] text-slate-500 line-clamp-1 mt-0.5">
                      {o.description}
                    </div>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      )}

      {isText && (
        <textarea
          rows={3}
          value={textValue}
          disabled={disabled || c.answered}
          onChange={(e) => setTextValue(e.target.value)}
          placeholder="Type your answer…"
          className="w-full px-3 py-2 rounded-xl border border-slate-200 focus:border-amber-400 focus:ring-2 focus:ring-amber-200 outline-none text-sm resize-none"
        />
      )}

      <div className="flex items-center justify-between gap-2 pt-1">
        {(isSingle || isMulti) && (
          <div className="text-[11px] text-slate-500">
            {isMulti
              ? `Pick ${c.minPicks === c.maxPicks ? c.minPicks : `${c.minPicks}-${c.maxPicks}`}`
              : "Pick one"}{" "}
            · {picked.size} selected
          </div>
        )}
        {isText && <div />}
        <button
          type="button"
          onClick={submit}
          disabled={!canSubmit()}
          className="bg-slate-900 text-white rounded-lg px-3 py-1.5 text-xs font-bold inline-flex items-center gap-1.5 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Send className="w-3 h-3" /> Continue
        </button>
      </div>
    </div>
  );
}
