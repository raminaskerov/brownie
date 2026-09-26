# Search-result choice evaluation

Brownie now records a search_result_selection event after a validated click on
an observed external result. It contains the chosen URL and all visible
external link candidates from that observation. It is factual instrumentation,
not an automatic ranking or a claim that the opened source is relevant.

For each fixed task, save the private trace and review every candidate. Create
a JSON manifest with one relevance judgment per visible candidate URL:

    {
      "cases": [
        {
          "id": "official-documentation",
          "trace": "../artifacts/runs/RUN_ID.jsonl",
          "judgments": {
            "https://example.test/official": 2,
            "https://example.test/overview": 1,
            "https://example.test/irrelevant": 0
          }
        }
      ]
    }

Scores mean 0 irrelevant, 1 partly useful, and 2 directly useful for the task.
A missing candidate judgment fails evaluation. Run:

    .venv/bin/python benchmarks/evaluate_foraging.py benchmarks/foraging-cases.json

The result reports whether Brownie chose the best visible candidate, elapsed
time to that choice, and model request/attempt counts. Use the same search-result
screens and human judgments when comparing another agent. Measure actual
source relevance and task completion separately; a good-looking result link
can still lead to weak evidence. Do not tune a scent score from a single run.

## First local run

On 2026-09-26, three live read-only searches (Python pathlib, Playwright
Python browser installation, Erasmus Mundus Joint Masters eligibility)
each selected a human-rated best visible official page. Brownie used Jev
for result steering and made 10 total model requests across the three runs,
including Gemini query generation and decisions repeated after changing
search observations. Gemini steering, asked to predict on the exact saved
result observations without executing, chose the same three official URLs
in three requests. Private traces and the judgment manifest are under
artifacts/foraging-*.jsonl and artifacts/foraging-judgments.json. This is a
three-task check, not a success-rate estimate or a cost comparison with
agent-browser or Browser Use.
