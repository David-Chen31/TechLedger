"""FastAPI entry point for TechLedger's first runnable milestone."""

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from techledger.config import WEB_ORIGIN
from techledger.db import SessionLocal, get_db
from techledger.evaluation import freeze_dataset, replay
from techledger.research_eval import compare_planners
import json
import difflib
import asyncio

from techledger.models import CardEvent, DecisionCard, IndexedDocument, ResearchRun, RunEvent, Source, SourceSnapshot, SyncJob, utcnow
from techledger.schemas import CardRevisionIn, CitationOut, ResearchCreate, ReviewIn, SearchOut, SnapshotOut, SourceCreate, SourceOut, SourceReviewIn, SyncJobOut
from techledger.search import get_citation, search_chunks
from techledger.service import archive_source, enqueue_sync, rebuild_source_index, register_source, review_source
from techledger.source_client import SourceError

app = FastAPI(title="TechLedger API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[WEB_ORIGIN],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"code": "database_unavailable"}) from exc
    return {"status": "ok"}


@app.get("/api/sources", response_model=list[SourceOut])
def list_sources(db: Session = Depends(get_db)) -> list[Source]:
    return list(db.scalars(select(Source).where(Source.status != "archived").order_by(Source.created_at.desc())).all())


@app.post("/api/sources", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
def create_source(payload: SourceCreate, db: Session = Depends(get_db)) -> Source:
    try:
        return register_source(db, payload.url)
    except SourceError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc


@app.get("/api/sources/{source_id}", response_model=SourceOut)
def get_source(source_id: str, db: Session = Depends(get_db)) -> Source:
    source = db.get(Source, source_id)
    if source is None or source.status == "archived":
        raise HTTPException(status_code=404, detail={"code": "source_not_found"})
    return source


@app.delete("/api/sources/{source_id}", status_code=204)
def delete_source(source_id: str, reason: str = Query(min_length=1, max_length=1000),
                  db: Session = Depends(get_db)) -> None:
    source = db.get(Source, source_id)
    if source is None or source.status == "archived":
        raise HTTPException(status_code=404, detail={"code": "source_not_found"})
    archive_source(db, source, reason)


@app.get("/api/sources/{source_id}/snapshots", response_model=list[SnapshotOut])
def list_snapshots(source_id: str, db: Session = Depends(get_db)) -> list[SourceSnapshot]:
    if db.get(Source, source_id) is None:
        raise HTTPException(status_code=404, detail={"code": "source_not_found"})
    return list(
        db.scalars(
            select(SourceSnapshot)
            .where(SourceSnapshot.source_id == source_id)
            .order_by(SourceSnapshot.fetched_at.desc())
        ).all()
    )


@app.get("/api/sources/{source_id}/diff")
def source_diff(source_id: str, db: Session = Depends(get_db)) -> dict:
    source = db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail={"code": "source_not_found"})
    snapshots = list(db.scalars(select(SourceSnapshot).where(SourceSnapshot.source_id == source_id)
                                .order_by(SourceSnapshot.fetched_at.desc(), SourceSnapshot.id.desc()).limit(2)))
    if len(snapshots) < 2:
        return {"available": False, "reason": "need_two_snapshots"}
    current = next((item for item in snapshots if item.id == source.latest_snapshot_id), snapshots[0])
    previous = next((item for item in snapshots if item.id != current.id), None)
    if previous is None:
        return {"available": False, "reason": "need_two_snapshots"}
    old_text = db.get(IndexedDocument, previous.id)
    new_text = db.get(IndexedDocument, current.id)
    if old_text is None or new_text is None:
        return {"available": False, "reason": "text_not_indexed", "from_sha256": previous.content_sha256,
                "to_sha256": current.content_sha256}
    lines = list(difflib.unified_diff(old_text.text_content.splitlines(), new_text.text_content.splitlines(),
                                      fromfile=previous.content_sha256[:12], tofile=current.content_sha256[:12], lineterm=""))
    diff = "\n".join(lines)
    return {"available": True, "from_sha256": previous.content_sha256,
            "to_sha256": current.content_sha256, "diff": diff[:12000], "truncated": len(diff) > 12000}


@app.post("/api/sources/{source_id}/sync", response_model=SyncJobOut, status_code=status.HTTP_202_ACCEPTED)
def sync_source(source_id: str, db: Session = Depends(get_db)) -> SyncJob:
    source = db.get(Source, source_id)
    if source is None or source.status == "archived":
        raise HTTPException(status_code=404, detail={"code": "source_not_found"})
    return enqueue_sync(db, source)


@app.post("/api/sources/{source_id}/rebuild", response_model=SyncJobOut, status_code=status.HTTP_202_ACCEPTED)
def rebuild_source(source_id: str, db: Session = Depends(get_db)) -> SyncJob:
    source = db.get(Source, source_id)
    if source is None or source.status == "archived":
        raise HTTPException(status_code=404, detail={"code": "source_not_found"})
    if source.review_status != "approved" or source.storage_policy != "index_local":
        raise HTTPException(status_code=409, detail={"code": "source_not_indexable"})
    return rebuild_source_index(db, source)


@app.get("/api/jobs/{job_id}", response_model=SyncJobOut)
def get_job(job_id: str, db: Session = Depends(get_db)) -> SyncJob:
    job = db.get(SyncJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "job_not_found"})
    return job


