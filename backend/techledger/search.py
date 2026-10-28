"""Reproducible BM25 and local character n-gram TF-IDF retrieval baselines."""

import math
import re
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from techledger.models import Chunk, IndexedDocument, Source, SourceSnapshot

TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")


def tokenize(value: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(value)]


def _grams(value: str) -> Counter[str]:
    normalized = re.sub(r"\s+", " ", value.lower()).strip()
    return Counter(normalized[index:index + 3] for index in range(max(0, len(normalized) - 2)))


def _focused_snippet(content: str, terms: list[str], width: int = 220) -> str:
    if len(content) <= width:
        return content
    lowered = content.lower()
    meaningful = [term for term in dict.fromkeys(terms) if len(term) >= 2]
    positions = [match.start() for term in meaningful for match in re.finditer(re.escape(term), lowered)]
    if not positions:
        return content[:width]
    best_start = 0
    best_score = -1
    for position in positions:
        start = max(0, min(position - 35, len(content) - width))
        window = lowered[start:start + width]
        score = sum(term in window for term in meaningful)
        if score > best_score:
            best_score, best_start = score, start
    return content[best_start:best_start + width]


def search_chunks(db: Session, query: str, limit: int = 5, mode: str = "bm25", source_id: str | None = None) -> list[dict]:
    if mode not in {"bm25", "vector", "hybrid"}:
        raise ValueError("Unknown retrieval mode")
    terms = tokenize(query)
    if not terms or len(query.strip()) < 3 and mode == "vector":
        return []
    statement = (select(Chunk, SourceSnapshot, Source)
        .join(SourceSnapshot, Chunk.snapshot_id == SourceSnapshot.id)
        .join(Source, SourceSnapshot.source_id == Source.id)
        .where(Source.review_status == "approved",
               Source.storage_policy == "index_local",
               Source.latest_snapshot_id == SourceSnapshot.id))
    if source_id:
        statement = statement.where(Source.id == source_id)
    rows = db.execute(statement).all()
    if not rows:
        return []

    corpus = [tokenize(chunk.text_content) for chunk, _, _ in rows]
    lengths = [len(tokens) for tokens in corpus]
    average_length = sum(lengths) / len(lengths) or 1
    document_frequency = Counter(token for tokens in corpus for token in set(tokens))
    bm25_scores: dict[str, float] = {}
    for (chunk, _, _), tokens, length in zip(rows, corpus, lengths):
        counts = Counter(tokens)
        score = 0.0
        for term in set(terms):
            frequency = counts[term]
            if not frequency:
                continue
            df = document_frequency[term]
            idf = math.log(1 + (len(rows) - df + 0.5) / (df + 0.5))
            score += idf * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * length / average_length))
        if score:
            bm25_scores[chunk.id] = score

    query_grams = _grams(query)
    doc_grams = [_grams(chunk.text_content) for chunk, _, _ in rows]
    gram_df = Counter(gram for counts in doc_grams for gram in counts)
    def weight(gram: str) -> float:
        return math.log(1 + (len(rows) + 1) / (gram_df[gram] + 1))
    query_norm = math.sqrt(sum((count * weight(gram)) ** 2 for gram, count in query_grams.items()))
    vector_scores: dict[str, float] = {}
    if query_norm:
        for (chunk, _, _), counts in zip(rows, doc_grams):
            dot = sum(count * query_grams[gram] * weight(gram) ** 2 for gram, count in counts.items() if gram in query_grams)
            doc_norm = math.sqrt(sum((count * weight(gram)) ** 2 for gram, count in counts.items()))
            if dot and doc_norm:
                vector_scores[chunk.id] = dot / (query_norm * doc_norm)

    tie_break = {chunk.id: (source.url, chunk.ordinal) for chunk, _, source in rows}
    bm25_rank = {chunk_id: index for index, chunk_id in enumerate(sorted(bm25_scores, key=lambda key: (-bm25_scores[key], tie_break[key])), 1)}
    vector_rank = {chunk_id: index for index, chunk_id in enumerate(sorted(vector_scores, key=lambda key: (-vector_scores[key], tie_break[key])), 1)}
    if mode == "bm25":
        scores = bm25_scores
    elif mode == "vector":
        scores = vector_scores
    else:
        scores = {chunk_id: (1 / (60 + bm25_rank[chunk_id]) if chunk_id in bm25_rank else 0) +
                  (1 / (60 + vector_rank[chunk_id]) if chunk_id in vector_rank else 0)
                  for chunk_id in bm25_rank.keys() | vector_rank.keys()}
    scored = [(scores[chunk.id], chunk, snapshot, source) for chunk, snapshot, source in rows if chunk.id in scores]
    scored.sort(key=lambda item: (-item[0], item[3].url, item[1].ordinal))
    return [
        {
            "chunk_id": chunk.id,
            "source_id": source.id,
            "source_url": source.url,
            "snapshot_id": snapshot.id,
            "snapshot_sha256": snapshot.content_sha256,
            "title": snapshot.title,
            "start_char": chunk.start_char,
            "end_char": chunk.end_char,
            "snippet": _focused_snippet(chunk.text_content, terms),
            "score": round(score, 6),
            "mode": mode,
        }
        for score, chunk, snapshot, source in scored[:limit]
    ]


def get_citation(db: Session, chunk_id: str) -> dict | None:
    row = db.execute(
        select(Chunk, IndexedDocument, SourceSnapshot, Source)
        .join(IndexedDocument, Chunk.snapshot_id == IndexedDocument.snapshot_id)
        .join(SourceSnapshot, Chunk.snapshot_id == SourceSnapshot.id)
        .join(Source, SourceSnapshot.source_id == Source.id)
        .where(Chunk.id == chunk_id, Source.review_status == "approved",
               Source.storage_policy == "index_local")
    ).one_or_none()
    if row is None:
        return None
    chunk, document, snapshot, source = row
    if document.text_content[chunk.start_char:chunk.end_char] != chunk.text_content:
        return None
    return {
        "chunk_id": chunk.id,
        "source_url": source.url,
        "snapshot_id": snapshot.id,
        "snapshot_sha256": snapshot.content_sha256,
        "title": snapshot.title,
        "start_char": chunk.start_char,
        "end_char": chunk.end_char,
        "text": chunk.text_content,
    }
