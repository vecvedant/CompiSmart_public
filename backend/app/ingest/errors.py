"""Shared exception types for the ingest pipeline."""


class IngestError(Exception):
    """Raised when a video can't be ingested (missing transcript, private, etc.)."""