@app.post("/api/sources/{source_id}/review", response_model=SourceOut)
def review_source_use(source_id: str, payload: SourceReviewIn, db: Session = Depends(get_db)) -> Source:
    source = db.get(Source, source_id)
    if source is None or source.status == "archived":
        raise HTTPException(status_code=404, detail={"code": "source_not_found"})
    return review_source(db, source, allow_local_index=payload.allow_local_index, note=payload.note)


@app.get("/api/search", response_model=list[SearchOut])
def search(query: str = Query(min_length=1, max_length=200), limit: int = Query(5, ge=1, le=20),
           mode: str = Query("bm25", pattern="^(bm25|vector|hybrid)$"),
           db: Session = Depends(get_db)) -> list[dict]:
    return search_chunks(db, query, limit, mode)


@app.post("/api/evaluation/replay")
def replay_evaluation(dataset: dict, mode: str = Query("bm25", pattern="^(bm25|vector|hybrid)$"),
                      db: Session = Depends(get_db)) -> dict:
    validate_evaluation_dataset(dataset)
    try:
        return replay(db, dataset, mode=mode)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_dataset", "message": str(exc)}) from exc


def validate_evaluation_dataset(dataset: dict) -> None:
    cases = dataset.get("cases")
    if not isinstance(cases, list) or len(cases) > 100:
        raise HTTPException(status_code=422, detail={"code": "invalid_case_count"})
    try:
        for case in cases:
            if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not isinstance(case.get("question"), str):
                raise ValueError("Invalid case shape")
            if len(case["question"]) > 200 or not case["question"].strip():
                raise ValueError("Invalid question")
            if not isinstance(case.get("expected_source_urls", []), list) or not all(isinstance(item, str) for item in case.get("expected_source_urls", [])):
                raise ValueError("Invalid expected_source_urls")
            if not isinstance(case.get("expected_terms", []), list) or not all(isinstance(item, str) for item in case.get("expected_terms", [])):
                raise ValueError("Invalid expected_terms")
            if "expected_no_hit" in case and not isinstance(case["expected_no_hit"], bool):
                raise ValueError("Invalid expected_no_hit")
            if case.get("expected_no_hit") and case.get("expected_source_urls"):
                raise ValueError("Negative case cannot require a source")
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_dataset", "message": str(exc)}) from exc


@app.post("/api/evaluation/freeze")
def freeze_evaluation(dataset: dict, db: Session = Depends(get_db)) -> dict:
    validate_evaluation_dataset(dataset)
    try:
        return freeze_dataset(db, dataset)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"code": "cannot_freeze_dataset", "message": str(exc)}) from exc


