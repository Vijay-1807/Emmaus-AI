from app.evaluation.metrics import mrr, ndcg_at_k, recall_at_k
from app.rag.retriever import RetrievedChunk, rrf_fuse


def make_chunk(chunk_id: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id="d1",
        document_name="doc.pdf",
        source_type="document",
        content="content of " + chunk_id,
    )


def test_rrf_prefers_chunks_in_both_lists():
    vector = [make_chunk("a"), make_chunk("b"), make_chunk("c")]
    lexical = [make_chunk("b"), make_chunk("a"), make_chunk("d")]
    fused = rrf_fuse(vector, lexical, k=60)
    assert fused[0].chunk_id in ("a", "b")
    assert fused[-1].chunk_id in ("c", "d")
    assert fused[0].fused_score > fused[-1].fused_score


def test_rrf_single_list_fallback():
    vector = [make_chunk("a"), make_chunk("b")]
    fused = rrf_fuse(vector, [], k=60)
    assert [c.chunk_id for c in fused] == ["a", "b"]


def test_recall_at_k():
    retrieved = ["a", "b", "c", "d", "e", "f"]
    assert recall_at_k(retrieved, ["a", "c"], k=5) == 1.0
    assert recall_at_k(retrieved, ["a", "z"], k=5) == 0.5
    assert recall_at_k(retrieved, [], k=5) == 0.0


def test_mrr():
    assert mrr(["a", "b"], ["b"]) == 0.5
    assert mrr(["a", "b"], ["a"]) == 1.0
    assert mrr(["a", "b"], ["z"]) == 0.0


def test_ndcg():
    assert ndcg_at_k(["a", "b", "c"], ["a"], k=5) == 1.0
    assert 0 < ndcg_at_k(["a", "b"], ["b"], k=5) < 1
    assert ndcg_at_k(["a"], [], k=5) == 0.0
