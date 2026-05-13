import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchNiches } from "../lib/api";
import type { Niche } from "../lib/types";

export default function NicheSelector() {
  const navigate = useNavigate();
  const [niches, setNiches] = useState<Niche[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchNiches()
      .then((n) => {
        if (!cancelled) setNiches(n);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="min-h-screen bg-white">
      <header className="border-b border-slate-100">
        <div className="max-w-5xl mx-auto px-6 py-4">
          <span className="text-sm font-semibold tracking-tight text-slate-900">
            CompiSMART
          </span>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-16 md:py-24">
        <h1 className="text-3xl md:text-4xl font-semibold tracking-tight text-slate-900 mb-3">
          What are you writing about?
        </h1>
        <p className="text-slate-500 mb-12 max-w-xl leading-relaxed">
          Pick a niche. We pull current news and trending videos, you save the
          ones worth keeping, and the chat turns them into blog posts, scripts,
          or threads.
        </p>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 text-red-700 px-4 py-3 mb-6 text-sm">
            {error}
          </div>
        )}

        {!niches && !error && (
          <div className="text-slate-400 text-sm">Loading niches…</div>
        )}

        {niches && (
          <div className="grid sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {niches.map((n) => (
              <button
                key={n.slug}
                type="button"
                onClick={() => navigate(`/feed/${n.slug}`)}
                className="text-left bg-white border border-slate-200 hover:border-slate-900 hover:bg-slate-50 rounded-xl p-4 transition-all group"
              >
                <div className="text-2xl mb-3">{n.icon || "•"}</div>
                <div className="text-sm font-semibold text-slate-900 mb-1">{n.label}</div>
                <div className="text-xs text-slate-500 leading-relaxed line-clamp-2">
                  {n.description}
                </div>
              </button>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
