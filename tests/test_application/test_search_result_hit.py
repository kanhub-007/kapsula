"""Tests for the SearchResultHit DTO (H4).

Black-box: the DTO must faithfully round-trip the legacy dict shape and
tolerate missing/extra keys at the dict boundary. This is the contract
that lets the search pipeline be typed end-to-end.
"""

from kapsula.core.application.dto.search_result_hit import SearchResultHit


class TestSearchResultHitRoundTrip:
    def test_from_dict_picks_up_all_known_fields(self):
        data = {
            "index": 7,
            "content": "body",
            "score": 0.9,
            "dense_score": 0.8,
            "sparse_score": 0.1,
            "rerank_score": 0.95,
            "expanded_content": "expanded body",
            "context_mode": "deep",
            "parent_hash": "abc",
            "contributing_chunks": [1, 2],
            "contributing_scores": [0.9, 0.8],
            "collection_id": 3,
            "collection_name": "Coll",
            "document_id": 5,
            "document_filename": "doc.md",
            "sub_document_id": 9,
            "sub_document_key": "ch1",
            "subdocument_route_confidence": 0.7,
            "collection_route_confidence": 0.6,
            "metadata_route_confidence": 0.55,
            "unknown_future_field": "ignored",
        }

        hit = SearchResultHit.from_dict(data)

        assert hit.index == 7
        assert hit.content == "body"
        assert hit.score == 0.9
        assert hit.rerank_score == 0.95
        assert hit.expanded_content == "expanded body"
        assert hit.parent_hash == "abc"
        assert hit.contributing_chunks == [1, 2]
        assert hit.collection_name == "Coll"
        assert hit.sub_document_key == "ch1"
        assert hit.subdocument_route_confidence == 0.7

    def test_from_dict_ignores_none_optionals(self):
        """None optional values must not override dataclass defaults."""
        hit = SearchResultHit.from_dict(
            {"index": 0, "content": "c", "rerank_score": None, "parent_hash": None}
        )
        assert hit.rerank_score is None
        assert hit.parent_hash is None

    def test_as_dict_is_sparse(self):
        """as_dict must omit None optionals (no wave of nulls in API output)."""
        hit = SearchResultHit(index=1, content="c", score=0.5)
        d = hit.as_dict()
        assert d["index"] == 1
        assert d["content"] == "c"
        assert d["score"] == 0.5
        # Optional fields absent when None.
        assert "rerank_score" not in d
        assert "expanded_content" not in d
        assert "collection_name" not in d

    def test_as_dict_includes_populated_optionals(self):
        hit = SearchResultHit(
            index=1, content="c", rerank_score=0.9, collection_name="X"
        )
        d = hit.as_dict()
        assert d["rerank_score"] == 0.9
        assert d["collection_name"] == "X"

    def test_from_dicts_maps_a_list(self):
        hits = SearchResultHit.from_dicts(
            [{"index": 1, "content": "a"}, {"index": 2, "content": "b"}]
        )
        assert [h.index for h in hits] == [1, 2]

    def test_round_trip_preserves_shape(self):
        original = {
            "index": 4,
            "content": "x",
            "score": 0.3,
            "dense_score": 0.2,
            "sparse_score": 0.1,
            "document_filename": "d.md",
        }
        round_tripped = SearchResultHit.from_dict(original).as_dict()
        for key, value in original.items():
            assert round_tripped[key] == value
