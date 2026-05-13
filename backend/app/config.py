from pathlib import Path
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    apify_token: str = ""
    deepgram_api_key: str = ""
    # Accept either name. The library is `google.generativeai` but most folks
    # in the wild call the key GEMINI_API_KEY because the model is Gemini.
    google_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    )
    qdrant_url: str = ""
    qdrant_api_key: str = ""

    # Supabase Postgres — connect string via the project's transaction
    # pooler (port 6543, host like `aws-1-<region>.pooler.supabase.com`).
    # We use asyncpg directly. Empty string is tolerated so legacy smoke
    # scripts that don't touch the DB keep running.
    supabase_url: str = Field(
        default="",
        validation_alias=AliasChoices("SUPABASE_URL", "DATABASE_URL", "POSTGRES_URL"),
    )

    # NewsAPI — feed source for niches. Accept either name.
    newsapi_key: str = Field(
        default="",
        validation_alias=AliasChoices("NEWSAPI_KEY", "NEWS_API_KEY"),
    )

    # YouTube Data API v3 — separate Google Cloud project / API key from the
    # Gemini one. Falls back to google_api_key for backwards compat with the
    # original single-key setup.
    yt_data_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("YT_DATA_API", "YT_DATA_API_KEY", "YOUTUBE_DATA_API_KEY"),
    )

    embedding_model: str = "BAAI/bge-small-en-v1.5"
    # Chat model for full RAG answers.
    # Was "gemini-2.5-flash" -- best quality, but has a HARD 20-RPD daily
    # cap on the AI Studio free tier. To remove that cap, link billing on
    # the API key at https://aistudio.google.com/app/apikey ("Set up
    # billing") -- then bump this back to gemini-2.5-flash.
    # Until then, run on flash-lite which has ~1500 RPD on free tier.
    # Quality drops a touch on the long WHY-comparison answers, but
    # search grounding still works.
    # gemini-2.5-flash-lite is the most free-tier-friendly model.
    # By default it includes "thinking" tokens which add 15-25s of TTFT.
    # We disable thinking everywhere via the thinking_budget parameter
    # (see app/rag/chain.py, verdict.py, build/writer.py).
    gemini_model: str = "gemini-2.5-flash-lite"
    gemini_classifier_model: str = "gemini-2.5-flash-lite"

    chunk_target_tokens: int = 400
    chunk_overlap_tokens: int = 50

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
