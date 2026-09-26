# Browser tool comparison and near-term decisions

Review date: 2026-09-26. This compares public capabilities and Brownie's tested
contract, not measured success rates or prices. A claim that Brownie is generally
better or cheaper for basic automation would be false. A maintained Playwright
script is usually the simplest and cheapest way to run a known, stable workflow;
Brownie adds a constrained task format, fresh-observation checks, structured
stops, and a local control room at the cost of a smaller action set.

| Tool | What it already offers | Brownie decision |
| --- | --- | --- |
| [Playwright](https://playwright.dev/python/docs/intro) | Cross-browser automation, semantic locators, tracing, mature input APIs | Keep the foundation. Opt-in Firefox and WebKit launch paths passed a local capture-and-paste fixture; use Playwright primitives where a captured failure requires them. |
| [agent-browser](https://github.com/vercel-labs/agent-browser) | Compact accessibility snapshots, refs, text extraction, screenshots, persistent sessions, a CLI | It has a broader manual/agent tool surface than Brownie. Brownie now captures and reports named visible values for Basic tasks. Do not replace Brownie's validated executor with arbitrary selectors or JS. |
| [Playwright MCP](https://github.com/microsoft/playwright-mcp) | Accessibility snapshots and many browser tools usable by an external agent | Useful as a baseline for generic exploration. Brownie's smaller closed action contract remains useful for unattended, audited tasks. |
| [Browser Use](https://github.com/browser-use/browser-use) | General multi-step agent, human-help tools, structured results, local or hosted browsers | Its general task coverage is ahead of Brownie's. Borrow bounded user return and structured results; keep deterministic Basic tasks model-free. |
| [Stagehand](https://github.com/browserbase/stagehand) | `act`, `extract`, `observe`, and a full agent path; repeatable actions can be cached | The code-first / AI-when-needed split fits Brownie's two modes. Avoid importing its broader action path without Brownie's validation. |
| [Skyvern](https://github.com/Skyvern-AI/skyvern) | Form-heavy workflows, validation and extraction, cloud browsers | A serious alternative for complex business process automation. Replacing Brownie now would add a large service surface without proving the user's local workflows improve. |
| [Mobile Jev](https://github.com/droidrun/mobile-jev) | Android device runner through Mobilerun with Jev steering | Separate runtime and device access. Reuse only the principle of one observed action and bounded control; no Android claim for Brownie yet. |

## Decisions against the short and medium term note

- **Copy, paste, reporting:** implemented as `CAPTURE_TEXT`, later `TYPE_TEXT`
  from a named capture, and source-linked captured values in Basic results.
  This stays within visible text and does not use the system clipboard.
- **Planner dialogue:** already implemented in Research mode with Gemini for
  planning and optionally LLM steering, plus bounded same-run questions in the
  control room. The planner proposes search queries, answers, questions, or stop;
  it does not directly select raw browser actions.
- **API:** existing localhost run/state/stop/reply routes now publish a private
  token file and structured result for programmatic use. See [Local API](local-api.md).
- **Other browsers:** opt-in Firefox and WebKit launch paths added. Both passed
  a local capture-and-paste fixture. WebKit still needs host dependencies for
  ordinary use on this machine; see [the reliability matrix](reliability-matrix.md).
- **Information foraging:** useful lens for deciding whether a source is worth
  opening and when another query has low expected value. Brownie now records
  observed search-result candidates and the clicked source in a compact trace
  event. A [human-labeled evaluator](../benchmarks/foraging.md) measures whether
  that choice was best among visible candidates and counts model requests. This
  instrumentation also scored three fixed live tasks on 2026-09-26. Jev
  steering chose a human-rated best visible official result in all three;
  the full runs made 10 model requests including query generation and stale
  decisions. Gemini steering, tested without execution on the same three
  result-page observations, chose the same official URLs in three requests.
  This small set does not justify automatic scent scoring or provider routing.
- **Memory:** the factual ResearchState is compact within a run. The control
  room archives exact private traces and small indexes under `artifacts/runs/`,
  lists recent runs, and renders past traces. A separate bounded ledger stores
  only decisions the user explicitly accepts; Research receives them as context,
  never as source evidence or browser authority. Planner proposals and source
  claims remain in the archive. Runs still cannot resume after restart.
- **Artificial delays:** Playwright supports per-key delays and mouse timing,
  but adding human-like delays globally has no observed benefit here. Time and
  failure rates should be measured on the affected site before adding one.
- **Press and hold:** Playwright exposes mouse down/up and gesture durations.
  A read-only Sahibinden homepage observation on 2026-09-26 returned a temporary
  access block with a support code and no hold control. Brownie now classifies
  that captured state locally as `access_blocked`. A validated `PRESS_HOLD` action
  still needs an observation of the actual hold target and its outcome;
  duration must be bounded and mouse-up guaranteed even on failure.
- **Android:** Mobile Jev is a separate device stack, not a browser backend.
  Treat a Brownie Android mode as a later product decision after a concrete
  mobile-only task justifies it.
- **Receiving input during a run:** bounded planner clarification exists. A
  general mid-run goal change, approval, or pause/resume needs serialized run
  state and explicit authority; a free-form message cannot become a browser
  command.

## Evidence needed before a general superiority claim

The [local Basic baseline](../benchmarks/README.md) now compares Brownie with a
direct Playwright script on four fixed Chrome fixtures: copy/report, search
submission, delayed navigation, and ambiguity. On 2026-09-26, both verified
all three repetitions of every case and made zero model calls. Brownie median
times were 916, 915, 1219, and 748 ms; direct Playwright was 810, 818, 1089,
and 760 ms in the same order. These are local startup-to-close times, not
general performance estimates. Direct Playwright remains the simpler choice
for a known stable page; Brownie adds a reusable contract and structured
guardrails. The exact JSON records are in ignored artifacts/basic-comparison.json.

A second [same-page comparison](../benchmarks/README.md) ran the local
copy/paste fixture through Brownie Basic, direct Playwright, and
agent-browser 0.38.1. All passed 3/3; medians were 1006, 950, and 892 ms
respectively, with zero model calls. Agent-browser was fastest in this
small fixture, while Brownie kept its stricter task contract and structured
stops. Browser Use 0.13.10 also completed one independently checked copy
task with Gemini 3.1 Flash Lite: 8.5 seconds from agent run start, two model
invocations, and 15,729 reported tokens. Its zero-valued cost field did not
price that model, so it is not a free-inference claim. These runs do not
justify replacing Brownie or claiming it is the cheapest general tool.

The next comparison must use the same fixed public-site tasks across Brownie,
agent-browser, and Browser Use, measuring completed outcomes, false success,
safe stops, model calls/tokens, elapsed time, and setup effort. Include page
changes, ambiguous controls, and copy/report workflows. Public feature lists
and these local fixtures cannot establish that Brownie is generally faster,
cheaper, or more reliable.
