import hashlib

from techledger.models import Source
from techledger.search import _focused_snippet
from techledger.service import process_one_job
from techledger.source_client import FetchedSource


def fetched(body: str) -> FetchedSource:
    data = body.encode()
    return FetchedSource(
        url="https://docs.langchain.com/oss/python/langgraph/overview",
        title="Agent workflow guide",
        excerpt=body[:100],
        content_sha256=hashlib.sha256(data).hexdigest(),
        content_type="text/plain",
        byte_size=len(data),
        text_content=body,
    )


def test_focused_snippet_prioritizes_evidence_over_intro():
    content = "CrewAI marketing introduction. " + "navigation " * 35 + "State Management: Persist data across steps and executions."
    snippet = _focused_snippet(content, ["crewai", "persist", "data"], 160)
    assert "Persist data" in snippet


def test_review_gate_search_citation_and_revocation(client, session_factory, monkeypatch):
    source_id = client.post(
        "/api/sources", json={"url": "https://docs.langchain.com/oss/python/langgraph/overview"}
    ).json()["id"]
    current = [fetched("LangGraph supports durable execution and human review.")]
    monkeypatch.setattr("techledger.service.fetch_source", lambda _: current[0])

    client.post(f"/api/sources/{source_id}/sync")
    with session_factory() as db:
        process_one_job(db)
    assert client.get("/api/search", params={"query": "durable execution"}).json() == []

    invalid = client.post(f"/api/sources/{source_id}/review", json={"allow_local_index": True, "note": "short"})
    assert invalid.status_code == 422
    approved = client.post(
        f"/api/sources/{source_id}/review",
        json={"allow_local_index": True, "note": "已核对该来源的本地索引使用方式"},
    )
    assert approved.status_code == 200
    assert approved.json()["storage_policy"] == "index_local"
    client.post(f"/api/sources/{source_id}/sync")
    with session_factory() as db:
        assert process_one_job(db).result == "unchanged"
    results = client.get("/api/search", params={"query": "durable execution"}).json()
    assert len(results) == 1
    assert results[0]["mode"] == "bm25"
    assert client.get("/api/search", params={"query": "durable executio", "mode": "vector"}).json()[0]["chunk_id"] == results[0]["chunk_id"]
    assert client.get("/api/search", params={"query": "durable execution", "mode": "hybrid"}).json()[0]["chunk_id"] == results[0]["chunk_id"]
    assert client.get("/api/search", params={"query": "durable execution", "mode": "unknown"}).status_code == 422
    citation = client.get(f"/api/chunks/{results[0]['chunk_id']}").json()
    assert citation["text"][citation["start_char"]:citation["end_char"]] == citation["text"]
    assert citation["snapshot_sha256"] == current[0].content_sha256

    current[0] = fetched("CrewAI offers collaborative agent workflows.")
    client.post(f"/api/sources/{source_id}/sync")
    with session_factory() as db:
        process_one_job(db)
        assert db.get(Source, source_id).latest_snapshot_id != results[0]["snapshot_id"]
    assert client.get("/api/search", params={"query": "durable execution"}).json() == []

    client.post(
        f"/api/sources/{source_id}/review",
        json={"allow_local_index": False, "note": "撤销全文索引，仅保留元数据"},
    )
    assert client.get("/api/search", params={"query": "collaborative"}).json() == []
    assert client.get(f"/api/chunks/{results[0]['chunk_id']}").status_code == 404


def test_rebuild_replaces_index_for_same_source_hash(client, session_factory, monkeypatch):
    source_id = client.post("/api/sources", json={"url": "https://docs.langchain.com/oss/python/langgraph/overview"}).json()["id"]
    current = fetched("Navigation Durable execution")
    monkeypatch.setattr("techledger.service.fetch_source", lambda _: current)
    client.post(f"/api/sources/{source_id}/review", json={"allow_local_index": True,
        "note": "Local indexing approved for the test"})
    client.post(f"/api/sources/{source_id}/sync")
    with session_factory() as db:
        process_one_job(db)
    old_id = client.get("/api/search", params={"query": "durable execution"}).json()[0]["chunk_id"]
    assert client.post(f"/api/sources/{source_id}/rebuild").status_code == 202
    with session_factory() as db:
        process_one_job(db)
    new_id = client.get("/api/search", params={"query": "durable execution"}).json()[0]["chunk_id"]
    assert new_id != old_id
    assert client.get(f"/api/chunks/{old_id}").status_code == 404
