import json

from techledger.models import Chunk, DecisionCard, IndexedDocument, ResearchRun, Source, SourceSnapshot, SyncJob
from techledger.research import process_one_research
from techledger.service import process_one_job
from techledger.source_client import FetchedSource


def test_source_change_requires_card_review(client, session_factory, monkeypatch):
    with session_factory() as db:
        source = Source(url="https://docs.langchain.com/oss/python/langgraph/overview",
                        host="docs.langchain.com", review_status="approved", storage_policy="index_local")
        db.add(source)
        db.flush()
        snapshot = SourceSnapshot(source_id=source.id, content_sha256="a" * 64, title="Old",
                                  excerpt="", content_type="text/plain", byte_size=30)
        db.add(snapshot)
        db.flush()
        source.latest_snapshot_id = snapshot.id
        content = "LangGraph supports durable execution."
        db.add(IndexedDocument(snapshot_id=snapshot.id, text_content=content))
        db.add(Chunk(snapshot_id=snapshot.id, ordinal=0, start_char=0, end_char=len(content), text_content=content))
        db.commit()
        source_id = source.id

    run_id = client.post("/api/research", json={"question": "Does LangGraph support durable execution?",
        "constraints": "Need persistence", "candidates": ["LangGraph"]}).json()["id"]
    with session_factory() as db:
        process_one_research(db)
    result = client.get(f"/api/research/{run_id}").json()
    card_id = result["card_id"]
    assert result["events"][-1]["stage"] == "completed"
    assert client.post(f"/api/cards/{card_id}/review", json={"action": "approve", "note": "Verified"}).status_code == 200
    assert len(client.get("/api/cards").json()) == 1

    monkeypatch.setattr("techledger.service.fetch_source", lambda _url: FetchedSource(
        url=_url, title="New", excerpt="", text_content="Different content", content_sha256="b" * 64,
        content_type="text/plain", byte_size=17))
    client.post(f"/api/sources/{source_id}/sync")
    with session_factory() as db:
        assert process_one_job(db).status == "completed"
    diff = client.get(f"/api/sources/{source_id}/diff").json()
    assert diff["available"] is True
    assert "Different content" in diff["diff"]
    card = client.get(f"/api/cards/{card_id}").json()
    assert card["status"] == "needs_review"
    assert card["stale_source_ids"] == [source_id]
    assert card["history"][-1]["action"] == "source_changed"
    assert client.post(f"/api/cards/{card_id}/review", json={"action": "keep", "note": "Still valid"}).json()["status"] == "approved"
    old_chunk_id = card["content"]["evidence"][0]["chunk_id"]
    assert client.post(f"/api/cards/{card_id}/revision", json={"summary": "Old evidence", "note": "Trying old",
        "evidence_chunk_ids": [old_chunk_id]}).status_code == 409
    with session_factory() as db:
        new_chunk_id = db.query(Chunk).filter(Chunk.snapshot_id != card["content"]["evidence"][0]["snapshot_id"]).one().id
    revised = client.post(f"/api/cards/{card_id}/revision", json={"summary": "Updated conclusion", "note": "New evidence",
        "evidence_chunk_ids": [new_chunk_id]}).json()
    assert revised["status"] == "draft"
    assert revised["history"][-1]["content"]["summary"] != "Updated conclusion"
    assert client.post(f"/api/cards/{card_id}/review", json={"action": "approve", "note": "Checked"}).status_code == 200
    assert client.delete(f"/api/sources/{source_id}", params={"reason": "No longer used"}).status_code == 204
    assert client.get(f"/api/cards/{card_id}").json()["status"] == "needs_review"
    assert client.get(f"/api/chunks/{new_chunk_id}").status_code == 404
    assert client.get(f"/api/sources/{source_id}").status_code == 404
    restored = client.post("/api/sources", json={"url": "https://docs.langchain.com/oss/python/langgraph/overview"}).json()
    assert restored["id"] == source_id
    assert restored["review_status"] == "pending"
    assert client.post(f"/api/cards/{card_id}/review", json={"action": "archive", "note": "Obsolete"}).status_code == 200
    assert client.get("/api/cards").json() == []
