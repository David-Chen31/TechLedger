import pytest

from techledger.evaluation import freeze_dataset
from techledger.models import Chunk, IndexedDocument, Source, SourceSnapshot
from techledger.research_eval import compare_planners


def test_planner_comparison_is_frozen_and_checks_model_input(session_factory):
    url = "https://docs.langchain.com/oss/python/langgraph/overview"
    phrase = "persist through failures"
    content = "LangGraph durable execution can " + phrase + "."
    with session_factory() as db:
        source = Source(url=url, host="docs.langchain.com", review_status="approved", storage_policy="index_local")
        db.add(source)
        db.flush()
        snapshot = SourceSnapshot(source_id=source.id, content_sha256="b" * 64,
                                  title="LangGraph", excerpt="", content_type="text/plain", byte_size=len(content))
        db.add(snapshot)
        db.flush()
        source.latest_snapshot_id = snapshot.id
        db.add(IndexedDocument(snapshot_id=snapshot.id, text_content=content))
        db.add(Chunk(snapshot_id=snapshot.id, ordinal=0, start_char=0,
                     end_char=len(content), text_content=content))
        db.commit()
        dataset = {"version": 1, "cases": [{"id": "one", "question": "运行中断后可以恢复吗？",
                    "constraints": "必须持久化", "candidates": ["LangGraph"],
                    "expected_source_urls": [url],
                    "expected_evidence": [{"source_url": url, "phrase": phrase}]}]}
        with pytest.raises(ValueError, match="frozen"):
            compare_planners(db, dataset)
        report = compare_planners(db, freeze_dataset(db, dataset))
    assert report["case_count"] == 1
    assert report["capability"]["mean_chunk_coverage"] == 1
    assert report["capability"]["mean_input_coverage"] == 1
    assert report["legacy"]["mean_chunk_coverage"] == 1