@app.post("/api/evaluation/research-retrieval")
def compare_research_retrieval(dataset: dict, db: Session = Depends(get_db)) -> dict:
    validate_evaluation_dataset(dataset)
    try:
        return compare_planners(db, dataset)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_research_dataset", "message": str(exc)}) from exc


@app.get("/api/chunks/{chunk_id}", response_model=CitationOut)
def citation(chunk_id: str, db: Session = Depends(get_db)) -> dict:
    found = get_citation(db, chunk_id)
    if found is None:
        raise HTTPException(status_code=404, detail={"code": "citation_not_found"})
    return found


@app.post("/api/research", status_code=202)
def create_research(payload: ResearchCreate, db: Session = Depends(get_db)) -> dict:
    run = ResearchRun(question=payload.question, constraints=payload.constraints,
                      candidates=json.dumps(payload.candidates, ensure_ascii=False))
    db.add(run)
    db.commit()
    return {"id": run.id, "status": run.status}


@app.post("/api/research/{run_id}/cancel")
def cancel_research(run_id: str, db: Session = Depends(get_db)) -> dict:
    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "run_not_found"})
    if run.status not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail={"code": "run_finished"})
    run.status = "cancelled"
    db.add(RunEvent(run_id=run.id, stage="cancel_requested", detail_json="{}"))
    db.commit()
    return {"id": run.id, "status": run.status}


@app.get("/api/research/{run_id}")
def get_research(run_id: str, db: Session = Depends(get_db)) -> dict:
    run = db.get(ResearchRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "run_not_found"})
    card = db.scalar(select(DecisionCard).where(DecisionCard.run_id == run_id))
    return {"id": run.id, "status": run.status, "error_code": run.error_code,
            "result": json.loads(run.result_json) if run.result_json else None,
            "card_id": card.id if card else None, "card_status": card.status if card else None,
            "events": [{"stage": event.stage, "detail": json.loads(event.detail_json), "at": event.created_at.isoformat()}
                       for event in db.scalars(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.created_at, RunEvent.id))]}


@app.get("/api/research/{run_id}/events")
def research_events(run_id: str, cursor: int = Query(0, ge=0), db: Session = Depends(get_db)) -> StreamingResponse:
    if db.get(ResearchRun, run_id) is None:
        raise HTTPException(status_code=404, detail={"code": "run_not_found"})

    async def stream():
        index = cursor
        while True:
            with SessionLocal() as event_db:
                events = list(event_db.scalars(select(RunEvent).where(RunEvent.run_id == run_id)
                                                .order_by(RunEvent.created_at, RunEvent.id)))
                run = event_db.get(ResearchRun, run_id)
                for event in events[index:]:
                    index += 1
                    payload = {"stage": event.stage, "detail": json.loads(event.detail_json),
                               "at": event.created_at.isoformat()}
                    yield f"id: {index}\nevent: stage\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if run is None or run.status in {"completed", "partial", "failed", "cancelled"}:
                    yield f"event: done\ndata: {json.dumps({'status': run.status if run else 'missing'})}\n\n"
                    break
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


def card_view(card: DecisionCard, db: Session) -> dict:
    return {"id": card.id, "run_id": card.run_id, "status": card.status,
            "content": json.loads(card.content_json), "stale_source_ids": json.loads(card.stale_sources_json),
            "review_note": card.review_note,
            "history": [{"action": event.action, "note": event.note, "at": event.created_at.isoformat(),
                         "content": json.loads(event.content_json)}
                        for event in db.scalars(select(CardEvent).where(CardEvent.card_id == card.id)
                                                .order_by(CardEvent.created_at, CardEvent.id))]}


@app.get("/api/cards")
def list_cards(db: Session = Depends(get_db)) -> list[dict]:
    cards = db.scalars(select(DecisionCard).where(DecisionCard.status.in_(["approved", "needs_review"])))
    return [card_view(card, db) for card in cards]


