import { useEffect, useState } from "react";
import { Check, Loader2, Circle } from "lucide-react";

// No real progress events from the backend; this is a paced animation that
// mirrors the typical ~80s ingest. Labels are deliberately non-technical --
// a creator opening this app shouldn't need to know what "embeddings" or
// "vector DB" mean.
const STEPS: { label: string; etaMs: number }[] = [
  { label: "Looking up Video A", etaMs: 6000 },
  { label: "Looking up Video B", etaMs: 12000 },
  { label: "Reading what's said in the videos", etaMs: 30000 },
  { label: "Reading the top comments", etaMs: 45000 },
  { label: "Understanding the audience reaction", etaMs: 55000 },
  { label: "Checking what's trending", etaMs: 65000 },
  { label: "Almost ready", etaMs: 80000 },
];

export function ProgressUI() {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const start = Date.now();
    const id = setInterval(() => setElapsed(Date.now() - start), 250);
    return () => clearInterval(id);
  }, []);

  // Determine the current "in-progress" step from elapsed ms.
  let currentIdx = STEPS.findIndex((s) => elapsed < s.etaMs);
  if (currentIdx === -1) currentIdx = STEPS.length - 1;

  const totalEta = STEPS[STEPS.length - 1].etaMs;
  const pct = Math.min(95, (elapsed / totalEta) * 100);

  return (
    <div className="min-h-screen flex items-center justify-center px-6 bg-hero-radial">
      <div className="w-full max-w-xl bg-white border border-slate-200 rounded-3xl p-10 shadow-sm">
        <h2 className="text-2xl font-bold tracking-tight text-slate-900 text-center">
          Crunching numbers on your videos…
        </h2>
        <p className="text-sm text-slate-500 text-center mt-1">
          This usually takes about a minute.
        </p>

        <ul className="mt-8 space-y-3">
          {STEPS.map((step, idx) => {
            const status =
              idx < currentIdx
                ? "done"
                : idx === currentIdx
                ? "active"
                : "pending";
            return (
              <li
                key={step.label}
                className="flex items-center gap-3 text-sm font-medium"
              >
                {status === "done" && (
                  <Check className="w-5 h-5 text-emerald-500 shrink-0" />
                )}
                {status === "active" && (
                  <Loader2 className="w-5 h-5 text-orange-500 animate-spin shrink-0" />
                )}
                {status === "pending" && (
                  <Circle className="w-5 h-5 text-slate-300 shrink-0" />
                )}
                <span
                  className={
                    status === "done"
                      ? "text-slate-500"
                      : status === "active"
                      ? "text-slate-900"
                      : "text-slate-400"
                  }
                >
                  {step.label}
                </span>
              </li>
            );
          })}
        </ul>

        <div className="mt-8 h-3 w-full bg-slate-100 rounded-full overflow-hidden p-0.5 border border-slate-200/60">
          <div
            className="h-full rounded-full progress-bar-glow shadow-sm transition-all duration-500 ease-out"
            style={{ width: `${pct}%` }}
          />
        </div>
        <p className="mt-3 text-xs font-bold uppercase tracking-widest text-slate-400 text-center">
          {Math.round(pct)}%
        </p>
      </div>
    </div>
  );
}
