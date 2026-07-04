"""Tests for rag/engine.py: RRF fusion and hybrid search helpers."""

from cognits.rag.engine import rrf_fuse


def test_rrf_empty_inputs():
    result = rrf_fuse([], [], max_results=5)
    assert result == []


def test_rrf_dense_only():
    dense = [
        {"id": "c1", "text": "hello"},
        {"id": "c2", "text": "world"},
    ]
    result = rrf_fuse(dense, [], max_results=5)
    assert len(result) == 2
    assert result[0]["id"] == "c1"


def test_rrf_sparse_only():
    sparse = [
        {"id": "c3", "text": "bonjour"},
        {"id": "c4", "text": "monde"},
    ]
    result = rrf_fuse([], sparse, max_results=5)
    assert len(result) == 2
    assert result[0]["id"] == "c3"


def test_rrf_combines_scores():
    dense = [
        {"id": "a", "text": "first"},
        {"id": "b", "text": "second"},
    ]
    sparse = [
        {"id": "b", "text": "second sparse"},
        {"id": "a", "text": "first sparse"},
    ]
    result = rrf_fuse(dense, sparse, max_results=5)
    assert len(result) == 2
    # 'a' should rank higher (rank 0 in dense, rank 1 in sparse)
    assert result[0]["id"] == "a"


def test_rrf_respects_max_results():
    dense = [{"id": f"c{i}", "text": f"doc{i}"} for i in range(20)]
    result = rrf_fuse(dense, [], max_results=5)
    assert len(result) == 5


def test_rrf_overlapping_ranks():
    # Same doc in both lists at different ranks -> boosted score
    dense = [{"id": "x", "text": "xd"}, {"id": "y", "text": "yd"}]
    sparse = [{"id": "y", "text": "ys"}, {"id": "x", "text": "xs"}]
    result = rrf_fuse(dense, sparse, max_results=5)
    assert result[0]["id"] == "x"  # x: rank0 dense + rank1 sparse > y


def test_rrf_preserves_document_data():
    dense = [{"id": "c1", "text": "hello world", "report_id": "r1"}]
    result = rrf_fuse(dense, [], max_results=1)
    assert result[0]["report_id"] == "r1"