@app.get("/api/cards/{card_id}")
def get_card(card_id: str, db: Session = Depends(get_db)) -> dict:
    card = db.get(DecisionCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail={"code": "card_not_found"})
    return card_view(card, db)


@app.post("/api/cards/{card_id}/revision")
def revise_card(card_id: str, payload: CardRevisionIn, db: Session = Depends(get_db)) -> dict:
    card = db.get(DecisionCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail={"code": "card_not_found"})
    if card.status == "archived":
        raise HTTPException(status_code=409, detail={"code": "card_archived"})
    evidence = []
    claims = []
    for chunk_id in dict.fromkeys(payload.evidence_chunk_ids):
        citation = get_citation(db, chunk_id)
        if citation is None:
            raise HTTPException(status_code=409, detail={"code": "invalid_evidence"})
        snapshot = db.get(SourceSnapshot, citation["snapshot_id"])
        source = db.get(Source, snapshot.source_id) if snapshot else None
        if source is None or source.latest_snapshot_id != citation["snapshot_id"]:
            raise HTTPException(status_code=409, detail={"code": "stale_evidence"})
        evidence.append({"chunk_id": chunk_id, "source_id": source.id, "source_url": source.url,
                         "snapshot_id": snapshot.id, "snapshot_sha256": snapshot.content_sha256,
                         "title": citation["title"], "start_char": citation["start_char"],
                         "end_char": citation["end_char"], "snippet": citation["text"][:360], "score": 0.0})
        claims.append({"text": citation["text"].strip()[:360], "chunk_id": chunk_id,
                       "source_url": source.url, "snapshot_sha256": snapshot.content_sha256,
                       "verification": "literal_excerpt"})
    db.add(CardEvent(card_id=card.id, action="revision", note=payload.note, content_json=card.content_json))
    content = json.loads(card.content_json)
    content["summary"] = payload.summary
    content["evidence"] = evidence
    content["claims"] = claims
    card.content_json = json.dumps(content, ensure_ascii=False)
    card.status = "draft"
    db.commit()
    return card_view(card, db)


@app.post("/api/cards/{card_id}/review")
def review_card(card_id: str, payload: ReviewIn, db: Session = Depends(get_db)) -> dict:
    if payload.action not in {"approve", "return", "keep", "archive"}:
        raise HTTPException(status_code=422, detail={"code": "invalid_action"})
    card = db.get(DecisionCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail={"code": "card_not_found"})
    if payload.action in {"approve", "return"} and card.status != "draft":
        raise HTTPException(status_code=409, detail={"code": "invalid_card_state"})
    if payload.action == "approve":
        content = json.loads(card.content_json)
        evidence = content.get("evidence", [])
        claims = content.get("claims", [])
        if not evidence or not claims or any(get_citation(db, item.get("chunk_id", "")) is None for item in evidence):
            raise HTTPException(status_code=409, detail={"code": "invalid_evidence"})
        for claim in claims:
            citation = get_citation(db, claim.get("chunk_id", ""))
            if citation is None or claim.get("text", "") not in citation["text"]:
                raise HTTPException(status_code=409, detail={"code": "invalid_claim"})
        for item in evidence:
            source = db.get(Source, item["source_id"])
            if source is None or source.latest_snapshot_id != item["snapshot_id"]:
                raise HTTPException(status_code=409, detail={"code": "stale_evidence"})
    if payload.action == "keep" and card.status != "needs_review":
        raise HTTPException(status_code=409, detail={"code": "invalid_card_state"})
    if payload.action == "archive" and card.status == "archived":
        raise HTTPException(status_code=409, detail={"code": "invalid_card_state"})
    db.add(CardEvent(card_id=card.id, action=payload.action, note=payload.note, content_json=card.content_json))
    card.status = {"approve": "approved", "return": "returned", "keep": "approved", "archive": "archived"}[payload.action]
    if payload.action in {"keep", "approve"}:
        card.stale_sources_json = "[]"
    card.review_note = payload.note
    card.reviewed_at = utcnow()
    db.commit()
    return {"id": card.id, "status": card.status}
