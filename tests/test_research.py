import json

import pytest

from brownie_agent.research import ResearchSource, ResearchState, plan_research, run_research


def proposal(decision, *, query=None, question=None, answer=None, citations=None):
    return {
        "decision": decision,
        "reason": f"Reason for {decision}",
        "evidence_needs": ["Find independent evidence"],
        "search_query": query,
        "user_question": question,
        "answer": answer,
        "citations": citations or [],
        "model": "fixture",
        "latency_ms": 1,
        "usage": {},
        "model_attempts": [],
    }


def search_result(url, title, passage):
    return {
        "status": "source_read",
        "stop_reason": "one_source_read",
        "source": {
            "url": url,
            "title": title,
            "material": passage,
            "evidence_candidates": {"passages": [passage]},
        },
    }


def test_research_collects_two_sources_then_returns_cited_answer():
    plans = iter([
        proposal("SEARCH_WEB", query="official solar capacity report"),
        proposal("SEARCH_WEB", query="independent solar capacity statistics"),
        proposal(
            "ANSWER",
            answer="Capacity reached 100 GW [S1], independently reported by the statistics office [S2].",
            citations=[1, 2],
        ),
    ])
    searches = iter([
        search_result("https://institute.test/report", "Institute report", "Capacity reached 100 GW."),
        search_result("https://stats.test/data", "Statistics office", "The published total was 100 GW."),
    ])
    calls = []

    def search(_browser, focus, **options):
        calls.append((focus, options))
        return next(searches)

    result = run_research(
        object(),
        "Find the reported solar capacity",
        provider="llm",
        planner=lambda _state: next(plans),
        search=search,
    )

    assert result["status"] == "answered"
    assert result["stop_reason"] == "answer_grounded_in_sources"
    assert [source["id"] for source in result["sources"]] == ["S1", "S2"]
    assert [source["id"] for source in result["cited_sources"]] == ["S1", "S2"]
    assert "[S1]" in result["answer"]
    assert len(calls) == 2
    assert all(call[1]["provider"] == "llm" for call in calls)
    assert calls[0][1]["write_text"]({})[0] == "official solar capacity report"


def test_research_rejects_premature_answer_and_replans():
    seen_feedback = []

    def planner(state):
        seen_feedback.append(state.controller_feedback)
        if not state.sources:
            return proposal("SEARCH_WEB", query="first source")
        if not state.controller_feedback:
            return proposal("ANSWER", answer="Too early [S1].", citations=[1])
        return proposal("SEARCH_WEB", query="second source")

    searches = iter([
        search_result("https://one.test/", "One", "First evidence"),
        search_result("https://two.test/", "Two", "Second evidence"),
    ])
    result = run_research(
        object(),
        "Compare evidence",
        planner=planner,
        search=lambda *_args, **_kwargs: next(searches),
        max_sources=2,
    )

    assert "ANSWER rejected" in seen_feedback[2]
    assert result["stop_reason"] == "source_budget"
    assert len(result["sources"]) == 2


def test_research_can_return_a_user_question_without_browser_search():
    result = run_research(
        object(),
        "Research the best option",
        planner=lambda _state: proposal(
            "ASK_USER",
            question="Which country and time period should I use?",
        ),
        search=lambda *_args, **_kwargs: pytest.fail("Search must wait for the user"),
    )

    assert result["status"] == "needs_user"
    assert result["question"] == "Which country and time period should I use?"
    assert result["sources"] == []


def test_research_dialogue_resumes_same_state_and_browser_run():
    planner_states = []

    def planner(state):
        planner_states.append(state.planner_state())
        if not state.dialogue:
            return proposal("ASK_USER", question="Which year should I use?")
        if not state.sources:
            return proposal("SEARCH_WEB", query="official report 2025")
        return proposal("ANSWER", answer="The 2025 report states the result [S1].", citations=[1])

    result = run_research(
        object(),
        "Find the result",
        max_sources=1,
        planner=planner,
        ask_user=lambda question: "2025" if question == "Which year should I use?" else "",
        search=lambda *_args, **_kwargs: search_result(
            "https://official.test/report", "Official report", "The 2025 result was published.",
        ),
    )

    assert result["status"] == "answered"
    assert result["dialogue"] == [{"question": "Which year should I use?", "answer": "2025"}]
    assert planner_states[1]["dialogue"] == result["dialogue"]
    assert [source["id"] for source in result["sources"]] == ["S1"]


