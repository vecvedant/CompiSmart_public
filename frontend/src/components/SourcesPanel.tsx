import { useState } from "react";
import { ChevronDown, Layers, X } from "lucide-react";
import type { SourcesPayload } from "../lib/types";
import { InternalSignalList } from "./InternalSignalList";

interface SourcesPanelProps {
  data: SourcesPayload | null;
  loading?: boolean;
  // Mobile drawer state managed by parent so the topbar can toggle it.
  open?: boolean;
  onClose?: () => void;
}

interface SectionProps {
  title: React.ReactNode;
  count?: number;
  defaultOpen?: boolean;
  children: React.ReactNode;
}

function Section({ title, count, defaultOpen = true, children }: SectionProps) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-slate-200 rounded-2xl bg-white">
      <button
        type="button"
        onClick={() => setOpen((p) => !p)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-50 rounded-2xl transition-colors"
      >
        <div className="flex items-center gap-2 text-sm font-bold text-slate-900">
          {title}
          {typeof count === "number" && (
            <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
              {count}
            </span>
          )}
        </div>
        <ChevronDown
          className={`w-4 h-4 text-slate-400 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </div>
  );
}

export function SourcesPanel({
  data,
  loading = false,
  open = true,
  onClose,
}: SourcesPanelProps) {
  return (
    <aside
      className={`bg-slate-50 border-r border-slate-200 overflow-y-auto fixed lg:static inset-y-0 left-0 z-40 w-80 transform transition-transform ${
        open ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
      }`}
    >
      <div className="sticky top-0 bg-slate-50 px-5 py-4 border-b border-slate-200 flex items-center gap-2">
        <Layers className="w-4 h-4 text-orange-500" />
        <h2 className="font-bold text-slate-900 text-sm">Sources & Signals</h2>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="ml-auto lg:hidden text-slate-400 hover:text-slate-700"
            aria-label="Close sources panel"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      <div className="p-5 space-y-4">
        {loading && (
          <p className="text-xs text-slate-400 italic">Loading signals...</p>
        )}

        {data && (
          <>
            <Section title={<span>Video A</span>}>
              <InternalSignalList data={data.A} />
            </Section>

            <Section title={<span>Video B</span>}>
              <InternalSignalList data={data.B} />
            </Section>

            {/* "From the web" used to live here. It's now rendered in the
               center InsightPanel (between the cards and the chat) so the
               world-context sits next to the verdict it informs. */}
          </>
        )}
      </div>
    </aside>
  );
}
