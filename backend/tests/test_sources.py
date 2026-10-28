import hashlib

import httpx
import pytest
from sqlalchemy import select

from techledger.models import Source, SourceSnapshot, SyncJob
from techledger.service import process_one_job
from techledger.source_client import FetchedSource, SourceError, _metadata, fetch_source, normalize_url


def fake_result(body: bytes) -> FetchedSource:
    return FetchedSource(
        url="https://docs.langchain.com/oss/python/langgraph/overview",
        title="LangGraph overview",
        excerpt="Sample content",
        content_sha256=hashlib.sha256(body).hexdigest(),
        content_type="text/html",
        byte_size=len(body),
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://docs.langchain.com/oss/python/langgraph/overview",
        "https://docs.langchain.com.evil.test/oss/python/langgraph/overview",
        "https://github.com/other/repo/releases",
        "https://user:pass@docs.crewai.com/en/introduction",
        "https://docs.crewai.com:8443/en/introduction",
    ],
)
def test_source_allowlist_rejects_unapproved_urls(url):
    with pytest.raises(SourceError) as error:
        normalize_url(url)
    assert error.value.code in {"source_not_allowed", "invalid_url"}


def test_source_allowlist_accepts_official_versioned_path():
    canonical, host = normalize_url("https://docs.crewai.com/v1.15.32/en/introduction?ref=demo#section")
    assert canonical == "https://docs.crewai.com/v1.15.32/en/introduction"
    assert host == "docs.crewai.com"


def test_html_extraction_uses_main_and_ignores_navigation():
    html = b"<html><head><title>Guide</title></head><body><nav>Irrelevant menu</nav><main><h1>Durable execution</h1><p>Resume after failure.</p><aside>Sidebar</aside></main><footer>Footer</footer></body></html>"
    result = _metadata(html, "text/html", "https://docs.langchain.com/oss/python/langgraph/overview")
    assert result.title == "Guide"
    assert result.text_content == "Durable execution Resume after failure."


def test_fetch_rejects_redirect_outside_allowlist(monkeypatch):
    real_client = httpx.Client

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://127.0.0.1/internal"})

    monkeypatch.setattr(
        "techledger.source_client.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    with pytest.raises(SourceError) as error:
        fetch_source("https://docs.langchain.com/oss/python/langgraph/overview")
    assert error.value.code == "source_not_allowed"


def test_fetch_enforces_response_size_limit(monkeypatch):
    real_client = httpx.Client
    monkeypatch.setattr("techledger.source_client.SOURCE_MAX_BYTES", 8)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"longer than eight")

    monkeypatch.setattr(
        "techledger.source_client.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    with pytest.raises(SourceError) as error:
        fetch_source("https://docs.langchain.com/oss/python/langgraph/overview")
    assert error.value.code == "source_too_large"


def test_source_registry_and_immutable_snapshots(client, session_factory, monkeypatch):
    url = "https://docs.langchain.com/oss/python/langgraph/overview"
    created = client.post("/api/sources", json={"url": url})
    assert created.status_code == 201
    source_id = created.json()["id"]
    assert created.json()["storage_policy"] == "metadata_only"
    assert client.post("/api/sources", json={"url": url + "#anchor"}).json()["id"] == source_id

    current = [fake_result(b"version-one")]
    monkeypatch.setattr("techledger.service.fetch_source", lambda _: current[0])

    first_job = client.post(f"/api/sources/{source_id}/sync")
    assert first_job.status_code == 202
    assert client.post(f"/api/sources/{source_id}/sync").json()["id"] == first_job.json()["id"]
    with session_factory() as db:
        assert process_one_job(db).result == "new_snapshot"
    first_snapshots = client.get(f"/api/sources/{source_id}/snapshots").json()
    assert len(first_snapshots) == 1
    assert first_snapshots[0]["excerpt"] == ""  # no unreviewed source text persisted

    client.post(f"/api/sources/{source_id}/sync")
    with session_factory() as db:
        assert process_one_job(db).result == "unchanged"
    assert len(client.get(f"/api/sources/{source_id}/snapshots").json()) == 1

    current[0] = fake_result(b"version-two")
    client.post(f"/api/sources/{source_id}/sync")
    with session_factory() as db:
        assert process_one_job(db).result == "new_snapshot"
        source = db.get(Source, source_id)
        assert source.latest_snapshot_id is not None
        assert db.scalar(select(SyncJob).where(SyncJob.status == "failed")) is None
        assert len(db.scalars(select(SourceSnapshot)).all()) == 2


def test_failed_sync_preserves_old_snapshot(client, session_factory, monkeypatch):
    source_id = client.post(
        "/api/sources", json={"url": "https://docs.crewai.com/en/introduction"}
    ).json()["id"]
    monkeypatch.setattr("techledger.service.fetch_source", lambda _: fake_result(b"valid"))
    client.post(f"/api/sources/{source_id}/sync")
    with session_factory() as db:
        process_one_job(db)
        old_snapshot = db.get(Source, source_id).latest_snapshot_id

    def fail(_):
        raise SourceError("source_unavailable", "暂时无法访问")

    monkeypatch.setattr("techledger.service.fetch_source", fail)
    job_id = client.post(f"/api/sources/{source_id}/sync").json()["id"]
    with session_factory() as db:
        job = process_one_job(db)
        assert job.status == "failed"
        assert job.error_code == "source_unavailable"
        assert db.get(Source, source_id).latest_snapshot_id == old_snapshot
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "failed"


def test_api_reports_validation_and_missing_resources(client):
    assert client.post("/api/sources", json={"url": "https://example.com"}).status_code == 422
    assert client.get("/api/sources/missing").status_code == 404
    assert client.get("/api/jobs/missing").status_code == 404
    assert client.get("/health").json() == {"status": "ok"}