def test_research_dialogue_has_a_code_owned_turn_budget():
    answers = []

    result = run_research(
        object(),
        "Clarify forever",
        planner=lambda state: proposal("ASK_USER", question=f"Question {len(state.dialogue) + 1}?"),
        ask_user=lambda question: answers.append(question) or "answer",
    )

    assert result["stop_reason"] == "user_turn_budget"
    assert len(answers) == 3
    assert len(result["dialogue"]) == 3


def test_plan_research_uses_strict_state_and_validates_citations(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "private")
    monkeypatch.setenv("RESEARCH_MODEL", "research-model")
    state = ResearchState(goal="Find evidence", max_sources=3)
    captured = {}

    def post(_url, key, body):
        captured.update(key=key, body=body)
        content = {
            "decision": "SEARCH_WEB",
            "reason": "Need an official source",
            "evidence_needs": ["Official measurement"],
            "search_query": "official measurement report",
            "user_question": None,
            "answer": None,
            "citations": [],
        }
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(content)}}]}

    result = plan_research(state, post=post)

    assert captured["key"] == "private"
    assert captured["body"]["model"] == "research-model"
    assert json.loads(captured["body"]["messages"][1]["content"])["sources"] == []
    assert result["decision"] == "SEARCH_WEB"


def test_plan_research_rejects_out_of_range_citation(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "private")

    def post(_url, _key, _body):
        content = {
            "decision": "ANSWER",
            "reason": "Done",
            "evidence_needs": [],
            "search_query": None,
            "user_question": None,
            "answer": "Unsupported [S1].",
            "citations": [1],
        }
        return {"choices": [{"message": {"content": json.dumps(content)}}]}

    with pytest.raises(ValueError, match="citations"):
        plan_research(ResearchState(goal="Find evidence", max_sources=3), post=post)


def test_research_rejects_answer_when_markers_and_citation_list_disagree(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "private")
    state = ResearchState(goal="Compare", max_sources=2)
    state.sources.extend([
        ResearchSource("S1", "https://one.test/", "One", ("First",)),
        ResearchSource("S2", "https://two.test/", "Two", ("Second",)),
    ])

    with pytest.raises(ValueError, match="markers"):
        plan_research(state, post=lambda *_args, **_kwargs: {
            "choices": [{"message": {"content": json.dumps({
                "decision": "ANSWER",
                "reason": "Done",
                "evidence_needs": [],
                "search_query": None,
                "user_question": None,
                "answer": "Only the first source is marked [S1].",
                "citations": [1, 2],
            })}}],
        })


def test_research_rejects_fragment_variant_of_collected_source():
    plans = iter([
        proposal("SEARCH_WEB", query="first source"),
        proposal("SEARCH_WEB", query="second source"),
    ])
    searches = iter([
        search_result("https://example.test/report#top", "Report", "First excerpt"),
        search_result("https://example.test/report#details", "Report details", "Second excerpt"),
    ])

    result = run_research(
        object(),
        "Compare",
        planner=lambda _state: next(plans),
        search=lambda *_args, **_kwargs: next(searches),
    )

    assert result["stop_reason"] == "duplicate_source"
    assert len(result["sources"]) == 1


def test_user_accepted_memory_is_planning_context_but_not_source_evidence():
    saved = [{
        "id": "0123456789abcdef",
        "created_at": "2026-09-26T09:00:00+00:00",
        "decision": "Prefer official documentation for this topic.",
        "source_run_id": None,
    }]
    seen = []

    def planner(state):
        seen.append(state.planner_state())
        return proposal("ANSWER", answer="Memory alone proves it [S1].", citations=[1]) if state.sources else \
            proposal("STOP")

    result = run_research(
        object(),
        "Find official documentation",
        accepted_decisions=saved,
        planner=planner,
        search=lambda *_args, **_kwargs: pytest.fail("No search should run"),
    )

    assert seen[0]["accepted_decisions"] == saved
    assert seen[0]["sources"] == []
    assert result["status"] == "stopped"
    assert result["memory_decision_ids"] == ["0123456789abcdef"]


def test_research_rejects_unbounded_or_malformed_accepted_memory_before_search():
    with pytest.raises(ValueError, match="invalid size"):
        run_research(
            object(), "Find evidence", accepted_decisions=[{}] * 31,
            planner=lambda _state: pytest.fail("Planner must not run"),
        )
    with pytest.raises(ValueError, match="invalid record"):
        run_research(
            object(), "Find evidence", accepted_decisions=[{"decision": "model proposal"}],
            planner=lambda _state: pytest.fail("Planner must not run"),
        )
