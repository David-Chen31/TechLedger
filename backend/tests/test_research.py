import json
import httpx

from techledger.models import DecisionCard, ResearchRun
from techledger.research import _collect_evidence, _model_summary, _research_plan, process_one_research


def test_research_without_evidence_is_partial(client, session_factory, monkeypatch):
    monkeypatch.setattr("techledger.api.SessionLocal", session_factory)
    created = client.post("/api/research", json={
        "question": "Which agent framework should this team choose?",
        "constraints": "Must support review",
        "candidates": ["LangGraph", "CrewAI"],
    })
    assert created.status_code == 202
    with session_factory() as db:
        run = process_one_research(db)
        assert run.status == "partial"
        card = db.query(DecisionCard).filter_by(run_id=run.id).one()
        assert card.status == "draft"
    result = client.get(f"/api/research/{created.json()['id']}").json()
    assert result["result"]["unknowns"]
    assert result["result"]["evidence"] == []
    stream = client.get(f"/api/research/{created.json()['id']}/events")
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "event: done" in stream.text
    assert client.post(f"/api/cards/{result['card_id']}/review", json={"action": "approve", "note": "No evidence"}).status_code == 409
    reviewed = client.post(f"/api/cards/{result['card_id']}/review", json={"action": "return", "note": "Need sources"})
    assert reviewed.json()["status"] == "returned"
    assert client.post(f"/api/cards/{result['card_id']}/review", json={"action": "approve", "note": "OK"}).status_code == 409


def test_research_with_indexed_evidence_uses_fixed_citation(client, session_factory):
    from techledger.models import Chunk, IndexedDocument, Source, SourceSnapshot

    with session_factory() as db:
        source = Source(url="https://docs.langchain.com/oss/python/langgraph/overview",
                        host="docs.langchain.com", review_status="approved", storage_policy="index_local")
        db.add(source)
        db.flush()
        snapshot = SourceSnapshot(source_id=source.id, content_sha256="a" * 64,
                                  title="LangGraph", excerpt="", content_type="text/plain", byte_size=30)
        db.add(snapshot)
        db.flush()
        source.latest_snapshot_id = snapshot.id
        text = "LangGraph supports durable execution."
        db.add(IndexedDocument(snapshot_id=snapshot.id, text_content=text))
        db.add(Chunk(snapshot_id=snapshot.id, ordinal=0, start_char=0, end_char=len(text), text_content=text))
        db.commit()

    run_id = client.post("/api/research", json={
        "question": "Does LangGraph support durable execution?",
        "constraints": "Need persistence",
        "candidates": ["LangGraph"],
    }).json()["id"]
    with session_factory() as db:
        assert process_one_research(db).status == "completed"
    result = client.get(f"/api/research/{run_id}").json()
    assert result["result"]["evidence"][0]["snapshot_sha256"] == "a" * 64
    assert result["result"]["model_mode"] == "fake"
    assert client.post(f"/api/cards/{result['card_id']}/review", json={"action": "approve", "note": "Verified"}).json()["status"] == "approved"


def test_model_timeout_is_visible(client, session_factory, monkeypatch):
    from techledger.models import Chunk, IndexedDocument, Source, SourceSnapshot
    with session_factory() as db:
        source = Source(url="https://docs.langchain.com/oss/python/langgraph/overview",
                        host="docs.langchain.com", review_status="approved", storage_policy="index_local")
        db.add(source); db.flush()
        snapshot = SourceSnapshot(source_id=source.id, content_sha256="a" * 64, title="LangGraph",
                                  excerpt="", content_type="text/plain", byte_size=10)
        db.add(snapshot); db.flush()
        source.latest_snapshot_id = snapshot.id
        db.add(IndexedDocument(snapshot_id=snapshot.id, text_content="LangGraph"))
        db.add(Chunk(snapshot_id=snapshot.id, ordinal=0, start_char=0, end_char=9, text_content="LangGraph"))
        db.commit()
    monkeypatch.setattr("techledger.research._model_summary", lambda *_: (_ for _ in ()).throw(httpx.TimeoutException("timed out")))
    run_id = client.post("/api/research", json={"question": "What is LangGraph for?",
        "constraints": "Must be supported", "candidates": ["LangGraph"]}).json()["id"]
    with session_factory() as db:
        assert process_one_research(db).status == "failed"
    result = client.get(f"/api/research/{run_id}").json()
    assert result["error_code"] == "model_timeout"
    assert result["events"][-1]["detail"]["code"] == "model_timeout"


