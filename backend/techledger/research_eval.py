"""Equal-budget evidence planning comparison; no model calls are made."""

from sqlalchemy.orm import Session

from techledger.config import RESEARCH_MAX_EVIDENCE
from techledger.evaluation import validate_frozen_sources
from techledger.research import _collect_evidence
from techledger.search import get_citation, search_chunks


def _legacy_collect(db: Session, question: str, candidates: list[str]) -> tuple[list[dict], list[str]]:
    evidence = []
    seen = set()
    queries = []
    for query, limit in [(candidate, 2) for candidate in candidates[:3]] + [(question, 5)]:
        queries.append(query)
        for hit in search_chunks(db, query, limit, "bm25"):
            if hit["chunk_id"] not in seen:
                seen.add(hit["chunk_id"])
                evidence.append(hit)
    return evidence[:RESEARCH_MAX_EVIDENCE], queries


def compare_planners(db: Session, dataset: dict) -> dict:
    if dataset.get("status") != "frozen" or not dataset.get("frozen_sources"):
        raise ValueError("Planner comparison requires a frozen dataset")
    validate_frozen_sources(db, dataset)
    cases = dataset["cases"]
    if not cases or any(not case.get("expected_evidence") for case in cases):
        raise ValueError("Every planner case needs expected_evidence")
    reports = []
    for case in cases:
        candidates = case.get("candidates", [])
        if not isinstance(candidates, list) or not candidates or len(candidates) > 3:
            raise ValueError("Planner case needs 1-3 candidates")
        expectations = case["expected_evidence"]
        if any(not isinstance(item, dict) or not item.get("source_url") or not item.get("phrase") for item in expectations):
            raise ValueError("Expected evidence needs source_url and phrase")
        strategies = {}
        for name, collector in (
            ("legacy", lambda: _legacy_collect(db, case["question"], candidates)),
            ("capability", lambda: _collect_evidence(db, case["question"], case.get("constraints", ""), candidates)),
        ):
            hits, queries = collector()
            citations = [get_citation(db, hit["chunk_id"]) for hit in hits]
            checks = []
            for expected in expectations:
                phrase = expected["phrase"].lower()
                matching = [(hit, citation) for hit, citation in zip(hits, citations)
                            if citation and hit["source_url"] == expected["source_url"]]
                checks.append({"source_url": expected["source_url"], "phrase": expected["phrase"],
                               "in_chunk": any(phrase in citation["text"].lower() for _, citation in matching),
                               "in_model_input": any(phrase in hit["snippet"][:220].lower() for hit, _ in matching)})
            strategies[name] = {"evidence_count": len(hits), "model_input_chars": sum(len(hit["snippet"][:220]) for hit in hits),
                                "query_count": len(queries), "chunk_coverage": sum(item["in_chunk"] for item in checks) / len(checks),
                                "input_coverage": sum(item["in_model_input"] for item in checks) / len(checks),
                                "checks": checks,
                                "hits": [{"chunk_id": hit["chunk_id"], "source_url": hit["source_url"],
                                          "snapshot_sha256": hit["snapshot_sha256"]} for hit in hits]}
        reports.append({"id": case["id"], "strategies": strategies})
    def mean(strategy: str, metric: str) -> float:
        return round(sum(case["strategies"][strategy][metric] for case in reports) / len(reports), 4)
    return {"dataset_status": dataset.get("status"), "case_count": len(reports),
            "legacy": {"mean_chunk_coverage": mean("legacy", "chunk_coverage"),
                       "mean_input_coverage": mean("legacy", "input_coverage"),
                       "mean_model_input_chars": mean("legacy", "model_input_chars")},
            "capability": {"mean_chunk_coverage": mean("capability", "chunk_coverage"),
                           "mean_input_coverage": mean("capability", "input_coverage"),
                           "mean_model_input_chars": mean("capability", "model_input_chars")},
            "cases": reports}
