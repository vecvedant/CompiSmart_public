from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


Platform = Literal["youtube", "instagram"]
VideoSlot = Literal["A", "B"]
LifeStage = Literal["fresh", "early", "mature", "saturated"]
TrendStatus = Literal["rising", "steady", "declining", "niche", "unavailable"]
ChunkKind = Literal["transcript", "comment"]


class TranscriptSegment(BaseModel):
    """One timestamped piece of a transcript before chunking."""

    text: str
    start_sec: float
    end_sec: float


class Comment(BaseModel):
    """Top-of-thread comment on a video. Platform-agnostic."""

    text: str
    likes: int = 0
    replies: int = 0
    author: Optional[str] = None


class CommentSentimentMix(BaseModel):
    """Counts of top comments by sentiment bucket. Sum may differ from total
    if Gemini couldn't classify some."""

    positive: int = 0
    negative: int = 0
    curious: int = 0
    confused: int = 0
    other: int = 0


class VideoMeta(BaseModel):
    """Normalized metadata for a single video, platform-agnostic."""

    slot: VideoSlot
    platform: Platform
    url: str
    video_id: str

    title: Optional[str] = None
    creator: str
    follower_count: Optional[int] = None

    views: int = 0
    likes: int = 0
    comments: int = 0

    hashtags: list[str] = Field(default_factory=list)
    upload_date: Optional[datetime] = None
    duration_sec: Optional[float] = None
    thumbnail_url: Optional[str] = None

    # computed
    engagement_rate: float = 0.0
    age_days: Optional[int] = None
    view_velocity: Optional[float] = None
    life_stage: Optional[LifeStage] = None

    # add-ons (filled later)
    topic_keywords: list[str] = Field(default_factory=list)
    topic_trend_status: TrendStatus = "unavailable"
    discussion_depth: Optional[float] = None
    comment_sentiment_mix: Optional[CommentSentimentMix] = None
    top_comments: list[Comment] = Field(default_factory=list)


class Chunk(BaseModel):
    """A unit ready to be embedded and stored in Qdrant."""

    video_slot: VideoSlot
    chunk_idx: int
    kind: ChunkKind = "transcript"
    text: str
    start_sec: Optional[float] = None
    end_sec: Optional[float] = None
    # comment-specific
    comment_likes: Optional[int] = None
    comment_replies: Optional[int] = None


class IngestRequest(BaseModel):
    url_a: str
    url_b: str


class IngestResponse(BaseModel):
    session_id: str
    video_a: VideoMeta
    video_b: VideoMeta


class ChatRequest(BaseModel):
    session_id: str
    message: str


class WebSource(BaseModel):
    """One web page Gemini cited via Google Search grounding.

    Title and snippet are best-effort -- Gemini sometimes returns only the
    URL. Frontend falls back to domain name when title is missing.
    """

    url: str
    title: str = ""
    snippet: str = ""


class Verdict(BaseModel):
    """One-shot at-a-glance summary rendered between the video cards and
    the chat panel. Generated once per session by a grounded Gemini call.

    Fields are short, ESL-friendly, and meant to be skim-readable on the
    landing view. The chat panel is for deeper questions; this is the
    "what's the headline?" line.

    `topic_a` / `topic_b` are PER-VIDEO domain labels (each video gets
    its own one-line topic). Two videos in a session can be on completely
    different topics -- showing them side by side makes the comparison
    intelligible. `domain` is kept for backwards compat and can hold the
    overall comparison context when the two are on the same topic.
    """

    topic_a: str = ""       # e.g. "Engineering & entrepreneurship"
    topic_b: str = ""       # e.g. "B-school internships"
    domain: str = ""        # legacy/overall context; may be empty
    winning_video: VideoSlot | None = None  # "A" or "B"; None if too close
    opinion: str = ""       # 1-2 plain sentences
    reasons: list[str] = Field(default_factory=list)  # 2-3 short bullets
    web_sources: list[WebSource] = Field(default_factory=list)
    used_search: bool = False  # was Google Search grounding actually used?


# ===========================================================================
# v2 models — niche workflow, feed, generalized assets, drafts.
# v1 models above (VideoMeta, Chunk, IngestRequest/Response, Verdict) stay
# put because the two-video compare flow keeps using them under the hood.
# ===========================================================================

AssetType = Literal["article", "video", "note", "compare"]
IngestStatus = Literal["pending", "ready", "failed"]
FeedItemType = Literal["news", "video"]
OutputType = Literal["blog_post", "video_script", "x_thread", "linkedin_post", "newsletter"]
DraftTone = Literal["confident", "analytical", "casual", "irreverent"]
DraftLength = Literal["short", "medium", "long"]


class Niche(BaseModel):
    slug: str
    label: str
    description: str = ""
    icon: str = ""
    search_keywords: list[str] = Field(default_factory=list)


class FeedItem(BaseModel):
    """One item in a niche's feed — either a news article or a YT video.
    Lightweight: no full body / no embeddings until promoted to an asset.
    """
    type: FeedItemType
    title: str
    url: str
    source: str = ""                              # publisher domain or YT channel
    published_at: Optional[datetime] = None
    summary: str = ""
    thumbnail: Optional[str] = None
    # YT-only
    video_id: Optional[str] = None
    channel: Optional[str] = None
    view_count: Optional[int] = None
    duration_sec: Optional[float] = None
    # ranking score (recency × popularity) — computed by aggregator
    score: float = 0.0


class Asset(BaseModel):
    """Persistent saved item in a session. Mirrors Supabase `assets` row."""
    id: str
    session_id: str
    type: AssetType
    source_url: Optional[str] = None
    title: str
    summary: str = ""
    body_text: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
    niche_slug: Optional[str] = None
    added_at: Optional[datetime] = None
    ingest_status: IngestStatus = "pending"


class AddAssetRequest(BaseModel):
    session_id: str
    type: AssetType
    source_url: Optional[str] = None
    title: Optional[str] = None         # frontend can pass title from FeedItem
    summary: Optional[str] = None
    niche_slug: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class ChatV2Request(BaseModel):
    """Chat against a session's saved assets (replaces ChatRequest in v2 flow)."""
    session_id: str
    message: str


class BuildRequest(BaseModel):
    session_id: str
    asset_ids: list[str]                # subset of session's assets to use
    output_type: OutputType
    tone: DraftTone = "confident"
    length: DraftLength = "medium"
    instruction: str = ""               # optional extra steering ("focus on X")
    chat_context_turns: int = 6         # how many recent chat turns to inject


class Draft(BaseModel):
    id: str
    session_id: str
    asset_ids: list[str] = Field(default_factory=list)
    output_type: OutputType
    tone: DraftTone = "confident"
    length: DraftLength = "medium"
    title: str = ""
    content_md: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UpdateDraftRequest(BaseModel):
    session_id: str
    title: Optional[str] = None
    content_md: Optional[str] = None


class CompareRequest(BaseModel):
    session_id: str
    asset_a_id: str
    asset_b_id: str
