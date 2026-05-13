// Mirrors backend/app/models.py Pydantic shapes for the fields the UI uses.

export type Platform = "youtube" | "instagram";
export type VideoSlot = "A" | "B";
export type LifeStage = "fresh" | "early" | "mature" | "saturated";
export type TrendStatus =
  | "rising"
  | "steady"
  | "declining"
  | "niche"
  | "unavailable";

export interface CommentSentimentMix {
  positive: number;
  negative: number;
  curious: number;
  confused: number;
  other: number;
}

export interface Comment {
  text: string;
  likes: number;
  replies: number;
  author?: string | null;
}

export interface VideoMeta {
  slot: VideoSlot;
  platform: Platform;
  url: string;
  video_id: string;

  title?: string | null;
  creator: string;
  follower_count?: number | null;

  views: number;
  likes: number;
  comments: number;

  hashtags: string[];
  upload_date?: string | null;
  duration_sec?: number | null;
  thumbnail_url?: string | null;

  engagement_rate: number;
  age_days?: number | null;
  view_velocity?: number | null;
  life_stage?: LifeStage | null;

  topic_keywords: string[];
  topic_trend_status: TrendStatus;
  discussion_depth?: number | null;
  comment_sentiment_mix?: CommentSentimentMix | null;
  top_comments: Comment[];
}

export interface IngestResponse {
  session_id: string;
  video_a: VideoMeta;
  video_b: VideoMeta;
}

// Citation reference, parsed out of streamed AI tokens.
// transcript/comment chips link to a video chunk; web chips link to a Gemini-
// grounded web source. Web chips carry a 1-indexed `idx` matching the
// position of that source in the answer's grounding-metadata list.
// asset chips link to an asset position in the session's sidebar list.
export interface CitationRef {
  slot: VideoSlot | "web" | "asset";
  kind: "transcript" | "comment" | "web" | "article";
  idx: number;
  commentIdx?: number; // for [asset:N-comment:M]
}

// One web page Gemini cited via Google Search grounding.
export interface WebSource {
  url: string;
  title: string;
  snippet: string;
}

// One-shot session verdict: rendered between the video cards and the chat.
// `winning_video` is null when the model called the result a tie. The
// `web_sources` list is whatever Gemini grounded against during the call,
// so the same panel can render the "From the web" section.
export interface Verdict {
  topic_a: string;       // Video A's topic in 2-5 words
  topic_b: string;       // Video B's topic in 2-5 words
  domain: string;        // legacy/overall context; usually empty now
  winning_video: VideoSlot | null;
  opinion: string;
  reasons: string[];
  web_sources: WebSource[];
  used_search: boolean;
}

// Internal signals per video for the Sources & Signals panel.
export interface SourcesInternal {
  hook: {
    text: string;
    start_sec?: number | null;
    end_sec?: number | null;
    chunk_idx: number;
  } | null;
  top_transcript: {
    text: string;
    start_sec?: number | null;
    end_sec?: number | null;
    chunk_idx?: number | null;
  }[];
  top_comments: Comment[];
  metrics: {
    views: number;
    likes: number;
    comments: number;
    engagement_rate: number;
    follower_count?: number | null;
    view_velocity?: number | null;
    life_stage?: LifeStage | null;
  };
}

// Full Sources & Signals panel payload.
export interface SourcesPayload {
  A: SourcesInternal;
  B: SourcesInternal;
  external: WebSource[];
}

// One UI bubble in the chat panel.
export type ChatRole = "user" | "ai" | "artifact" | "clarification";
export interface ChatTurn {
  id: string;
  role: ChatRole;
  text: string;
  done: boolean; // false while AI is still streaming

  // Artifact turn — chat-stream inline card. References an Artifact by id.
  artifactId?: string;

  // Clarification turn — backend asked the user to pick before generating.
  clarification?: {
    question: string;
    kind: "mcq_single" | "mcq_multi" | "text";
    options?: { id: string; label: string; description?: string }[];
    minPicks?: number;
    maxPicks?: number;
    intentHint?: string;       // what intent will be triggered after answer
    answered?: boolean;
  };
}

// ===========================================================================
// v2 — niche-driven content studio
// ===========================================================================

export interface Niche {
  slug: string;
  label: string;
  description: string;
  icon: string;
}

export type FeedItemType = "news" | "video";

export interface FeedItem {
  type: FeedItemType;
  title: string;
  url: string;
  source: string;
  published_at?: string | null;
  summary: string;
  thumbnail?: string | null;
  video_id?: string | null;
  channel?: string | null;
  view_count?: number | null;
  duration_sec?: number | null;
  score: number;
}

export interface FeedResponse {
  niche: string;
  cached: boolean;
  count: number;
  items: FeedItem[];
}

export type AssetType = "article" | "video" | "note" | "compare";
export type IngestStatus = "pending" | "ready" | "failed";

export interface Asset {
  id: string;
  session_id: string;
  type: AssetType;
  source_url?: string | null;
  title: string;
  summary: string;
  body_text?: string | null;
  metadata_json: Record<string, unknown>;
  niche_slug?: string | null;
  added_at?: string | null;
  ingest_status: IngestStatus;
}

export type OutputType =
  | "blog_post"
  | "video_script"
  | "x_thread"
  | "linkedin_post"
  | "newsletter";

export type DraftTone = "confident" | "analytical" | "casual" | "irreverent";
export type DraftLength = "short" | "medium" | "long";

export interface Draft {
  id: string;
  session_id: string;
  asset_ids: string[];
  output_type: OutputType;
  tone: DraftTone;
  length: DraftLength;
  title: string;
  content_md: string;
  created_at?: string | null;
  updated_at?: string | null;
}

// Build stream events.
export type BuildEvent =
  | { kind: "outline"; bullets: string[] }
  | { kind: "expand"; section_count: number }
  | { kind: "token"; text: string }
  | { kind: "done"; draft_id: string }
  | { kind: "error"; message: string };

// ===========================================================================
// Artifacts — Claude-Code-style typed side panels spawned by chat intent.
// ===========================================================================

export type ArtifactKind = "compare" | "draft" | "summary" | "metrics" | "quotes";
export type ArtifactStatus = "pending" | "ready" | "failed";

export interface Artifact {
  id: string;
  session_id: string;
  kind: ArtifactKind;
  title: string;
  status: ArtifactStatus;
  asset_ids: string[];
  prompt: string;
  payload_json: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

// SSE events the chat stream emits for artifact lifecycle.
export type ArtifactStreamEvent =
  | { kind: "artifact_create"; id: string; artifactKind: ArtifactKind; title: string; status: ArtifactStatus; payload?: Record<string, unknown> }
  | { kind: "artifact_update"; id: string; patch: Record<string, unknown> }
  | { kind: "artifact_token"; id: string; field: string; text: string }
  | { kind: "artifact_done"; id: string; title: string; payload: Record<string, unknown> }
  | { kind: "artifact_error"; id: string; message: string };
