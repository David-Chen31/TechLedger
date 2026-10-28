"""Public API shapes for the source registry."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SourceCreate(BaseModel):
    url: str = Field(min_length=10, max_length=2048)


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    url: str
    host: str
    status: str
    review_status: str
    storage_policy: str
    review_note: str | None
    reviewed_at: datetime | None
    created_at: datetime
    latest_snapshot_id: str | None


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    content_sha256: str
    title: str
    excerpt: str
    content_type: str
    byte_size: int
    fetched_at: datetime


class SyncJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    status: str
    result: str | None
    error_code: str | None
    error_message: str | None
    snapshot_id: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class SourceReviewIn(BaseModel):
    allow_local_index: bool
    note: str = Field(min_length=10, max_length=1000)


class SearchOut(BaseModel):
    chunk_id: str
    source_id: str
    source_url: str
    snapshot_id: str
    snapshot_sha256: str
    title: str
    start_char: int
    end_char: int
    snippet: str
    score: float
    mode: str


class CitationOut(BaseModel):
    chunk_id: str
    source_url: str
    snapshot_id: str
    snapshot_sha256: str
    title: str
    start_char: int
    end_char: int
    text: str


class ResearchCreate(BaseModel):
    question: str = Field(min_length=10, max_length=2000)
    constraints: str = Field(min_length=1, max_length=2000)
    candidates: list[str] = Field(min_length=1, max_length=3)


class ReviewIn(BaseModel):
    action: str
    note: str = Field(min_length=1, max_length=1000)


class CardRevisionIn(BaseModel):
    summary: str = Field(min_length=1, max_length=3000)
    note: str = Field(min_length=1, max_length=1000)
    evidence_chunk_ids: list[str] = Field(min_length=1, max_length=12)
