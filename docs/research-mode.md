# Bounded research mode

Research mode is a small multi-source controller above Brownie's existing
one-source web search. It is intended for questions that benefit from comparing
a few sources. It is not an unrestricted autonomous browser.

## Run research

    uv run brownie --managed-cdp --research --steerer llm \
      --max-sources 3 \
      --goal "Compare the official eligibility rules and application deadlines"

`--max-sources` accepts one through five. Research requires a Gemini-compatible
model for planning. Browser action steering can use either Jev or the LLM. With
Jev steering, both the TypeSafe and Gemini keys are required.

The local control room exposes the same mode and source budget:

    uv run python -m brownie_agent.ui

When the planner needs a material constraint, the control room shows its
question and a reply box. Brownie continues in the same process, browser
session, and research state after the answer. Terminal users can enable the same
behavior with `--research-dialogue`.

The control room also projects the latest planner decision, explanation, open
evidence needs, remaining source slots, and collected source links. Exact source
excerpts, model traffic, and dialogue remain in the separate private inspector.

## Authority boundary

The research planner receives only a compact JSON state containing the goal,
budget, open evidence needs, prior queries, source URLs, titles, and bounded
source excerpts. It can return exactly one of four advisory decisions:

- **SEARCH_WEB:** provide one concise query for the next evidence need;
- **ANSWER:** synthesize only from supplied excerpts and cite source IDs;
- **ASK_USER:** request a user choice that materially changes the research;
- **STOP:** end when another search will not resolve the evidence gap.

The planner also receives at most 30 short decisions explicitly saved by the
user in the control room. Each has a timestamp and optional archived run ID.
These are prior user context, not source evidence, citations, or browser authority.
The planner cannot return selectors, browser actions, JavaScript, credentials,
or new task authority. `SEARCH_WEB` is executed by the existing bounded search
runner, which starts at Brownie's code-owned search page, validates one action
at a time against fresh observations, opens one source, reads it, and stops.

## Controller guards

The code-owned controller:

- requires one to five as the source budget;
- requires two collected source URLs before an answer, except when the budget is one;
- rejects duplicate queries and duplicate source URLs;
- validates every cited source number against collected sources and requires the
  answer's `[S#]` markers to match the citation list;
- limits evidence needs, query length, answer length, excerpts, and planning cycles;
- returns structured `answered`, `needs_user`, or `stopped` status;
- permits at most three clarification-and-answer turns in one run;
- never retries a browser mutation.

Source IDs prove which collected excerpts were made available to the answering
model. They do not by themselves prove that a claim is true, that sources are
independent, or that the model interpreted them correctly. Exact traces should
be used to audit important outputs.

## Current limitations

Research mode currently searches the public web through the same DuckDuckGo
path for each source. It does not follow references inside a source, inspect a
PDF with a specialized parser, score publisher credibility, identify
contradictions mechanically, or preserve a run for later resumption.

The dialogue is run-scoped and is not persisted for later restart or recovery.
Accepted decisions persist across runs, but source claims and planner proposals
are not automatically turned into memory. An archived trace remains available
for review; saving a decision requires an explicit user action.
Access barriers, login, challenges, source-search failure, duplicate results,
and exhausted budgets stop explicitly rather than broadening authority.
