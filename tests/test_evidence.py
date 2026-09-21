import pytest

from brownie_agent.evidence import evidence_candidates


def test_evidence_candidates_returns_exact_ranked_source_lines():
    material = """Navigation
The pathlib module provides object-oriented filesystem paths.
Path is usually the correct concrete filesystem path class.
This unrelated sentence describes network sockets and ports.
"""

    result = evidence_candidates("Find Python pathlib filesystem path documentation", material)

    assert result["method"] == "local_goal_term_overlap"
    assert result["passages"] == [
        "The pathlib module provides object-oriented filesystem paths.\n"
        "Path is usually the correct concrete filesystem path class.",
    ]
    assert result["matched_terms"] == ["filesystem", "path", "pathlib"]
    assert result["relevance"] is None
    assert result["sufficient"] is None
    assert all(passage in material for passage in result["passages"])


def test_evidence_candidates_does_not_invent_relevance_without_matching_material():
    result = evidence_candidates("Find pathlib documentation", "A sufficiently long unrelated weather report.")

    assert result["passages"] == []
    assert result["matched_terms"] == []
    assert result["relevance"] is None
    assert result["sufficient"] is None


def test_evidence_candidate_limit_is_bounded():
    with pytest.raises(ValueError, match="limit"):
        evidence_candidates("goal", "material", limit=6)
