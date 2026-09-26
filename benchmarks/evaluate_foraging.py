"""Score recorded search-result choices against human-labeled visible candidates."""

import argparse
import json
from pathlib import Path


def evaluate_case(case: dict, base_dir: Path) -> dict:
    if not isinstance(case, dict) or set(case) != {"id", "trace", "judgments"}:
        raise ValueError("Each case needs id, trace, and judgments")
    if not isinstance(case["id"], str) or not case["id"].strip():
        raise ValueError("Case id must be non-empty text")
    if not isinstance(case["trace"], str) or not case["trace"].strip():
        raise ValueError("Trace path must be non-empty text")
    judgments = case["judgments"]
    if not isinstance(judgments, dict) or any(
        not isinstance(url, str) or type(score) is not int or score not in {0, 1, 2}
        for url, score in judgments.items()
    ):
        raise ValueError("Judgments must map candidate URLs to relevance 0, 1, or 2")
    trace_path = (base_dir / case["trace"]).resolve()
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    selections = [event for event in events if event.get("event") == "search_result_selection"]
    if len(selections) != 1:
        raise ValueError(f"{case['id']}: expected one recorded result choice, found {len(selections)}")
    event = selections[0]
    choice = event["data"]
    candidates = choice["candidates"]
    chosen_url = choice["chosen"]["url"]
    candidate_urls = {item["url"] for item in candidates}
    if not candidate_urls:
        raise ValueError(f"{case['id']}: selection has no visible candidates")
    missing = sorted(candidate_urls - set(judgments))
    if missing:
        raise ValueError(f"{case['id']}: judgments missing visible candidates: {', '.join(missing)}")
    if chosen_url not in candidate_urls:
        raise ValueError(f"{case['id']}: chosen URL was not in the observed candidate list")
    best = max(judgments[url] for url in candidate_urls)
    selected = judgments[chosen_url]
    return {
        "id": case["id"],
        "trace": str(trace_path),
        "query": choice.get("query"),
        "provider": choice.get("provider"),
        "visible_candidates": len(candidates),
        "chosen_url": chosen_url,
        "selected_relevance": selected,
        "best_visible_relevance": best,
        "selected_best_visible": selected == best,
        "elapsed_to_selection_ms": event.get("elapsed_ms"),
        "model_requests": sum(item.get("event") == "model_request" for item in events),
        "model_attempts": sum(item.get("event") == "model_attempt" for item in events),
    }


def evaluate_manifest(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != {"cases"} or not isinstance(raw["cases"], list):
        raise ValueError("Manifest must contain one cases array")
    if not raw["cases"]:
        raise ValueError("Manifest must contain at least one case")
    cases = [evaluate_case(case, path.parent) for case in raw["cases"]]
    return {
        "cases": cases,
        "selected_best_visible": sum(case["selected_best_visible"] for case in cases),
        "total": len(cases),
        "model_requests": sum(case["model_requests"] for case in cases),
        "model_attempts": sum(case["model_attempts"] for case in cases),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(evaluate_manifest(arguments.manifest.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