def test_deepseek_flash_request_is_bounded(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "test-only")
    monkeypatch.setenv("MODEL_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("MODEL_NAME", "deepseek-flash")
    seen = {}

    def fake_post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "证据有限"}}],
                                         "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr("techledger.research.httpx.post", fake_post)
    summary, usage = _model_summary("Which framework?", "Review required", ["LangGraph"],
                                    [{"chunk_id": "id1", "source_url": "https://example.com", "snippet": "x" * 500}])
    assert summary == "证据有限"
    assert usage["total_tokens"] == 25
    assert seen["json"]["model"] == "deepseek-flash"
    assert seen["json"]["thinking"] == {"type": "disabled"}
    assert seen["json"]["max_tokens"] <= 256
    assert len(json.loads(seen["json"]["messages"][1]["content"])["evidence"][0]["text"]) == 220


def test_model_key_can_be_read_from_worker_secret(tmp_path, monkeypatch):
    secret = tmp_path / "key"
    secret.write_text("test-only", encoding="utf-8")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("MODEL_API_KEY_FILE", str(secret))
    monkeypatch.setenv("MODEL_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("MODEL_NAME", "deepseek-flash")
    captured = {}

    def fake_post(url, **kwargs):
        captured["authorized"] = kwargs["headers"]["Authorization"] == "Bearer test-only"
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr("techledger.research.httpx.post", fake_post)
    _model_summary("Question", "Constraints", ["LangGraph"], [{"chunk_id": "id", "source_url": "https://example.com", "snippet": "evidence"}])
    assert captured["authorized"]


def test_capability_queries_cover_each_candidate(session_factory):
    from techledger.models import Chunk, IndexedDocument, Source, SourceSnapshot
    fixtures = [
        ("https://docs.langchain.com/oss/python/langgraph/overview", "docs.langchain.com",
         "LangGraph durable execution human-in-the-loop persistence."),
        ("https://docs.crewai.com/en/introduction", "docs.crewai.com",
         "CrewAI Flows persist data across steps and executions. Conditional logic and branching."),
    ]
    with session_factory() as db:
        for url, host, content in fixtures:
            source = Source(url=url, host=host, review_status="approved", storage_policy="index_local")
            db.add(source); db.flush()
            snapshot = SourceSnapshot(source_id=source.id, content_sha256="a" * 64, title=host,
                                      excerpt="", content_type="text/plain", byte_size=len(content))
            db.add(snapshot); db.flush()
            source.latest_snapshot_id = snapshot.id
            db.add(IndexedDocument(snapshot_id=snapshot.id, text_content=content))
            db.add(Chunk(snapshot_id=snapshot.id, ordinal=0, start_char=0, end_char=len(content), text_content=content))
        db.commit()
        evidence, queries = _collect_evidence(db, "持久化和人工审核如何比较？", "需要可恢复执行", ["LangGraph", "CrewAI"])
    assert len({item["source_url"] for item in evidence}) == 2
    assert any("persistence" in item["snippet"] for item in evidence)
    assert any("persist data" in item["snippet"] for item in evidence)
    assert any("human-in-the-loop" in query for query in queries)


def test_repair_pass_is_bounded_and_records_missing_capability(session_factory, monkeypatch):
    from techledger.models import Source
    with session_factory() as db:
        source = Source(url="https://docs.crewai.com/en/introduction", host="docs.crewai.com",
                        review_status="approved", storage_policy="index_local")
        db.add(source)
        db.commit()
        calls = []
        def fake_search(_db, query, limit, mode, source_id=None):
            calls.append((query, limit, source_id))
            if len(calls) == 1:
                return [{"chunk_id": "initial", "source_id": source.id, "snippet": "CrewAI introduction"}]
            return [{"chunk_id": "repair", "source_id": source.id,
                     "snippet": "Flows provide event-driven workflows."}]
        monkeypatch.setattr("techledger.research.search_chunks", fake_search)
        plan = _research_plan(db, "是否支持事件驱动？", "需要事件驱动流程", ["CrewAI"])
    assert len([call for call in plan["calls"] if call["stage"] == "repair"]) == 1
    assert plan["repaired"] == [{"candidate": "CrewAI", "capability": "event_driven", "added": 1}]
    assert plan["stop_reason"] == "coverage_met"
    assert plan["unresolved"] == []
