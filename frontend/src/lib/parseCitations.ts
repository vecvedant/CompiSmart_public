import type { CitationRef } from "./types";

// Citation tag formats we emit:
//   [A:3]                       — transcript chunk, video slot A (legacy compare mode)
//   [B-comment:5]               — comment 5 on slot B            (legacy compare mode)
//   [web:2]                     — web source #2 (Gemini grounding)
//   [asset:1]                   — body/transcript chunk from asset 1 (v2 asset mode)
//   [asset:1-comment:3]         — comment 3 on video asset 1     (v2 asset mode)
//
// The trailing `| 0:00-0:05` or `| article §3` parts inside the brackets are
// metadata Gemini sometimes echoes from the chunks block; we strip them.

const LEGACY_RE = /\[([AB])(?:-(comment))?:(\d+)(?:\s*\|[^\]]*)?\]/g;
const WEB_RE = /\[web:(\d+)(?:\s*\|[^\]]*)?\]/g;
const ASSET_RE = /\[asset:(\d+)(?:-comment:(\d+))?(?:\s*\|[^\]]*)?\]/g;
const BOLD_RE = /\*\*([^*\n]+?)\*\*/g;

export interface TextSegment {
  kind: "text";
  text: string;
}
export interface BoldSegment {
  kind: "bold";
  text: string;
}
export interface CitationSegment {
  kind: "citation";
  citation: CitationRef;
  raw: string;
}
export type Segment = TextSegment | BoldSegment | CitationSegment;

interface Hit {
  start: number;
  end: number;
  segment: Segment;
}

export function splitCitations(text: string): Segment[] {
  const hits: Hit[] = [];

  for (const m of text.matchAll(LEGACY_RE)) {
    const [raw, slot, kindMaybe, idxStr] = m;
    const start = m.index ?? 0;
    hits.push({
      start,
      end: start + raw.length,
      segment: {
        kind: "citation",
        raw,
        citation: {
          slot: slot as "A" | "B",
          kind: kindMaybe === "comment" ? "comment" : "transcript",
          idx: parseInt(idxStr, 10),
        },
      },
    });
  }

  for (const m of text.matchAll(WEB_RE)) {
    const [raw, idxStr] = m;
    const start = m.index ?? 0;
    hits.push({
      start,
      end: start + raw.length,
      segment: {
        kind: "citation",
        raw,
        citation: {
          slot: "web",
          kind: "web",
          idx: parseInt(idxStr, 10),
        },
      },
    });
  }

  for (const m of text.matchAll(ASSET_RE)) {
    const [raw, assetIdxStr, commentIdxStr] = m;
    const start = m.index ?? 0;
    const idx = parseInt(assetIdxStr, 10);
    const commentIdx = commentIdxStr !== undefined ? parseInt(commentIdxStr, 10) : undefined;
    hits.push({
      start,
      end: start + raw.length,
      segment: {
        kind: "citation",
        raw,
        citation: {
          slot: "asset",
          kind: commentIdx !== undefined ? "comment" : "article",
          idx,
          commentIdx,
        },
      },
    });
  }

  for (const m of text.matchAll(BOLD_RE)) {
    const start = m.index ?? 0;
    hits.push({
      start,
      end: start + m[0].length,
      segment: { kind: "bold", text: m[1] },
    });
  }

  hits.sort((a, b) => a.start - b.start);

  // Drop hits that overlap an earlier one.
  const filtered: Hit[] = [];
  let cursor = 0;
  for (const h of hits) {
    if (h.start < cursor) continue;
    filtered.push(h);
    cursor = h.end;
  }

  const out: Segment[] = [];
  let lastIdx = 0;
  for (const h of filtered) {
    if (h.start > lastIdx) {
      out.push({ kind: "text", text: text.slice(lastIdx, h.start) });
    }
    out.push(h.segment);
    lastIdx = h.end;
  }
  if (lastIdx < text.length) {
    out.push({ kind: "text", text: text.slice(lastIdx) });
  }
  return collapseDuplicateCitations(out);
}

function citationKey(c: CitationRef): string {
  return `${c.slot}|${c.kind}|${c.idx}|${c.commentIdx ?? ""}`;
}

function collapseDuplicateCitations(segs: Segment[]): Segment[] {
  const out: Segment[] = [];
  for (const s of segs) {
    const prev = out[out.length - 1];
    if (s.kind === "citation" && prev && prev.kind === "citation") {
      if (citationKey(prev.citation) === citationKey(s.citation)) continue;
    }
    if (s.kind === "citation" && prev && prev.kind === "text") {
      const prevPrev = out[out.length - 2];
      if (
        prevPrev &&
        prevPrev.kind === "citation" &&
        /^\s*$/.test(prev.text) &&
        citationKey(prevPrev.citation) === citationKey(s.citation)
      ) {
        out.pop();
        continue;
      }
    }
    out.push(s);
  }
  return out;
}
