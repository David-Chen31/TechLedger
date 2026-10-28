import pytest

from techledger.evaluation import freeze_dataset, replay


def test_empty_replay_reports_unknown_quality(session_factory):
    with session_factory() as db:
        report = replay(db, {"version": 1, "cases": [{"id": "fact-001", "question": "durable execution",
            "expected_source_urls": ["https://docs.langchain.com/oss/python/langgraph/overview"]}]})
    assert report["case_count"] == 1
    assert report["source_recall_at_k"] == 0
    assert report["citation_valid_rate"] is None


def test_replay_rejects_duplicate_cases(session_factory):
    with session_factory() as db, pytest.raises(ValueError):
        replay(db, {"version": 1, "cases": [{"id": "x", "question": "one"}, {"id": "x", "question": "two"}]})


def test_replay_api(client):
    response = client.post("/api/evaluation/replay", json={"version": 1, "cases": [
        {"id": "fact-001", "question": "durable execution", "expected_source_urls": []}]})
    assert response.status_code == 200
    assert response.json()["case_count"] == 1
    assert client.post("/api/evaluation/replay?mode=hybrid", json={"version": 1, "cases": []}).json()["mode"] == "hybrid"
    assert client.post("/api/evaluation/replay", json={"version": 1, "cases": [
        {"id": "x", "question": "one"}, {"id": "x", "question": "two"}]}).status_code == 422
    assert client.post("/api/evaluation/freeze", json={"version": 1, "cases": [
        {"id": "one", "question": "durable execution", "expected_source_urls": ["https://example.com"]}]}).status_code == 422


def test_freeze_requires_approved_snapshot(session_factory):
    dataset = {"version": 1, "cases": [{"id": "one", "question": "durable execution",
        "expected_source_urls": ["https://docs.langchain.com/oss/python/langgraph/overview"]}]}
    with session_factory() as db, pytest.raises(ValueError, match="not approved"):
        freeze_dataset(db, dataset)


def test_replay_rejects_changed_frozen_source(session_factory):
    dataset = {"version": 1, "frozen_sources": {"https://example.com": "a" * 64},
               "cases": [{"id": "one", "question": "durable execution"}]}
    with session_factory() as db, pytest.raises(ValueError, match="Frozen source changed"):
        replay(db, dataset)


def test_freeze_binds_approved_source_hash(session_factory):
    from techledger.models import IndexedDocument, Source, SourceSnapshot
    url = "https://docs.langchain.com/oss/python/langgraph/overview"
    dataset = {"version": 1, "cases": [{"id": "one", "question": "durable execution",
        "expected_source_urls": [url]}]}
    with session_factory() as db:
        source = Source(url=url, host="docs.langchain.com", review_status="approved", storage_policy="index_local")
        db.add(source); db.flush()
        snapshot = SourceSnapshot(source_id=source.id, content_sha256="a" * 64, title="Overview",
                                  excerpt="", content_type="text/plain", byte_size=10)
        db.add(snapshot); db.flush()
        source.latest_snapshot_id = snapshot.id
        db.add(IndexedDocument(snapshot_id=snapshot.id, text_content="durable execution"))
        db.commit()
        frozen = freeze_dataset(db, dataset)
        assert frozen["frozen_sources"][url]["source_sha256"] == "a" * 64
        assert len(frozen["frozen_sources"][url]["indexed_text_sha256"]) == 64
        assert replay(db, frozen)["frozen"] is True
