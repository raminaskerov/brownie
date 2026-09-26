import json

import pytest

from benchmarks.evaluate_foraging import evaluate_manifest


def test_foraging_evaluation_requires_judgment_for_each_visible_candidate(tmp_path):
    trace = tmp_path / "run.jsonl"
    events = [
        {"event": "model_request", "elapsed_ms": 50, "data": {}},
        {"event": "search_result_selection", "elapsed_ms": 200, "data": {
            "query": "official report",
            "provider": "llm",
            "chosen": {"url": "https://example.test/official"},
            "candidates": [
                {"url": "https://example.test/official"},
                {"url": "https://example.test/other"},
            ],
        }},
    ]
    trace.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
    manifest = tmp_path / "cases.json"
    manifest.write_text(json.dumps({"cases": [{
        "id": "report", "trace": "run.jsonl",
        "judgments": {"https://example.test/official": 2},
    }]}), encoding="utf-8")

    with pytest.raises(ValueError, match="judgments missing"):
        evaluate_manifest(manifest)

    manifest.write_text(json.dumps({"cases": [{
        "id": "report", "trace": "run.jsonl",
        "judgments": {
            "https://example.test/official": 2,
            "https://example.test/other": 0,
        },
    }]}), encoding="utf-8")
    result = evaluate_manifest(manifest)
    assert result["selected_best_visible"] == 1
    assert result["model_requests"] == 1
    assert result["cases"][0]["elapsed_to_selection_ms"] == 200


def test_foraging_evaluation_rejects_empty_candidate_set(tmp_path):
    trace = tmp_path / "run.jsonl"
    trace.write_text(json.dumps({
        "event": "search_result_selection",
        "data": {"chosen": {"url": "https://example.test/official"}, "candidates": []},
    }) + "\n", encoding="utf-8")
    manifest = tmp_path / "cases.json"
    manifest.write_text(json.dumps({"cases": [{
        "id": "empty", "trace": "run.jsonl", "judgments": {},
    }]}), encoding="utf-8")

    with pytest.raises(ValueError, match="no visible candidates"):
        evaluate_manifest(manifest)
