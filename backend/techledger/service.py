"""Source registration and durable sync-job processing."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from techledger.models import CardEvent, Chunk, DecisionCard, IndexedDocument, Source, SourceSnapshot, SyncJob, utcnow
import json
from techledger.source_client import SourceError, fetch_source, normalize_url


def register_source(db: Session, url: str) -> Source:
    canonical, host = normalize_url(url)
    existing = db.scalar(select(Source).where(Source.url == canonical))
    if existing:
        if existing.status == "archived":
            existing.status = "registered"
            existing.review_status = "pending"
            existing.storage_policy = "metadata_only"
            existing.review_note = None
            existing.reviewed_at = None
            db.commit()
        return existing
    source = Source(url=canonical, host=host)
    db.add(source)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.scalar(select(Source).where(Source.url == canonical))  # type: ignore[return-value]
    db.refresh(source)
    return source


def enqueue_sync(db: Session, source: Source) -> SyncJob:
    pending = db.scalar(
        select(SyncJob).where(SyncJob.source_id == source.id, SyncJob.status.in_(["queued", "running"]))
    )
    if pending:
        return pending
    job = SyncJob(source_id=source.id)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def review_source(db: Session, source: Source, *, allow_local_index: bool, note: str) -> Source:
    """Record a human source-use decision; revocation removes local text."""
    source.review_status = "approved"
    source.storage_policy = "index_local" if allow_local_index else "metadata_only"
    source.review_note = note
    source.reviewed_at = utcnow()
    if not allow_local_index:
        snapshot_ids = list(db.scalars(select(SourceSnapshot.id).where(SourceSnapshot.source_id == source.id)))
        if snapshot_ids:
            db.query(Chunk).filter(Chunk.snapshot_id.in_(snapshot_ids)).delete(synchronize_session=False)
            db.query(IndexedDocument).filter(IndexedDocument.snapshot_id.in_(snapshot_ids)).delete(synchronize_session=False)
    db.commit()
    db.refresh(source)
    return source


def archive_source(db: Session, source: Source, reason: str) -> None:
    """Remove searchable text while preserving snapshot metadata and decision audit history."""
    source.status = "archived"
    source.review_status = "revoked"
    source.storage_policy = "metadata_only"
    source.review_note = reason
    source.reviewed_at = utcnow()
    snapshot_ids = list(db.scalars(select(SourceSnapshot.id).where(SourceSnapshot.source_id == source.id)))
    if snapshot_ids:
        db.query(Chunk).filter(Chunk.snapshot_id.in_(snapshot_ids)).delete(synchronize_session=False)
        db.query(IndexedDocument).filter(IndexedDocument.snapshot_id.in_(snapshot_ids)).delete(synchronize_session=False)
    for card in db.scalars(select(DecisionCard).where(DecisionCard.status.in_(["approved", "needs_review"]))):
        if any(item.get("source_id") == source.id for item in json.loads(card.content_json).get("evidence", [])):
            stale = json.loads(card.stale_sources_json)
            if source.id not in stale:
                stale.append(source.id)
                card.stale_sources_json = json.dumps(stale)
            card.status = "needs_review"
            db.add(CardEvent(card_id=card.id, action="source_archived", note=f"来源 {source.url} 已归档：{reason}", content_json=card.content_json))
    db.commit()


def rebuild_source_index(db: Session, source: Source) -> SyncJob:
    """Refetch with the current parser and replace local chunks for this source."""
    pending = db.scalar(select(SyncJob).where(SyncJob.source_id == source.id,
                                             SyncJob.status.in_(["queued", "running"])))
    if pending:
        return pending
    snapshot_ids = list(db.scalars(select(SourceSnapshot.id).where(SourceSnapshot.source_id == source.id)))
    if snapshot_ids:
        db.query(Chunk).filter(Chunk.snapshot_id.in_(snapshot_ids)).delete(synchronize_session=False)
        db.query(IndexedDocument).filter(IndexedDocument.snapshot_id.in_(snapshot_ids)).delete(synchronize_session=False)
    for card in db.scalars(select(DecisionCard).where(DecisionCard.status == "approved")):
        if any(item.get("source_id") == source.id for item in json.loads(card.content_json).get("evidence", [])):
            card.status = "needs_review"
            card.stale_sources_json = json.dumps(list(set(json.loads(card.stale_sources_json) + [source.id])))
            db.add(CardEvent(card_id=card.id, action="source_reindexed", note=f"来源 {source.url} 重新解析索引", content_json=card.content_json))
    db.commit()
    return enqueue_sync(db, source)


def _index_text(db: Session, snapshot: SourceSnapshot, text_content: str) -> None:
    if not text_content or db.get(IndexedDocument, snapshot.id):
        return
    db.add(IndexedDocument(snapshot_id=snapshot.id, text_content=text_content))
    # Character offsets refer to the normalized text stored in IndexedDocument.
    start = 0
    ordinal = 0
    while start < len(text_content):
        end = min(start + 800, len(text_content))
        if end < len(text_content):
            boundary = text_content.rfind(" ", start + 400, end)
            if boundary > start:
                end = boundary
        db.add(Chunk(snapshot_id=snapshot.id, ordinal=ordinal, start_char=start,
                     end_char=end, text_content=text_content[start:end]))
        ordinal += 1
        start = end
        while start < len(text_content) and text_content[start] == " ":
            start += 1


def process_one_job(db: Session) -> SyncJob | None:
    """Process one job. The MVP runs a single worker process."""
    job = db.scalar(
        select(SyncJob)
        .where(SyncJob.status == "queued")
        .order_by(SyncJob.created_at, SyncJob.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None

    job.status = "running"
    job.started_at = utcnow()
    db.commit()
    source = db.get(Source, job.source_id)
    if source is None:
        job.status = "failed"
        job.error_code = "source_missing"
        job.error_message = "来源不存在"
        job.finished_at = utcnow()
        db.commit()
        return job

    try:
        fetched = fetch_source(source.url)
        existing = db.scalar(
            select(SourceSnapshot).where(
                SourceSnapshot.source_id == source.id,
                SourceSnapshot.content_sha256 == fetched.content_sha256,
            )
        )
        if existing:
            snapshot = existing
            job.result = "unchanged"
        else:
            snapshot = SourceSnapshot(
                source_id=source.id,
                title=fetched.title,
                excerpt=fetched.excerpt if source.storage_policy == "short_excerpt" else "",
                content_sha256=fetched.content_sha256,
                content_type=fetched.content_type,
                byte_size=fetched.byte_size,
            )
            db.add(snapshot)
            db.flush()
            job.result = "new_snapshot"
        previous_snapshot_id = source.latest_snapshot_id
        source.latest_snapshot_id = snapshot.id
        if previous_snapshot_id and previous_snapshot_id != snapshot.id:
            for card in db.scalars(select(DecisionCard).where(DecisionCard.status.in_(["approved", "needs_review"]))):
                evidence = json.loads(card.content_json).get("evidence", [])
                if any(item.get("source_id") == source.id for item in evidence):
                    stale = json.loads(card.stale_sources_json)
                    if source.id not in stale:
                        stale.append(source.id)
                        card.stale_sources_json = json.dumps(stale)
                        card.status = "needs_review"
                        db.add(CardEvent(card_id=card.id, action="source_changed", note=f"来源 {source.url} 内容变化", content_json=card.content_json))
        if source.review_status == "approved" and source.storage_policy == "index_local":
            _index_text(db, snapshot, fetched.text_content)
        source.status = "ready"
        job.snapshot_id = snapshot.id
        job.status = "completed"
    except SourceError as exc:
        source.status = "sync_failed"
        job.status = "failed"
        job.error_code = exc.code
        job.error_message = str(exc)
    except Exception:
        db.rollback()
        job = db.get(SyncJob, job.id)
        source = db.get(Source, job.source_id) if job else None
        if job is None:
            raise
        if source:
            source.status = "sync_failed"
        job.status = "failed"
        job.error_code = "internal_error"
        job.error_message = "同步任务发生内部错误"
    job.finished_at = utcnow()
    db.commit()
    db.refresh(job)
    return job
