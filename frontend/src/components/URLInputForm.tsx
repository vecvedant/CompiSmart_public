import { useState } from "react";
import { ArrowRight, Layers } from "lucide-react";

interface URLInputFormProps {
  onSubmit: (urlA: string, urlB: string) => void;
  disabled?: boolean;
  errorMessage?: string | null;
}

export function URLInputForm({ onSubmit, disabled, errorMessage }: URLInputFormProps) {
  const [urlA, setUrlA] = useState("");
  const [urlB, setUrlB] = useState("");

  const canSubmit = !disabled && urlA.trim().length > 8 && urlB.trim().length > 8;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (canSubmit) onSubmit(urlA.trim(), urlB.trim());
  }

  return (
    <div className="min-h-screen flex flex-col bg-hero-radial">
      {/* Bare logo header. No marketing nav -- this is a tool, not a SaaS site. */}
      <header className="px-8 py-6 max-w-7xl mx-auto w-full flex items-center gap-3">
        <div className="w-10 h-10 bg-orange-500 rounded-xl flex items-center justify-center text-white shadow-sm shadow-orange-500/20">
          <Layers className="w-5 h-5" />
        </div>
        <span className="text-2xl font-bold tracking-tight text-slate-900">
          Compi<span className="text-orange-500">SMART</span>
        </span>
      </header>

      <main className="flex-1 flex items-center justify-center px-6 pb-16">
        <div className="w-full max-w-2xl">
          <h1 className="text-4xl md:text-5xl font-extrabold tracking-tight text-slate-900 text-center">
            Compare two short videos with AI
          </h1>
          <p className="mt-4 text-lg text-slate-500 text-center">
            Paste two YouTube or Instagram links. Find out why one performed better.
          </p>

          <form onSubmit={handleSubmit} className="mt-12 space-y-6">
            <UrlField
              label="Video A"
              placeholder="https://youtube.com/shorts/..."
              value={urlA}
              onChange={setUrlA}
              disabled={disabled}
            />
            <UrlField
              label="Video B"
              placeholder="https://www.instagram.com/reel/..."
              value={urlB}
              onChange={setUrlB}
              disabled={disabled}
            />

            <div className="flex flex-col items-center gap-4 pt-2">
              <button
                type="submit"
                disabled={!canSubmit}
                className="group inline-flex items-center gap-3 bg-orange-500 text-white px-10 py-5 rounded-2xl text-lg font-bold shadow-lg shadow-orange-500/25 transition-all hover:bg-orange-600 hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100"
              >
                Compare videos
                <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
              </button>
              {errorMessage && (
                <p className="text-sm text-red-600 max-w-md text-center">
                  {errorMessage}
                </p>
              )}
              <p className="text-xs text-slate-400 max-w-md text-center">
                Takes about a minute. Then you can ask anything.
              </p>
            </div>
          </form>
        </div>
      </main>
    </div>
  );
}

function UrlField({
  label,
  placeholder,
  value,
  onChange,
  disabled,
}: {
  label: string;
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
}) {
  return (
    <div>
      <label className="block text-xs font-bold uppercase tracking-widest text-slate-500 mb-2">
        {label}
      </label>
      <input
        type="text"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="w-full px-5 py-4 bg-white border border-slate-200 rounded-2xl outline-none focus:ring-4 focus:ring-orange-500/10 focus:border-orange-500 transition-all text-slate-700 placeholder:text-slate-400 disabled:bg-slate-50 disabled:opacity-60"
      />
    </div>
  );
}
