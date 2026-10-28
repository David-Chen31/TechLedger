"""Replay a frozen, human-labelled question set against the current retrieval index.

Dataset format: {"version": 1, "cases": [{"id": ..., "question": ...,
"expected_source_urls": [...], "expected_terms": [...]}]}.
This evaluates retrieval and citation integrity, not subjective decision quality.
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from techledger.db import SessionLocal
from techledger.models import IndexedDocument, Source, SourceSnapshot
from techledger.search import get_citation, search_chunks


def freeze_dataset(db: Session, dataset: dict) -> dict:
    if dataset.get("version") != 1 or not isinstance(dataset.get("cases"), list):
        raise ValueError("Invalid evaluation dataset")
    urls = {url for case in dataset["cases"] for url in case.get("expected_source_urls", [])}
    frozen = {}
    for url in sorted(urls):
        source = db.scalar(select(Source).where(Source.url == url, Source.review_status == "approved",
                                                Source.storage_policy == "index_local"))
        snapshot = db.get(SourceSnapshot, source.latest_snapshot_id) if source and source.latest_snapshot_id else None
        if snapshot is None or db.get(IndexedDocument, snapshot.id) is None:
            raise ValueError(f"Source is not approved and indexed: {url}")
        document = db.get(IndexedDocument, snapshot.id)
        frozen[url] = {"source_sha256": snapshot.content_sha256,
                       "indexed_text_sha256": hashlib.sha256(document.text_content.encode("utf-8")).hexdigest()}
    return {**dataset, "status": "frozen", "frozen_at": datetime.now(timezone.utc).isoformat(), "frozen_sources": frozen}


def validate_frozen_sources(db: Session, dataset: dict) -> None:
    if dataset.get("version") != 1 or not isinstance(dataset.get("cases"), list):
        raise ValueError("Invalid evaluation dataset")
    for url, expected_hash in dataset.get("frozen_sources", {}).items():
        source = db.scalar(select(Source).where(Source.url == url))
        snapshot = db.get(SourceSnapshot, source.latest_snapshot_id) if source and source.latest_snapshot_id else None
        document = db.get(IndexedDocument, snapshot.id) if snapshot else None
        expected_source_hash = expected_hash.get("source_sha256") if isinstance(expected_hash, dict) else expected_hash
        expected_text_hash = expected_hash.get("indexed_text_sha256") if isinstance(expected_hash, dict) else None
        actual_text_hash = hashlib.sha256(document.text_content.encode("utf-8")).hexdigest() if document else None
        if (snapshot is None or snapshot.content_sha256 != expected_source_hash or source.review_status != "approved"
                or source.storage_policy != "index_local" or document is None or
                (expected_text_hash is not None and actual_text_hash != expected_text_hash)):
            raise ValueError(f"Frozen source changed: {url}")


def replay(db: Session, dataset: dict, limit: int = 5, mode: str = "bm25") -> dict:
    validate_frozen_sources(db, dataset)
    seen_ids: set[str] = set()
    results = []
    for case in dataset["cases"]:
        case_id = case["id"]
        if case_id in seen_ids:
            raise ValueError(f"Duplicate case id: {case_id}")
        seen_ids.add(case_id)
        hits = search_chunks(db, case["question"], limit, mode)
        citations = [get_citation(db, hit["chunk_id"]) for hit in hits]
        valid = [citation for citation in citations if citation is not None]
        expected_urls = set(case.get("expected_source_urls", []))
        expected_terms = [term.lower() for term in case.get("expected_terms", [])]
        retrieved_urls = {hit["source_url"] for hit in hits}
        top_url = hits[0]["source_url"] if hits else None
        combined_text = " ".join(citation["text"] for citation in valid).lower()
        results.append({"id": case_id, "question": case["question"],
                        "hit_count": len(hits), "citation_valid_count": len(valid),
                        "expected_source_recall": len(expected_urls & retrieved_urls) / len(expected_urls) if expected_urls else None,
                        "expected_source_top1": int(top_url in expected_urls) if expected_urls else None,
                        "negative_abstained": int(not hits) if case.get("expected_no_hit") else None,
                        "expected_term_recall": sum(term in combined_text for term in expected_terms) / len(expected_terms) if expected_terms else None,
                        "hits": [{"chunk_id": hit["chunk_id"], "source_url": hit["source_url"],
                                  "snapshot_sha256": hit["snapshot_sha256"], "score": hit["score"],
                                  "mode": hit["mode"]} for hit in hits]})
    def average(key: str) -> float | None:
        values = [row[key] for row in results if row[key] is not None]
        return round(sum(values) / len(values), 4) if values else None
    return {"mode": mode, "frozen": "frozen_sources" in dataset, "case_count": len(results), "source_recall_at_k": average("expected_source_recall"),
            "source_top1_accuracy": average("expected_source_top1"), "negative_abstention_rate": average("negative_abstained"),
            "term_recall_at_k": average("expected_term_recall"),
            "citation_valid_rate": round(sum(row["citation_valid_count"] for row in results) /
                                         sum(row["hit_count"] for row in results), 4) if any(row["hit_count"] for row in results) else None,
            "cases": results}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--mode", choices=["bm25", "vector", "hybrid"], default="bm25")
    parser.add_argument("--freeze-output", type=Path, help="Write a dataset bound to current approved source hashes")
    args = parser.parse_args()
    with SessionLocal() as db:
        dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
        if args.freeze_output:
            result = freeze_dataset(db, dataset)
        else:
            result = replay(db, dataset, args.limit, args.mode)
    output = json.dumps(result, ensure_ascii=False, indent=2)
    destination = args.freeze_output or args.output
    if destination:
        destination.write_text(output, encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
