# Brownie reliability matrix

This file separates repeatable offline regression evidence from dated live smoke
evidence. A successful smoke run is not a claim that Brownie supports an entire
site or task family.

## Repeatable fixture matrix

| Boundary | Fixture or test | Required behavior |
| --- | --- | --- |
| ordinary controls and scrolling | `fixture.html`, `test_observe.py` | expose only visible semantic targets; execute one fresh target; read bounded viewports |
| login | `login_fixture.html`, framed-login test | classify access locally and never expose password values |
| delayed navigation | `delayed_fixture.html` | wait for observable destination content without retrying the click |
| delayed same-page update | `settle_fixture.html` | detect a changed observation without assuming URL navigation |
| popup/new tab | `popup_fixture.html` | adopt the new task page and clean up Brownie-owned pages |
| pagination context | `pagination_fixture.html` | distinguish navigation links and preserve safe destinations |
| visible frame | `perception_fixture.html` | merge semantic text and targets, then execute through the owning frame |
| open shadow root | `perception_fixture.html` | traverse semantic text and targets without exposing a selector |
| sparse accessibility tree | generated browser fixture | add bounded non-executable ARIA structure with editable values and URLs removed |
| deterministic Basic workflow | `test_basic.py` | replay validated semantic steps, enforce origins, and stop on mismatch |
| bounded research and dialogue | `test_research.py`, `test_ui.py` | enforce source and dialogue budgets, validate citations, and resume the same run after a user answer |
| search-result evaluation | `test_search.py`, `test_foraging_benchmark.py` | record only observed candidates after a validated click; require human judgments for every visible candidate |
| accepted cross-run decisions | `test_memory.py`, `test_research.py`, `test_ui.py` | keep user-accepted context separate from source evidence; protect and render private archives |

The full offline suite is the release gate. Each observed live failure should be
reduced to one fixture row before changing prompts or broadening autonomy.

## Live smoke evidence

Environment: Linux, installed Google Chrome, Playwright-owned isolated profiles.
Date: 2026-09-25. These checks made no model calls.

| Site and surface | Result | Evidence observed |
| --- | --- | --- |
| `https://example.com` | pass | title, 357 visible-text characters, and the external IANA link were observed |
| `https://docs.python.org/3/library/pathlib.html` | pass | documentation title, 44 semantic controls, search field, navigation context, and downward scrolling were observed |
| `https://en.wikipedia.org/wiki/Web_browser` | pass | article title, 58 semantic controls, search, contents navigation, and downward scrolling were observed |
| Wikipedia contents panel | pass | a freshly observed `Hide Contents` button was clicked once; the observation fingerprint changed and outcome settling returned ready |

Model-powered follow-up: 2026-09-26.

| Task | Result | Evidence observed |
| --- | --- | --- |
| two-source comparison of official Python pathlib documentation and PEP 428 with LLM steering | external failure | the search form and result page succeeded, then the steering endpoint returned HTTP 503 twice; Brownie executed no result click |
| the identical task with Jev steering | pass | three planner cycles collected PEP 428 and the Python 3.14 pathlib documentation, then returned a citation-validated answer |
| DuckDuckGo result volatility during that Jev run | pass with safe replanning | four actions used exact freshness, two used action-structural freshness, and two genuinely stale decisions were rejected before mutation |

Read-only Sahibinden observation: 2026-09-26. The public homepage returned a
Turkish temporary-access-block page with a support code, no press-and-hold
target, and no useful task controls. The saved private trace is under
`artifacts/sahibinden-observe.jsonl`. A fixture regression now classifies that
specific captured text as `access_blocked` before model steering. This does
not establish how a real hold control should be operated.

The captured volatility was DuckDuckGo status text and document-height churn
while URL, controls, values, contexts, and destinations remained stable. Brownie
now permits that narrow case but still rejects action-relevant structural changes.

Local copy/paste tool comparison: 2026-09-26. Brownie Basic, direct Playwright,
and agent-browser 0.38.1 each passed three runs on the same localhost fixture,
with verified textbox values and no model calls. Median startup-to-close
times were 1006, 950, and 892 ms. Browser Use 0.13.10 completed one
independently verified run with Gemini 3.1 Flash Lite in 8.5 seconds from
agent run start, two invocations, and 15,729 reported tokens. The different
timing boundary and tiny local fixture prevent a general speed or cost claim.

Search-result choice check: 2026-09-26. Three bounded live searches for
official Python pathlib, Playwright Python browser installation, and Erasmus
Mundus Joint Masters pages each chose a human-rated best visible official
result. Jev made 10 model requests across the full searches, including
Gemini query generation; no-execution Gemini steering on the same three
result-page observations chose the same URLs in three requests. The private
traces and per-candidate judgments are in ignored artifacts. This small
sample does not establish general relevance, speed, or cost advantage.

Cross-browser fixture smoke: 2026-09-26. The same local `capture_fixture.html`
Basic task captured `solar report` from a visible line and typed it into the
observed `Reference` textbox in Playwright Firefox and WebKit. Both returned
`completed`. This proves the local launch, observation, and validated executor
path for that fixture. The WebKit run needed temporary local copies of
`libavif16` and `libmanette-0.2-0`; a normal launch on this host still needs
those system packages installed. It does not establish broad site compatibility.

## What this does not prove

- model steering quality or live multi-source research quality;
- authenticated applications, uploads, downloads, dialogs, or consequential writes;
- closed shadow roots, canvas-only interfaces, or visual-only targets;
- frame-local scrolling and deeply nested frames across many origins;
- Windows-native browser behavior;
- stable behavior after any listed site changes its markup.

Use the private trace for a failing run, classify the primary failure, build the
smallest local reproduction, then add it to the repeatable matrix. Do not count a
larger prompt or a claimed completion as a reliability improvement.
